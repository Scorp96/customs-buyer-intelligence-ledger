#!/usr/bin/env python3
"""Exact Closure issuance crash recovery over the correlated v6.1 entrypoint.

Only a mutation that durably created a new, correlation-bound CLOSURE_ISSUED
event is automatically reconciled. The exact Decision Saturation snapshot used
for that issuance is persisted with the event so recovery never recomputes the
original response from a later investigation state.

No-event outcomes remain fail-closed. That includes unsaturated evaluations and
calls that only reused an already-issued Closure: after PREPARED there is no
new durable event proving which state the handler actually observed. Historical
Closure events that predate the saturation snapshot also remain fail-closed.
"""

from __future__ import annotations

import copy
import sys
from contextvars import ContextVar
from pathlib import Path
from types import MethodType
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_provider_recovery as _provider  # noqa: E402
from unified_runtime import ValidationError  # noqa: E402
from unified_runtime.resilience import digest, exclusive_file_lock  # noqa: E402


_v61 = _provider._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]
_BASE_APPEND_IF_TAIL = _RUNTIME.store.append_if_tail

_CLOSURE_PROOF = "CORRELATED_CLOSURE_EVENT_WITH_SATURATION_SNAPSHOT"
_ACTIVE_CLOSURE_SATURATION: ContextVar[dict[str, Any] | None] = ContextVar(
    "cbi_v61_active_closure_saturation",
    default=None,
)


def _find_unwrapped_closure() -> Callable[[Any, dict[str, Any]], dict[str, Any]]:
    for cls in type(_RUNTIME).__mro__:
        candidate = cls.__dict__.get("evaluate_investigation_closure")
        if candidate is None:
            continue
        original = getattr(candidate, "__wrapped__", None)
        if callable(original):
            return original
    raise RuntimeError("decorated v6 evaluate_investigation_closure implementation not found")


_CLOSURE_UNWRAPPED = _find_unwrapped_closure()


def _append_if_tail_with_closure_snapshot(
    self: Any,
    investigation_id: str,
    expected_tail_hash: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if event_type != "CLOSURE_ISSUED":
        return _BASE_APPEND_IF_TAIL(
            investigation_id,
            expected_tail_hash,
            event_type,
            payload,
        )

    snapshot = _ACTIVE_CLOSURE_SATURATION.get()
    if snapshot is None:
        return _BASE_APPEND_IF_TAIL(
            investigation_id,
            expected_tail_hash,
            event_type,
            payload,
        )

    enriched = copy.deepcopy(payload)
    declared = str(enriched.get("decision_saturation_sha256") or "").strip()
    calculated = digest(snapshot)
    if not declared or declared != calculated:
        raise ValidationError(
            "closure saturation snapshot hash does not match the evaluated Decision Saturation"
        )
    if snapshot.get("investigation_id") != investigation_id:
        raise ValidationError("closure saturation snapshot investigation mismatch")
    if snapshot.get("decision_saturated") is not True or snapshot.get("blockers") != []:
        raise ValidationError("closure issuance requires a saturated blocker-free snapshot")

    enriched["decision_saturation_snapshot"] = copy.deepcopy(snapshot)
    return _BASE_APPEND_IF_TAIL(
        investigation_id,
        expected_tail_hash,
        event_type,
        enriched,
    )


def _closure_runtime_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    args = copy.deepcopy(arguments)
    investigation_id = str(args.get("investigation_id") or "").strip()
    if not investigation_id:
        # Preserve the Runtime's original validation/error semantics.
        return _CLOSURE_UNWRAPPED(_RUNTIME, args)

    lock = _RUNTIME.store.root / f".{investigation_id}.v6-mutation.lock"
    with exclusive_file_lock(lock, timeout_seconds=60.0):
        # Match the original method's initialization boundary before capturing
        # the exact derived state that can authorize Closure issuance.
        _RUNTIME._ensure_v6(investigation_id)
        saturation = _RUNTIME.evaluate_decision_saturation(
            {"investigation_id": investigation_id}
        )
        token = _ACTIVE_CLOSURE_SATURATION.set(copy.deepcopy(saturation))
        try:
            return _CLOSURE_UNWRAPPED(_RUNTIME, args)
        finally:
            _ACTIVE_CLOSURE_SATURATION.reset(token)


def _closure_mcp_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return _v61._invoke_mutation(
        "evaluate_investigation_closure",
        _closure_runtime_handler,
        arguments,
    )


def _reconcile_closure(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if not investigation_id or not correlation_id:
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
        if event.get("event_type") != "CLOSURE_ISSUED":
            continue
        correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        if not isinstance(correlation, dict) or not isinstance(payload, dict):
            continue
        snapshot = payload.get("decision_saturation_snapshot")
        dimensions = payload.get("state_dimensions")
        if not isinstance(snapshot, dict) or not isinstance(dimensions, dict):
            # Historical correlated Closure rows without the exact snapshot are
            # intentionally not upgraded by inference.
            continue
        if (
            str(correlation.get("correlation_id") or "") != correlation_id
            or str(correlation.get("tool") or "") != "evaluate_investigation_closure"
            or str(payload.get("schema") or "") != "cbi.closure.v6.1"
            or str(payload.get("investigation_id") or "") != investigation_id
            or str(payload.get("basis_hash") or "") != str(event.get("prev_hash") or "")
            or str(payload.get("decision_saturation_sha256") or "") != digest(snapshot)
            or str(snapshot.get("investigation_id") or "") != investigation_id
            or snapshot.get("decision_saturated") is not True
            or snapshot.get("blockers") != []
            or dimensions.get("research_complete") is not True
        ):
            continue
        matches.append(event)

    if len(matches) != 1:
        return None

    event = matches[0]
    payload = copy.deepcopy(event["payload"])
    raw_result = {
        "schema": "cbi.closure-evaluation.v6.1",
        "investigation_id": investigation_id,
        "closed": True,
        "closed_scope": "DECISION_SATURATION",
        "closure_id": payload["closure_id"],
        "closure_expires_at": payload["expires_at"],
        "status": payload["status"],
        "state_dimensions": payload["state_dimensions"],
        "decision_saturation": payload["decision_saturation_snapshot"],
        "blockers": [],
        "crm_sync_blocks_research_closure": False,
        "reused_evaluation_receipt": False,
    }
    result = {
        **raw_result,
        "mutation_meta": _v61._reconciled_meta(
            "evaluate_investigation_closure",
            stored,
            request_hash,
            int(event["seq"]),
            _CLOSURE_PROOF,
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
    if tool_name == "evaluate_investigation_closure":
        reconciled = _reconcile_closure(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(
        tool_name,
        args,
        stored,
        request_hash,
        path,
    )


def _contract_with_closure_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["closure_issuance_recovery"] = {
        "enabled": True,
        "proof": _CLOSURE_PROOF,
        "new_correlated_closure_issuance_only": True,
        "persists_exact_decision_saturation_snapshot": True,
        "recomputes_from_later_state": False,
        "uncorrelated_or_snapshotless_closure": "FAIL_CLOSED",
        "unsaturated_no_event_result": "FAIL_CLOSED",
        "reused_existing_closure_no_event_result": "FAIL_CLOSED",
    }
    return contract


def _health_with_closure_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["closure_issuance_recovery"] = {
        "status": "ENABLED",
        "new_issuance_requires_event_correlation": True,
        "new_issuance_requires_saturation_snapshot": True,
        "no_event_paths_fail_closed": True,
    }
    return health


# Instance-level interception preserves direct/non-production Runtime behavior.
_RUNTIME.store.append_if_tail = MethodType(
    _append_if_tail_with_closure_snapshot,
    _RUNTIME.store,
)
_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("evaluate_investigation_closure")
_v61._server.TOOL_HANDLERS["evaluate_investigation_closure"] = _closure_mcp_handler
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_closure_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_closure_recovery


def main() -> int:
    return _provider.main()


if __name__ == "__main__":
    raise SystemExit(main())
