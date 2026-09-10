from __future__ import annotations

import gzip
import hashlib
import hmac
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from mcp.object_store_persistence import (
    ObjectStoreConflict,
    ObjectStorePersistenceError,
)

from .backup_recovery import SNAPSHOT_SCHEMA


BACKUP_OBJECT_SCHEMA = "cbi.v64-backup-object.v1"
ARCHIVE_FORMAT = "deterministic-tar-gzip-v1"
_SNAPSHOT_ID_RE = re.compile(r"^SNAP-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


class BackupObjectStoreError(ObjectStorePersistenceError):
    """Fail-closed error for the v6.4 immutable backup namespace."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_relative(relative: str) -> PurePosixPath:
    value = PurePosixPath(str(relative))
    if (
        value.is_absolute()
        or not value.parts
        or any(part in {"", ".", ".."} for part in value.parts)
    ):
        raise BackupObjectStoreError(f"unsafe backup member: {relative}")
    return value


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _tar_info(name: str, *, directory: bool, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = 0o755 if directory else 0o644
    info.size = 0 if directory else int(size)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _deterministic_snapshot_archive(snapshot_dir: Path, snapshot_id: str) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            archive.addfile(_tar_info(snapshot_id, directory=True))
            for path in sorted(snapshot_dir.rglob("*"), key=lambda item: item.relative_to(snapshot_dir).as_posix()):
                relative = path.relative_to(snapshot_dir).as_posix()
                safe = _safe_relative(relative)
                member_name = f"{snapshot_id}/{safe.as_posix()}"
                if path.is_symlink():
                    raise BackupObjectStoreError(f"backup symlink forbidden: {relative}")
                if path.is_dir():
                    archive.addfile(_tar_info(member_name, directory=True))
                    continue
                if not path.is_file():
                    raise BackupObjectStoreError(f"unsupported backup member: {relative}")
                body = path.read_bytes()
                archive.addfile(
                    _tar_info(member_name, directory=False, size=len(body)),
                    io.BytesIO(body),
                )
    return output.getvalue()


class BackupObjectStoreReplica:
    """Replicate completed v6.1 backup snapshots to a separate immutable prefix.

    This class intentionally does not participate in the hot object-state CAS
    pointer.  It uses the same S3-compatible client but a disjoint namespace so
    backup history does not amplify every runtime generation archive.
    """

    def __init__(self, client: Any, *, prefix: str, retention: int = 20):
        clean = str(prefix or "").strip().strip("/")
        if not clean or any(part in {"", ".", ".."} for part in clean.split("/")):
            raise BackupObjectStoreError("backup object-store prefix is invalid")
        if isinstance(retention, bool) or not isinstance(retention, int) or retention < 1:
            raise BackupObjectStoreError("backup retention must be a positive integer")
        self.client = client
        self.prefix = clean
        self.retention = retention
        self.root_prefix = f"{clean}/backups-v61"
        self.snapshot_prefix = f"{self.root_prefix}/snapshots/"
        self.manifest_prefix = f"{self.root_prefix}/manifests/"

    @staticmethod
    def _validate_snapshot_id(snapshot_id: str) -> str:
        value = str(snapshot_id or "").strip()
        if not _SNAPSHOT_ID_RE.fullmatch(value):
            raise BackupObjectStoreError("invalid backup snapshot_id")
        return value

    def _validate_local_snapshot(
        self,
        snapshot_dir: Path,
        snapshot_id: str,
    ) -> tuple[dict[str, Any], str]:
        snapshot = Path(snapshot_dir).expanduser().resolve()
        if not snapshot.is_dir() or snapshot.name != snapshot_id:
            raise BackupObjectStoreError("snapshot directory/id mismatch")
        manifest_path = snapshot / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupObjectStoreError("invalid local backup manifest") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != SNAPSHOT_SCHEMA
            or manifest.get("snapshot_id") != snapshot_id
        ):
            raise BackupObjectStoreError("local backup manifest contract mismatch")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise BackupObjectStoreError("local backup file manifest missing")
        actual = {
            path.relative_to(snapshot).as_posix()
            for path in snapshot.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        if set(files) != actual:
            raise BackupObjectStoreError("local backup file inventory mismatch")
        for relative, expected_hash in files.items():
            safe = _safe_relative(str(relative))
            path = snapshot.joinpath(*safe.parts)
            if path.is_symlink() or not path.is_file():
                raise BackupObjectStoreError(f"local backup member invalid: {relative}")
            if not hmac.compare_digest(_sha256_file(path), str(expected_hash)):
                raise BackupObjectStoreError(f"local backup member hash mismatch: {relative}")
        return manifest, _sha256_file(manifest_path)

    def _manifest_key(self, snapshot_id: str) -> str:
        return f"{self.manifest_prefix}{snapshot_id}.json"

    def _archive_key(self, snapshot_id: str, archive_sha256: str) -> str:
        return f"{self.snapshot_prefix}{snapshot_id}-{archive_sha256}.tar.gz"

    def _put_immutable(self, key: str, body: bytes) -> None:
        try:
            self.client.put(key, body, if_none_match=True)
        except ObjectStoreConflict as exc:
            existing, _etag = self.client.get(key)
            if existing is None or not hmac.compare_digest(existing, body):
                raise BackupObjectStoreError(
                    f"immutable backup object conflict: {key}"
                ) from exc

    def _decode_external_manifest(
        self,
        body: bytes,
        *,
        expected_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupObjectStoreError("invalid external backup manifest JSON") from exc
        if not isinstance(value, dict) or value.get("schema") != BACKUP_OBJECT_SCHEMA:
            raise BackupObjectStoreError("invalid external backup manifest schema")
        snapshot_id = self._validate_snapshot_id(str(value.get("snapshot_id") or ""))
        if expected_snapshot_id and snapshot_id != expected_snapshot_id:
            raise BackupObjectStoreError("external backup manifest snapshot mismatch")
        archive_sha256 = str(value.get("archive_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
            raise BackupObjectStoreError("external backup archive hash invalid")
        expected_key = self._archive_key(snapshot_id, archive_sha256)
        if value.get("archive_key") != expected_key:
            raise BackupObjectStoreError("external backup archive key mismatch")
        local_manifest_sha256 = str(value.get("local_manifest_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", local_manifest_sha256):
            raise BackupObjectStoreError("external local-manifest hash invalid")
        if value.get("archive_format") != ARCHIVE_FORMAT:
            raise BackupObjectStoreError("external backup archive format mismatch")
        return value

    def _verified_external_row(self, manifest: dict[str, Any]) -> dict[str, Any]:
        archive_key = str(manifest["archive_key"])
        archive, _etag = self.client.get(archive_key)
        if archive is None:
            raise BackupObjectStoreError("external backup archive missing")
        observed = _sha256_bytes(archive)
        if not hmac.compare_digest(observed, str(manifest["archive_sha256"])):
            raise BackupObjectStoreError("external backup archive SHA-256 mismatch")
        return {
            "verified": True,
            "snapshot_id": str(manifest["snapshot_id"]),
            "created_at": manifest.get("created_at"),
            "reasons": list(manifest.get("reasons") or []),
            "archive_key": archive_key,
            "archive_sha256": observed,
            "local_manifest_sha256": str(manifest["local_manifest_sha256"]),
            "archive_format": ARCHIVE_FORMAT,
            "persistence_mode": "OBJECT_STORE_REPLICATED",
        }

    def replicate_snapshot(self, snapshot_dir: Path, snapshot_id: str) -> dict[str, Any]:
        sid = self._validate_snapshot_id(snapshot_id)
        local_manifest, local_manifest_sha256 = self._validate_local_snapshot(
            Path(snapshot_dir), sid
        )
        archive = _deterministic_snapshot_archive(Path(snapshot_dir).resolve(), sid)
        archive_sha256 = _sha256_bytes(archive)
        archive_key = self._archive_key(sid, archive_sha256)
        manifest_key = self._manifest_key(sid)
        external_manifest = {
            "schema": BACKUP_OBJECT_SCHEMA,
            "snapshot_id": sid,
            "created_at": local_manifest.get("created_at"),
            "reasons": list(local_manifest.get("reasons") or []),
            "archive_key": archive_key,
            "archive_sha256": archive_sha256,
            "archive_format": ARCHIVE_FORMAT,
            "local_manifest_sha256": local_manifest_sha256,
            "source_fingerprint": local_manifest.get("source_fingerprint"),
            "file_count": len(local_manifest.get("files") or {}),
        }
        manifest_body = _canonical_json_bytes(external_manifest)

        existing_manifest_body, _etag = self.client.get(manifest_key)
        if existing_manifest_body is not None:
            existing = self._decode_external_manifest(
                existing_manifest_body,
                expected_snapshot_id=sid,
            )
            if (
                existing.get("archive_sha256") != archive_sha256
                or existing.get("local_manifest_sha256") != local_manifest_sha256
                or existing_manifest_body != manifest_body
            ):
                raise BackupObjectStoreError(
                    "snapshot_id already bound to different immutable backup content"
                )
            row = self._verified_external_row(existing)
            return {**row, "deduplicated": True, "manifest_key": manifest_key}

        self._put_immutable(archive_key, archive)
        self._put_immutable(manifest_key, manifest_body)
        stored_manifest_body, _etag = self.client.get(manifest_key)
        if stored_manifest_body is None:
            raise BackupObjectStoreError("external backup manifest missing after write")
        stored = self._decode_external_manifest(
            stored_manifest_body,
            expected_snapshot_id=sid,
        )
        if stored_manifest_body != manifest_body:
            raise BackupObjectStoreError("external backup manifest changed after write")
        row = self._verified_external_row(stored)
        return {**row, "deduplicated": False, "manifest_key": manifest_key}

    def list_snapshots(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key in self.client.list_keys(self.manifest_prefix):
            if not key.startswith(self.manifest_prefix) or not key.endswith(".json"):
                continue
            filename = key[len(self.manifest_prefix) :]
            snapshot_id = filename[:-5]
            if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
                raise BackupObjectStoreError("unexpected object in backup manifest prefix")
            body, _etag = self.client.get(key)
            if body is None:
                raise BackupObjectStoreError("backup manifest disappeared during discovery")
            manifest = self._decode_external_manifest(
                body,
                expected_snapshot_id=snapshot_id,
            )
            row = self._verified_external_row(manifest)
            rows.append({**row, "manifest_key": key})
        rows.sort(key=lambda row: str(row["snapshot_id"]), reverse=True)
        return rows

    def latest_snapshot(self) -> dict[str, Any] | None:
        rows = self.list_snapshots()
        return rows[0] if rows else None
