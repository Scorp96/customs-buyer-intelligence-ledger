from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .backup_recovery import (
    RESTORE_SCHEMA,
    SNAPSHOT_SCHEMA,
    _append_proven_tail,
    _atomic_json,
    _fsync_directory,
    _read_valid_chain_prefix,
    _sha256_file,
    _write_chain,
)
from .errors import ValidationError
from .resilience import digest, exclusive_file_lock, iso_utc


_SNAPSHOT_ID_RE = re.compile(r"^SNAP-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
_PENDING_ID_RE = re.compile(r"^PEND-[0-9TZ-]+-[0-9a-f]{12}$")
_HOST_ID_RE = re.compile(r"^HOSTQ-[0-9TZ-]+-[0-9a-f]{12}$")


def _normalize_reasons(reasons: str | list[str] | tuple[str, ...]) -> list[str]:
    values = [reasons] if isinstance(reasons, str) else list(reasons)
    result = sorted({str(value).strip().upper() for value in values if str(value).strip()})
    if not result:
        raise ValidationError("backup reason required")
    return result


def _overlaps(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _safe_member(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate == root.resolve() or root.resolve() not in candidate.parents:
        raise ValidationError("snapshot member escapes snapshot root")
    return candidate


def _read_chain_locked(path: Path, lock_path: Path) -> tuple[list[dict[str, Any]], str]:
    if not path.parent.is_dir():
        return [], ""
    with exclusive_file_lock(lock_path, timeout_seconds=60.0):
        return _read_valid_chain_prefix(path)


def _pending_validator(path: Path, value: dict[str, Any]) -> None:
    journal_id = str(value.get("journal_id") or "")
    target_tool = str(value.get("target_tool") or "")
    payload = value.get("payload")
    if path.stem != journal_id or not _PENDING_ID_RE.fullmatch(journal_id):
        raise ValidationError("pending envelope ID mismatch")
    if not target_tool or not isinstance(payload, dict):
        raise ValidationError("pending envelope target/payload invalid")
    if value.get("request_sha256") != digest({"target_tool": target_tool, "payload": payload}):
        raise ValidationError("pending envelope request hash mismatch")


def _host_validator(path: Path, value: dict[str, Any]) -> None:
    queue_id = str(value.get("bundle_queue_id") or "")
    payload = value.get("payload")
    if path.stem != queue_id or not _HOST_ID_RE.fullmatch(queue_id):
        raise ValidationError("host envelope ID mismatch")
    if not isinstance(payload, dict):
        raise ValidationError("host envelope payload invalid")
    if value.get("request_sha256") != digest(payload):
        raise ValidationError("host envelope request hash mismatch")


def _sidecars(
    root: Path,
    pattern: str,
    validator: Callable[[Path, dict[str, Any]], None],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    rows: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []
    if not root.is_dir():
        return rows, warnings
    for path in sorted(root.glob(pattern)):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict):
                raise ValidationError("sidecar JSON object required")
            validator(path, value)
            rows[path.name] = value
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            warnings.append({"component": path.name, "warning": str(exc)})
    return rows, warnings


def _write_sidecars(rows: dict[str, dict[str, Any]], target: Path) -> None:
    for name, value in rows.items():
        _atomic_json(target / name, value)


class ProductionBackupRecoveryManager:
    """Fail-closed §132/§133 backup and recovery manager.

    Snapshots contain only validated append-only prefixes and valid queue
    sidecars. Restore never writes the live roots: it stages an isolated target,
    validates every restored chain, then atomically renames the staging tree.
    """

    def __init__(
        self,
        *,
        session_root: str | Path,
        canonical_root: str | Path,
        pending_root: str | Path,
        host_root: str | Path,
        backup_root: str | Path | None = None,
    ):
        self.source_session_root = Path(session_root).expanduser().resolve()
        self.canonical_root = Path(canonical_root).expanduser().resolve()
        self.pending_root = Path(pending_root).expanduser().resolve()
        self.host_root = Path(host_root).expanduser().resolve()
        configured = backup_root or os.environ.get("CBI_BACKUP_ROOT")
        self.backup_root = (
            Path(configured).expanduser().resolve()
            if configured
            else (self.source_session_root.parent / "backups-v61").resolve()
        )
        self.source_fingerprint = hashlib.sha256(
            str(self.source_session_root).encode("utf-8")
        ).hexdigest()[:12]

    @classmethod
    def from_runtime(
        cls,
        runtime: Any,
        backup_root: str | Path | None = None,
    ) -> "ProductionBackupRecoveryManager":
        return cls(
            session_root=runtime.store.root,
            canonical_root=runtime.canonical_registry.root,
            pending_root=runtime.pending_journal.root,
            host_root=runtime._v6_queue().root,
            backup_root=backup_root,
        )

    @classmethod
    def for_session_root(
        cls,
        session_root: str | Path,
        backup_root: str | Path | None = None,
    ) -> "ProductionBackupRecoveryManager":
        root = Path(session_root).expanduser().resolve()
        explicit = root / ".runtime"
        canonical = explicit / "canonical" if (explicit / "canonical").is_dir() else root.parent / "canonical"
        pending = explicit / "pending" if (explicit / "pending").is_dir() else root.parent / "pending"
        parent_host = root.parent / "host-pending-v6"
        host = parent_host if parent_host.is_dir() else explicit / "host-pending-v6"
        return cls(
            session_root=root,
            canonical_root=canonical,
            pending_root=pending,
            host_root=host,
            backup_root=backup_root,
        )

    def _snapshot_dirs(self) -> list[Path]:
        if not self.backup_root.is_dir():
            return []
        return sorted(
            [
                path
                for path in self.backup_root.iterdir()
                if path.is_dir() and _SNAPSHOT_ID_RE.fullmatch(path.name)
            ],
            key=lambda path: path.name,
            reverse=True,
        )

    def _manifest(self, snapshot_dir: Path) -> dict[str, Any]:
        try:
            value = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid backup manifest: {snapshot_dir.name}") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != SNAPSHOT_SCHEMA
            or value.get("snapshot_id") != snapshot_dir.name
        ):
            raise ValidationError(f"invalid backup manifest contract: {snapshot_dir.name}")
        return value

    def validate_snapshot(self, snapshot: str | Path) -> dict[str, Any]:
        snapshot_dir = Path(snapshot)
        if not snapshot_dir.is_absolute():
            snapshot_dir = self.backup_root / snapshot_dir
        snapshot_dir = snapshot_dir.resolve()
        if snapshot_dir.parent != self.backup_root.resolve() or not _SNAPSHOT_ID_RE.fullmatch(snapshot_dir.name):
            raise ValidationError("snapshot path outside configured backup root")
        manifest = self._manifest(snapshot_dir)
        if manifest.get("source_session_root") != str(self.source_session_root):
            raise ValidationError("snapshot belongs to a different session root")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValidationError("snapshot files manifest missing")
        actual = {
            path.relative_to(snapshot_dir).as_posix()
            for path in snapshot_dir.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        if set(files) != actual:
            raise ValidationError("snapshot file inventory mismatch")
        for relative, expected in files.items():
            path = _safe_member(snapshot_dir, str(relative))
            if path.is_symlink() or not path.is_file():
                raise ValidationError(f"snapshot member invalid: {relative}")
            if _sha256_file(path) != str(expected):
                raise ValidationError(f"snapshot file hash mismatch: {relative}")
            if path.suffix == ".jsonl":
                _, error = _read_valid_chain_prefix(path)
                if error:
                    raise ValidationError(f"snapshot chain invalid: {relative}: {error}")
            elif path.suffix == ".json":
                try:
                    value = json.loads(path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValidationError(f"snapshot JSON invalid: {relative}") from exc
                if relative.startswith("pending/envelopes/"):
                    _pending_validator(path, value)
                elif relative.startswith("host-queue/envelopes/"):
                    _host_validator(path, value)
        return {
            "valid": True,
            "snapshot_id": snapshot_dir.name,
            "created_at": manifest.get("created_at"),
            "reasons": list(manifest.get("reasons") or []),
            "warnings": list(manifest.get("warnings") or []),
            "file_count": len(files),
            "session_count": len((manifest.get("chains") or {}).get("sessions") or {}),
        }

    def latest_valid_snapshot(self) -> dict[str, Any] | None:
        for path in self._snapshot_dirs():
            try:
                result = self.validate_snapshot(path)
            except ValidationError:
                continue
            return {**result, "path": str(path)}
        return None

    def _capture_sessions(self) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
        if not self.source_session_root.is_dir():
            raise ValidationError("backup source session root does not exist")
        rows: dict[str, list[dict[str, Any]]] = {}
        warnings: list[dict[str, str]] = []
        for path in sorted(self.source_session_root.glob("INV-*.jsonl")):
            events, error = _read_chain_locked(
                path,
                self.source_session_root / f".{path.stem}.write.lock",
            )
            if events:
                rows[path.stem] = events
            if error or not events:
                warnings.append(
                    {"component": path.stem, "warning": error or "empty session chain"}
                )
        return rows, warnings

    def _capture_canonical(self) -> tuple[list[dict[str, Any]], str]:
        path = self.canonical_root / "accounts.jsonl"
        if not self.canonical_root.is_dir():
            return [], ""
        with exclusive_file_lock(self.canonical_root / "registry-write.lock", timeout_seconds=60.0):
            return _read_chain_locked(path, path.with_suffix(path.suffix + ".lock"))

    def _capture_pending(
        self,
    ) -> tuple[list[dict[str, Any]], str, dict[str, dict[str, Any]], list[dict[str, str]]]:
        path = self.pending_root / "journal-events.jsonl"
        if not self.pending_root.is_dir():
            return [], "", {}, []
        with ExitStack() as stack:
            stack.enter_context(exclusive_file_lock(self.pending_root / "journal-write.lock", timeout_seconds=60.0))
            stack.enter_context(exclusive_file_lock(self.pending_root / "journal-sync.lock", timeout_seconds=60.0))
            stack.enter_context(exclusive_file_lock(path.with_suffix(path.suffix + ".lock"), timeout_seconds=60.0))
            events, error = _read_valid_chain_prefix(path)
            sidecars, warnings = _sidecars(self.pending_root, "PEND-*.json", _pending_validator)
        return events, error, sidecars, warnings

    def _capture_host(
        self,
    ) -> tuple[list[dict[str, Any]], str, dict[str, dict[str, Any]], list[dict[str, str]]]:
        path = self.host_root / "queue-events.jsonl"
        if not self.host_root.is_dir():
            return [], "", {}, []
        with ExitStack() as stack:
            stack.enter_context(exclusive_file_lock(self.host_root / "host-queue-write.lock", timeout_seconds=60.0))
            stack.enter_context(exclusive_file_lock(self.host_root / "host-queue-sync.lock", timeout_seconds=60.0))
            stack.enter_context(exclusive_file_lock(path.with_suffix(path.suffix + ".lock"), timeout_seconds=60.0))
            events, error = _read_valid_chain_prefix(path)
            sidecars, warnings = _sidecars(self.host_root, "HOSTQ-*.json", _host_validator)
        return events, error, sidecars, warnings

    @staticmethod
    def _tail(events: list[dict[str, Any]], warning: str = "") -> dict[str, Any]:
        return {
            "seq": int(events[-1]["seq"]) if events else 0,
            "event_hash": str(events[-1]["event_hash"]) if events else "0" * 64,
            "source_warning": warning,
        }

    def _create_locked(self, reasons: list[str]) -> dict[str, Any]:
        snapshot_id = (
            "SNAP-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + secrets.token_hex(6)
        )
        temp = self.backup_root / f".{snapshot_id}.tmp-{os.getpid()}-{secrets.token_hex(3)}"
        final = self.backup_root / snapshot_id
        temp.mkdir(parents=True, exist_ok=False)
        warnings: list[dict[str, str]] = []
        try:
            sessions, session_warnings = self._capture_sessions()
            warnings.extend(session_warnings)
            canonical, canonical_error = self._capture_canonical()
            pending, pending_error, pending_sidecars, pending_warnings = self._capture_pending()
            host, host_error, host_sidecars, host_warnings = self._capture_host()
            warnings.extend(pending_warnings)
            warnings.extend(host_warnings)
            for name, error in (
                ("canonical", canonical_error),
                ("pending", pending_error),
                ("host_queue", host_error),
            ):
                if error:
                    warnings.append({"component": name, "warning": error})

            for investigation_id, events in sessions.items():
                _write_chain(temp / "sessions" / f"{investigation_id}.jsonl", events)
            if canonical:
                _write_chain(temp / "canonical" / "accounts.jsonl", canonical)
            if pending:
                _write_chain(temp / "pending" / "journal-events.jsonl", pending)
            if host:
                _write_chain(temp / "host-queue" / "queue-events.jsonl", host)
            _write_sidecars(pending_sidecars, temp / "pending" / "envelopes")
            _write_sidecars(host_sidecars, temp / "host-queue" / "envelopes")

            files = {
                path.relative_to(temp).as_posix(): _sha256_file(path)
                for path in sorted(temp.rglob("*"))
                if path.is_file()
            }
            manifest = {
                "schema": SNAPSHOT_SCHEMA,
                "snapshot_id": snapshot_id,
                "created_at": iso_utc(),
                "reasons": reasons,
                "source_session_root": str(self.source_session_root),
                "source_fingerprint": self.source_fingerprint,
                "source_roots": {
                    "canonical": str(self.canonical_root),
                    "pending": str(self.pending_root),
                    "host_queue": str(self.host_root),
                },
                "snapshot_consistency": "PER_COMPONENT_SERIALIZED_APPEND_ONLY_TAILS",
                "source_of_truth_scope": [
                    "SESSION_EVENT_CHAINS",
                    "CANONICAL_REGISTRY",
                    "PENDING_RECEIPT_JOURNAL",
                    "HOST_BUNDLE_QUEUE",
                ],
                "mcp_adapter_wal_included": False,
                "mcp_adapter_wal_recovery_boundary": "RECONCILE_FROM_DURABLE_DOMAIN_STATE",
                "chains": {
                    "sessions": {
                        key: self._tail(events)
                        for key, events in sessions.items()
                    },
                    "canonical": self._tail(canonical, canonical_error),
                    "pending": self._tail(pending, pending_error),
                    "host_queue": self._tail(host, host_error),
                },
                "warnings": warnings,
                "files": files,
            }
            _atomic_json(temp / "manifest.json", manifest)
            os.replace(temp, final)
            _fsync_directory(self.backup_root)
            result = self.validate_snapshot(final)
            return {**result, "path": str(final), "deduplicated": False}
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise

    def create_snapshot(self, reasons: str | list[str] | tuple[str, ...]) -> dict[str, Any]:
        normalized = _normalize_reasons(reasons)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.backup_root / ".backup.lock", timeout_seconds=120.0):
            return self._create_locked(normalized)

    def _marker(self, prefix: str, key: str) -> Path:
        token = hashlib.sha256(
            f"{self.source_fingerprint}|{prefix}|{key}".encode("utf-8")
        ).hexdigest()[:20]
        return self.backup_root / f"{prefix}-{self.source_fingerprint}-{token}.json"

    def _marker_snapshot(self, marker: Path) -> dict[str, Any] | None:
        try:
            if not marker.is_file():
                return None
            row = json.loads(marker.read_text(encoding="utf-8-sig"))
            result = self.validate_snapshot(str(row.get("snapshot_id") or ""))
            return {
                **result,
                "path": str(self.backup_root / result["snapshot_id"]),
                "deduplicated": True,
                "marker": str(marker),
            }
        except (OSError, json.JSONDecodeError, ValidationError):
            return None

    def ensure_daily_snapshot(self) -> dict[str, Any]:
        date = datetime.now(timezone.utc).date().isoformat()
        marker = self._marker("daily", date)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.backup_root / ".backup.lock", timeout_seconds=120.0):
            existing = self._marker_snapshot(marker)
            if existing is not None:
                return existing
            result = self._create_locked(["DAILY"])
            _atomic_json(marker, {"snapshot_id": result["snapshot_id"], "created_at": result["created_at"], "utc_date": date})
            return {**result, "marker": str(marker)}

    def ensure_guard_snapshot(
        self,
        reasons: str | list[str] | tuple[str, ...],
        guard_key: str,
    ) -> dict[str, Any]:
        normalized = _normalize_reasons(reasons)
        if not str(guard_key).strip():
            raise ValidationError("backup guard_key required")
        label = "guard-" + "-".join(normalized).lower().replace("_", "-")
        marker = self._marker(label, str(guard_key))
        self.backup_root.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.backup_root / ".backup.lock", timeout_seconds=120.0):
            existing = self._marker_snapshot(marker)
            if existing is not None:
                return existing
            result = self._create_locked(normalized)
            _atomic_json(marker, {
                "snapshot_id": result["snapshot_id"],
                "created_at": result["created_at"],
                "reasons": normalized,
                "guard_key_sha256": hashlib.sha256(str(guard_key).encode("utf-8")).hexdigest(),
            })
            return {**result, "marker": str(marker)}

    def status(self, *, validate_latest: bool = True) -> dict[str, Any]:
        latest = self.latest_valid_snapshot() if validate_latest else None
        if not validate_latest:
            dirs = self._snapshot_dirs()
            if dirs:
                try:
                    manifest = self._manifest(dirs[0])
                    latest = {
                        "snapshot_id": dirs[0].name,
                        "created_at": manifest.get("created_at"),
                        "reasons": list(manifest.get("reasons") or []),
                        "path": str(dirs[0]),
                        "validation_deferred": True,
                    }
                except ValidationError:
                    latest = {"snapshot_id": dirs[0].name, "path": str(dirs[0]), "manifest_readable": False}
        date = datetime.now(timezone.utc).date().isoformat()
        daily = self._marker_snapshot(self._marker("daily", date)) if validate_latest else None
        return {
            "schema": "cbi.backup-status.v6.1",
            "source_session_root": str(self.source_session_root),
            "backup_root": str(self.backup_root),
            "latest": latest,
            "daily_snapshot_present": daily is not None if validate_latest else self._marker("daily", date).is_file(),
            "daily_snapshot": daily,
            "restore_overwrites_live_root": False,
        }

    def _safe_target(self, target: Path) -> None:
        for protected in (
            self.source_session_root,
            self.canonical_root,
            self.pending_root,
            self.host_root,
            self.backup_root,
        ):
            if _overlaps(target, protected):
                raise ValidationError(f"restore target overlaps protected root: {protected}")
        if target.exists():
            raise ValidationError("restore target must not already exist")

    def _merge_component(
        self,
        name: str,
        snapshot_path: Path,
        live_events: list[dict[str, Any]],
        live_warning: str,
        conflicts: list[dict[str, str]],
    ) -> dict[str, Any]:
        snapshot_events, snapshot_error = _read_valid_chain_prefix(snapshot_path)
        if snapshot_error:
            raise ValidationError(f"restored snapshot chain invalid: {name}: {snapshot_error}")
        merged, status = _append_proven_tail(snapshot_events, live_events)
        if status in {"LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT", "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT"}:
            conflicts.append({"component": name, "reason": status})
        elif merged != snapshot_events:
            _write_chain(snapshot_path, merged)
        return {
            "status": status,
            "live_prefix_warning": live_warning,
            "restored_seq": int(merged[-1]["seq"]) if merged else 0,
        }

    def restore_latest_valid_snapshot(
        self,
        target_session_root: str | Path,
        *,
        snapshot_id: str = "",
        replay_live_tail: bool = True,
    ) -> dict[str, Any]:
        target = Path(target_session_root).expanduser().resolve()
        self._safe_target(target)
        validation = (
            self.validate_snapshot(snapshot_id)
            if snapshot_id
            else self.latest_valid_snapshot()
        )
        if validation is None:
            raise ValidationError("no valid backup snapshot available")
        snapshot = self.backup_root / validation["snapshot_id"]

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.restore-{os.getpid()}-{secrets.token_hex(4)}"
        staging.mkdir(parents=False, exist_ok=False)
        staged_canonical = staging / ".runtime" / "canonical"
        staged_pending = staging / ".runtime" / "pending"
        staged_host = staging / ".runtime" / "host-pending-v6"
        conflicts: list[dict[str, str]] = []
        replay: dict[str, Any] = {"sessions": {}, "canonical": "NOT_REQUESTED", "pending": "NOT_REQUESTED", "host_queue": "NOT_REQUESTED"}
        try:
            session_snapshot = snapshot / "sessions"
            if session_snapshot.is_dir():
                for source in session_snapshot.glob("INV-*.jsonl"):
                    shutil.copy2(source, staging / source.name)
            for source, destination in (
                (snapshot / "canonical" / "accounts.jsonl", staged_canonical / "accounts.jsonl"),
                (snapshot / "pending" / "journal-events.jsonl", staged_pending / "journal-events.jsonl"),
                (snapshot / "host-queue" / "queue-events.jsonl", staged_host / "queue-events.jsonl"),
            ):
                if source.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            pending_snapshot, pending_snapshot_warn = _sidecars(snapshot / "pending" / "envelopes", "PEND-*.json", _pending_validator)
            host_snapshot, host_snapshot_warn = _sidecars(snapshot / "host-queue" / "envelopes", "HOSTQ-*.json", _host_validator)
            if pending_snapshot_warn or host_snapshot_warn:
                raise ValidationError("validated snapshot contains invalid sidecar")
            _write_sidecars(pending_snapshot, staged_pending)
            _write_sidecars(host_snapshot, staged_host)

            if replay_live_tail:
                ids = {path.stem for path in self.source_session_root.glob("INV-*.jsonl")}
                if session_snapshot.is_dir():
                    ids |= {path.stem for path in session_snapshot.glob("INV-*.jsonl")}
                for investigation_id in sorted(ids):
                    live_events, live_error = _read_chain_locked(
                        self.source_session_root / f"{investigation_id}.jsonl",
                        self.source_session_root / f".{investigation_id}.write.lock",
                    )
                    replay["sessions"][investigation_id] = self._merge_component(
                        investigation_id,
                        staging / f"{investigation_id}.jsonl",
                        live_events,
                        live_error,
                        conflicts,
                    )

                canonical, canonical_error = self._capture_canonical()
                replay["canonical"] = self._merge_component(
                    "canonical",
                    staged_canonical / "accounts.jsonl",
                    canonical,
                    canonical_error,
                    conflicts,
                )

                pending, pending_error, pending_sidecars, pending_warnings = self._capture_pending()
                pending_result = self._merge_component(
                    "pending",
                    staged_pending / "journal-events.jsonl",
                    pending,
                    pending_error,
                    conflicts,
                )
                if pending_result["status"] not in {"LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT", "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT"}:
                    _write_sidecars(pending_sidecars, staged_pending)
                for warning in pending_warnings:
                    conflicts.append({"component": f"pending:{warning['component']}", "reason": "INVALID_LIVE_SIDECAR_SKIPPED"})
                pending_result["sidecar_warnings"] = pending_warnings
                replay["pending"] = pending_result

                host, host_error, host_sidecars, host_warnings = self._capture_host()
                host_result = self._merge_component(
                    "host_queue",
                    staged_host / "queue-events.jsonl",
                    host,
                    host_error,
                    conflicts,
                )
                if host_result["status"] not in {"LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT", "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT"}:
                    _write_sidecars(host_sidecars, staged_host)
                for warning in host_warnings:
                    conflicts.append({"component": f"host_queue:{warning['component']}", "reason": "INVALID_LIVE_SIDECAR_SKIPPED"})
                host_result["sidecar_warnings"] = host_warnings
                replay["host_queue"] = host_result

            errors: list[str] = []
            for path in staging.glob("INV-*.jsonl"):
                _, error = _read_valid_chain_prefix(path)
                if error:
                    errors.append(f"{path.name}: {error}")
            for name, path in (
                ("canonical", staged_canonical / "accounts.jsonl"),
                ("pending", staged_pending / "journal-events.jsonl"),
                ("host_queue", staged_host / "queue-events.jsonl"),
            ):
                _, error = _read_valid_chain_prefix(path)
                if error:
                    errors.append(f"{name}: {error}")
            for root, pattern, validator in (
                (staged_pending, "PEND-*.json", _pending_validator),
                (staged_host, "HOSTQ-*.json", _host_validator),
            ):
                _, warnings = _sidecars(root, pattern, validator)
                errors.extend(f"{row['component']}: {row['warning']}" for row in warnings)
            if errors:
                raise ValidationError("restored target failed validation: " + "; ".join(errors))

            report = {
                "schema": RESTORE_SCHEMA,
                "snapshot_id": validation["snapshot_id"],
                "snapshot_created_at": validation.get("created_at"),
                "source_session_root": str(self.source_session_root),
                "target_session_root": str(target),
                "replay_live_tail": replay_live_tail,
                "replay_report": replay,
                "replay_conflicts": conflicts,
                "hash_chains_valid": True,
                "live_root_overwritten": False,
                "staged_restore": True,
                "target_not_activated": True,
                "activation_ready": not conflicts,
                "activation_environment": {
                    "CBI_SESSION_ROOT": str(target),
                    "CBI_CANONICAL_ROOT": str(target / ".runtime" / "canonical"),
                    "CBI_PENDING_ROOT": str(target / ".runtime" / "pending"),
                    "CBI_HOST_PENDING_ROOT": str(target / ".runtime" / "host-pending-v6"),
                },
                "activation_instruction": "Review V6_RESTORE_REPORT.json, then activate the returned roots and restart.",
            }
            _atomic_json(staging / "V6_RESTORE_REPORT.json", report)
            os.replace(staging, target)
            _fsync_directory(target.parent)
            return report
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
