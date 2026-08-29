#!/usr/bin/env python3
"""Exact append_peer_receipt crash recovery over research-bundle recovery.

Both successful append_peer_receipt branches are append-only and persist enough
material to reconstruct the original public result without re-running Runtime
validation or side effects:

* PEER_VALIDATION -> PEER_RECEIPT_APPENDED {receipt: normalized_receipt}
* ANCHOR_EXPANSION -> ANCHOR_EXPANSION_CLOSED {anchor_id, branch_status, ...}

Recovery requires exactly one event after WAL PREPARED, bound to the same
mutation correlation. Missing, ambiguous, uncorrelated, or no-event outcomes
remain fail-closed.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_bundle_recovery as _bundle  # noqa: E402


_v61 = _bundle._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]

_PROOFS = {
    "PEER_VALIDATION": "CORRELATED_PEER_RECEIPT_EVENT",
    "ANCHOR_EXPANSION": "CORRELATED_ANCHOR_EXPANSION_CLOSED_EVENT",
}
_EVENT_TYPES = {
    "PEER_VALIDATION": "PEER_RECEIPT_APPENDED",
    "ANCHOR_EXPANSION": "ANCHOR_EXPANSION_CLOSED",
}
_UPPER_FIELDS = {
    "promotion_decision",
    "target_fit_grade",
    "promotion_evidence_grade",
    "canonical_status",
}


def _receipt_type(args: dict[str, Any]) -> str:
    return str(args.get("receipt_type") or "PEER_VALIDATION").upper()


def _normalized_request_value(key: str, value: Any) -> Any:
    if key in _UPPER_FIELDS:
        return str(value or "").upper()
    return value


def _peer_validation_matches(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    requested = args.get("receipt")
    persisted = payload.get("receipt")
    if not isinstance(requested, dict) or not isinstance(persisted, dict):
        return False
    for key, value in requested.items():
        if persisted.get(key) != _normalized_request_value(key, value):
            return False
    return (
        bool(str(persisted.get("peer_id") or ""))
        and str(persisted.get("promotion_decision") or "")
        in {"PROMOTE", "DO_NOT_PROMOTE"}
    )


def _anchor_expansion_matches(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    return (
        str(payload.get("anchor_id") or "") == str(args.get("anchor_id") or "")
        and args.get("cycle_dedup_checked") is True
        and payload.get("cycle_dedup_checked") is True
        and isinstance(payload.get("branch_status"), dict)
        and isinstance(payload.get("discovered_peer_ids"), list)
    )


def _matching_event(
    args: dict[str, Any],
    stored: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    receipt_type = _receipt_type(args)
    event_type = _EVENT_TYPES.get(receipt_type)
    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if not investigation_id or event_type is None or not correlation_id:
        return None
    try:
        before = int(stored.get("state_version_before") or 0)
        events = _RUNTIME.store.read(investigation_id)
    except Exception:
        return None
    matches: list[dict[str, Any]] = []
    for event in events:
        if int(event.get("seq") or 0) <= before:
            continue
        if event.get("event_type") != event_type:
            continue
        correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        if not isinstance(correlation, dict) or not isinstance(payload, dict):
            continue
        if (
            str(correlation.get("correlation_id") or "") != correlation_id
            or str(correlation.get("tool") or "") != "append_peer_receipt"
        ):
            continue
        if receipt_type == "PEER_VALIDATION":
            valid = _peer_validation_matches(args, payload)
        else:
            valid = _anchor_expansion_matches(args, payload)
        if valid:
            matches.append(event)
    if len(matches) != 1:
        return None
    return receipt_type, matches[0]


def _raw_result(receipt_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if receipt_type == "ANCHOR_EXPANSION":
        return {
            "accepted": True,
            "receipt_type": "ANCHOR_EXPANSION",
            "anchor_id": payload["anchor_id"],
            "branch_status": copy.deepcopy(payload["branch_status"]),
        }
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        return None
    return {
        "accepted": True,
        "receipt_type": "PEER_VALIDATION",
        "peer_id": receipt.get("peer_id"),
        "promotion_decision": receipt.get("promotion_decision"),
        "promotion_gate": receipt.get("promotion_gate", "NOT_REQUIRED"),
        "anchor_depth": receipt.get("anchor_depth"),
        "promotion_sequence": receipt.get("promotion_sequence"),
        "fixed_depth_or_anchor_cap_applied": receipt.get(
            "fixed_depth_or_anchor_cap_applied", False
        ),
        "independent": True,
    }


def _reconcile_peer_receipt(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    matched = _matching_event(args, stored)
    if matched is None:
        return None
    receipt_type, event = matched
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    raw_result = _raw_result(receipt_type, payload)
    if raw_result is None:
        return None
    result = {
        **raw_result,
        "mutation_meta": _v61._reconciled_meta(
            "append_peer_receipt",
            stored,
            request_hash,
            int(event["seq"]),
            _PROOFS[receipt_type],
        ),
    }
    _v61._commit_receipt(path, stored, result, int(event["seq"]))
    return result


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "append_peer_receipt":
        reconciled = _reconcile_peer_receipt(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_peer_receipt_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["peer_receipt_recovery"] = {
        "enabled": True,
        "tool": "append_peer_receipt",
        "proofs": copy.deepcopy(_PROOFS),
        "requires_exact_event_correlation": True,
        "reexecutes_side_effect": False,
        "missing_or_ambiguous_event": "FAIL_CLOSED",
        "no_event_result": "FAIL_CLOSED",
    }
    return contract


def _health_with_peer_receipt_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["peer_receipt_recovery"] = {
        "status": "ENABLED",
        "automatic_reconciliation_tools": ["append_peer_receipt"],
        "requires_event_correlation": True,
    }
    return health


_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("append_peer_receipt")
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_peer_receipt_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_peer_receipt_recovery


def main() -> int:
    return _bundle.main()


if __name__ == "__main__":
    raise SystemExit(main())
