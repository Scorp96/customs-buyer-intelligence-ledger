#!/usr/bin/env python3
"""Read-only, value-free selector for an authoritative POSITIVE_ROUTE case."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from typing import Any

SUPPORTED = frozenset({"EMAIL", "PHONE", "WHATSAPP", "ZALO", "SOCIAL", "FORM"})
OUTPUT_KEYS = frozenset({"schema", "result", "candidate", "failure_stage", "reason_codes", "production_before", "production_after"})
READ_TIMEOUT_SECONDS = 60


def _owner_aliases_are_safe(row: dict[str, object], account_id: object, *, allow_legacy: bool) -> bool:
    account = str(account_id or "").strip()
    if not account:
        return False

    has_explicit_owner_field = "owned_by_account" in row or "owner_entity_id" in row
    if has_explicit_owner_field:
        if row.get("owned_by_account") is not True:
            return False
        if str(row.get("owner_entity_id") or "").strip() != account:
            return False
        if "owner_id" in row and str(row.get("owner_id") or "").strip() != account:
            return False
        return True

    return allow_legacy and str(row.get("owner_id") or "").strip() == account


def route_is_fully_qualified(
    row: object,
    account_id: object,
    *,
    require_named_person: bool = False,
) -> bool:
    """Validate one explicit canonical route without combining row facts."""
    if not isinstance(row, dict):
        return False
    account = str(account_id or "").strip()
    if not account or not _owner_aliases_are_safe(row, account, allow_legacy=False):
        return False

    channel = str(row.get("kind") or row.get("channel") or "").strip().upper()
    value = row.get("value")
    evidence = row.get("evidence_ids")
    observation_id = str(row.get("observation_id") or "").strip()
    information_id = str(row.get("information_id") or "").strip()
    if not (
        channel in SUPPORTED
        and isinstance(value, str)
        and bool(value.strip())
        and row.get("verified") is True
        and row.get("current") is True
        and row.get("route_scope") == "BUYER_DIRECT"
        and row.get("masked") is not True
        and row.get("guessed") is not True
        and isinstance(evidence, list)
        and any(str(item).strip() for item in evidence)
        and bool(observation_id) != bool(information_id)
        and (channel not in {"WHATSAPP", "ZALO"} or row.get("channel_proof") is True)
    ):
        return False
    if require_named_person:
        named_person = row.get("named_person")
        if not isinstance(named_person, str) or not named_person.strip():
            return False
    return True


def qualified_count(routes: object, account_id: object, *, require_named_person: bool = False) -> int:
    rows = routes if isinstance(routes, list) else []
    return sum(
        route_is_fully_qualified(
            row,
            account_id,
            require_named_person=require_named_person,
        )
        for row in rows
    )


def _named_lane_bound(row: object, readiness: object) -> bool:
    if not isinstance(row, dict):
        return False
    view = dict(readiness) if isinstance(readiness, dict) else {}
    named_ids = {
        str(item).strip()
        for item in (view.get("valid_named_route_observation_ids") or [])
        if str(item).strip()
    }
    information_ids = {
        str(item).strip()
        for item in (view.get("valid_information_route_ids") or [])
        if str(item).strip()
    }
    observation_id = str(row.get("observation_id") or "").strip()
    information_id = str(row.get("information_id") or "").strip()
    source = str(row.get("route_source") or row.get("source") or "").strip().upper()
    return (
        source == "COMPILED_OBSERVATION"
        and observation_id in named_ids
        and not information_id
    ) or (
        source in {"INFORMATION_RECORD", "INFORMATION_HISTORY", "INFORMATION_HISTORY_DERIVED"}
        and information_id in information_ids
        and not observation_id
    )


def qualified_named_count(routes: object, account_id: object, readiness: object) -> int:
    """Count only routes that pass every safety gate and the named lane bind."""
    account = str(account_id or "").strip()
    total = 0
    for row in routes if isinstance(routes, list) else []:
        if not isinstance(row, dict) or not _named_lane_bound(row, readiness):
            continue
        if qualified_count([row], account, require_named_person=True) == 1:
            total += 1
    return total


def normalizable_lower_named_count(routes: object, account_id: object, readiness: object) -> int:
    """Recognize only lower named rows the integrated projection can revalidate.

    This is not executable-route acceptance: a caller still needs the exact
    integrated runtime to emit its explicit ownership projection before any
    isolated draft attempt.  The return value contains no row or value.
    """
    view = dict(readiness) if isinstance(readiness, dict) else {}
    named_ids = {str(item).strip() for item in (view.get("valid_named_route_observation_ids") or []) if str(item).strip()}
    account = str(account_id or "").strip()
    if not account:
        return 0
    total = 0
    for row in routes if isinstance(routes, list) else []:
        if not isinstance(row, dict):
            continue
        channel = str(row.get("kind") or row.get("channel") or "").strip().upper()
        value = row.get("value")
        evidence = row.get("evidence_ids")
        named = row.get("named_person")
        observation_id = str(row.get("observation_id") or "").strip()
        information_id = str(row.get("information_id") or "").strip()
        source = str(row.get("route_source") or row.get("source") or "").strip().upper()
        # Only the integrated compiled-observation projection has a narrowly
        # defined compatibility normalization. Information records must already
        # pass the current evidence-index recheck and arrive as explicit rows.
        exact_lane = source == "COMPILED_OBSERVATION" and observation_id in named_ids and not information_id
        if not (
            exact_lane and channel in SUPPORTED and isinstance(value, str) and bool(value.strip())
            and isinstance(named, str) and bool(named.strip())
            and row.get("verified") is True and row.get("current") is True
            and _owner_aliases_are_safe(row, account, allow_legacy=True)
            and row.get("route_scope") == "BUYER_DIRECT"
            and row.get("masked") is not True and row.get("guessed") is not True
            and isinstance(evidence, list) and any(str(item).strip() for item in evidence)
            and (channel not in {"WHATSAPP", "ZALO"} or row.get("channel_proof") is True)
        ):
            continue
        total += 1
    return total


def named_route_lane_count(routes: object, readiness: object) -> int:
    """Count named rows bound to an explicit compiled or Information lane."""
    total = 0
    for row in routes if isinstance(routes, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("named_person"), str) or not row["named_person"].strip():
            continue
        if _named_lane_bound(row, readiness):
            total += 1
    return total


def sanitize_health(value: object, runtime_health: object) -> dict[str, object]:
    health = dict(value) if isinstance(value, dict) else {}
    identity = health.get("deployment_identity") if isinstance(health.get("deployment_identity"), dict) else {}
    persistence = health.get("object_store_persistence") if isinstance(health.get("object_store_persistence"), dict) else {}
    runtime = dict(runtime_health) if isinstance(runtime_health, dict) else {}
    wal = runtime.get("mutation_wal") if isinstance(runtime.get("mutation_wal"), dict) else {}
    return {
        "status": str(health.get("status") or "UNKNOWN"),
        "git_sha": str(identity.get("git_sha") or ""),
        "object_state_generation": identity.get("object_state_generation"),
        "restore_generation": identity.get("restore_generation"),
        "recovery_fingerprint_sha256": str(persistence.get("recovery_fingerprint_sha256") or ""),
        "runtime_ready": health.get("status") == "ok" and health.get("durable_root_bound") is True,
        "wal_prepared_count": wal.get("prepared_count"),
        "wal_invalid_count": wal.get("invalid_count"),
        "wal_reconciliation_required": wal.get("reconciliation_required"),
    }


def select_candidate(portfolio: object, call: Any) -> dict[str, object]:
    rows = portfolio.get("queue") if isinstance(portfolio, dict) else []
    candidates: list[tuple[int, str, dict[str, object], dict[str, object], int, str]] = []
    normalizable_candidates: list[tuple[int, str, dict[str, object], dict[str, object], int, str]] = []
    company_route_only_seen = False
    for row in sorted((row for row in rows if isinstance(row, dict)), key=lambda item: str(item.get("investigation_id") or "")):
        if not isinstance(row, dict):
            continue
        investigation_id = str(row.get("investigation_id") or "").strip()
        # Portfolio carries this projection already.  Reject every row other
        # than the Runtime's exact SATURATED state before its expensive account
        # reconciliation call; no inferred or truthy aliases are accepted.
        if not investigation_id or str(row.get("decision_saturation") or "").strip().upper() != "SATURATED":
            continue
        state = call("get_account_state", {"investigation_id": investigation_id})
        if not isinstance(state, dict):
            continue
        account = state.get("account") if isinstance(state.get("account"), dict) else {}
        readiness = state.get("outreach_readiness") if isinstance(state.get("outreach_readiness"), dict) else {}
        routes = readiness.get("canonical_route_view") if isinstance(readiness, dict) else []
        account_id = str(account.get("account_id") or "").strip()
        qualified = qualified_count(routes, account_id)
        # A positive candidate must have one row that is both fully qualified
        # and bound to the Runtime's named lane.  Counting these properties
        # independently would let two incomplete rows be combined.
        named_qualified = qualified_named_count(routes, account_id, readiness)
        route_count = len(routes) if isinstance(routes, list) else 0
        named_lane_count = named_route_lane_count(routes, readiness)
        readiness_value = str(readiness.get("outreach_readiness") or readiness.get("readiness") or "UNKNOWN").strip().upper()
        saturation = state.get("decision_saturation") if isinstance(state.get("decision_saturation"), dict) else {}
        decision_saturated = saturation.get("decision_saturated") is True
        if qualified >= 1 and readiness_value == "COMPANY_ROUTE_READY":
            company_route_only_seen = True
        common_positive = (
            named_lane_count >= 1
            and decision_saturated
            and readiness_value in {"NAMED_ROUTE_READY", "FOLLOW_UP_READY", "SEND_READY"}
        )
        if not common_positive:
            continue
        priority = 0 if readiness_value in {"FOLLOW_UP_READY", "SEND_READY"} else 1
        source_type = "EXPLICIT_CANONICAL"
        if named_qualified >= 1:
            candidates.append((priority, investigation_id, state, readiness, named_qualified, source_type))
        else:
            normalizable = normalizable_lower_named_count(routes, account_id, readiness)
            if normalizable >= 1:
                normalizable_candidates.append((priority, investigation_id, state, readiness, normalizable, "NORMALIZABLE_LOWER_NAMED"))

    if candidates:
        _priority, investigation_id, state, readiness, named_qualified, source_type = min(candidates, key=lambda item: (item[0], item[1]))
        account = state.get("account") if isinstance(state.get("account"), dict) else {}
        account_id = str(account.get("account_id") or "").strip()
        routes = readiness.get("canonical_route_view") if isinstance(readiness, dict) else []
        route_count = len(routes) if isinstance(routes, list) else 0
        tail = call("get_investigation_state", {"investigation_id": investigation_id})
        if not isinstance(tail, dict):
            return {"result": "BLOCKED_EXTERNAL", "candidate": None, "failure_stage": "TAIL_PIN", "reason_codes": ["MCP_READ_FAILED"]}
        return {
            "result": "ELIGIBLE_POSITIVE_CASE_SELECTED", "failure_stage": None, "reason_codes": [], "candidate": {
            "investigation_id": investigation_id,
            "account_id": account_id,
            "last_safe_seq": tail.get("last_safe_seq"),
            "last_safe_event_hash": str(tail.get("last_safe_event_hash") or ""),
            "readiness": str(readiness.get("outreach_readiness") or readiness.get("readiness") or "UNKNOWN"),
            "route_count": route_count,
            "qualified_route_count": named_qualified,
            "route_source_types": sorted({str(item.get("source") or item.get("route_source") or "") for item in routes if isinstance(item, dict)} - {""}),
            "source_projection_type": source_type,
            "eligibility": {"fully_qualified_canonical_route": True, "normalizable_lower_named_route": False, "named_route": True, "decision_saturated": True, "prepare_outreach_called": False},
        }}
    if normalizable_candidates:
        _priority, investigation_id, state, readiness, named_qualified, source_type = min(normalizable_candidates, key=lambda item: (item[0], item[1]))
        account = state.get("account") if isinstance(state.get("account"), dict) else {}
        account_id = str(account.get("account_id") or "").strip()
        routes = readiness.get("canonical_route_view") if isinstance(readiness, dict) else []
        tail = call("get_investigation_state", {"investigation_id": investigation_id})
        if not isinstance(tail, dict):
            return {"result": "BLOCKED_EXTERNAL", "candidate": None, "failure_stage": "TAIL_PIN", "reason_codes": ["MCP_READ_FAILED"]}
        return {"result": "ELIGIBLE_POSITIVE_CASE_SELECTED", "failure_stage": None, "reason_codes": ["INTEGRATED_RUNTIME_NORMALIZATION_REQUIRED"], "candidate": {
            "investigation_id": investigation_id, "account_id": account_id,
            "last_safe_seq": tail.get("last_safe_seq"), "last_safe_event_hash": str(tail.get("last_safe_event_hash") or ""), "readiness": str(readiness.get("outreach_readiness") or readiness.get("readiness") or "UNKNOWN"),
            "route_count": len(routes) if isinstance(routes, list) else 0, "qualified_route_count": named_qualified,
            "route_source_types": sorted({str(item.get("source") or item.get("route_source") or "") for item in routes if isinstance(item, dict)} - {""}),
            "source_projection_type": source_type,
            "eligibility": {"fully_qualified_canonical_route": False, "normalizable_lower_named_route": True, "candidate_projection_required": True, "named_route": True, "decision_saturated": True, "prepare_outreach_called": False},
        }}
    return {
        "result": "NO_ELIGIBLE_POSITIVE_CASE",
        "candidate": None,
        "failure_stage": None,
        "reason_codes": ["COMPANY_ROUTE_ONLY_REJECTED"] if company_route_only_seen else [],
    }


def _mcp(base: str, bearer: str, number: int, name: str, arguments: dict[str, object]) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).encode()
    request = urllib.request.Request(base.rstrip("/") + "/mcp", data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + bearer, "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": name}, method="POST")
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
            break
        except TimeoutError:
            if attempt:
                raise ValueError("MCP_READ_TIMEOUT")
    if "error" in payload:
        raise ValueError("MCP_READ_FAILED")
    result = payload.get("result")
    return result.get("structuredContent", result) if isinstance(result, dict) else result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    bearer = os.environ.get("CBI_V64_DISCOVERY_BEARER", "").strip()
    if not bearer:
        raise SystemExit("DISCOVERY_BEARER_INVALID")
    before = sanitize_health({}, {})
    stage = "BEFORE_HEALTH"
    selected = {"result": "BLOCKED_EXTERNAL", "candidate": None, "failure_stage": stage, "reason_codes": ["MCP_READ_FAILED"]}
    try:
        before = sanitize_health(json.load(urllib.request.urlopen(args.base_url.rstrip("/") + "/healthz", timeout=READ_TIMEOUT_SECONDS)), _mcp(args.base_url, bearer, 0, "get_runtime_health", {}))
        stage = "PORTFOLIO"
        portfolio = _mcp(args.base_url, bearer, 1, "get_portfolio_queue", {"limit": 1000})
        serial = iter(range(10, 100000))
        selected = select_candidate(portfolio, lambda name, arguments: _mcp(args.base_url, bearer, next(serial), name, arguments))
    except Exception as exc:
        selected = {"result": "BLOCKED_EXTERNAL", "candidate": None, "failure_stage": stage, "reason_codes": ["MCP_READ_TIMEOUT" if str(exc) == "MCP_READ_TIMEOUT" else "MCP_READ_FAILED"]}
    try:
        after = sanitize_health(json.load(urllib.request.urlopen(args.base_url.rstrip("/") + "/healthz", timeout=READ_TIMEOUT_SECONDS)), _mcp(args.base_url, bearer, 999999, "get_runtime_health", {}))
    except Exception:
        after = sanitize_health({}, {})
    if before != after:
        selected = {"result": "BLOCKED_EXTERNAL", "candidate": None, "failure_stage": "AFTER_HEALTH", "reason_codes": ["PRODUCTION_INVARIANT_CHANGED"]}
    receipt = {"schema": "cbi.v64-positive-route-discovery.v1", **selected, "production_before": before, "production_after": after}
    if set(receipt) != OUTPUT_KEYS:
        raise ValueError("DISCOVERY_RECEIPT_ALLOWLIST_INVALID")
    with open(args.output, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, sort_keys=True, separators=(",", ":")); handle.write("\n")
    return 0 if receipt["result"] == "ELIGIBLE_POSITIVE_CASE_SELECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
