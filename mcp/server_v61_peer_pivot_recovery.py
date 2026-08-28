#!/usr/bin/env python3
"""Exact Peer/Pivot lifecycle crash recovery over the Outreach production entry.

The current production entry already provides durable mutation correlation and
exact Outreach recovery. This overlay adds mechanically proven reconciliation
for monotonic Peer/Pivot lifecycle mutations whose append-only Runtime events
carry the exact public result material.

Recovery never re-executes a lifecycle mutation. It requires exactly one event
emitted after the WAL PREPARED state, bound to the same mutation correlation,
and validates the event payload against the retried request. Missing,
ambiguous, historical, or no-event outcomes remain fail-closed.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_outreach_recovery as _outreach  # noqa: E402


_v61 = _outreach._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]

_PROOFS = {
    "append_peer_discovery": "CORRELATED_PEER_DISCOVERY_EVENT",
    "evaluate_peer": "CORRELATED_PEER_EVALUATION_EVENT",
    "promote_anchor": "CORRELATED_ANCHOR_PROMOTION_EVENT",
    "close_pivot": "CORRELATED_PIVOT_CLOSED_EVENT",
}
_EVENT_TYPES = {
    "append_peer_discovery": "V6_PEER_DISCOVERED",
    "evaluate_peer": "V6_PEER_EVALUATED",
    "promote_anchor": "V6_ANCHOR_PROMOTED",
    "close_pivot": "V6_PIVOT_CLOSED",
}


def _correlated_event(
    tool_name: str,
    investigation_id: str,
    stored: dict[str, Any],
) -> dict[str, Any] | None:
    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if not correlation_id:
        return None
    try:
        before = int(stored.get("state_version_before") or 0)
        events = _RUNTIME.store.read(investigation_id)
    except Exception:
        return None
    matches = [
        event
        for event in events
        if int(event.get("seq") or 0) > before
        and event.get("event_type") == _EVENT_TYPES[tool_name]
        and isinstance(event.get("mutation_correlation"), dict)
        and str(event["mutation_correlation"].get("correlation_id") or "") == correlation_id
        and str(event["mutation_correlation"].get("tool") or "") == tool_name
        and isinstance(event.get("payload"), dict)
    ]
    return matches[0] if len(matches) == 1 else None


def _matches_request(tool_name: str, args: dict[str, Any], payload: dict[str, Any]) -> bool:
    if str(payload.get("investigation_id") or "") != str(args.get("investigation_id") or ""):
        return False

    if tool_name == "append_peer_discovery":
        raw = args.get("peer")
        if not isinstance(raw, dict):
            return False
        for field in (
            "peer_id",
            "account_id",
            "name",
            "country",
            "relationship_type",
        ):
            if field in raw and str(payload.get(field) or "") != str(raw.get(field) or ""):
                return False
        return payload.get("stage") == "DISCOVERED"

    if tool_name == "evaluate_peer":
        if str(payload.get("peer_id") or "") != str(args.get("peer_id") or ""):
            return False
        assessment = args.get("assessment")
        if not isinstance(assessment, dict):
            return False
        for field in (
            "target_fit",
            "evidence_grade",
            "commercial_novelty",
            "canonical_new",
        ):
            if field in assessment and payload.get(field) != assessment.get(field):
                return False
        return str(payload.get("stage") or "") in {
            "DISCOVERED",
            "QUALIFIED",
            "ANCHOR_ELIGIBLE",
        }

    if tool_name == "promote_anchor":
        return (
            str(payload.get("peer_id") or "") == str(args.get("peer_id") or "")
            and str(payload.get("promotion_reason") or "")
            == str(args.get("promotion_reason") or "").strip()
            and payload.get("stage") == "PROMOTED_ANCHOR"
            and payload.get("six_branch_research_required") is True
        )

    if tool_name == "close_pivot":
        return (
            str(payload.get("pivot_id") or "") == str(args.get("pivot_id") or "")
            and str(payload.get("status") or "") == str(args.get("status") or "").upper()
            and str(payload.get("reason") or "") == str(args.get("reason") or "").strip()
        )

    return False


def _raw_result(payload: dict[str, Any]) -> dict[str, Any]:
    # All four Runtime methods return accepted=True plus the exact event payload.
    # Copying the durable payload therefore reconstructs the original public
    # result without consulting later derived state.
    return {"accepted": True, **copy.deepcopy(payload)}


def _reconcile_lifecycle(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    if not investigation_id:
        return None
    event = _correlated_event(tool_name, investigation_id, stored)
    if event is None:
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or not _matches_request(tool_name, args, payload):
        return None
    result = {
        **_raw_result(payload),
        "mutation_meta": _v61._reconciled_meta(
            tool_name,
            stored,
            request_hash,
            int(event["seq"]),
            _PROOFS[tool_name],
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
    if tool_name in _PROOFS:
        reconciled = _reconcile_lifecycle(tool_name, args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_peer_pivot_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["peer_pivot_lifecycle_recovery"] = {
        "enabled": True,
        "tools": sorted(_PROOFS),
        "proofs": copy.deepcopy(_PROOFS),
        "requires_exact_event_correlation": True,
        "reexecutes_side_effect": False,
        "historical_or_ambiguous_event": "FAIL_CLOSED",
        "no_event_result": "FAIL_CLOSED",
    }
    return contract


def _health_with_peer_pivot_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["peer_pivot_lifecycle_recovery"] = {
        "status": "ENABLED",
        "automatic_reconciliation_tools": sorted(_PROOFS),
        "requires_event_correlation": True,
    }
    return health


_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.update(_PROOFS)
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_peer_pivot_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_peer_pivot_recovery


def main() -> int:
    return _outreach.main()


if __name__ == "__main__":
    raise SystemExit(main())
