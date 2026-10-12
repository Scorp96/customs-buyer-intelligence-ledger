from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any
from collections import deque


SOURCE_FAMILIES_BY_BRANCH_GROUP: dict[str, tuple[str, ...]] = {
    "TRADE_GRAPH": (
        "trade_history",
        "supplier_official",
        "customs_parties",
        "partner_reference",
    ),
    "APPLICATION_GRAPH": (
        "search_engine",
        "official_home",
        "industry_directory",
        "maps_region",
        "association_exhibition_chamber",
    ),
    "CHANNEL_GRAPH": (
        "search_engine",
        "maps_region",
        "local_directory",
        "industry_directory",
        "association_exhibition_chamber",
    ),
    "MARKET_GRAPH": (
        "maps_region",
        "local_directory",
        "search_engine",
        "association_exhibition_chamber",
    ),
    "COMPETITIVE_GRAPH": (
        "supplier_official",
        "trade_history",
        "product_alternative_search",
        "search_engine",
    ),
    "CROSS_SELL_GRAPH": (
        "official_products",
        "official_catalog",
        "public_store_inventory",
        "search_engine",
    ),
}

_TERMINAL_RESULTS = {"POSITIVE", "NEGATIVE_EXHAUSTED", "NOT_APPLICABLE_JUSTIFIED"}
_CURSOR_SCHEMA = "cbi.v63-source-task-cursor.v1"
_TASK_ORDER_POLICY = "BALANCED_GROUP_BRANCH_FAMILY_V1"


def _call_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "V63CALL-" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _plan_fingerprint(expansion_plan: dict[str, Any], queries: list[str]) -> str:
    payload = {
        "task_order_policy": _TASK_ORDER_POLICY,
        "product_profile_id": str(expansion_plan.get("product_profile_id") or "").upper(),
        "market_acceptance": str(expansion_plan.get("market_acceptance") or "").upper(),
        "branches": expansion_plan.get("branches") or {},
        "queries": list(queries),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _encode_cursor(plan_fingerprint: str, offset: int) -> str:
    payload = {
        "schema": _CURSOR_SCHEMA,
        "plan_fingerprint": plan_fingerprint,
        "offset": int(offset),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(token: str, plan_fingerprint: str) -> int:
    encoded = str(token or "").strip()
    if not encoded:
        return 0
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("INVALID_SOURCE_TASK_CONTINUATION_TOKEN") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _CURSOR_SCHEMA:
        raise ValueError("INVALID_SOURCE_TASK_CONTINUATION_TOKEN")
    if str(payload.get("plan_fingerprint") or "") != plan_fingerprint:
        raise ValueError("SOURCE_TASK_CONTINUATION_PLAN_MISMATCH")
    try:
        offset = int(payload.get("offset"))
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_SOURCE_TASK_CONTINUATION_TOKEN") from exc
    if offset < 0:
        raise ValueError("INVALID_SOURCE_TASK_CONTINUATION_TOKEN")
    return offset


def plan_public_source_tasks(
    expansion_plan: dict[str, Any],
    discovery_plan: dict[str, Any],
    *,
    max_tasks: int = 1000,
    continuation_token: str | None = None,
) -> dict[str, Any]:
    if not isinstance(expansion_plan, dict) or not isinstance(discovery_plan, dict):
        raise ValueError("expansion_plan and discovery_plan must be objects")
    if max_tasks < 1:
        raise ValueError("max_tasks must be >= 1")
    max_tasks = min(int(max_tasks), 1000)

    queries = [
        str(row.get("query") or "").strip()
        for row in discovery_plan.get("queries", [])
        if isinstance(row, dict) and str(row.get("query") or "").strip()
    ]
    plan_fingerprint = _plan_fingerprint(expansion_plan, queries)
    offset = _decode_cursor(continuation_token or "", plan_fingerprint)
    branches = expansion_plan.get("branches") or {}

    def branch_candidates(group: str, branch: str):
        # Query-major produces source-family diversity before trying dozens of
        # variants from the same data provider. Identity/call_id stay stable.
        for query in queries:
            for family in SOURCE_FAMILIES_BY_BRANCH_GROUP[group]:
                yield {
                    "branch_group": group,
                    "branch": branch,
                    "source_family": family,
                    "query": query,
                }

    def group_candidates(group: str):
        # Interleave branches inside each group so 'same_supplier_buyer'
        # cannot consume the entire TRADE_GRAPH allocation.
        pending = deque(
            branch_candidates(group, str(branch))
            for branch in (branches.get(group) or [])
            if str(branch).strip()
        )
        while pending:
            iterator = pending.popleft()
            try:
                item = next(iterator)
            except StopIteration:
                continue
            pending.append(iterator)
            yield item

    def iter_tasks():
        # Deterministic six-group round robin; the dict's incidental insertion
        # order cannot change pagination with an unchanged plan fingerprint.
        pending = deque(
            group_candidates(group)
            for group in SOURCE_FAMILIES_BY_BRANCH_GROUP
            if branches.get(group)
        )
        seen: set[str] = set()
        while pending:
            iterator = pending.popleft()
            try:
                identity = next(iterator)
            except StopIteration:
                continue
            pending.append(iterator)
            call_id = _call_id(identity)
            if call_id in seen:
                continue
            seen.add(call_id)
            yield {
                "call_id": call_id,
                **identity,
                "execution_required": True,
                "receipt_required": True,
                "search_execution_performed": False,
            }

    candidate_count = 0
    returned: list[dict[str, Any]] = []
    page_end = offset + max_tasks
    for task in iter_tasks():
        if offset <= candidate_count < page_end:
            returned.append(task)
        candidate_count += 1
    if offset > candidate_count:
        raise ValueError("SOURCE_TASK_CONTINUATION_OFFSET_OUT_OF_RANGE")
    next_offset = offset + len(returned)
    has_more = next_offset < candidate_count
    # A continuation page cannot independently prove exhaustive coverage.
    # Even its final page omits every earlier task.
    local_truncated = has_more or offset > 0
    next_token = _encode_cursor(plan_fingerprint, next_offset) if has_more else None
    upstream_truncated = bool(discovery_plan.get("truncated"))
    return {
        "status": "PLANNED",
        "product_profile_id": expansion_plan.get("product_profile_id"),
        "market_acceptance": expansion_plan.get("market_acceptance"),
        "task_candidate_count": candidate_count,
        "returned_count": len(returned),
        "offset": offset,
        "plan_fingerprint": plan_fingerprint,
        "task_order_policy": _TASK_ORDER_POLICY,
        "continuation_token": next_token,
        "next_cursor": next_token,
        "has_more": has_more,
        "truncated": local_truncated or upstream_truncated,
        "page_is_complete_plan": not (local_truncated or upstream_truncated),
        "local_task_truncated": local_truncated,
        "upstream_query_plan_truncated": upstream_truncated,
        "tasks": returned,
        "planning_is_execution_proof": False,
        "host_execution_required": True,
        "source_coverage_complete": False,
    }


def _receipt_is_terminal(receipt: dict[str, Any]) -> bool:
    result = str(receipt.get("result") or "").upper()
    if result not in _TERMINAL_RESULTS:
        return False
    if not str(receipt.get("completed_at") or "").strip():
        return False
    if result == "POSITIVE":
        evidence_ids = [str(value) for value in receipt.get("evidence_ids", []) if str(value).strip()]
        return bool(evidence_ids) and bool(str(receipt.get("raw_result_locator") or "").strip())
    if result == "NEGATIVE_EXHAUSTED":
        return bool(str(receipt.get("raw_result_locator") or "").strip())
    if result == "NOT_APPLICABLE_JUSTIFIED":
        return bool(str(receipt.get("not_applicable_reason") or receipt.get("justification") or "").strip())
    return False


def evaluate_source_coverage(plan: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    planned_tasks = [row for row in plan.get("tasks", []) if isinstance(row, dict)]
    planned_ids = [str(row.get("call_id") or "") for row in planned_tasks if str(row.get("call_id") or "")]

    receipts_by_call: dict[str, list[dict[str, Any]]] = {}
    for receipt in receipts or []:
        if not isinstance(receipt, dict):
            continue
        call_id = str(receipt.get("call_id") or "").strip()
        if not call_id:
            continue
        receipts_by_call.setdefault(call_id, []).append(receipt)

    terminal_ids: set[str] = set()
    for call_id in planned_ids:
        if any(_receipt_is_terminal(receipt) for receipt in receipts_by_call.get(call_id, [])):
            terminal_ids.add(call_id)

    open_call_ids = [call_id for call_id in planned_ids if call_id not in terminal_ids]
    # Final continuation pages and hand-assembled partial plans are not
    # whole-plan coverage receipts, even when has_more=False.
    offset = plan.get("offset", 0)
    try:
        offset_is_positive = int(offset) > 0
    except (TypeError, ValueError):
        offset_is_positive = True
    candidate_count = plan.get("task_candidate_count")
    try:
        candidate_count_exceeds_page = (
            candidate_count is not None and int(candidate_count) > len(planned_ids)
        )
    except (TypeError, ValueError):
        candidate_count_exceeds_page = True
    is_truncated = bool(
        plan.get("truncated")
        or plan.get("has_more")
        or plan.get("upstream_query_plan_truncated")
        or offset_is_positive
        or candidate_count_exceeds_page
    )
    if is_truncated:
        complete = False
        status = "INCOMPLETE_TRUNCATED_PLAN"
    elif not planned_ids:
        complete = False
        status = "NO_PLANNED_CALLS"
    elif open_call_ids:
        complete = False
        status = "INCOMPLETE"
    else:
        complete = True
        status = "PROVEN_COMPLETE"

    return {
        "source_coverage_complete": complete,
        "status": status,
        "planned_call_count": len(planned_ids),
        "terminal_call_count": len(terminal_ids),
        "missing_call_count": len(open_call_ids),
        "open_call_ids": open_call_ids,
        "plan_truncated": is_truncated,
        "planning_is_execution_proof": False,
    }
