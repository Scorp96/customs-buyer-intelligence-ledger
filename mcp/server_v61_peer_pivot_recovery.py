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
_PEER_STAGES = {
    "DISCOVERED",
    "QUALIFIED",
    "ANCHOR_ELIGIBLE",
    "PROMOTED_ANCHOR",
    "FULLY_AUDITED",
}
_PEER_FACT_KEYS = {
    "entity_verified",
    "product_fit_verified",
    "business_or_trade_verified",
    "relationship_verified",
    "commercial_novelty",
    "canonical_new",
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


def _matches_peer_discovery(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    raw = args.get("peer")
    if not isinstance(raw, dict):
        return False
    for field in (
        "name",
        "country",
        "tax_id",
        "network_branch",
        "discovered_from_owner_id",
        "discovered_by_observation_id",
    ):
        if field not in raw:
            continue
        expected = str(raw.get(field) or "")
        actual = str(payload.get(field) or "")
        if field == "network_branch":
            expected = expected.upper()
        if actual != expected:
            return False
    if "relationship_evidence_ids" in raw:
        expected_ids = [str(item) for item in raw.get("relationship_evidence_ids") or []]
        if payload.get("relationship_evidence_ids") != expected_ids:
            return False
    return (
        bool(str(payload.get("peer_id") or ""))
        and payload.get("stage") == "DISCOVERED"
    )


def _matches_peer_evaluation(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    if str(payload.get("peer_id") or "") != str(args.get("peer_id") or ""):
        return False
    assessment = args.get("assessment")
    persisted_facts = payload.get("assessment")
    if not isinstance(assessment, dict) or not isinstance(persisted_facts, dict):
        return False
    for field in _PEER_FACT_KEYS:
        if field in assessment and persisted_facts.get(field) is not (assessment.get(field) is True):
            return False
    if "fact_evidence_ids" in assessment:
        supplied = assessment.get("fact_evidence_ids")
        persisted = payload.get("fact_evidence_ids")
        if not isinstance(supplied, dict) or not isinstance(persisted, dict):
            return False
        for key, value in supplied.items():
            if [str(item) for item in (value or [])] != persisted.get(key):
                return False
    if "commercial_novelty_basis" in assessment:
        if str(payload.get("commercial_novelty_basis") or "") != str(
            assessment.get("commercial_novelty_basis") or ""
        ).strip():
            return False
    return str(payload.get("stage") or "") in _PEER_STAGES


def _matches_anchor_promotion(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    return (
        str(payload.get("peer_id") or "") == str(args.get("peer_id") or "")
        and str(payload.get("promotion_reason") or "")
        == str(args.get("promotion_reason") or "").strip()
        and payload.get("stage") == "PROMOTED_ANCHOR"
        and payload.get("six_branch_research_required") is True
        and payload.get("contact_coverage_required") is False
    )


def _matches_pivot_close(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    if (
        str(payload.get("pivot_id") or "") != str(args.get("pivot_id") or "")
        or str(payload.get("status") or "") != str(args.get("status") or "").upper()
        or str(payload.get("reason") or "") != str(args.get("reason") or "").strip()
    ):
        return False
    if "consumed_by_objective_id" in args and str(
        payload.get("consumed_by_objective_id") or ""
    ) != str(args.get("consumed_by_objective_id") or ""):
        return False
    if "max_remaining_eiv" in args:
        try:
            if float(payload.get("max_remaining_eiv")) != float(args.get("max_remaining_eiv")):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _matches_request(tool_name: str, args: dict[str, Any], payload: dict[str, Any]) -> bool:
    # The SessionStore selected above already binds the event to investigation_id.
    # Several v6 lifecycle event payloads deliberately omit that redundant field,
    # so investigation identity must not be inferred from payload presence.
    if tool_name == "append_peer_discovery":
        return _matches_peer_discovery(args, payload)
    if tool_name == "evaluate_peer":
        return _matches_peer_evaluation(args, payload)
    if tool_name == "promote_anchor":
        return _matches_anchor_promotion(args, payload)
    if tool_name == "close_pivot":
        return _matches_pivot_close(args, payload)
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
