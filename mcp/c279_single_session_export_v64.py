"""Fail-closed zero-write snapshot validator for the temporary v6.4 C279 export.

This module deliberately reads the already-bound session root directly. It does
not instantiate a Runtime, acquire SessionStore locks, access object storage, or
mutate the live root.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from unified_runtime.resilience import digest


_DEFAULT_MAX_BYTES = 2 * 1024 * 1024
_HARD_MAX_BYTES = 8 * 1024 * 1024
_INVESTIGATION_ID_RE = re.compile(r"^INV-[0-9TZ-]+-[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class C279ExportConfig:
    investigation_id: str
    expected_tail_seq: int
    expected_tail_hash: str
    expires_at: datetime
    max_bytes: int


@dataclass(frozen=True)
class C279SessionSnapshot:
    payload: bytes
    snapshot_sha256: str
    byte_length: int
    tail_seq: int
    tail_event_hash: str


class C279ExportError(RuntimeError):
    def __init__(self, code: str, http_status: int) -> None:
        self.code = str(code)
        self.http_status = int(http_status)
        super().__init__(self.code)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def load_export_config(
    env: Mapping[str, str],
    *,
    process_started_at: datetime,
) -> C279ExportConfig | None:
    """Return the one-shot export configuration or None on any invalid input."""

    if str(env.get("CBI_V64_C279_EXPORT_ENABLED", "")).strip().lower() != "true":
        return None
    if process_started_at.tzinfo is None:
        return None
    started = process_started_at.astimezone(timezone.utc)

    investigation_id = str(env.get("CBI_V64_C279_EXPORT_INVESTIGATION_ID", "")).strip()
    if not _INVESTIGATION_ID_RE.fullmatch(investigation_id):
        return None

    expected_hash = str(env.get("CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH", "")).strip().lower()
    if not _SHA256_RE.fullmatch(expected_hash):
        return None

    try:
        expected_seq = int(str(env.get("CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ", "")).strip())
    except (TypeError, ValueError):
        return None
    if expected_seq < 1:
        return None

    expires = _parse_utc(str(env.get("CBI_V64_C279_EXPORT_EXPIRES_AT", "")))
    if expires is None or expires <= started or expires > started + timedelta(minutes=30):
        return None

    raw_max = str(env.get("CBI_V64_C279_EXPORT_MAX_BYTES", "")).strip()
    if raw_max:
        try:
            max_bytes = int(raw_max)
        except ValueError:
            return None
    else:
        max_bytes = _DEFAULT_MAX_BYTES
    if not 1 <= max_bytes <= _HARD_MAX_BYTES:
        return None

    return C279ExportConfig(
        investigation_id=investigation_id,
        expected_tail_seq=expected_seq,
        expected_tail_hash=expected_hash,
        expires_at=expires,
        max_bytes=max_bytes,
    )


def _bounded_read(path: Path, max_bytes: int) -> bytes:
    with path.open("rb") as handle:
        body = handle.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise C279ExportError("SNAPSHOT_TOO_LARGE", 413)
    return body


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _target(config: C279ExportConfig, session_root: Path) -> tuple[Path, Path]:
    if not _INVESTIGATION_ID_RE.fullmatch(config.investigation_id):
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
    try:
        root = Path(session_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409) from exc
    if not root.is_dir():
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)

    candidate = root / f"{config.investigation_id}.jsonl"
    try:
        if candidate.is_symlink():
            raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
        resolved = candidate.resolve(strict=True)
        info = os.stat(resolved, follow_symlinks=False)
    except C279ExportError:
        raise
    except (OSError, RuntimeError) as exc:
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409) from exc
    if resolved.parent != root or not stat.S_ISREG(info.st_mode):
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
    return root, resolved


def _validate_payload(payload: bytes, config: C279ExportConfig) -> tuple[int, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise C279ExportError("SNAPSHOT_INVALID", 409) from exc

    events: list[dict] = []
    previous = "0" * 64
    for line_number, line in enumerate(text.splitlines(), 1):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            raise C279ExportError("SNAPSHOT_INVALID", 409) from exc
        if not isinstance(event, dict):
            raise C279ExportError("SNAPSHOT_INVALID", 409)
        claimed = event.get("event_hash")
        unsigned = {key: value for key, value in event.items() if key != "event_hash"}
        if event.get("seq") != line_number or event.get("prev_hash") != previous:
            raise C279ExportError("SNAPSHOT_INVALID", 409)
        if not isinstance(claimed, str) or claimed != digest(unsigned):
            raise C279ExportError("SNAPSHOT_INVALID", 409)
        events.append(event)
        previous = claimed

    if not events or events[0].get("event_type") != "INVESTIGATION_STARTED":
        raise C279ExportError("SNAPSHOT_INVALID", 409)
    start_payload = events[0].get("payload")
    if not isinstance(start_payload, dict) or start_payload.get("investigation_id") != config.investigation_id:
        raise C279ExportError("SNAPSHOT_INVALID", 409)

    tail = events[-1]
    tail_seq = tail.get("seq")
    tail_hash = tail.get("event_hash")
    if tail_seq != config.expected_tail_seq or tail_hash != config.expected_tail_hash:
        raise C279ExportError("SNAPSHOT_COMMITMENT_MISMATCH", 409)
    return int(tail_seq), str(tail_hash)


def capture_stable_session(
    config: C279ExportConfig,
    session_root: Path,
) -> C279SessionSnapshot:
    """Capture one stable session without locks, sidecars, Runtime, or writes."""

    _root, resolved = _target(config, Path(session_root))
    try:
        pre = os.stat(resolved, follow_symlinks=False)
    except OSError as exc:
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409) from exc
    if not stat.S_ISREG(pre.st_mode):
        raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
    if pre.st_size > config.max_bytes:
        raise C279ExportError("SNAPSHOT_TOO_LARGE", 413)

    first = _bounded_read(resolved, config.max_bytes)
    try:
        mid = os.stat(resolved, follow_symlinks=False)
    except OSError as exc:
        raise C279ExportError("SNAPSHOT_NOT_STABLE", 409) from exc
    second = _bounded_read(resolved, config.max_bytes)
    try:
        post = os.stat(resolved, follow_symlinks=False)
    except OSError as exc:
        raise C279ExportError("SNAPSHOT_NOT_STABLE", 409) from exc

    first_sha256 = hashlib.sha256(first).digest()
    second_sha256 = hashlib.sha256(second).digest()
    if (
        first != second
        or first_sha256 != second_sha256
        or _file_identity(pre) != _file_identity(mid)
        or _file_identity(mid) != _file_identity(post)
    ):
        raise C279ExportError("SNAPSHOT_NOT_STABLE", 409)

    tail_seq, tail_hash = _validate_payload(first, config)
    return C279SessionSnapshot(
        payload=first,
        snapshot_sha256=hashlib.sha256(first).hexdigest(),
        byte_length=len(first),
        tail_seq=tail_seq,
        tail_event_hash=tail_hash,
    )


class _C279ExportCallback:
    def __init__(self, session_root: Path, config: C279ExportConfig) -> None:
        self._session_root = Path(session_root)
        self._config = config

    def is_available(self) -> bool:
        return _utc_now() < self._config.expires_at

    def __call__(self) -> dict[str, Any]:
        if not self.is_available():
            raise C279ExportError("EXPORT_UNAVAILABLE", 404)
        snapshot = capture_stable_session(self._config, self._session_root)
        # Do not release plaintext if the request crossed the expiry boundary
        # while the stable read/hash-chain validation was in progress.
        if not self.is_available():
            raise C279ExportError("EXPORT_UNAVAILABLE", 404)
        return {
            "schema": "cbi.v64-c279-single-session-export.v1",
            "snapshot_sha256": snapshot.snapshot_sha256,
            "byte_length": snapshot.byte_length,
            "tail_seq": snapshot.tail_seq,
            "tail_event_hash": snapshot.tail_event_hash,
            "payload_encoding": "base64",
            "payload": base64.b64encode(snapshot.payload).decode("ascii"),
        }


def build_export_callback(
    session_root: Path,
    env: Mapping[str, str],
    *,
    process_started_at: datetime,
) -> Callable[[], dict[str, Any]] | None:
    config = load_export_config(env, process_started_at=process_started_at)
    if config is None:
        return None
    return _C279ExportCallback(Path(session_root), config)
