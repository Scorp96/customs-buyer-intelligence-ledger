from __future__ import annotations

from typing import Any

from .capability_profile import evaluate_capability_fit
from .local_context_resolution import plan_local_context_resolution
from .local_outreach_policy import plan_local_outreach
from .opportunity_domain import validate_product_opportunity
from .route_reuse import reuse_route_for_opportunity


_PRIORITY_GRADES = frozenset({"A+", "A", "A-", "B+"})
_STRATEGIC_GRADES = frozenset({"B", "B-"})


def _channel_from_route(route: dict[str, Any], context: dict[str, Any]) -> str:
    channel = str(route.get("channel") or context.get("channel") or "").strip().upper()
    if not channel:
        raise ValueError("selected route must identify an outreach channel")
    return channel


def evaluate_sales_readiness(payload: dict[str, Any], capability_profile: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether one qualified opportunity is ready for commercial outreach.

    This is a read-only planning projection. It deliberately separates:
      * commercial opportunity value,
      * route usability,
      * recipient-local execution timing/language,
      * seller technical capability,
      * technical-offer readiness.

    It never sends a message, creates a server-side draft, or mutates the
    opportunity's commercial grade.
    """
    if not isinstance(payload, dict):
        raise ValueError("sales readiness payload must be an object")
    if not isinstance(capability_profile, dict):
        raise ValueError("capability_profile must be an object")

    opportunity = validate_product_opportunity(dict(payload.get("opportunity") or {}))
    grade = str(opportunity.get("commercial_value_grade") or "NQ").strip().upper()
    strategic_material = bool(payload.get("strategic_material", False))

    selected_route = dict(payload.get("selected_route") or {})
    local_context = dict(payload.get("local_context") or {})
    product_demand = dict(payload.get("product_demand") or {})
    product_demand.setdefault("product_profile_id", opportunity["product_profile_id"])
    if opportunity.get("product_variant") and not product_demand.get("product_variant"):
        product_demand["product_variant"] = opportunity.get("product_variant")

    capability = evaluate_capability_fit(capability_profile, product_demand)

    # Commercial prioritization is independent of route/timing/capability.
    outreach_priority_eligible = grade in _PRIORITY_GRADES or (
        strategic_material and grade in _STRATEGIC_GRADES
    )

    if not outreach_priority_eligible:
        return {
            "sales_readiness_state": "LOW_PRIORITY_RESEARCH_ONLY",
            "commercial_outreach_ready": False,
            "technical_offer_ready": False,
            "technical_promises_blocked": True,
            "commercial_value_grade": grade,
            "commercial_grade_mutated": False,
            "capability_fit": capability,
            "route_reuse": None,
            "local_context_resolution": None,
            "local_outreach": None,
            "channel": None,
            "outreach_language": None,
            "secondary_language": None,
            "next_window_local": None,
            "sends_message": False,
            "server_side_draft_created": False,
            "advisory_only": True,
            "persistent_mutation_performed": False,
        }

    if not selected_route:
        route_reuse = {
            "route_reusable": False,
            "blockers": ["SELECTED_ROUTE_REQUIRED"],
            "route_proves_product_interest": False,
            "route_proves_procurement": False,
            "commercial_grade_mutated": False,
        }
    else:
        route_reuse = reuse_route_for_opportunity(selected_route, opportunity)

    if not route_reuse["route_reusable"]:
        return {
            "sales_readiness_state": "CONTACT_RESEARCH_REQUIRED",
            "commercial_outreach_ready": False,
            "technical_offer_ready": False,
            "technical_promises_blocked": True,
            "commercial_value_grade": grade,
            "commercial_grade_mutated": False,
            "capability_fit": capability,
            "route_reuse": route_reuse,
            "local_context_resolution": None,
            "local_outreach": None,
            "channel": str(selected_route.get("channel") or "").strip().upper() or None,
            "outreach_language": None,
            "secondary_language": None,
            "next_window_local": None,
            "sends_message": False,
            "server_side_draft_created": False,
            "advisory_only": True,
            "persistent_mutation_performed": False,
        }

    context_resolution_input = {**local_context, "account_id": opportunity["account_id"]}
    local_resolution = plan_local_context_resolution(context_resolution_input)
    if local_resolution["tasks"]:
        return {
            "sales_readiness_state": "LOCAL_CONTEXT_RESOLUTION_REQUIRED",
            "commercial_outreach_ready": False,
            "technical_offer_ready": False,
            "technical_promises_blocked": True,
            "commercial_value_grade": grade,
            "commercial_grade_mutated": False,
            "capability_fit": capability,
            "route_reuse": route_reuse,
            "local_context_resolution": local_resolution,
            "local_outreach": None,
            "channel": str(selected_route.get("channel") or "").strip().upper() or None,
            "outreach_language": None,
            "secondary_language": None,
            "next_window_local": None,
            "sends_message": False,
            "server_side_draft_created": False,
            "advisory_only": True,
            "persistent_mutation_performed": False,
        }

    channel = _channel_from_route(selected_route, local_context)
    local_plan = plan_local_outreach({**local_context, "channel": channel})

    if not local_plan["execution_ready"]:
        # A valid context with a closed local window is a scheduling issue. Route
        # disablement/cooldown remains visible through the local plan next_action.
        state = "WAIT_FOR_LOCAL_WINDOW"
        if "SAME_ROUTE_DISABLED" in local_plan["execution_blockers"]:
            state = "CONTACT_RESEARCH_REQUIRED"
        elif "GENERIC_FOLLOWUP_BLOCKED_BY_ACTIVE_CONVERSATION" in local_plan["execution_blockers"]:
            state = "ACTIVE_CONVERSATION_CONTEXT_REQUIRED"
        elif "FOLLOWUP_COOLDOWN" in local_plan["execution_blockers"]:
            state = "FOLLOWUP_COOLDOWN"
        return {
            "sales_readiness_state": state,
            "commercial_outreach_ready": False,
            "technical_offer_ready": False,
            "technical_promises_blocked": capability["capability_fit"] != "SUPPORTED",
            "commercial_value_grade": grade,
            "commercial_grade_mutated": False,
            "capability_fit": capability,
            "route_reuse": route_reuse,
            "local_context_resolution": local_resolution,
            "local_outreach": local_plan,
            "channel": channel,
            "outreach_language": local_plan.get("outreach_language"),
            "secondary_language": local_plan.get("secondary_language"),
            "next_window_local": local_plan.get("next_window_local"),
            "sends_message": False,
            "server_side_draft_created": False,
            "advisory_only": True,
            "persistent_mutation_performed": False,
        }

    capability_state = capability["capability_fit"]
    if capability_state == "UNSUPPORTED":
        state = "CAPABILITY_MISMATCH"
        commercial_outreach_ready = False
        technical_offer_ready = False
        technical_promises_blocked = True
    elif capability_state == "NEEDS_VERIFICATION":
        state = "OUTREACH_READY_TECH_CONFIRMATION_REQUIRED"
        commercial_outreach_ready = True
        technical_offer_ready = False
        technical_promises_blocked = True
    else:
        state = "OUTREACH_EXECUTION_READY"
        commercial_outreach_ready = True
        technical_offer_ready = True
        technical_promises_blocked = False

    return {
        "sales_readiness_state": state,
        "commercial_outreach_ready": commercial_outreach_ready,
        "technical_offer_ready": technical_offer_ready,
        "technical_promises_blocked": technical_promises_blocked,
        "commercial_value_grade": grade,
        "commercial_grade_mutated": False,
        "capability_fit": capability,
        "route_reuse": route_reuse,
        "local_context_resolution": local_resolution,
        "local_outreach": local_plan,
        "channel": channel,
        "outreach_language": local_plan.get("outreach_language"),
        "secondary_language": local_plan.get("secondary_language"),
        "next_window_local": local_plan.get("next_window_local"),
        "sends_message": False,
        "server_side_draft_created": False,
        "advisory_only": True,
        "persistent_mutation_performed": False,
    }
