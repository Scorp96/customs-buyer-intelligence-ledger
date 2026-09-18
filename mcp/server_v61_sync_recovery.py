#!/usr/bin/env python3
"""Strict correlated fallback and final WAL inventory proof for Sync recovery.

The full batch implementation remains byte-identical in
``server_v61_sync_recovery_base``. This wrapper adds the exact correlated proof
path for a pending-sync child that crashes after ``append_information_record``
has durably appended its event but before the sidecar/child-WAL terminal receipt
is written.

It also computes the final production mutation-WAL completeness declaration
from the live guarded-mutation and automatic-reconciliation sets. The contract
therefore reports complete only when there is mechanically no guarded mutation
family left without an automatic reconciliation implementation; a future new
mutation automatically makes the declaration false until recovery is added.
"""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_sync_recovery_base as _base  # noqa: E402


_v61 = _base._v61
_RUNTIME = _base._RUNTIME
_BASE_RECOVER_TARGET_RESULT = _base._recover_target_result
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]
_INFORMATION_CHILD_PROOF = "CORRELATED_INFORMATION_EVENT_AFTER_CHILD_PREPARED"
_STABLE_INFORMATION_FIELDS = (
    "information_id",
    "investigation_id",
    "related_account_id",
    "subject_owner_id",
    "claim_key",
    "source_reference_type",
    "source_locator",
    "observed_at",
    "content_sha256",
)


def _stable_value(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if field != "observed_at" or not text:
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        return text
    return parsed.astimezone(timezone.utc).isoformat()


def _correlated_information_result(
    arguments: dict[str, Any],
    stored: dict[str, Any],
    path: Path,
    correlation: dict[str, str],
) -> dict[str, Any] | None:
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    raw = arguments.get("record")
    correlation_id = str(correlation.get("correlation_id") or "").strip()
    if not investigation_id or not isinstance(raw, dict) or not correlation_id:
        return None
    information_id = str(raw.get("information_id") or "").strip()
    content_sha256 = str(raw.get("content_sha256") or "").strip().lower()
    if not information_id or not content_sha256:
        return None

    try:
        before = int(stored.get("state_version_before") or 0)
        events = _RUNTIME.store.read(investigation_id)
    except Exception:
        return None

    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in events:
        event_seq = int(event.get("seq") or 0)
        if event_seq <= before or event.get("event_type") != "INFORMATION_RECORD_APPENDED":
            continue
        event_correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(event_correlation, dict) or not isinstance(record, dict):
            continue
        if (
            str(event_correlation.get("correlation_id") or "") != correlation_id
            or str(event_correlation.get("tool") or "") != "append_information_record"
            or str(record.get("information_id") or "") != information_id
            or str(record.get("content_sha256") or "").lower() != content_sha256
        ):
            continue
        if any(
            field in raw
            and _stable_value(field, record.get(field)) != _stable_value(field, raw.get(field))
            for field in _STABLE_INFORMATION_FIELDS
        ):
            continue
        matches.append((event, record))

    if len(matches) != 1:
        return None

    event, record = matches[0]
    event_seq = int(event["seq"])
    information_records: dict[str, dict[str, Any]] = {}
    for row in events:
        if int(row.get("seq") or 0) > event_seq:
            break
        if row.get("event_type") != "INFORMATION_RECORD_APPENDED":
            continue
        payload = row.get("payload")
        item = payload.get("record") if isinstance(payload, dict) else None
        if isinstance(item, dict) and item.get("information_id"):
            information_records[str(item["information_id"])] = item

    historical_count = sum(
        item.get("temporal_status") == "HISTORICAL"
        or item.get("information_type") == "HISTORICAL"
        for item in information_records.values()
    )
    raw_result = {
        "accepted": True,
        "information_id": information_id,
        "append_only": True,
        "historical_records_preserved": historical_count,
        "total_information_records": len(information_records),
        "effective_outreach_eligible": bool(record.get("outreach_eligible_effective")),
        "usage_warnings": list(record.get("usage_warnings") or []),
        "policy": "PRESERVE_HISTORY_APPEND_NEW_INFORMATION_CLASSIFY_USE_SEPARATELY",
    }
    request_hash = str(stored.get("request_sha256") or "")
    committed = {
        **copy.deepcopy(raw_result),
        "mutation_meta": _v61._reconciled_meta(
            "append_information_record",
            stored,
            request_hash,
            event_seq,
            _INFORMATION_CHILD_PROOF,
        ),
    }
    _v61._commit_receipt(path, stored, committed, event_seq)
    return raw_result


def _recover_target_result(
    item_tool: str,
    arguments: dict[str, Any],
    stored: dict[str, Any],
    path: Path,
    correlation: dict[str, str],
) -> dict[str, Any] | None:
    recovered = _BASE_RECOVER_TARGET_RESULT(
        item_tool,
        arguments,
        stored,
        path,
        correlation,
    )
    if recovered is not None:
        return recovered
    if item_tool == "append_information_record":
        return _correlated_information_result(arguments, stored, path, correlation)
    return None


def _reconciliation_inventory() -> tuple[list[str], list[str], list[str]]:
    guarded = sorted(set(_v61._MUTATING_TOOLS))
    automatic = sorted(set(_v61._AUTOMATIC_RECONCILIATION_TOOLS))
    remaining = sorted(set(guarded) - set(automatic))
    return guarded, automatic, remaining


def _contract_with_complete_inventory(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    guarded, automatic, remaining = _reconciliation_inventory()
    wal["guarded_mutation_tools"] = guarded
    wal["automatic_reconciliation_tools"] = automatic
    wal["unreconciled_mutation_tools"] = remaining
    wal["exact_automatic_reconciliation_complete"] = not remaining
    wal["completeness_is_computed_from_live_inventory"] = True
    return contract


def _health_with_complete_inventory(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    guarded, automatic, remaining = _reconciliation_inventory()
    wal = health.setdefault("mutation_wal", {})
    wal["guarded_mutation_tools"] = guarded
    wal["automatic_reconciliation_tools"] = automatic
    wal["unreconciled_mutation_tools"] = remaining
    wal["exact_automatic_reconciliation_complete"] = not remaining
    return health


# The base module's batch functions resolve this global at call time. Replace
# only the proof resolver; selection, child WAL, sidecar persistence, locking,
# fail-closed behavior and public handlers remain unchanged.
_base._recover_target_result = _recover_target_result
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_complete_inventory
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_complete_inventory


from mcp import server_v61_production as _production
from unified_runtime.recovery_semantics_v63 import recover_prepared_v63_mutation
from unified_runtime.wal_contract_v63 import V63_WAL_BINDINGS as _V63_WAL_BINDINGS

_BASE_V63_RECONCILE_PREPARED = _v61._reconcile_prepared

def _v63_normalized_durable_events(arguments, stored):
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    if not investigation_id:
        return []
    try:
        before = int(stored.get("state_version_before") or 0)
        events = _RUNTIME.store.read(investigation_id)
    except Exception:
        return []
    normalized = []
    for event in events:
        seq = int(event.get("seq") or 0)
        if seq <= before:
            continue
        correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        if not isinstance(correlation, dict) or not isinstance(payload, dict):
            continue
        row = dict(payload)
        row["event_type"] = str(event.get("event_type") or "")
        row["correlation_id"] = str(correlation.get("correlation_id") or "")
        row["seq"] = seq
        normalized.append(row)
    return normalized

def _v63_reconcile_prepared(tool_name, args, stored, request_hash, path):
    if tool_name not in _V63_WAL_BINDINGS:
        return _BASE_V63_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)
    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if not correlation_id:
        return None
    recovered = recover_prepared_v63_mutation(tool_name, args, expected_correlation_id=correlation_id, durable_events=_v63_normalized_durable_events(args, stored))
    if recovered.get("status") != "RECOVERED":
        return None
    event_seq = int(recovered.get("event_seq") or 0)
    raw_result = recovered.get("result")
    if event_seq <= int(stored.get("state_version_before") or 0) or not isinstance(raw_result, dict):
        return None
    return _production._finish_reconciliation(tool_name, stored, request_hash, path, raw_result, event_seq, str(recovered.get("proof") or "V63_EXACT_CORRELATED_DURABLE_EVENT"))

_v61._reconcile_prepared = _v63_reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.update(_V63_WAL_BINDINGS)


def main() -> int:
    return _base.main()


if __name__ == "__main__":
    raise SystemExit(main())
