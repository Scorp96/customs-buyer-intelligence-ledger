#!/usr/bin/env python3
"""Exact Outreach prepare/render crash recovery for the final v6.1 MCP surface.

Successful Outreach mutations persist the exact public result snapshot in the
same append-only event that proves the side effect. Recovery therefore never
recomputes a prior canonical-route count or mailto action from later state.
Blocked/no-event outcomes remain fail-closed.

Render is additionally serialized by the same per-investigation mutation lock
used by v6 state changes. Two distinct idempotency keys racing the same render
token can no longer both observe it as unused.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import MethodType
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_closure_recovery as _closure  # noqa: E402
from unified_runtime.resilience import digest, exclusive_file_lock  # noqa: E402
from unified_runtime.v6 import V6_BUILD_ID, V6_RUNTIME_VERSION  # noqa: E402


_v61 = _closure._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]
_BASE_APPEND_IF_TAIL = _RUNTIME.store.append_if_tail
_BASE_APPEND = _RUNTIME.store.append
_BASE_RENDER_HANDLER = _v61._ORIGINAL_HANDLERS["render_outreach_action_card"]

_PREPARE_PROOF = "CORRELATED_OUTREACH_PREPARED_WITH_RESULT_SNAPSHOT"
_RENDER_PROOF = "CORRELATED_OUTREACH_RENDERED_WITH_RESULT_SNAPSHOT"


def _prepare_result_snapshot(
    investigation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    account_id = str(payload.get("account_id") or "")
    matching_routes = [
        candidate
        for candidate in _RUNTIME._canonical_route_view(investigation_id)
        if _RUNTIME._route_matches_candidate(route, candidate, account_id)
    ]
    kind = str(route.get("kind") or "").upper()
    return {
        "status": "PREPARED_FOR_RENDER" if kind == "EMAIL" else "PREPARED_CONTENT_ONLY",
        "prepared": True,
        "block_reasons": [],
        "prepared_id": payload["prepared_id"],
        "render_token": payload["render_token"],
        "expires_at": payload["expires_at"],
        "render_transport": "MAILTO" if kind == "EMAIL" else "CONTENT_ONLY_NO_ONE_CLICK_TRANSPORT",
        "action": None,
        "sends_message": False,
        "canonical_route_match_count": len(matching_routes),
        "canonical_route_binding": copy.deepcopy(payload.get("canonical_route_binding") or {}),
    }


def _render_result_snapshot(prepared: dict[str, Any]) -> dict[str, Any]:
    route = prepared.get("route") if isinstance(prepared.get("route"), dict) else {}
    recipient = str(route.get("value") or "")
    subject = str(prepared.get("subject") or "")
    body = str(prepared.get("body") or "")
    mailto = (
        f"mailto:{quote(recipient, safe='@+._-')}"
        f"?subject={quote(subject)}&body={quote(body)}"
    )
    return {
        "schema_version": "6.1.0",
        "runtime_version": V6_RUNTIME_VERSION,
        "build_id": V6_BUILD_ID,
        "terminal_state": "SENDABLE_DRAFT",
        "recipient": recipient,
        "route_kind": route.get("kind"),
        "subject": subject,
        "body": body,
        "chinese_translation": str(prepared.get("chinese_translation") or ""),
        "stage": prepared.get("stage"),
        "block_reasons": [],
        "action": {
            "label": "一键打开邮件草稿 / Open email draft",
            "kind": "open_url",
            "url": mailto,
            "enabled": True,
            "sends_message": False,
            "requires_preview": True,
        },
        "server_side_draft_created": False,
        "provider_draft_id": None,
        "connector_receipt": None,
        "simultaneous_multi_send_prohibited": True,
        "send_boundary": (
            "This tool only opens a local UTF-8 mailto draft. It never sends "
            "and never claims a provider-side draft receipt."
        ),
    }


def _append_if_tail_with_prepare_snapshot(
    self: Any,
    investigation_id: str,
    expected_tail_hash: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if event_type != "OUTREACH_PREPARED":
        return _BASE_APPEND_IF_TAIL(
            investigation_id,
            expected_tail_hash,
            event_type,
            payload,
        )

    enriched = copy.deepcopy(payload)
    snapshot = _prepare_result_snapshot(investigation_id, enriched)
    if snapshot["canonical_route_match_count"] < 1:
        raise _v61.ValidationError(
            "OUTREACH_PREPARED snapshot requires a canonical route match"
        )
    enriched["prepare_result_snapshot"] = snapshot
    enriched["prepare_result_sha256"] = digest(snapshot)
    return _BASE_APPEND_IF_TAIL(
        investigation_id,
        expected_tail_hash,
        event_type,
        enriched,
    )


def _append_with_render_snapshot(
    self: Any,
    investigation_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if event_type != "OUTREACH_RENDERED":
        return _BASE_APPEND(investigation_id, event_type, payload)

    prepared_id = str(payload.get("prepared_id") or "").strip()
    render_token = str(payload.get("render_token") or "").strip()
    try:
        state = _RUNTIME._v6_state(investigation_id)
    except Exception:
        return _BASE_APPEND(investigation_id, event_type, payload)
    prepared_events = [
        event
        for event in state["events"]
        if event.get("event_type") == "OUTREACH_PREPARED"
        and str((event.get("payload") or {}).get("prepared_id") or "") == prepared_id
        and str((event.get("payload") or {}).get("render_token") or "") == render_token
    ]
    if len(prepared_events) != 1:
        raise _v61.ValidationError("render snapshot requires exactly one prepared outreach")
    prepared = prepared_events[0]["payload"]
    snapshot = _render_result_snapshot(prepared)
    if str((prepared.get("route") or {}).get("kind") or "").upper() != "EMAIL":
        raise _v61.ValidationError("render snapshot requires an email preparation")
    if len(str(snapshot["action"]["url"] or "")) > 8000:
        raise _v61.ValidationError("render snapshot mailto exceeds the production limit")

    enriched = copy.deepcopy(payload)
    enriched["render_result_snapshot"] = snapshot
    enriched["render_result_sha256"] = digest(snapshot)
    return _BASE_APPEND(investigation_id, event_type, enriched)


def _render_runtime_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    if not investigation_id:
        return _BASE_RENDER_HANDLER(arguments)
    lock = _RUNTIME.store.root / f".{investigation_id}.v6-mutation.lock"
    with exclusive_file_lock(lock, timeout_seconds=60.0):
        return _BASE_RENDER_HANDLER(arguments)


def _render_mcp_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return _v61._invoke_mutation(
        "render_outreach_action_card",
        _render_runtime_handler,
        arguments,
    )


def _correlated_event(
    investigation_id: str,
    stored: dict[str, Any],
    event_type: str,
    tool_name: str,
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
        and event.get("event_type") == event_type
        and isinstance(event.get("mutation_correlation"), dict)
        and str(event["mutation_correlation"].get("correlation_id") or "") == correlation_id
        and str(event["mutation_correlation"].get("tool") or "") == tool_name
    ]
    return matches[0] if len(matches) == 1 else None


def _finish_reconciliation(
    tool_name: str,
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
    event: dict[str, Any],
    result: dict[str, Any],
    proof: str,
) -> dict[str, Any]:
    wrapped = {
        **copy.deepcopy(result),
        "mutation_meta": _v61._reconciled_meta(
            tool_name,
            stored,
            request_hash,
            int(event["seq"]),
            proof,
        ),
    }
    _v61._commit_receipt(path, stored, wrapped, int(event["seq"]))
    return wrapped


def _reconcile_prepare(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    if not investigation_id:
        return None
    event = _correlated_event(
        investigation_id,
        stored,
        "OUTREACH_PREPARED",
        "prepare_outreach",
    )
    if event is None:
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    snapshot = payload.get("prepare_result_snapshot")
    if not isinstance(snapshot, dict):
        return None
    if str(payload.get("prepare_result_sha256") or "") != digest(snapshot):
        return None
    if (
        str(payload.get("investigation_id") or "") != investigation_id
        or str(payload.get("closure_id") or "") != str(args.get("closure_id") or "")
        or payload.get("route") != args.get("route")
        or str(payload.get("history_digest") or "") != str(args.get("history_digest") or "")
        or str(payload.get("authority_digest") or "") != str(args.get("authority_digest") or "")
        or str(payload.get("subject") or "") != str(args.get("subject") or "").strip()
        or str(payload.get("body") or "") != str(args.get("body") or "").strip()
        or str(payload.get("stage") or "") != str(args.get("stage") or "").upper()
        or str(payload.get("chinese_translation") or "") != str(args.get("chinese_translation") or "")
        or snapshot.get("prepared") is not True
        or snapshot.get("prepared_id") != payload.get("prepared_id")
        or snapshot.get("render_token") != payload.get("render_token")
        or snapshot.get("canonical_route_binding") != payload.get("canonical_route_binding")
    ):
        return None
    return _finish_reconciliation(
        "prepare_outreach",
        stored,
        request_hash,
        path,
        event,
        snapshot,
        _PREPARE_PROOF,
    )


def _reconcile_render(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    if not investigation_id:
        return None
    event = _correlated_event(
        investigation_id,
        stored,
        "OUTREACH_RENDERED",
        "render_outreach_action_card",
    )
    if event is None:
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    snapshot = payload.get("render_result_snapshot")
    if not isinstance(snapshot, dict):
        return None
    if str(payload.get("render_result_sha256") or "") != digest(snapshot):
        return None
    if (
        str(payload.get("prepared_id") or "") != str(args.get("prepared_id") or "")
        or str(payload.get("render_token") or "") != str(args.get("render_token") or "")
        or snapshot.get("terminal_state") != "SENDABLE_DRAFT"
        or snapshot.get("server_side_draft_created") is not False
        or (snapshot.get("action") or {}).get("sends_message") is not False
    ):
        return None
    return _finish_reconciliation(
        "render_outreach_action_card",
        stored,
        request_hash,
        path,
        event,
        snapshot,
        _RENDER_PROOF,
    )


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "prepare_outreach":
        reconciled = _reconcile_prepare(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    elif tool_name == "render_outreach_action_card":
        reconciled = _reconcile_render(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_outreach_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["outreach_recovery"] = {
        "enabled": True,
        "prepare_success_proof": _PREPARE_PROOF,
        "render_success_proof": _RENDER_PROOF,
        "successful_results_persist_exact_snapshot": True,
        "blocked_no_event_results": "FAIL_CLOSED",
        "render_serialized_per_investigation": True,
        "same_render_token_distinct_keys": "AT_MOST_ONE_SENDABLE_DRAFT",
        "server_side_send_capability": False,
    }
    return contract


def _health_with_outreach_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["outreach_recovery"] = {
        "status": "ENABLED",
        "successful_prepare_requires_result_snapshot": True,
        "successful_render_requires_result_snapshot": True,
        "render_token_race_guard": "PER_INVESTIGATION_SERIALIZATION",
        "sends_message": False,
    }
    return health


_RUNTIME.store.append_if_tail = MethodType(
    _append_if_tail_with_prepare_snapshot,
    _RUNTIME.store,
)
_RUNTIME.store.append = MethodType(_append_with_render_snapshot, _RUNTIME.store)
_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.update({
    "prepare_outreach",
    "render_outreach_action_card",
})
_v61._server.TOOL_HANDLERS["render_outreach_action_card"] = _render_mcp_handler
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_outreach_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_outreach_recovery


def main() -> int:
    return _closure.main()


if __name__ == "__main__":
    raise SystemExit(main())
