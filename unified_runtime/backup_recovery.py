from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .resilience import canonical_json, digest, exclusive_file_lock, iso_utc


SNAPSHOT_SCHEMA = "cbi.backup-snapshot.v6.1"
RESTORE_SCHEMA = "cbi.backup-restore.v6.1"
_SNAPSHOT_ID_RE = re.compile(r"^SNAP-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{secrets.token_hex(4)}.tmp")
    payload = (canonical_json(value) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_chain(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(canonical_json(event) + "\n" for event in events).encode("utf-8")
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_valid_chain_prefix(path: Path) -> tuple[list[dict[str, Any]], str]:
    if not path.is_file():
        return [], ""
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return events, f"corrupt JSONL at line {line_number}"
        claimed = event.get("event_hash")
        unsigned = {key: value for key, value in event.items() if key != "event_hash"}
        if event.get("seq") != line_number or event.get("prev_hash") != previous:
            return events, f"hash chain broken at line {line_number}"
        if claimed != digest(unsigned):
            return events, f"event hash mismatch at line {line_number}"
        previous = str(claimed)
        events.append(event)
    return events, ""


def _copy_json_sidecars(source_root: Path, target_root: Path, pattern: str, *, replace: bool) -> list[str]:
    copied: list[str] = []
    if not source_root.is_dir():
        return copied
    target_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_root.glob(pattern)):
        if not source.is_file():
            continue
        try:
            value = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        target = target_root / source.name
        if target.exists() and not replace:
            continue
        _atomic_json(target, value)
        copied.append(source.name)
    return copied


def _append_proven_tail(snapshot_events: list[dict[str, Any]], live_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not snapshot_events:
        return live_events, "NEW_CHAIN_FROM_LIVE_VALID_PREFIX"
    if len(live_events) < len(snapshot_events):
        return snapshot_events, "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT"
    snapshot_tail = snapshot_events[-1]
    live_at_snapshot_tail = live_events[len(snapshot_events) - 1]
    if (
        snapshot_tail.get("seq") != live_at_snapshot_tail.get("seq")
        or snapshot_tail.get("event_hash") != live_at_snapshot_tail.get("event_hash")
    ):
        return snapshot_events, "LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT"
    if len(live_events) == len(snapshot_events):
        return snapshot_events, "NO_LIVE_TAIL"
    return [*snapshot_events, *live_events[len(snapshot_events):]], "REPLAYED_PROVEN_APPEND_ONLY_TAIL"


class BackupRecoveryManager:
    """Logical snapshots for v6 Source-of-Truth state.

    Snapshots are intentionally outside the live session directory and contain
    only validated hash-chain prefixes plus parseable queue sidecars. A corrupt
    tail is reported and excluded rather than copied into a backup.
    """

    def __init__(self, runtime: Any, backup_root: str | Path | None = None):
        self.runtime = runtime
        configured = backup_root or os.environ.get("CBI_BACKUP_ROOT")
        self.backup_root = Path(configured).expanduser().resolve() if configured else (
            runtime.store.root.parent / "backups-v61"
        ).resolve()
        self.source_session_root = runtime.store.root.resolve()
        self.source_fingerprint = hashlib.sha256(str(self.source_session_root).encode("utf-8")).hexdigest()[:12]

    def _snapshot_dirs(self) -> list[Path]:
        if not self.backup_root.is_dir():
            return []
        return sorted(
            (path for path in self.backup_root.iterdir() if path.is_dir() and _SNAPSHOT_ID_RE.fullmatch(path.name)),
            key=lambda path: path.name,
            reverse=True,
        )

    def _read_manifest(self, snapshot_dir: Path) -> dict[str, Any]:
        try:
            manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid backup manifest: {snapshot_dir.name}") from exc
        if manifest.get("schema") != SNAPSHOT_SCHEMA or manifest.get("snapshot_id") != snapshot_dir.name:
            raise ValidationError(f"invalid backup manifest contract: {snapshot_dir.name}")
        return manifest

    def validate_snapshot(self, snapshot: str | Path) -> dict[str, Any]:
        snapshot_dir = Path(snapshot)
        if not snapshot_dir.is_absolute():
            snapshot_dir = self.backup_root / snapshot_dir
        snapshot_dir = snapshot_dir.resolve()
        manifest = self._read_manifest(snapshot_dir)
        if str(manifest.get("source_session_root") or "") != str(self.source_session_root):
            raise ValidationError("snapshot belongs to a different session root")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValidationError("snapshot files manifest missing")
        for relative, expected_hash in files.items():
            path = snapshot_dir / str(relative)
            if not path.is_file() or _sha256_file(path) != str(expected_hash):
                raise ValidationError(f"snapshot file hash mismatch: {relative}")
            if path.suffix == ".jsonl":
                _, error = _read_valid_chain_prefix(path)
                if error:
                    raise ValidationError(f"snapshot chain invalid: {relative}: {error}")
        return {
            "valid": True,
            "snapshot_id": snapshot_dir.name,
            "created_at": manifest.get("created_at"),
            "reasons": list(manifest.get("reasons") or []),
            "file_count": len(files),
            "session_count": len((manifest.get("chains") or {}).get("sessions") or {}),
        }

    def latest_valid_snapshot(self) -> dict[str, Any] | None:
        for snapshot_dir in self._snapshot_dirs():
            try:
                validation = self.validate_snapshot(snapshot_dir)
            except ValidationError:
                continue
            return {**validation, "path": str(snapshot_dir)}
        return None

    def _same_day_snapshot(self, utc_date: str) -> dict[str, Any] | None:
        marker = self.backup_root / f"daily-{self.source_fingerprint}-{utc_date}.json"
        if not marker.is_file():
            return None
        try:
            row = json.loads(marker.read_text(encoding="utf-8-sig"))
            snapshot_id = str(row.get("snapshot_id") or "")
            validation = self.validate_snapshot(snapshot_id)
        except (OSError, json.JSONDecodeError, ValidationError):
            return None
        return {**validation, "path": str(self.backup_root / snapshot_id), "deduplicated": True}

    def ensure_daily_snapshot(self) -> dict[str, Any]:
        utc_date = datetime.now(timezone.utc).date().isoformat()
        existing = self._same_day_snapshot(utc_date)
        if existing is not None:
            return existing
        return self.create_snapshot(["DAILY"], write_daily_marker=True)

    def create_snapshot(self, reasons: str | list[str], *, write_daily_marker: bool = False) -> dict[str, Any]:
        normalized_reasons = [str(reasons)] if isinstance(reasons, str) else [str(value) for value in reasons]
        normalized_reasons = sorted({value.strip().upper() for value in normalized_reasons if value.strip()})
        if not normalized_reasons:
            raise ValidationError("backup reason required")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.backup_root / ".backup.lock", timeout_seconds=120.0):
            created_at = iso_utc()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            snapshot_id = f"SNAP-{stamp}-{secrets.token_hex(6)}"
            temporary = self.backup_root / f".{snapshot_id}.tmp-{os.getpid()}-{secrets.token_hex(3)}"
            final = self.backup_root / snapshot_id
            temporary.mkdir(parents=True, exist_ok=False)
            chains: dict[str, Any] = {"sessions": {}, "canonical": {}, "pending": {}, "host_queue": {}}
            warnings: list[dict[str, str]] = []
            try:
                sessions_dir = temporary / "sessions"
                sessions_dir.mkdir(parents=True, exist_ok=True)
                for source in sorted(self.runtime.store.root.glob("INV-*.jsonl")):
                    investigation_id = source.stem
                    events, error = self.runtime.store.read_valid_prefix(investigation_id)
                    if not events:
                        warnings.append({"component": investigation_id, "warning": error or "empty session chain"})
                        continue
                    target = sessions_dir / source.name
                    _write_chain(target, events)
                    chains["sessions"][investigation_id] = {
                        "seq": int(events[-1]["seq"]),
                        "event_hash": str(events[-1]["event_hash"]),
                        "source_warning": error,
                    }
                    if error:
                        warnings.append({"component": investigation_id, "warning": error})

                chain_specs = [
                    ("canonical", self.runtime.canonical_registry.log.path, temporary / "canonical" / "accounts.jsonl"),
                    ("pending", self.runtime.pending_journal.events.path, temporary / "pending" / "journal-events.jsonl"),
                ]
                queue = self.runtime._v6_queue()
                chain_specs.append(("host_queue", queue.events.path, temporary / "host-queue" / "queue-events.jsonl"))
                for name, source, target in chain_specs:
                    events, error = _read_valid_chain_prefix(source)
                    if events:
                        _write_chain(target, events)
                        chains[name] = {
                            "seq": int(events[-1]["seq"]),
                            "event_hash": str(events[-1]["event_hash"]),
                            "source_warning": error,
                        }
                    else:
                        chains[name] = {"seq": 0, "event_hash": "0" * 64, "source_warning": error}
                    if error:
                        warnings.append({"component": name, "warning": error})

                _copy_json_sidecars(self.runtime.pending_journal.root, temporary / "pending" / "envelopes", "PEND-*.json", replace=True)
                _copy_json_sidecars(queue.root, temporary / "host-queue" / "envelopes", "HOSTQ-*.json", replace=True)

                files: dict[str, str] = {}
                for path in sorted(temporary.rglob("*")):
                    if path.is_file():
                        files[path.relative_to(temporary).as_posix()] = _sha256_file(path)
                manifest = {
                    "schema": SNAPSHOT_SCHEMA,
                    "snapshot_id": snapshot_id,
                    "created_at": created_at,
                    "reasons": normalized_reasons,
                    "source_session_root": str(self.source_session_root),
                    "source_fingerprint": self.source_fingerprint,
                    "source_of_truth_scope": [
                        "SESSION_EVENT_CHAINS",
                        "CANONICAL_REGISTRY",
                        "PENDING_RECEIPT_JOURNAL",
                        "HOST_BUNDLE_QUEUE",
                    ],
                    "mcp_adapter_wal_included": False,
                    "mcp_adapter_wal_recovery_boundary": "RECONCILE_FROM_DURABLE_DOMAIN_STATE",
                    "chains": chains,
                    "warnings": warnings,
                    "files": files,
                }
                _atomic_json(temporary / "manifest.json", manifest)
                os.replace(temporary, final)
                _fsync_directory(self.backup_root)
                validation = self.validate_snapshot(final)
                utc_date = datetime.now(timezone.utc).date().isoformat()
                if write_daily_marker or "DAILY" in normalized_reasons:
                    _atomic_json(
                        self.backup_root / f"daily-{self.source_fingerprint}-{utc_date}.json",
                        {"snapshot_id": snapshot_id, "created_at": created_at, "source_session_root": str(self.source_session_root)},
                    )
                return {
                    **validation,
                    "path": str(final),
                    "deduplicated": False,
                    "warnings": warnings,
                }
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

    def restore_latest_valid_snapshot(
        self,
        target_session_root: str | Path,
        *,
        snapshot_id: str = "",
        replay_live_tail: bool = True,
    ) -> dict[str, Any]:
        target_root = Path(target_session_root).expanduser().resolve()
        if target_root == self.source_session_root:
            raise ValidationError("restore target must be separate from the live session root")
        if target_root.exists() and any(target_root.iterdir()):
            raise ValidationError("restore target must not exist or must be empty")
        if snapshot_id:
            validation = self.validate_snapshot(snapshot_id)
            snapshot_dir = (self.backup_root / snapshot_id).resolve()
        else:
            latest = self.latest_valid_snapshot()
            if latest is None:
                raise ValidationError("no valid backup snapshot available")
            validation = latest
            snapshot_dir = Path(latest["path"])

        target_runtime = self.runtime.__class__(target_root)
        snapshot_sessions = snapshot_dir / "sessions"
        if snapshot_sessions.is_dir():
            for source in sorted(snapshot_sessions.glob("INV-*.jsonl")):
                shutil.copy2(source, target_runtime.store.root / source.name)
        canonical_source = snapshot_dir / "canonical" / "accounts.jsonl"
        if canonical_source.is_file():
            target_runtime.canonical_registry.root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(canonical_source, target_runtime.canonical_registry.log.path)
        pending_source = snapshot_dir / "pending" / "journal-events.jsonl"
        if pending_source.is_file():
            target_runtime.pending_journal.root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pending_source, target_runtime.pending_journal.events.path)
        target_queue = target_runtime._v6_queue()
        host_source = snapshot_dir / "host-queue" / "queue-events.jsonl"
        if host_source.is_file():
            target_queue.root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(host_source, target_queue.events.path)
        _copy_json_sidecars(snapshot_dir / "pending" / "envelopes", target_runtime.pending_journal.root, "PEND-*.json", replace=True)
        _copy_json_sidecars(snapshot_dir / "host-queue" / "envelopes", target_queue.root, "HOSTQ-*.json", replace=True)

        replay_report: dict[str, Any] = {"sessions": {}, "canonical": "NOT_REQUESTED", "pending": "NOT_REQUESTED", "host_queue": "NOT_REQUESTED"}
        replay_conflicts: list[dict[str, str]] = []
        if replay_live_tail:
            live_session_ids = {path.stem for path in self.runtime.store.root.glob("INV-*.jsonl")}
            snapshot_session_ids = {path.stem for path in snapshot_sessions.glob("INV-*.jsonl")} if snapshot_sessions.is_dir() else set()
            for investigation_id in sorted(live_session_ids | snapshot_session_ids):
                live_events, live_error = self.runtime.store.read_valid_prefix(investigation_id)
                target_path = target_runtime.store.path(investigation_id)
                snapshot_events, snapshot_error = _read_valid_chain_prefix(target_path)
                if snapshot_error:
                    raise ValidationError(f"restored snapshot session invalid: {investigation_id}: {snapshot_error}")
                merged, status = _append_proven_tail(snapshot_events, live_events)
                if status == "LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT" or status == "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT":
                    replay_conflicts.append({"component": investigation_id, "reason": status})
                elif merged != snapshot_events:
                    _write_chain(target_path, merged)
                replay_report["sessions"][investigation_id] = {
                    "status": status,
                    "live_prefix_warning": live_error,
                    "restored_seq": int(merged[-1]["seq"]) if merged else 0,
                }

            chain_replays = [
                ("canonical", canonical_source, self.runtime.canonical_registry.log.path, target_runtime.canonical_registry.log.path),
                ("pending", pending_source, self.runtime.pending_journal.events.path, target_runtime.pending_journal.events.path),
                ("host_queue", host_source, self.runtime._v6_queue().events.path, target_queue.events.path),
            ]
            for name, _snapshot_source, live_path, target_path in chain_replays:
                snapshot_events, snapshot_error = _read_valid_chain_prefix(target_path)
                if snapshot_error:
                    raise ValidationError(f"restored snapshot chain invalid: {name}: {snapshot_error}")
                live_events, live_error = _read_valid_chain_prefix(live_path)
                merged, status = _append_proven_tail(snapshot_events, live_events)
                if status in {"LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT", "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT"}:
                    replay_conflicts.append({"component": name, "reason": status})
                elif merged != snapshot_events:
                    _write_chain(target_path, merged)
                replay_report[name] = {"status": status, "live_prefix_warning": live_error, "restored_seq": int(merged[-1]["seq"]) if merged else 0}

            _copy_json_sidecars(self.runtime.pending_journal.root, target_runtime.pending_journal.root, "PEND-*.json", replace=True)
            _copy_json_sidecars(self.runtime._v6_queue().root, target_queue.root, "HOSTQ-*.json", replace=True)

        validation_errors: list[str] = []
        for path in sorted(target_runtime.store.root.glob("INV-*.jsonl")):
            _, error = _read_valid_chain_prefix(path)
            if error:
                validation_errors.append(f"{path.name}: {error}")
        for name, path in (
            ("canonical", target_runtime.canonical_registry.log.path),
            ("pending", target_runtime.pending_journal.events.path),
            ("host_queue", target_queue.events.path),
        ):
            _, error = _read_valid_chain_prefix(path)
            if error:
                validation_errors.append(f"{name}: {error}")
        if validation_errors:
            raise ValidationError("restored target failed hash-chain validation: " + "; ".join(validation_errors))

        return {
            "schema": RESTORE_SCHEMA,
            "snapshot_id": validation["snapshot_id"],
            "source_session_root": str(self.source_session_root),
            "target_session_root": str(target_root),
            "replay_live_tail": replay_live_tail,
            "replay_report": replay_report,
            "replay_conflicts": replay_conflicts,
            "restored_read_only_first": True,
            "hash_chains_valid": True,
        }
