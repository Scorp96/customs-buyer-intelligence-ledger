#!/usr/bin/env python3
"""Final v6.1 production entry with automatic backup/recovery guards.

This module layers §132/§133 backup requirements over the already-complete
mutation WAL recovery entry. It does not weaken or replace the 23/23 mutation
reconciliation inventory. Backup snapshots are infrastructure copies of durable
Source-of-Truth state; the live mutation WAL remains authoritative for mutation
reconciliation.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_sync_recovery as _base  # noqa: E402
from unified_runtime.backup_recovery_hardened import ProductionBackupRecoveryManager  # noqa: E402
from unified_runtime.resilience import digest  # noqa: E402


_v61 = _base._v61
_RUNTIME = _base._RUNTIME
_BACKUP = ProductionBackupRecoveryManager.from_runtime(_RUNTIME)
_TOOL_HANDLERS = _v61._server.TOOL_HANDLERS
_ORIGINAL_HANDLERS = dict(_TOOL_HANDLERS)
_MUTATING_TOOLS = set(_v61._MUTATING_TOOLS)
_SYNC_TOOLS = {
    "sync_pending_receipts",
    "sync_pending_bundles",
    "sync_pending_research_bundles",
}


def _snapshot_public(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": value.get("snapshot_id"),
        "created_at": value.get("created_at"),
        "reasons": list(value.get("reasons") or []),
        "path": value.get("path"),
        "deduplicated": value.get("deduplicated") is True,
    }


def _session_upgrade_material(investigation_id: str) -> dict[str, Any] | None:
    investigation_id = str(investigation_id or "").strip()
    if not investigation_id:
        return None
    try:
        events, error = _RUNTIME.store.read_valid_prefix(investigation_id)
    except Exception:
        return None
    if not events:
        return None
    if any(event.get("event_type") == "V6_RUNTIME_INITIALIZED" for event in events):
        return None
    return {
        "investigation_id": investigation_id,
        "last_safe_seq": int(events[-1].get("seq") or 0),
        "last_safe_event_hash": str(events[-1].get("event_hash") or ""),
        "prefix_warning": error,
    }


def _schema_upgrade_targets(tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    if tool_name == "start_investigation":
        return []
    direct = str(arguments.get("investigation_id") or "").strip()
    if direct:
        row = _session_upgrade_material(direct)
        return [row] if row is not None else []
    if tool_name not in _SYNC_TOOLS:
        return []
    targets: list[dict[str, Any]] = []
    for path in sorted(_RUNTIME.store.root.glob("INV-*.jsonl")):
        row = _session_upgrade_material(path.stem)
        if row is not None:
            targets.append(row)
    return targets


def _migration_backup_manager(arguments: dict[str, Any]) -> ProductionBackupRecoveryManager:
    source_root = Path(
        arguments.get("source_session_root") or _RUNTIME.store.root
    ).expanduser().resolve()
    if source_root == Path(_RUNTIME.store.root).resolve():
        return _BACKUP
    return ProductionBackupRecoveryManager.for_session_root(source_root)


def _pre_mutation_backup(tool_name: str, arguments: dict[str, Any]) -> None:
    # Evaluate daily protection immediately before the first production mutation
    # of a UTC day. This preserves startup read-only behavior while ensuring any
    # day that changes durable state has a pre-change snapshot.
    _BACKUP.ensure_daily_snapshot()

    if tool_name == "migrate_v5_4_1_to_v6":
        manager = _migration_backup_manager(arguments)
        guard_key = str(arguments.get("idempotency_key") or digest(arguments))
        manager.ensure_guard_snapshot(
            ["BEFORE_MIGRATION", "BEFORE_SCHEMA_UPGRADE"],
            guard_key,
        )
        return

    upgrade_targets = _schema_upgrade_targets(tool_name, arguments)
    if upgrade_targets:
        _BACKUP.ensure_guard_snapshot(
            ["BEFORE_SCHEMA_UPGRADE"],
            digest({"tool": tool_name, "targets": upgrade_targets}),
        )


def _wrap_mutation(
    tool_name: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def wrapped(arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            return handler(arguments)
        _pre_mutation_backup(tool_name, arguments)
        return handler(arguments)

    return wrapped


for _tool_name in sorted(_MUTATING_TOOLS):
    _handler = _ORIGINAL_HANDLERS.get(_tool_name)
    if _handler is not None:
        _TOOL_HANDLERS[_tool_name] = _wrap_mutation(_tool_name, _handler)


_PREPARE_CRM = _ORIGINAL_HANDLERS.get("prepare_crm_writeback")
if _PREPARE_CRM is not None:
    def _prepare_crm_with_backup(arguments: dict[str, Any]) -> dict[str, Any]:
        plan = _PREPARE_CRM(arguments)
        plan_id = str(plan.get("writeback_plan_id") or "")
        if not plan_id:
            return plan
        backup = _BACKUP.ensure_guard_snapshot(
            ["BEFORE_CRM_COMMIT"],
            plan_id,
        )
        requirements = list(plan.get("requirements") or [])
        if "PRE_COMMIT_BACKUP_SNAPSHOT" not in requirements:
            requirements.append("PRE_COMMIT_BACKUP_SNAPSHOT")
        return {
            **plan,
            "requirements": requirements,
            "pre_commit_backup": _snapshot_public(backup),
            "crm_commit_without_bound_backup_supported": False,
        }

    _TOOL_HANDLERS["prepare_crm_writeback"] = _prepare_crm_with_backup


_BASE_CONTRACT = _ORIGINAL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH = _ORIGINAL_HANDLERS["get_runtime_health"]


def _contract_with_backup(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT(arguments))
    contract["backup_recovery_v6_1"] = {
        "snapshot_schema": "cbi.backup-snapshot.v6.1",
        "restore_schema": "cbi.backup-restore.v6.1",
        "automatic_triggers": [
            "DAILY_BEFORE_FIRST_PRODUCTION_MUTATION",
            "BEFORE_MIGRATION",
            "BEFORE_CRM_COMMIT_VIA_PREPARE_CRM_WRITEBACK",
            "BEFORE_IN_PLACE_SCHEMA_UPGRADE",
        ],
        "snapshot_consistency": "PER_COMPONENT_SERIALIZED_APPEND_ONLY_TAILS",
        "corrupt_tail_policy": "BACK_UP_LAST_VALID_PREFIX_AND_REPORT_WARNING",
        "restore_policy": "STAGE_VALIDATE_ATOMIC_RENAME_TO_SEPARATE_TARGET",
        "restore_overwrites_live_root": False,
        "append_only_tail_replay_requires_snapshot_ancestry_proof": True,
        "divergent_tail_policy": "RESTORE_SNAPSHOT_FAIL_ACTIVATION_READY_FALSE",
        "invalid_live_sidecar_policy": "SKIP_AND_FAIL_ACTIVATION_READY_FALSE",
        "mcp_mutation_wal_in_snapshot": False,
        "mcp_mutation_wal_recovery": "EXISTING_23_OF_23_DOMAIN_RECONCILIATION",
    }
    return contract


def _health_with_backup(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH(arguments))
    health["backup_recovery"] = _BACKUP.status(validate_latest=False)
    return health


_TOOL_HANDLERS["get_runtime_contract"] = _contract_with_backup
_TOOL_HANDLERS["get_runtime_health"] = _health_with_backup


def main() -> int:
    return _base.main()


if __name__ == "__main__":
    raise SystemExit(main())
