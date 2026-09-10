#!/usr/bin/env python3
"""Fail-closed S3-compatible persistence for ephemeral CBI cloud runtimes.

The accepted CBI Runtime remains file-backed.  Ephemeral hosts persist complete,
immutable session generations to an S3-compatible private bucket and advance one
small ``current.json`` pointer with conditional PutObject.  The pointer CAS is
the split-brain guard: a stale writer receives HTTP 412 and fails closed.

The client is stdlib-only AWS SigV4 so the Render Free image does not need boto3.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

STATE_SCHEMA = "cbi.object-store-state.v1"
POINTER_SCHEMA = "cbi.object-store-pointer.v1"
MAX_ARCHIVE_MEMBERS = 200_000
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024


class ObjectStorePersistenceError(RuntimeError):
    pass


class ObjectStoreConflict(ObjectStorePersistenceError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_etag(value: str | None) -> str:
    raw = str(value or "").strip()
    if raw.startswith('W/"') and raw.endswith('"'):
        return raw[3:-1]
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _sessions_fingerprint(session_root: Path) -> str:
    if not session_root.is_dir():
        raise ObjectStorePersistenceError(f"session root missing: {session_root}")
    h = hashlib.sha256()
    count = 0
    for path in sorted(session_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(session_root).as_posix()
        h.update(f"{rel}\0{path.stat().st_size}\0{_sha256_file(path)}\n".encode("utf-8"))
        count += 1
    h.update(f"files={count}\n".encode("ascii"))
    return h.hexdigest()


def _safe_relative(name: str, expected_root: str) -> PurePosixPath:
    value = PurePosixPath(name)
    if value.is_absolute() or not value.parts or any(p in {"", ".", ".."} for p in value.parts):
        raise ObjectStorePersistenceError(f"unsafe archive member: {name}")
    if value.parts[0] != expected_root:
        raise ObjectStorePersistenceError(f"unexpected archive root: {name}")
    return value


def _extract_tar_safely(archive: Path, staging: Path, expected_root: str) -> Path:
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        if not members:
            raise ObjectStorePersistenceError("state archive is empty")
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ObjectStorePersistenceError("state archive contains too many members")
        if sum(max(0, int(m.size)) for m in members) > MAX_UNCOMPRESSED_BYTES:
            raise ObjectStorePersistenceError("state archive exceeds uncompressed size limit")
        seen: set[str] = set()
        for member in members:
            rel = _safe_relative(member.name, expected_root)
            canonical = rel.as_posix()
            if canonical in seen:
                raise ObjectStorePersistenceError(f"duplicate archive member forbidden: {member.name}")
            seen.add(canonical)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ObjectStorePersistenceError(f"archive links/devices are forbidden: {member.name}")
            destination = staging.joinpath(*rel.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ObjectStorePersistenceError(f"unsupported archive member type: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = tf.extractfile(member)
            if source is None:
                raise ObjectStorePersistenceError(f"archive member unreadable: {member.name}")
            with source, destination.open("xb") as out:
                shutil.copyfileobj(source, out, length=1024 * 1024)
    return staging / expected_root


def _verify_payload(root: Path, manifest_name: str, expected: Any) -> None:
    if not isinstance(expected, dict):
        raise ObjectStorePersistenceError("payload hash manifest missing")
    actual = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != manifest_name
    }
    if actual != set(expected):
        raise ObjectStorePersistenceError("payload inventory mismatch")
    for relative, expected_hash in expected.items():
        if _sha256_file(root / str(relative)) != str(expected_hash):
            raise ObjectStorePersistenceError(f"payload hash mismatch: {relative}")


def _verify_migration_v1(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((root / "export-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectStorePersistenceError("invalid migration export-manifest.json") from exc
    if manifest.get("schema") != "cbi.cloud-runtime-export.v1":
        raise ObjectStorePersistenceError("unexpected migration export schema")
    if manifest.get("hash_chains_valid") is not True or manifest.get("activation_ready") is not True:
        raise ObjectStorePersistenceError("migration export was not activation-ready")
    if manifest.get("pre_archive_quiescence_check") is not True:
        raise ObjectStorePersistenceError("migration export lacks quiescence proof")
    _verify_payload(root, "export-manifest.json", manifest.get("payload_files"))
    if not (root / "sessions").is_dir():
        raise ObjectStorePersistenceError("migration sessions/ missing")
    return manifest


def _verify_state_v1(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((root / "state-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectStorePersistenceError("invalid state-manifest.json") from exc
    if manifest.get("schema") != STATE_SCHEMA:
        raise ObjectStorePersistenceError("unexpected object-state schema")
    _verify_payload(root, "state-manifest.json", manifest.get("payload_files"))
    sessions = root / "sessions"
    if not sessions.is_dir():
        raise ObjectStorePersistenceError("object-state sessions/ missing")
    if _sessions_fingerprint(sessions) != str(manifest.get("sessions_fingerprint_sha256") or ""):
        raise ObjectStorePersistenceError("object-state sessions fingerprint mismatch")
    return manifest


def _build_state_archive(session_root: Path, generation: int, output: Path) -> tuple[str, str]:
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ObjectStorePersistenceError("generation must be a non-negative integer")
    fingerprint = _sessions_fingerprint(session_root)
    with tempfile.TemporaryDirectory(prefix="cbi-object-state-build-") as tmp_name:
        root = Path(tmp_name) / "cbi-object-state"
        copied = root / "sessions"
        shutil.copytree(session_root, copied)
        payload = {
            p.relative_to(root).as_posix(): _sha256_file(p)
            for p in sorted(copied.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "schema": STATE_SCHEMA,
            "generation": generation,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "sessions_fingerprint_sha256": fingerprint,
            "payload_files": payload,
        }
        (root / "state-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as tf:
            tf.add(root, arcname="cbi-object-state", recursive=True)
    return _sha256_file(output), fingerprint


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str = "auto"


class S3CompatibleClient:
    def __init__(self, config: S3Config, *, timeout: float = 30.0):
        endpoint = str(config.endpoint or "").strip().rstrip("/")
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ObjectStorePersistenceError("CBI object-store endpoint must be a bare https URL")
        bucket = str(config.bucket or "").strip()
        if not bucket or "/" in bucket:
            raise ObjectStorePersistenceError("CBI object-store bucket is invalid")
        if not config.access_key_id or not config.secret_access_key:
            raise ObjectStorePersistenceError("CBI object-store credentials are required")
        self.config = config
        self.endpoint = endpoint
        self.parsed = parsed
        self.timeout = float(timeout)

    @staticmethod
    def _quote(value: str) -> str:
        return "/".join(urllib.parse.quote(part, safe="-_.~") for part in value.split("/"))

    def _request(
        self,
        method: str,
        *,
        key: str | None = None,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        allow: Iterable[int] = (),
    ) -> tuple[int, bytes, dict[str, str]]:
        path = "/" + self._quote(self.config.bucket)
        if key is not None:
            clean = str(key).lstrip("/")
            if not clean:
                raise ObjectStorePersistenceError("object key must not be empty")
            path += "/" + self._quote(clean)
        query = dict(query or {})
        canonical_query = urllib.parse.urlencode(
            sorted(query.items()), quote_via=urllib.parse.quote, safe="-_.~"
        )
        url = self.endpoint + path + ("?" + canonical_query if canonical_query else "")
        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = _sha256_bytes(body)
        host = self.parsed.netloc
        signed = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        canonical_headers = "".join(f"{name}:{signed[name]}\n" for name in sorted(signed))
        signed_headers = ";".join(sorted(signed))
        canonical_request = "\n".join(
            [method.upper(), path, canonical_query, canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, scope, _sha256_bytes(canonical_request.encode("utf-8"))]
        )

        def sign(key_bytes: bytes, text: str) -> bytes:
            return hmac.new(key_bytes, text.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + self.config.secret_access_key).encode("utf-8"), date_stamp)
        k_region = sign(k_date, self.config.region)
        k_service = sign(k_region, "s3")
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.access_key_id}/{scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )
        request_headers = {
            "Host": host,
            "X-Amz-Date": amz_date,
            "X-Amz-Content-Sha256": payload_hash,
            "Authorization": authorization,
            **(headers or {}),
        }
        request = urllib.request.Request(
            url,
            data=body if method.upper() in {"PUT", "POST"} else None,
            headers=request_headers,
            method=method.upper(),
        )
        allowed = {int(value) for value in allow}
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return int(response.status), response.read(), {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            data = exc.read()
            if int(exc.code) in allowed:
                return int(exc.code), data, {k.lower(): v for k, v in exc.headers.items()}
            detail = data.decode("utf-8", errors="replace")[:500]
            raise ObjectStorePersistenceError(
                f"object-store {method.upper()} failed HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ObjectStorePersistenceError(f"object-store request failed: {exc.reason}") from exc

    def get(self, key: str) -> tuple[bytes | None, str]:
        status, body, headers = self._request("GET", key=key, allow={404})
        return (None, "") if status == 404 else (body, _normalize_etag(headers.get("etag")))

    def head(self, key: str) -> tuple[bool, str]:
        status, _body, headers = self._request("HEAD", key=key, allow={404})
        return status != 404, _normalize_etag(headers.get("etag"))

    def put(self, key: str, body: bytes, *, if_match: str = "", if_none_match: bool = False) -> str:
        headers = {"Content-Type": "application/octet-stream"}
        if if_match:
            headers["If-Match"] = f'"{_normalize_etag(if_match)}"'
        if if_none_match:
            headers["If-None-Match"] = "*"
        status, _body, response_headers = self._request(
            "PUT", key=key, body=body, headers=headers, allow={412}
        )
        if status == 412:
            raise ObjectStoreConflict(f"conditional write conflict for {key}")
        etag = _normalize_etag(response_headers.get("etag"))
        if not etag:
            exists, etag = self.head(key)
            if not exists or not etag:
                raise ObjectStorePersistenceError(f"object-store did not return ETag for {key}")
        return etag

    def delete(self, key: str) -> None:
        self._request("DELETE", key=key, allow={404})

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token = ""
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                query["continuation-token"] = token
            _status, body, _headers = self._request("GET", query=query)
            try:
                root = ET.fromstring(body)
            except ET.ParseError as exc:
                raise ObjectStorePersistenceError("invalid ListObjectsV2 response") from exc
            ns = root.tag.split("}", 1)[0] + "}" if root.tag.startswith("{") else ""
            for content in root.findall(f"{ns}Contents"):
                node = content.find(f"{ns}Key")
                if node is not None and node.text:
                    keys.append(node.text)
            if (root.findtext(f"{ns}IsTruncated") or "false").lower() != "true":
                break
            token = root.findtext(f"{ns}NextContinuationToken") or ""
            if not token:
                raise ObjectStorePersistenceError("truncated listing lacks continuation token")
        return keys


@dataclass
class ObjectStorePointer:
    generation: int
    archive_key: str
    archive_sha256: str
    sessions_fingerprint_sha256: str
    archive_format: str
    etag: str = ""

    def to_bytes(self) -> bytes:
        value = {
            "schema": POINTER_SCHEMA,
            "generation": self.generation,
            "archive_key": self.archive_key,
            "archive_sha256": self.archive_sha256,
            "sessions_fingerprint_sha256": self.sessions_fingerprint_sha256,
            "archive_format": self.archive_format,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

    @classmethod
    def from_bytes(cls, value: bytes, etag: str = "") -> "ObjectStorePointer":
        try:
            row = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObjectStorePersistenceError("invalid object-store current pointer") from exc
        if not isinstance(row, dict) or row.get("schema") != POINTER_SCHEMA:
            raise ObjectStorePersistenceError("unexpected object-store pointer schema")
        raw_generation = row.get("generation")
        if isinstance(raw_generation, bool) or not isinstance(raw_generation, int):
            raise ObjectStorePersistenceError("object-store pointer generation must be an integer")
        generation = raw_generation
        archive_key = str(row.get("archive_key") or "").strip()
        archive_sha = str(row.get("archive_sha256") or "").strip().lower()
        fingerprint = str(row.get("sessions_fingerprint_sha256") or "").strip().lower()
        archive_format = str(row.get("archive_format") or "").strip()
        if generation < 0 or not archive_key:
            raise ObjectStorePersistenceError("invalid object-store pointer generation/key")
        if len(archive_sha) != 64 or any(ch not in "0123456789abcdef" for ch in archive_sha):
            raise ObjectStorePersistenceError("invalid object-store pointer archive hash")
        if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
            raise ObjectStorePersistenceError("invalid object-store pointer sessions fingerprint")
        if archive_format not in {"migration_v1", "object_state_v1"}:
            raise ObjectStorePersistenceError("unsupported object-store archive format")
        return cls(generation, archive_key, archive_sha, fingerprint, archive_format, etag)


class ObjectStoreStateManager:
    def __init__(self, client: S3CompatibleClient, *, prefix: str = "cbi-v61", retention: int = 20):
        prefix = str(prefix or "").strip().strip("/")
        if not prefix or ".." in PurePosixPath(prefix).parts:
            raise ObjectStorePersistenceError("CBI object-store prefix is invalid")
        self.client = client
        self.prefix = prefix
        self.pointer_key = f"{prefix}/current.json"
        self.state_prefix = f"{prefix}/states/"
        self.retention = max(2, min(int(retention), 500))
        self.pointer: ObjectStorePointer | None = None
        self.last_error = ""
        self.last_sync_changed = False
        self._lock = threading.RLock()

    @classmethod
    def from_env(cls) -> "ObjectStoreStateManager | None":
        mode = str(os.environ.get("CBI_OBJECT_STORE_MODE") or "none").strip().lower()
        if mode in {"", "none", "off", "disabled"}:
            return None
        if mode not in {"s3", "r2"}:
            raise ObjectStorePersistenceError("CBI_OBJECT_STORE_MODE must be none, s3, or r2")
        config = S3Config(
            endpoint=str(os.environ.get("CBI_OBJECT_STORE_ENDPOINT") or "").strip(),
            bucket=str(os.environ.get("CBI_OBJECT_STORE_BUCKET") or "").strip(),
            access_key_id=str(os.environ.get("CBI_OBJECT_STORE_ACCESS_KEY_ID") or "").strip(),
            secret_access_key=str(os.environ.get("CBI_OBJECT_STORE_SECRET_ACCESS_KEY") or "").strip(),
            region=str(os.environ.get("CBI_OBJECT_STORE_REGION") or "auto").strip() or "auto",
        )
        return cls(
            S3CompatibleClient(config),
            prefix=str(os.environ.get("CBI_OBJECT_STORE_PREFIX") or "cbi-v61"),
            retention=int(os.environ.get("CBI_OBJECT_STORE_RETENTION") or "20"),
        )

    def read_pointer(self, *, required: bool = False) -> ObjectStorePointer | None:
        body, etag = self.client.get(self.pointer_key)
        if body is None:
            if required:
                raise ObjectStorePersistenceError("object-store current pointer is missing")
            self.pointer = None
            return None
        self.pointer = ObjectStorePointer.from_bytes(body, etag)
        return self.pointer

    def restore_into(self, live_root: Path) -> bool:
        with self._lock:
            pointer = self.read_pointer(required=False)
            if pointer is None:
                return False
            live_root = live_root.expanduser().resolve()
            if live_root.exists() and (not live_root.is_dir() or any(live_root.iterdir())):
                raise ObjectStorePersistenceError(f"restore target must be empty: {live_root}")
            archive_bytes, _ = self.client.get(pointer.archive_key)
            if archive_bytes is None:
                raise ObjectStorePersistenceError("current pointer references a missing state archive")
            if not hmac.compare_digest(_sha256_bytes(archive_bytes), pointer.archive_sha256):
                raise ObjectStorePersistenceError("object-store state archive SHA-256 mismatch")
            live_root.parent.mkdir(parents=True, exist_ok=True)
            if live_root.exists():
                live_root.rmdir()
            staging = Path(tempfile.mkdtemp(prefix=f".{live_root.name}.restore-", dir=live_root.parent))
            try:
                archive = staging / "state.tar.gz"
                archive.write_bytes(archive_bytes)
                if pointer.archive_format == "migration_v1":
                    extracted = _extract_tar_safely(archive, staging, "cbi-cloud-runtime")
                    _verify_migration_v1(extracted)
                else:
                    extracted = _extract_tar_safely(archive, staging, "cbi-object-state")
                    _verify_state_v1(extracted)
                    (extracted / "export-manifest.json").write_text(
                        json.dumps({"schema": STATE_SCHEMA, "restored_generation": pointer.generation}) + "\n",
                        encoding="utf-8",
                    )
                if _sessions_fingerprint(extracted / "sessions") != pointer.sessions_fingerprint_sha256:
                    raise ObjectStorePersistenceError("restored sessions fingerprint mismatch")
                (extracted / "backups-v61").mkdir(exist_ok=True)
                os.replace(extracted, live_root)
                return True
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def attach_existing(self, live_root: Path) -> None:
        pointer = self.read_pointer(required=True)
        assert pointer is not None
        if _sessions_fingerprint(live_root.expanduser().resolve() / "sessions") != pointer.sessions_fingerprint_sha256:
            raise ObjectStorePersistenceError("local durable state does not match current object-store pointer")
        self.last_error = ""

    def _put_immutable(self, key: str, body: bytes) -> None:
        try:
            self.client.put(key, body, if_none_match=True)
        except ObjectStoreConflict:
            existing, _ = self.client.get(key)
            if existing is None or not hmac.compare_digest(existing, body):
                raise

    def _prune(self) -> None:
        try:
            keys = sorted(self.client.list_keys(self.state_prefix))
            for key in keys[: max(0, len(keys) - self.retention)]:
                if self.pointer is None or key != self.pointer.archive_key:
                    self.client.delete(key)
        except Exception:
            return

    def sync_if_changed(self, live_root: Path) -> bool:
        with self._lock:
            session_root = live_root.expanduser().resolve() / "sessions"
            observed = _sessions_fingerprint(session_root)
            if self.pointer is None:
                self.read_pointer(required=True)
            assert self.pointer is not None
            if observed == self.pointer.sessions_fingerprint_sha256:
                self.last_sync_changed = False
                self.last_error = ""
                return False
            generation = self.pointer.generation + 1
            with tempfile.TemporaryDirectory(prefix="cbi-object-sync-") as tmp_name:
                archive = Path(tmp_name) / "state.tar.gz"
                archive_sha, fingerprint = _build_state_archive(session_root, generation, archive)
                body = archive.read_bytes()
                key = f"{self.state_prefix}{generation:020d}-{archive_sha}.tar.gz"
                self._put_immutable(key, body)
                next_pointer = ObjectStorePointer(
                    generation, key, archive_sha, fingerprint, "object_state_v1"
                )
                try:
                    next_pointer.etag = self.client.put(
                        self.pointer_key, next_pointer.to_bytes(), if_match=self.pointer.etag
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
        pointer = self.pointer
        return {
            "enabled": True,
            "mode": "s3-compatible",
            "prefix": self.prefix,
            "generation": pointer.generation if pointer is not None else None,
            "archive_format": pointer.archive_format if pointer is not None else None,
            "last_sync_changed": self.last_sync_changed,
            "last_error": self.last_error or None,
            "cas_fail_closed": True,
            "retention_generations": self.retention,
        }

    def seed_migration_archive(self, archive: Path, expected_sha256: str) -> ObjectStorePointer:
        with self._lock:
            if self.read_pointer(required=False) is not None:
                raise ObjectStorePersistenceError("object store is already seeded")
            archive = archive.expanduser().resolve()
            if not archive.is_file():
                raise ObjectStorePersistenceError(f"migration archive not found: {archive}")
            expected = str(expected_sha256 or "").strip().lower()
            if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
                raise ObjectStorePersistenceError("trusted migration SHA-256 must be 64 hex characters")
            observed = _sha256_file(archive)
            if not hmac.compare_digest(expected, observed):
                raise ObjectStorePersistenceError("trusted migration archive SHA-256 mismatch")
            with tempfile.TemporaryDirectory(prefix="cbi-object-seed-") as tmp_name:
                extracted = _extract_tar_safely(archive, Path(tmp_name), "cbi-cloud-runtime")
                _verify_migration_v1(extracted)
                fingerprint = _sessions_fingerprint(extracted / "sessions")
            body = archive.read_bytes()
            key = f"{self.state_prefix}{0:020d}-migration-{observed}.tar.gz"
            self._put_immutable(key, body)
            pointer = ObjectStorePointer(0, key, observed, fingerprint, "migration_v1")
            pointer.etag = self.client.put(self.pointer_key, pointer.to_bytes(), if_none_match=True)
            self.pointer = pointer
            return pointer
