from __future__ import annotations

import copy
from typing import Any

from .product_profiles import get_product_profile


MATERIAL_NOVELTY_SIGNALS = frozenset({
    "NEW_MARKET_CELL",
    "NEW_APPLICATION",
    "NEW_SUPPLIER_NETWORK",
    "STRONG_CURRENT_PROCUREMENT",
    "STRONG_COMMERCIAL_NOVELTY",
    "COMPETITIVE_REPLACEMENT_OPPORTUNITY",
    "STRONG_CROSS_SELL_PORTFOLIO",
    "UNDERREPRESENTED_GEOGRAPHY",
    "UNDERREPRESENTED_CHANNEL",
})

ANCHOR_GRADE_ELIGIBILITY = frozenset({"A+", "A", "A-", "B+"})


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def build_candidate_discovery(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("candidate discovery must be an object")
    result = copy.deepcopy(payload)
    result["candidate_id"] = _required_string(payload, "candidate_id")
    result["discovered_from_anchor_id"] = _required_string(payload, "discovered_from_anchor_id")
    result["branch_group"] = _required_string(payload, "branch_group")
    result["branch"] = _required_string(payload, "branch")
    result["company_name"] = _required_string(payload, "company_name")
    profile_id = _required_string(payload, "product_profile_id").upper()
    try:
        get_product_profile(profile_id)
    except KeyError as exc:
        raise ValueError(f"unknown product profile: {profile_id}") from exc
    result["product_profile_id"] = profile_id
    result["stage"] = "DISCOVERED"
    result["inherited_anchor_facts"] = False
    result["product_evidence_ids"] = []
    result["procurement_evidence_ids"] = []
    return result


def build_cross_sell_hypotheses(source: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(source, dict):
        raise ValueError("cross-sell source must be an object")
    account_id = _required_string(source, "account_id")
    source_opportunity_id = _required_string(source, "source_opportunity_id")
    source_profile_id = _required_string(source, "source_product_profile_id").upper()
    try:
        profile = get_product_profile(source_profile_id)
    except KeyError as exc:
        raise ValueError(f"unknown product profile: {source_profile_id}") from exc

    hypotheses: list[dict[str, Any]] = []
    for target_profile_id in profile.get("cross_sell_profiles", []):
        target = get_product_profile(target_profile_id)
        hypotheses.append({
            "account_id": account_id,
            "source_opportunity_id": source_opportunity_id,
            "source_product_profile_id": source_profile_id,
            "product_profile_id": target["profile_id"],
            "state": "CROSS_SELL_HYPOTHESIS",
            "product_evidence_ids": [],
            "procurement_evidence_ids": [],
            "inherits_source_product_evidence": False,
            "requires_independent_product_evidence": True,
        })
    return hypotheses


def evaluate_anchor_eligibility(opportunity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(opportunity, dict):
        raise ValueError("opportunity must be an object")
    grade = str(opportunity.get("commercial_value_grade") or "").strip()
    canonical_status = str(opportunity.get("canonical_status") or "").strip().upper()
    commercial_evidence_bound = bool(opportunity.get("commercial_evidence_bound"))
    novelty_signals = {
        str(value).strip().upper()
        for value in (opportunity.get("novelty_signals") or [])
        if str(value).strip()
    }
    material_novelty = sorted(novelty_signals & MATERIAL_NOVELTY_SIGNALS)

    blockers: list[str] = []
    if canonical_status not in {"CONFIRMED", "CREATED"}:
        blockers.append("CANONICAL_ACCOUNT_NOT_CONFIRMED")
    if not commercial_evidence_bound:
        blockers.append("COMMERCIAL_EVIDENCE_NOT_BOUND")
    if grade not in ANCHOR_GRADE_ELIGIBILITY:
        blockers.append("COMMERCIAL_GRADE_BELOW_ANCHOR_THRESHOLD")
    if not material_novelty:
        if grade == "B+":
            blockers.append("BPLUS_REQUIRES_MATERIAL_NOVELTY")
        elif grade in {"A+", "A", "A-"}:
            blockers.append("MATERIAL_NOVELTY_REQUIRED")

    return {
        "anchor_eligible": not blockers,
        "commercial_value_grade": grade,
        "canonical_status": canonical_status,
        "commercial_evidence_bound": commercial_evidence_bound,
        "material_novelty_signals": material_novelty,
        "contact_readiness_is_gate": False,
        "blockers": blockers,
    }


def project_anchor_promotion(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("anchor promotion must be an object")
    opportunity_id = _required_string(payload, "opportunity_id")
    eligibility = payload.get("anchor_eligibility")
    if not isinstance(eligibility, dict) or not bool(eligibility.get("anchor_eligible")):
        raise ValueError("opportunity is not anchor eligible")
    if not bool(payload.get("cycle_dedup_complete")):
        raise ValueError("cycle dedup must be complete before anchor promotion")
    return {
        "opportunity_id": opportunity_id,
        "stage": "PROMOTED_ANCHOR",
        "cycle_dedup_complete": True,
        "contact_readiness_is_gate": False,
        "persistent_mutation_performed": False,
    }
