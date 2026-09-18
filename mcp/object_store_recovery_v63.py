#!/usr/bin/env python3
"""CBI v6.3 complete recovery-state persistence over the existing S3/R2 client.

The legacy object-store manager intentionally remains session-only for backward
compatibility.  This v6.3 manager upgrades a generation to recovery-state v2 as
soon as the v6.1 mutation WAL exists, binding sessions and WAL under one CAS
pointer so an ephemeral replacement instance can perform exact recovery.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .object_store_persistence import (
    POINTER_SCHEMA as LEGACY_POINTER_SCHEMA,
    ObjectStoreConflict,
    ObjectStorePersistenceError,
    ObjectStorePointer,
    ObjectStoreStateManager,
    _extract_tar_safely,
    _sessions_fingerprint,
    _sha256_bytes,
    _sha256_file,
)


STATE_SCHEMA_V2 = "cbi.object-store-state.v2"
POINTER_SCHEMA_V2 = "cbi.object-store-pointer.v2"
ARCHIVE_FORMAT_V2 = "object_state_v2"
RECOVERY_COMPONENTS = ("sessions", "mcp-idempotency-v61")


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _recovery_fingerprint(live_root: Path) -> str:
    root = live_root.expanduser().resolve()
    sessions = root / "sessions"
    wal = root / "mcp-idempotency-v61"
    if not sessions.is_dir():
        raise ObjectStorePersistenceError(f"session root missing: {sessions}")
    if not wal.is_dir():
        raise ObjectStorePersistenceError(f"mutation WAL root missing: {wal}")

    import hashlib

    digest = hashlib.sha256()
    count = 0
    for component in RECOVERY_COMPONENTS:
        component_root = root / component
        for path in sorted(component_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            digest.update(
                f"{rel}\0{path.stat().st_size}\0{_sha256_file(path)}\n".encode("utf-8")
            )
            count += 1
    digest.update(f"components={','.join(RECOVERY_COMPONENTS)}\nfiles={count}\n".encode("ascii"))
    return digest.hexdigest()


def _payload_inventory_v2(root: Path) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for component in RECOVERY_COMPONENTS:
        component_root = root / component
        if not component_root.is_dir():
            raise ObjectStorePersistenceError(f"recovery component missing: {component}")
        for path in sorted(component_root.rglob("*")):
            if not path.is_file():
                continue
            inventory[path.relative_to(root).as_posix()] = {
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
    return inventory


def _verify_payload_v2(root: Path, expected: Any) -> None:
    if not isinstance(expected, dict):
        raise ObjectStorePersistenceError("v2 payload manifest missing")
    actual = {
        path.relative_to(root).as_posix()
        for component in RECOVERY_COMPONENTS
        for path in (root / component).rglob("*")
        if path.is_file()
    }
    if actual != set(expected):
        raise ObjectStorePersistenceError("v2 payload inventory mismatch")
    for relative, raw in expected.items():
        row = dict(raw or {}) if isinstance(raw, dict) else {}
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = row.get("size_bytes")
        if not _valid_sha256(expected_sha):
            raise ObjectStorePersistenceError(f"v2 payload hash invalid: {relative}")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise ObjectStorePersistenceError(f"v2 payload size invalid: {relative}")
        path = root / str(relative)
        if path.stat().st_size != expected_size:
            raise ObjectStorePersistenceError(f"v2 payload size mismatch: {relative}")
        if _sha256_file(path) != expected_sha:
            raise ObjectStorePersistenceError(f"v2 payload hash mismatch: {relative}")


def _verify_state_v2(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((root / "state-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectStorePersistenceError("invalid v2 state-manifest.json") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != STATE_SCHEMA_V2:
        raise ObjectStorePersistenceError("unexpected v2 object-state schema")
    if tuple(manifest.get("components") or ()) != RECOVERY_COMPONENTS:
        raise ObjectStorePersistenceError("v2 recovery component inventory mismatch")
    for component in RECOVERY_COMPONENTS:
        if not (root / component).is_dir():
            raise ObjectStorePersistenceError(f"v2 recovery component missing: {component}")
    _verify_payload_v2(root, manifest.get("payload_files"))
    sessions_fp = str(manifest.get("sessions_fingerprint_sha256") or "").lower()
    recovery_fp = str(manifest.get("recovery_fingerprint_sha256") or "").lower()
    if not _valid_sha256(sessions_fp) or _sessions_fingerprint(root / "sessions") != sessions_fp:
        raise ObjectStorePersistenceError("v2 sessions fingerprint mismatch")
    if not _valid_sha256(recovery_fp) or _recovery_fingerprint(root) != recovery_fp:
        raise ObjectStorePersistenceError("v2 recovery fingerprint mismatch")
    return manifest


def _build_recovery_state_archive(
    live_root: Path,
    generation: int,
    output: Path,
) -> tuple[str, str, str]:
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ObjectStorePersistenceError("generation must be a non-negative integer")
    source = live_root.expanduser().resolve()
    sessions_fp = _sessions_fingerprint(source / "sessions")
    recovery_fp = _recovery_fingerprint(source)
    with tempfile.TemporaryDirectory(prefix="cbi-v63-recovery-state-build-") as tmp_name:
        root = Path(tmp_name) / "cbi-object-state"
        root.mkdir()
        for component in RECOVERY_COMPONENTS:
            shutil.copytree(source / component, root / component)
        manifest = {
            "schema": STATE_SCHEMA_V2,
            "generation": generation,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "components": list(RECOVERY_COMPONENTS),
            "sessions_fingerprint_sha256": sessions_fp,
            "recovery_fingerprint_sha256": recovery_fp,
            "payload_files": _payload_inventory_v2(root),
        }
        (root / "state-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as tf:
            tf.add(root, arcname="cbi-object-state", recursive=True)
    return _sha256_file(output), sessions_fp, recovery_fp


@dataclass
class RecoveryObjectStorePointerV63:
    generation: int
    archive_key: str
    archive_sha256: str
    sessions_fingerprint_sha256: str
    archive_format: str
    etag: str = ""
    recovery_fingerprint_sha256: str = ""

    def to_bytes(self) -> bytes:
        if self.archive_format != ARCHIVE_FORMAT_V2:
            raise ObjectStorePersistenceError("v2 pointer only writes object_state_v2")
        if not _valid_sha256(self.recovery_fingerprint_sha256):
            raise ObjectStorePersistenceError("v2 pointer recovery fingerprint invalid")
        value = {
            "schema": POINTER_SCHEMA_V2,
            "generation": self.generation,
            "archive_key": self.archive_key,
            "archive_sha256": self.archive_sha256,
            "sessions_fingerprint_sha256": self.sessions_fingerprint_sha256,
            "recovery_fingerprint_sha256": self.recovery_fingerprint_sha256,
            "archive_format": self.archive_format,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

    @classmethod
    def from_bytes(cls, value: bytes, etag: str = "") -> "RecoveryObjectStorePointerV63":
        try:
            row = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObjectStorePersistenceError("invalid v2 object-store current pointer") from exc
        if not isinstance(row, dict) or row.get("schema") != POINTER_SCHEMA_V2:
            raise ObjectStorePersistenceError("unexpected v2 object-store pointer schema")
        generation = row.get("generation")
        archive_key = str(row.get("archive_key") or "").strip()
        archive_sha = str(row.get("archive_sha256") or "").strip().lower()
        sessions_fp = str(row.get("sessions_fingerprint_sha256") or "").strip().lower()
        recovery_fp = str(row.get("recovery_fingerprint_sha256") or "").strip().lower()
        archive_format = str(row.get("archive_format") or "").strip()
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ObjectStorePersistenceError("v2 pointer generation invalid")
        if not archive_key or not _valid_sha256(archive_sha):
            raise ObjectStorePersistenceError("v2 pointer archive identity invalid")
        if not _valid_sha256(sessions_fp) or not _valid_sha256(recovery_fp):
            raise ObjectStorePersistenceError("v2 pointer fingerprint invalid")
        if archive_format != ARCHIVE_FORMAT_V2:
            raise ObjectStorePersistenceError("v2 pointer archive format invalid")
        return cls(
            generation=generation,
            archive_key=archive_key,
            archive_sha256=archive_sha,
            sessions_fingerprint_sha256=sessions_fp,
            archive_format=archive_format,
            etag=etag,
            recovery_fingerprint_sha256=recovery_fp,
        )


class RecoveryObjectStoreStateManagerV63(ObjectStoreStateManager):
    """Backward-readable object-store manager with complete v6.3 recovery generations."""

    def read_pointer(self, *, required: bool = False):
        body, etag = self.client.get(self.pointer_key)
        if body is None:
            if required:
                raise ObjectStorePersistenceError("object-store current pointer is missing")
            self.pointer = None
            return None
        try:
            raw = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObjectStorePersistenceError("invalid object-store current pointer") from exc
        schema = raw.get("schema") if isinstance(raw, dict) else None
        if schema == LEGACY_POINTER_SCHEMA:
            self.pointer = ObjectStorePointer.from_bytes(body, etag)
        elif schema == POINTER_SCHEMA_V2:
            self.pointer = RecoveryObjectStorePointerV63.from_bytes(body, etag)
        else:
            raise ObjectStorePersistenceError("unexpected object-store pointer schema")
        return self.pointer

    def restore_into(self, live_root: Path) -> bool:
        with self._lock:
            pointer = self.read_pointer(required=False)
            if pointer is None:
                return False
            if pointer.archive_format != ARCHIVE_FORMAT_V2:
                return super().restore_into(live_root)

            target = live_root.expanduser().resolve()
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ObjectStorePersistenceError(f"restore target must be empty: {target}")
            archive_bytes, _ = self.client.get(pointer.archive_key)
            if archive_bytes is None:
                raise ObjectStorePersistenceError("current pointer references a missing state archive")
            if not hmac.compare_digest(_sha256_bytes(archive_bytes), pointer.archive_sha256):
                raise ObjectStorePersistenceError("object-store state archive SHA-256 mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rmdir()
            staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent))
            try:
                archive = staging / "state.tar.gz"
                archive.write_bytes(archive_bytes)
                extracted = _extract_tar_safely(archive, staging, "cbi-object-state")
                manifest = _verify_state_v2(extracted)
                if manifest["sessions_fingerprint_sha256"] != pointer.sessions_fingerprint_sha256:
                    raise ObjectStorePersistenceError("restored v2 sessions pointer mismatch")
                if manifest["recovery_fingerprint_sha256"] != pointer.recovery_fingerprint_sha256:
                    raise ObjectStorePersistenceError("restored v2 recovery pointer mismatch")
                (extracted / "backups-v61").mkdir(exist_ok=True)
                (extracted / "export-manifest.json").write_text(
                    json.dumps(
                        {
                            "schema": STATE_SCHEMA_V2,
                            "restored_generation": pointer.generation,
                            "recovery_fingerprint_sha256": pointer.recovery_fingerprint_sha256,
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(extracted, target)
                return True
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def attach_existing(self, live_root: Path) -> None:
        pointer = self.read_pointer(required=True)
        assert pointer is not None
        root = live_root.expanduser().resolve()
        if pointer.archive_format == ARCHIVE_FORMAT_V2:
            if _sessions_fingerprint(root / "sessions") != pointer.sessions_fingerprint_sha256:
                raise ObjectStorePersistenceError(
                    "local sessions do not match current v2 object-store pointer"
                )
            if _recovery_fingerprint(root) != pointer.recovery_fingerprint_sha256:
                raise ObjectStorePersistenceError(
                    "local recovery state does not match current v2 object-store pointer"
                )
            self.last_error = ""
            return
        super().attach_existing(root)

    def sync_if_changed(self, live_root: Path) -> bool:
        with self._lock:
            root = live_root.expanduser().resolve()
            if self.pointer is None:
                self.read_pointer(required=True)
            assert self.pointer is not None
            wal_exists = (root / "mcp-idempotency-v61").is_dir()
            use_v2 = self.pointer.archive_format == ARCHIVE_FORMAT_V2 or wal_exists
            if not use_v2:
                return super().sync_if_changed(root)

            observed_recovery = _recovery_fingerprint(root)
            observed_sessions = _sessions_fingerprint(root / "sessions")
            current_recovery = str(
                getattr(self.pointer, "recovery_fingerprint_sha256", "") or ""
            ).lower()
            if (
                self.pointer.archive_format == ARCHIVE_FORMAT_V2
                and observed_recovery == current_recovery
                and observed_sessions == self.pointer.sessions_fingerprint_sha256
            ):
                self.last_sync_changed = False
                self.last_error = ""
                return False

            generation = self.pointer.generation + 1
            with tempfile.TemporaryDirectory(prefix="cbi-v63-object-sync-") as tmp_name:
                archive = Path(tmp_name) / "state.tar.gz"
                archive_sha, sessions_fp, recovery_fp = _build_recovery_state_archive(
                    root, generation, archive
                )
                body = archive.read_bytes()
                key = f"{self.state_prefix}{generation:020d}-{archive_sha}.tar.gz"
                self._put_immutable(key, body)
                next_pointer = RecoveryObjectStorePointerV63(
                    generation=generation,
                    archive_key=key,
                    archive_sha256=archive_sha,
                    sessions_fingerprint_sha256=sessions_fp,
                    archive_format=ARCHIVE_FORMAT_V2,
                    recovery_fingerprint_sha256=recovery_fp,
                )
                try:
                    next_pointer.etag = self.client.put(
                        self.pointer_key,
                        next_pointer.to_bytes(),
                        if_match=self.pointer.etag,
                    )
                except ObjectStoreConflict:
                    self.last_error = "OBJECT_STORE_CAS_CONFLICT"
                    raise
                self.pointer = next_pointer
                self.last_sync_changed = True
                self.last_error = ""
            self._prune()
            return True

    def health(self) -> dict[str, Any]:
        base = super().health()
        pointer = self.pointer
        base.update(
            {
                "recovery_state_schema": (
                    STATE_SCHEMA_V2
                    if pointer is not None and pointer.archive_format == ARCHIVE_FORMAT_V2
                    else None
                ),
                "recovery_fingerprint_sha256": (
                    getattr(pointer, "recovery_fingerprint_sha256", None)
                    if pointer is not None
                    else None
                ),
                "recovery_components": list(RECOVERY_COMPONENTS),
            }
        )
        return base
