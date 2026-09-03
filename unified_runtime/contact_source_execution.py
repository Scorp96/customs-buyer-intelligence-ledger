from __future__ import annotations

import hashlib
import json
from typing import Any


def _task_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "V63CONTACT-" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _query_for_source(company_name: str, source_family: str, route_target: str) -> str:
    company = f'"{company_name}"'
    if route_target == "NAMED":
        role_terms = "procurement purchasing sourcing owner operations"
        if source_family == "linkedin_people":
            return f"{company} {role_terms} LinkedIn"
        if source_family == "official_team":
            return f"{company} team management {role_terms}"
        return f"{company} {role_terms} {source_family.replace('_', ' ')}"
    if source_family == "official_contact":
        return f"{company} official contact email phone"
    if source_family in {"google_maps_business", "local_maps"}:
        return f"{company} maps phone website"
    return f"{company} {source_family.replace('_', ' ')} contact"


def plan_contact_source_tasks(
    opportunity_id: str,
    company_name: str,
    contact_plan: dict[str, Any],
    *,
    named_route_material: bool = False,
    max_tasks: int = 100,
) -> dict[str, Any]:
    opp_id = str(opportunity_id or "").strip()
    company = str(company_name or "").strip()
    if not opp_id or not company:
        raise ValueError("opportunity_id and company_name are required")
    if not isinstance(contact_plan, dict):
        raise ValueError("contact_plan must be an object")
    if max_tasks < 1:
        raise ValueError("max_tasks must be >= 1")
    max_tasks = min(int(max_tasks), 1000)

    company_ready = bool(contact_plan.get("company_route_ready"))
    named_ready = bool(contact_plan.get("named_route_ready"))
    named_policy = str(contact_plan.get("named_route_policy") or "NONE")
    company_required = bool(contact_plan.get("company_route_required"))
    named_required = named_policy == "EXHAUSTIVE"

    tasks: list[dict[str, Any]] = []

    def add(route_target: str, source_family: str, material: bool, required: bool) -> None:
        identity = {
            "opportunity_id": opp_id,
            "route_target": route_target,
            "source_family": str(source_family),
            "company_name": company,
        }
        tasks.append({
            "task_id": _task_id(identity),
            **identity,
            "query": _query_for_source(company, str(source_family), route_target),
            "material": bool(material),
            "required_for_completion": bool(required),
            "execution_required": True,
            "receipt_required": True,
            "search_execution_performed": False,
        })

    if not company_ready and company_required:
        for source_family in contact_plan.get("company_route_source_families", []) or []:
            add("COMPANY", str(source_family), True, True)

    if not named_ready and named_policy != "NONE":
        named_material = named_required or named_policy == "HIGH_PRIORITY" or bool(named_route_material)
        for source_family in contact_plan.get("named_route_source_families", []) or []:
            add("NAMED", str(source_family), named_material, named_required)

    candidate_count = len(tasks)
    returned = tasks[:max_tasks]
    truncated = candidate_count > len(returned)
    return {
        "status": "PLANNED",
        "opportunity_id": opp_id,
        "company_name": company,
        "commercial_value_grade": contact_plan.get("commercial_value_grade"),
        "company_route_required_for_completion": company_required,
        "named_route_required_for_completion": named_required,
        "initial_company_route_ready": company_ready,
        "initial_named_route_ready": named_ready,
        "task_candidate_count": candidate_count,
        "returned_count": len(returned),
        "truncated": truncated,
        "tasks": returned,
        "planning_is_execution_proof": False,
        "host_execution_required": True,
    }


def _negative_terminal(receipt: dict[str, Any]) -> bool:
    result = str(receipt.get("result") or "").upper()
    if not str(receipt.get("completed_at") or "").strip():
        return False
    if result == "NEGATIVE_EXHAUSTED":
        return bool(str(receipt.get("raw_result_locator") or "").strip())
    if result == "NOT_APPLICABLE_JUSTIFIED":
        return bool(str(receipt.get("not_applicable_reason") or receipt.get("justification") or "").strip())
    return False


def _positive_route(receipt: dict[str, Any], route_target: str) -> bool:
    if str(receipt.get("result") or "").upper() != "POSITIVE":
        return False
    if not str(receipt.get("completed_at") or "").strip():
        return False
    if not str(receipt.get("raw_result_locator") or "").strip():
        return False
    if not [value for value in receipt.get("route_evidence_ids", []) if str(value).strip()]:
        return False
    if not bool(receipt.get("verified")) or bool(receipt.get("guessed")):
        return False
    owner_scope = str(receipt.get("owner_scope") or "").upper()
    if route_target == "COMPANY":
        return owner_scope == "ACCOUNT"
    if route_target == "NAMED":
        return owner_scope == "PERSON" and bool(receipt.get("current_company_association"))
    return False


def evaluate_contact_coverage(plan: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    tasks = [task for task in plan.get("tasks", []) if isinstance(task, dict)]
    by_id = {str(task.get("task_id")): task for task in tasks if str(task.get("task_id") or "")}
    receipts_by_task: dict[str, list[dict[str, Any]]] = {}
    for receipt in receipts or []:
        if not isinstance(receipt, dict):
            continue
        task_id = str(receipt.get("task_id") or "").strip()
        if task_id:
            receipts_by_task.setdefault(task_id, []).append(receipt)

    company_route_proven = bool(plan.get("initial_company_route_ready"))
    named_route_proven = bool(plan.get("initial_named_route_ready"))
    terminal_negative_ids: set[str] = set()

    for task_id, task in by_id.items():
        route_target = str(task.get("route_target") or "").upper()
        task_receipts = receipts_by_task.get(task_id, [])
        if any(_positive_route(receipt, route_target) for receipt in task_receipts):
            if route_target == "COMPANY":
                company_route_proven = True
            elif route_target == "NAMED":
                named_route_proven = True
        if any(_negative_terminal(receipt) for receipt in task_receipts):
            terminal_negative_ids.add(task_id)

    # A verified named route is stronger than a company route for contact readiness.
    if named_route_proven:
        company_route_proven = True

    required_tasks = [task for task in tasks if bool(task.get("required_for_completion"))]
    open_required: list[str] = []
    for task in required_tasks:
        task_id = str(task.get("task_id"))
        target = str(task.get("route_target") or "").upper()
        satisfied_by_route = company_route_proven if target == "COMPANY" else named_route_proven
        if satisfied_by_route or task_id in terminal_negative_ids:
            continue
        open_required.append(task_id)

    truncated = bool(plan.get("truncated"))
    named_required = bool(plan.get("named_route_required_for_completion"))
    company_required = bool(plan.get("company_route_required_for_completion"))

    if truncated:
        complete = False
        reason = "TRUNCATED_CONTACT_PLAN"
    elif named_route_proven:
        complete = True
        reason = "NAMED_ROUTE_READY"
    elif company_route_proven and not named_required:
        complete = True
        reason = "COMPANY_ROUTE_READY"
    elif not open_required and required_tasks:
        complete = True
        reason = "REQUIRED_CONTACT_SOURCES_EXHAUSTED"
    elif not company_required and not named_required:
        complete = True
        reason = "NO_REQUIRED_CONTACT_RESEARCH"
    else:
        complete = False
        reason = "CONTACT_RESEARCH_REMAINS"

    return {
        "contact_exhaustion_complete": complete,
        "completion_reason": reason,
        "company_route_proven": company_route_proven,
        "named_route_proven": named_route_proven,
        "required_task_count": len(required_tasks),
        "open_required_task_count": len(open_required),
        "open_required_task_ids": open_required,
        "plan_truncated": truncated,
        "planning_is_execution_proof": False,
    }
