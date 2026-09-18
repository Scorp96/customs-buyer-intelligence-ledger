from __future__ import annotations

from typing import Any

from .product_profiles import get_product_profile, portfolio_priority


_SIGNAL_TIERS = {"D1", "D2", "D3", "D4"}
_CANONICAL_READY = {"CONFIRMED", "CREATED"}


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def assess_candidate_researchability(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep discovery high-recall while reserving strict gates for qualification.

    A candidate is rejected only on a proven negative, proven duplicate, or proven
    product/entity mismatch. Missing canonical identity, procurement proof, or
    contact routes are research gaps, not rejection criteria.
    """
    if not isinstance(payload, dict):
        raise ValueError("candidate research payload must be an object")

    candidate_id = _required_string(payload, "candidate_id")
    company_name = _required_string(payload, "company_name")
    profile_id = _required_string(payload, "product_profile_id").upper()
    try:
        get_product_profile(profile_id)
    except KeyError as exc:
        raise ValueError(f"unknown product profile: {profile_id}") from exc

    tier = str(payload.get("signal_tier") or "D4").strip().upper()
    if tier not in _SIGNAL_TIERS:
        raise ValueError(f"unknown signal tier: {tier}")

    eiv = max(0.0, float(payload.get("eiv") or 0.0))
    canonical_status = str(payload.get("canonical_status") or "UNRESOLVED").strip().upper()
    canonical_ready = canonical_status in _CANONICAL_READY
    procurement_proven = bool(payload.get("procurement_proven"))
    product_or_application_signal = bool(payload.get("product_or_application_signal"))

    rejection_reasons: list[str] = []
    if bool(payload.get("proven_negative")):
        rejection_reasons.append("PROVEN_NEGATIVE")
    if bool(payload.get("duplicate_proven")):
        rejection_reasons.append("PROVEN_DUPLICATE")
    if bool(payload.get("mismatch_proven")):
        rejection_reasons.append("PROVEN_MISMATCH")

    qualification_gaps: list[str] = []
    if not canonical_ready:
        qualification_gaps.append("CANONICAL_IDENTITY_UNRESOLVED")
    if not procurement_proven:
        qualification_gaps.append("PROCUREMENT_NOT_YET_PROVEN")
    if not product_or_application_signal:
        qualification_gaps.append("PRODUCT_OR_APPLICATION_SIGNAL_WEAK_OR_UNPROVEN")

    if rejection_reasons:
        research_state = "REJECTED_PROVEN"
        retain = False
        rejected = True
        opportunity_ready = False
    elif canonical_ready and procurement_proven and tier in {"D1", "D2"}:
        research_state = "READY_FOR_QUALIFICATION"
        retain = True
        rejected = False
        opportunity_ready = True
    elif eiv > 0.0 or product_or_application_signal:
        research_state = "RESEARCH_ACTIVE"
        retain = True
        rejected = False
        opportunity_ready = False
    else:
        research_state = "DEFERRED_LOW_EIV"
        retain = True
        rejected = False
        opportunity_ready = False

    return {
        **payload,
        "candidate_id": candidate_id,
        "company_name": company_name,
        "product_profile_id": profile_id,
        "signal_tier": tier,
        "eiv": eiv,
        "canonical_status": canonical_status,
        "research_state": research_state,
        "retain_in_candidate_pool": retain,
        "rejected": rejected,
        "rejection_requires_proof": True,
        "rejection_reasons": rejection_reasons,
        "qualification_gaps": qualification_gaps,
        "canonical_research_required": not canonical_ready,
        "opportunity_creation_ready": opportunity_ready,
        "contact_readiness_is_discovery_gate": False,
        "contact_readiness_is_research_gate": False,
        "strict_gates_apply_at_qualification_or_execution": True,
    }


_TIER_PRIORITY_MODIFIER = {
    "D1": 1.60,
    "D2": 1.35,
    "D3": 1.00,
    "D4": 0.70,
}


def rank_candidate_research_queue(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank discovery candidates without requiring a commercial grade.

    D1-D4 evidence affects research order, not whether a non-rejected candidate may
    remain in the research pool. Portfolio weights are scheduling priors only.
    """
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        assessed = assess_candidate_researchability(candidate)
        if assessed["rejected"] or assessed["research_state"] == "DEFERRED_LOW_EIV":
            continue
        tier = assessed["signal_tier"]
        tier_modifier = _TIER_PRIORITY_MODIFIER[tier]
        scheduler_weight = portfolio_priority(assessed["product_profile_id"])
        priority = round(assessed["eiv"] * tier_modifier * scheduler_weight, 6)
        rows.append({
            **assessed,
            "signal_tier_modifier": tier_modifier,
            "portfolio_scheduler_weight": scheduler_weight,
            "research_priority": priority,
            "priority_is_research_order_not_commercial_value": True,
            "commercial_grade_required_for_research_queue": False,
        })
    rows.sort(
        key=lambda row: (
            float(row["research_priority"]),
            float(row.get("eiv") or 0.0),
            str(row.get("candidate_id") or ""),
        ),
        reverse=True,
    )
    return rows
