"""Migration lineage provenance and split-brain detection for v6.1.

A v5.4 -> v6 migration copies append-only session logs into a distinct target
root and then appends v6 initialization. If the retired v5 source keeps
receiving writes after activation, the two valid hash chains can fork. This
mixin records the exact source snapshot in the target chain and exposes a
read-only lineage health check. It never merges or rewrites divergent history.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from . import v6 as _v6


MIGRATION_PROVENANCE_EVENT = "V6_MIGRATION_PROVENANCE_RECORDED"


class V61MigrationLineageHardeningMixin:
    """Record migration ancestry and detect post-migration source advancement."""

    @staticmethod
    def _session_sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _migration_provenance_from_events(
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        rows = [
            event.get("payload")
            for event in events
            if event.get("event_type") == MIGRATION_PROVENANCE_EVENT
            and isinstance(event.get("payload"), dict)
        ]
        return dict(rows[-1]) if rows else None

    def _migration_lineage_status(
        self,
        investigation_id: str,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if events is None:
            events = self.store.read(investigation_id)
        provenance = self._migration_provenance_from_events(events)
        if provenance is None:
            return {
                "schema": "cbi.migration-lineage-status.v6.1",
                "investigation_id": investigation_id,
                "status": "PROVENANCE_NOT_RECORDED",
                "provenance_recorded": False,
                "split_brain_risk": False,
                "source_advanced_after_migration": None,
                "release_gate": "MANUAL_LINEAGE_DIAGNOSTIC_REQUIRED_FOR_LEGACY_MIGRATIONS",
                "automatic_reconciliation_allowed": False,
            }

        source_file_text = str(provenance.get("source_session_file") or "").strip()
        source_file = Path(source_file_text) if source_file_text else Path()
        snapshot_count = int(provenance.get("source_event_count_at_migration") or 0)
        snapshot_tail = str(provenance.get("source_tail_event_hash_at_migration") or "")
        snapshot_sha = str(provenance.get("source_session_sha256_at_migration") or "")
        base = {
            "schema": "cbi.migration-lineage-status.v6.1",
            "investigation_id": investigation_id,
            "migration_id": provenance.get("migration_id"),
            "provenance_recorded": True,
            "source_session_file": source_file_text,
            "source_event_count_at_migration": snapshot_count,
            "source_tail_event_hash_at_migration": snapshot_tail,
            "source_session_sha256_at_migration": snapshot_sha,
            "automatic_reconciliation_allowed": False,
        }

        if not source_file_text or not source_file.is_file():
            return {
                **base,
                "status": "SOURCE_NOT_PRESENT",
                "split_brain_risk": False,
                "source_advanced_after_migration": None,
                "release_gate": "SOURCE_RETIREMENT_OR_ARCHIVE_STATE_NOT_MECHANICALLY_PROVEN",
            }

        source_root = source_file.parent
        try:
            source_store = self.store.__class__(source_root)
            source_events = source_store.read(investigation_id)
        except (OSError, ValueError, _v6.ValidationError) as exc:
            return {
                **base,
                "status": "SOURCE_INTEGRITY_ERROR",
                "split_brain_risk": True,
                "source_advanced_after_migration": None,
                "release_gate": "BLOCKED",
                "error": f"{type(exc).__name__}: {exc}",
            }

        current_count = len(source_events)
        current_tail = source_events[-1]["event_hash"] if source_events else None
        try:
            current_sha = self._session_sha256(source_file)
        except OSError as exc:
            return {
                **base,
                "status": "SOURCE_READ_ERROR",
                "split_brain_risk": True,
                "source_advanced_after_migration": None,
                "release_gate": "BLOCKED",
                "error": f"{type(exc).__name__}: {exc}",
            }

        current = {
            "source_current_event_count": current_count,
            "source_current_tail_event_hash": current_tail,
            "source_current_session_sha256": current_sha,
        }

        if (
            current_count == snapshot_count
            and current_tail == snapshot_tail
            and current_sha == snapshot_sha
        ):
            return {
                **base,
                **current,
                "status": "SOURCE_UNCHANGED_SINCE_MIGRATION",
                "split_brain_risk": False,
                "source_advanced_after_migration": False,
                "release_gate": "CLEAR",
            }

        if (
            snapshot_count > 0
            and current_count > snapshot_count
            and source_events[snapshot_count - 1].get("event_hash") == snapshot_tail
        ):
            return {
                **base,
                **current,
                "status": "SOURCE_ADVANCED_AFTER_MIGRATION",
                "split_brain_risk": True,
                "source_advanced_after_migration": True,
                "source_post_migration_event_count": current_count - snapshot_count,
                "release_gate": "BLOCKED",
            }

        if current_count < snapshot_count:
            status = "SOURCE_TRUNCATED_AFTER_MIGRATION"
        elif current_count == snapshot_count and current_tail == snapshot_tail:
            status = "SOURCE_RAW_FILE_REWRITTEN_AFTER_MIGRATION"
        else:
            status = "SOURCE_DIVERGED_OR_REWRITTEN_AFTER_MIGRATION"
        return {
            **base,
            **current,
            "status": status,
            "split_brain_risk": True,
            "source_advanced_after_migration": None,
            "release_gate": "BLOCKED",
        }

    def get_investigation_health(self, arguments: dict[str, Any]) -> dict[str, Any]:
        health = super().get_investigation_health(arguments)
        investigation_id = _v6._nonempty(
            arguments.get("investigation_id"),
            "investigation_id",
        )
        if health.get("status") == "QUARANTINED_READ_ONLY":
            return {
                **health,
                "migration_lineage": {
                    "schema": "cbi.migration-lineage-status.v6.1",
                    "investigation_id": investigation_id,
                    "status": "NOT_EVALUATED_DUE_TO_SESSION_INTEGRITY_ERROR",
                    "provenance_recorded": None,
                    "split_brain_risk": None,
                    "automatic_reconciliation_allowed": False,
                },
            }

        events = self.store.read(investigation_id)
        lineage = self._migration_lineage_status(
            investigation_id,
            events=events,
        )
        output = {**health, "migration_lineage": lineage}
        if lineage.get("split_brain_risk") is True:
            output["status"] = "SPLIT_BRAIN_RISK"
            output["migration_lineage_release_blocked"] = True
            output["automatic_history_reconciliation_allowed"] = False
        else:
            output["migration_lineage_release_blocked"] = False
        return output

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract["migration_lineage_v6_1"] = {
            "provenance_event": MIGRATION_PROVENANCE_EVENT,
            "records_source_event_count": True,
            "records_source_tail_event_hash": True,
            "records_source_session_sha256": True,
            "records_source_manifest_sha256": True,
            "detects_source_advance_after_migration": True,
            "detects_source_rewrite_or_divergence": True,
            "split_brain_blocks_release_gate": True,
            "automatic_history_merge": False,
            "automatic_peer_reconciliation_on_divergence": False,
            "health_surface": "get_investigation_health",
        }
        return contract

    def migrate_v5_4_1_to_v6(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _v6._require_object(arguments, "arguments")
        source_root = Path(
            args.get("source_session_root") or self.store.root
        ).resolve()
        target_root = Path(
            _v6._nonempty(args.get("target_root"), "target_root")
        ).resolve()
        if not source_root.is_dir():
            raise _v6.ValidationError(
                "migration source session root does not exist"
            )
        if (
            target_root == source_root
            or source_root in target_root.parents
            or target_root in source_root.parents
        ):
            raise _v6.ValidationError(
                "migration source and target must be distinct, non-overlapping roots"
            )
        if target_root.exists() and any(target_root.iterdir()):
            raise _v6.ValidationError(
                "migration target must not already contain files"
            )
        source_files = sorted(source_root.glob("INV-*.jsonl"))
        if not source_files:
            raise _v6.ValidationError(
                "migration source contains no investigation sessions"
            )

        source_store = self.store.__class__(source_root)
        for source in source_files:
            source_store.read(source.stem)

        explicit_runtime_root = source_root / ".runtime"
        if (
            (explicit_runtime_root / "canonical").is_dir()
            or (explicit_runtime_root / "pending").is_dir()
        ):
            source_canonical_root = explicit_runtime_root / "canonical"
            source_pending_root = explicit_runtime_root / "pending"
        else:
            source_canonical_root = source_root.parent / "canonical"
            source_pending_root = source_root.parent / "pending"

        tracked_roots = {
            "sessions": source_root,
            "canonical": source_canonical_root,
            "pending": source_pending_root,
        }

        def source_manifest() -> dict[str, str]:
            manifest: dict[str, str] = {}
            for label, root in tracked_roots.items():
                if not root.is_dir():
                    continue
                for path in sorted(
                    item
                    for item in root.rglob("*")
                    if item.is_file() and not item.name.endswith(".lock")
                ):
                    manifest[
                        f"{label}/{path.relative_to(root).as_posix()}"
                    ] = hashlib.sha256(path.read_bytes()).hexdigest()
            return manifest

        source_before = source_manifest()
        source_manifest_hash = _v6.digest(source_before)
        session_snapshots: dict[str, dict[str, Any]] = {}
        for source in source_files:
            events = source_store.read(source.stem)
            source_sha = self._session_sha256(source)
            manifest_sha = source_before.get(f"sessions/{source.name}")
            if manifest_sha != source_sha:
                raise _v6.ValidationError(
                    f"{source.name}: source changed while migration snapshot was being captured"
                )
            session_snapshots[source.stem] = {
                "source_session_file": str(source),
                "source_event_count_at_migration": len(events),
                "source_tail_event_hash_at_migration": events[-1]["event_hash"],
                "source_session_sha256_at_migration": source_sha,
            }

        migration_id = _v6._stable_id(
            "MIG",
            {
                "source_root": str(source_root),
                "target_root": str(target_root),
                "source_manifest_sha256": source_manifest_hash,
                "session_snapshots": session_snapshots,
            },
        )

        target_sessions = target_root / "sessions"
        target_sessions.mkdir(parents=True, exist_ok=True)
        for source in source_files:
            shutil.copy2(source, target_sessions / source.name)

        target_runtime = self.__class__(target_sessions)
        if source_canonical_root.is_dir():
            shutil.copytree(
                source_canonical_root,
                target_runtime.canonical_registry.root,
                dirs_exist_ok=True,
            )
        if source_pending_root.is_dir():
            shutil.copytree(
                source_pending_root,
                target_runtime.pending_journal.root,
                dirs_exist_ok=True,
            )

        migrated: list[str] = []
        errors: list[dict[str, str]] = []
        session_provenance: dict[str, dict[str, Any]] = {}
        for source in source_files:
            investigation_id = source.stem
            try:
                target_runtime._ensure_v6(investigation_id)
                target_events = target_runtime.store.read(investigation_id)
                snapshot = session_snapshots[investigation_id]
                payload = {
                    "schema": "cbi.migration-provenance.v6.1",
                    "migration_id": migration_id,
                    "investigation_id": investigation_id,
                    **snapshot,
                    "source_session_root": str(source_root),
                    "source_manifest_sha256_at_migration": source_manifest_hash,
                    "target_root": str(target_root),
                    "target_session_file": str(
                        target_sessions / f"{investigation_id}.jsonl"
                    ),
                    "target_tail_event_hash_before_provenance": target_events[-1][
                        "event_hash"
                    ],
                    "source_must_remain_frozen_or_retired_after_switch": True,
                    "automatic_history_merge_allowed": False,
                    "automatic_peer_reconciliation_allowed": False,
                    "recorded_at": _v6.iso_utc(),
                }
                _v6._walk_no_secrets(payload, "migration_provenance")
                target_runtime.store.append_if_tail(
                    investigation_id,
                    target_events[-1]["event_hash"],
                    MIGRATION_PROVENANCE_EVENT,
                    payload,
                )
                target_runtime.store.read(investigation_id)
                migrated.append(investigation_id)
                session_provenance[investigation_id] = payload
            except (OSError, ValueError, _v6.ValidationError) as exc:
                errors.append(
                    {
                        "investigation_id": investigation_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        source_after = source_manifest()
        source_unchanged = source_before == source_after
        verified = (
            not errors
            and len(migrated) == len(source_files)
            and source_unchanged
        )
        report = {
            "schema": "cbi.migration-report.v6.1",
            "migration_id": migration_id,
            "source_session_root": str(source_root),
            "target_root": str(target_root),
            "source_session_count": len(source_files),
            "migrated_session_count": len(migrated),
            "migrated_investigations": migrated,
            "session_provenance": session_provenance,
            "errors": errors,
            "verified": verified,
            "source_manifest_sha256_before": source_manifest_hash,
            "source_manifest_sha256_after": _v6.digest(source_after),
            "source_unchanged": source_unchanged,
            "source_mutated": not source_unchanged,
            "switch_ready": verified,
            "switched": False,
            "activation_invariant": (
                "The source session root must be frozen or retired before "
                "activating the migrated target. Any later source advancement "
                "is a split-brain release blocker and is never auto-merged."
            ),
            "activation_instruction": (
                "Set CBI_SESSION_ROOT to the migrated sessions directory only "
                "after external acceptance, source retirement/freeze, and restart."
            ),
        }
        (target_root / "V6_MIGRATION_REPORT.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
