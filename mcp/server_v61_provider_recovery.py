#!/usr/bin/env python3
"""Exact Provider Plan crash recovery over the correlated v6.1 entrypoint.

Provider plan business IDs are random, so content-only recovery is unsafe under
concurrency. The correlated entrypoint durably binds each production mutation
WAL intent to the events emitted by that exact idempotency key. This overlay
uses that binding to reconstruct only the matching PROVIDER_PLAN_CREATED result.

PUBLIC_ONLY planning has no Runtime side effect; its response is deterministic
from the immutable investigation provider policy plus the normalized requested
capabilities, so a crashed PREPARED intent can also be reconstructed without
re-executing a handler. Recovery still mirrors every validation performed by
the handler before that early PUBLIC_ONLY return.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_correlated as _correlated  # noqa: E402
from unified_runtime import core as _core  # noqa: E402


_v61 = _correlated._v61
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]

_PROVIDER_PLAN_PROOF = "CORRELATED_PROVIDER_PLAN_EVENT_AND_REQUEST_MATERIAL"
_PROVIDER_PUBLIC_ONLY_PROOF = "IMMUTABLE_PUBLIC_ONLY_POLICY_AND_REQUEST"


def _finish_reconciliation(
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
    raw_result: dict[str, Any],
    state_version_after: int,
    proof: str,
) -> dict[str, Any]:
    result = {
        **raw_result,
        "mutation_meta": _v61._reconciled_meta(
            "plan_provider_calls",
            stored,
            request_hash,
            state_version_after,
            proof,
        ),
    }
    _v61._commit_receipt(path, stored, result, state_version_after)
    return result


def _normalized_requested(value: Any) -> list[str] | None:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        return None
    return sorted(set(item.strip() for item in value), key=str.casefold)


def _normalized_provider_inventory(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            return None
        required = {
            "provider",
            "provider_class",
            "status",
            "capability_tools",
            "requires_paid_credit",
            "permissions",
        }
        if not required.issubset(raw):
            return None
        provider = str(raw.get("provider") or "").strip()
        provider_class = str(raw.get("provider_class") or "").upper()
        status = str(raw.get("status") or "").upper()
        capability_tools = raw.get("capability_tools")
        permissions = raw.get("permissions")
        provider_key = provider.casefold()
        if (
            not provider
            or provider_key in seen
            or not provider_class
            or not status
            or not isinstance(capability_tools, dict)
            or not isinstance(permissions, list)
        ):
            return None
        seen.add(provider_key)
        normalized_tools: dict[str, str] = {}
        for capability, tool_name in capability_tools.items():
            if not isinstance(capability, str) or not isinstance(tool_name, str):
                return None
            capability = capability.strip()
            tool_name = tool_name.strip()
            if not capability or not tool_name:
                return None
            normalized_tools[capability] = tool_name
        if not all(isinstance(item, str) and item.strip() for item in permissions):
            return None
        inventory.append({
            "provider": provider,
            "provider_class": provider_class,
            "status": status,
            "capability_tools": normalized_tools,
            "requires_paid_credit": raw.get("requires_paid_credit") is True,
            "permissions": sorted(set(item.strip() for item in permissions)),
        })
    return inventory


def _reconcile_provider_plan(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    requested = _normalized_requested(args.get("requested_capabilities"))
    inventory_input = args.get("provider_inventory") or []
    if (
        not investigation_id
        or requested is None
        or not isinstance(inventory_input, list)
    ):
        return None

    try:
        state = _v61._server.RUNTIME._state(investigation_id)
        policy = state["start"]["provider_policy"]
        account_id = str(state["start"]["account"].get("account_id") or "")
    except Exception:
        return None

    before = int(stored.get("state_version_before") or 0)
    provider_mode = str(policy.get("mode") or "")

    if provider_mode == "PUBLIC_ONLY":
        raw_result = {
            "investigation_id": investigation_id,
            "status": "PROVIDER_USE_DISABLED",
            "provider_mode": "PUBLIC_ONLY",
            "plan_id": None,
            "calls": [],
            "missing_capabilities": requested,
            "blocked": ["PUBLIC_ONLY_REQUIRES_A_NEW_EXPLICITLY_AUTHORIZED_INVESTIGATION"],
            "external_execution_required": False,
            "runtime_invokes_other_plugins": False,
        }
        return _finish_reconciliation(
            stored,
            request_hash,
            path,
            raw_result,
            before,
            _PROVIDER_PUBLIC_ONLY_PROOF,
        )

    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if not correlation_id:
        return None
    inventory = _normalized_provider_inventory(inventory_input)
    if inventory is None:
        return None
    inventory_sha256 = _core.digest(inventory)
    cost_consent = policy.get("cost_consent") is True and args.get("cost_consent") is True

    try:
        events = _v61._server.RUNTIME.store.read(investigation_id)
    except Exception:
        return None

    matches: list[dict[str, Any]] = []
    for event in events:
        if int(event.get("seq") or 0) <= before:
            continue
        if event.get("event_type") != "PROVIDER_PLAN_CREATED":
            continue
        correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        if not isinstance(correlation, dict) or not isinstance(payload, dict):
            continue
        if (
            str(correlation.get("correlation_id") or "") == correlation_id
            and str(correlation.get("tool") or "") == "plan_provider_calls"
            and str(payload.get("investigation_id") or "") == investigation_id
            and str(payload.get("account_id") or "") == account_id
            and str(payload.get("provider_mode") or "") == provider_mode
            and payload.get("requested_capabilities") == requested
            and str(payload.get("inventory_sha256") or "") == inventory_sha256
            and payload.get("cost_consent") is cost_consent
        ):
            matches.append(event)
    if len(matches) != 1:
        return None

    event = matches[0]
    payload = copy.deepcopy(event["payload"])
    raw_result = {
        **payload,
        "external_execution_required": bool(payload.get("calls")),
        "runtime_invokes_other_plugins": False,
        "execution_boundary": (
            "Codex must call each listed provider tool, then append the real result "
            "with append_provider_receipt."
        ),
    }
    return _finish_reconciliation(
        stored,
        request_hash,
        path,
        raw_result,
        int(event["seq"]),
        _PROVIDER_PLAN_PROOF,
    )


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "plan_provider_calls":
        reconciled = _reconcile_provider_plan(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_provider_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["provider_plan_recovery"] = {
        "enabled": True,
        "connected_mode_proof": _PROVIDER_PLAN_PROOF,
        "public_only_proof": _PROVIDER_PUBLIC_ONLY_PROOF,
        "requires_exact_event_correlation_for_random_plan_ids": True,
        "uncorrelated_historical_connected_prepared_intents": "FAIL_CLOSED",
        "public_only_recovery_requires_event_correlation": False,
    }
    return contract


def _health_with_provider_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["provider_plan_recovery"] = {
        "status": "ENABLED",
        "connected_mode_requires_event_correlation": True,
        "public_only_is_deterministic_no_side_effect": True,
    }
    return health


_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("plan_provider_calls")
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_provider_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_provider_recovery


def main() -> int:
    return _correlated.main()


if __name__ == "__main__":
    raise SystemExit(main())
