from __future__ import annotations

from typing import Any

from .expansion_planner import compute_expansion_priority


_GRADE_MODIFIER = {
    "A+": 2.00,
    "A": 1.60,
    "A-": 1.40,
    "B+": 1.00,
    "B": 0.75,
    "B-": 0.60,
    "C": 0.35,
    "D": 0.15,
    "NQ": 0.00,
}

_CONTACT_GAP_MODIFIER = {
    "BLOCKED": 1.20,
    "IDENTITY_ONLY": 1.15,
    "COMPANY_ROUTE_READY": 1.00,
    "NAMED_ROUTE_READY": 0.90,
    "FOLLOW_UP_READY": 0.85,
    "SEND_READY": 0.80,
}


def _commercial_score_modifier(score: float) -> float:
    value = min(100.0, max(0.0, float(score)))
    return 0.75 + value / 200.0


def rank_research_opportunities(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for opportunity in opportunities:
        if not isinstance(opportunity, dict):
            raise ValueError("each opportunity must be an object")
        grade = str(opportunity.get("commercial_value_grade") or "").strip()
        if grade not in _GRADE_MODIFIER:
            raise ValueError(f"unknown commercial grade: {grade}")

        base = compute_expansion_priority({
            "product_profile_id": opportunity.get("product_profile_id"),
            "eiv": opportunity.get("eiv", 0.0),
            "commercial_score": opportunity.get("commercial_score", 0.0),
            "relative_class": opportunity.get("relative_class", "SECONDARY"),
            "market_acceptance": opportunity.get("market_acceptance", "M0"),
        })
        grade_modifier = _GRADE_MODIFIER[grade]
        score_modifier = _commercial_score_modifier(float(opportunity.get("commercial_score") or 0.0))
        outreach = str(opportunity.get("outreach_readiness") or "IDENTITY_ONLY").upper()
        contact_gap_modifier = _CONTACT_GAP_MODIFIER.get(outreach, 1.0)
        source_gap_modifier = 1.0 if bool(opportunity.get("source_coverage_complete")) else 1.10

        research_priority = round(
            float(base["priority"])
            * grade_modifier
            * score_modifier
            * contact_gap_modifier
            * source_gap_modifier,
            6,
        )
        ranked.append({
            **opportunity,
            "commercial_value_grade": grade,
            "commercial_score": float(opportunity.get("commercial_score") or 0.0),
            "research_priority": research_priority,
            "portfolio_scheduler_weight": base["portfolio_scheduler_weight"],
            "commercial_grade_modifier": grade_modifier,
            "commercial_score_modifier": score_modifier,
            "contact_gap_modifier": contact_gap_modifier,
            "source_gap_modifier": source_gap_modifier,
            "commercial_grade_mutated": False,
            "priority_is_research_order_not_commercial_value": True,
        })

    ranked.sort(
        key=lambda row: (
            float(row["research_priority"]),
            float(row.get("commercial_score") or 0.0),
            str(row.get("opportunity_id") or ""),
        ),
        reverse=True,
    )
    return ranked


def schedule_research_work(opportunities: list[dict[str, Any]], budget_units: float) -> dict[str, Any]:
    """Allocate a soft resource budget without using budget state as completion authority."""
    budget = max(0.0, float(budget_units))
    ranked = rank_research_opportunities(opportunities)
    remaining = budget
    scheduled: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for row in ranked:
        cost = max(0.0, float(row.get("estimated_cost_units", 1.0) or 0.0))
        enriched = {**row, "estimated_cost_units": cost}
        if float(row.get("research_priority") or 0.0) <= 0.0:
            deferred.append(enriched)
            continue
        if cost <= remaining:
            scheduled.append(enriched)
            remaining = round(remaining - cost, 6)
        else:
            deferred.append(enriched)

    deferred_material = [
        row for row in deferred
        if bool(row.get("material")) and float(row.get("research_priority") or 0.0) > 0.0
    ]
    used = round(budget - remaining, 6)
    exhausted = bool(ranked) and remaining <= 0.0
    if deferred_material:
        research_action = "CONTINUE_WHEN_RESOURCE_AVAILABLE"
    elif scheduled:
        research_action = "EXECUTE_SCHEDULED_WORK"
    else:
        research_action = "NO_MATERIAL_DEFERRED_WORK"

    return {
        "budget": {
            "allocated_units": budget,
            "used_units": used,
            "remaining_units": remaining,
        },
        "resource_state": "EXHAUSTED" if exhausted else "AVAILABLE",
        "research_action": research_action,
        "scheduled": scheduled,
        "deferred": deferred,
        "deferred_material": deferred_material,
        "budget_exhaustion_closes_research": False,
        "research_complete": False,
        "decision_saturation_not_evaluated": True,
    }
