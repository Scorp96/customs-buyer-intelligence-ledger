from __future__ import annotations

import copy
import re
from typing import Any

from .product_profiles import get_product_profile


LIFECYCLE_STAGES = (
    "DISCOVERED",
    "IDENTITY_VERIFIED",
    "OPPORTUNITY_CREATED",
    "QUALIFIED_TARGET",
    "CONTACT_EXHAUSTION",
    "SALES_READY",
    "ANCHOR_ELIGIBLE",
    "PROMOTED_ANCHOR",
    "FULLY_AUDITED",
)

ALTERNATE_STATES = (
    "DUPLICATE",
    "AMBIGUOUS",
    "PRODUCT_MISMATCH",
    "LOW_VALUE",
    "SECONDARY_WATCH",
    "BLOCKED",
    "NEGATIVE_EXHAUSTED",
    "CONFLICTED",
    "STALE",
)

COMMERCIAL_GRADES = ("A+", "A", "A-", "B+", "B", "B-", "C", "D", "NQ")
_GRADE_RANK = {grade: idx for idx, grade in enumerate(COMMERCIAL_GRADES)}
_TIER_RANK = {"A+": 0, "A": 1, "A-": 1, "B+": 2, "B": 3, "B-": 3, "C": 4, "D": 5, "NQ": 6}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_+-]+", "_", str(value).strip())
    return normalized.strip("_").upper()


def build_opportunity_id(account_id: str, product_profile_id: str, discriminator: str = "PRIMARY") -> str:
    account = _slug(account_id)
    profile = _slug(product_profile_id)
    disc = _slug(discriminator)
    if not account or not profile or not disc:
        raise ValueError("account_id, product_profile_id and discriminator are required")
    get_product_profile(profile)
    return f"OPP-{account}-{profile}-{disc}"


def validate_product_opportunity(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("product opportunity must be an object")
    required = ("opportunity_id", "account_id", "product_profile_id")
    missing = [field for field in required if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    profile_id = str(payload["product_profile_id"]).strip().upper()
    try:
        profile = get_product_profile(profile_id)
    except KeyError as exc:
        raise ValueError(f"unknown product profile: {profile_id}") from exc
    supplied_version = payload.get("product_profile_version")
    if supplied_version is not None and str(supplied_version) != str(profile["profile_version"]):
        raise ValueError("product profile version pin mismatch")
    supplied_sha = payload.get("product_profile_sha256")
    if supplied_sha is not None and str(supplied_sha).lower() != str(profile["profile_sha256"]).lower():
        raise ValueError("product profile sha256 pin mismatch")
    grade = payload.get("commercial_value_grade")
    if grade is not None and grade not in COMMERCIAL_GRADES:
        raise ValueError(f"invalid commercial grade: {grade}")
    stage = payload.get("lifecycle_stage", "OPPORTUNITY_CREATED")
    if stage not in LIFECYCLE_STAGES and stage not in ALTERNATE_STATES:
        raise ValueError(f"invalid lifecycle stage: {stage}")
    result = copy.deepcopy(payload)
    result["product_profile_id"] = profile_id
    result["product_profile_version"] = str(profile["profile_version"])
    result["product_profile_sha256"] = str(profile["profile_sha256"])
    result["lifecycle_stage"] = stage
    return result



def derive_product_opportunity_evaluation(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("product opportunity evaluation must be an object")
    opportunity_id = str(payload.get("opportunity_id") or "").strip()
    assessment = payload.get("assessment")
    if not opportunity_id:
        raise ValueError("opportunity_id is required")
    if not isinstance(assessment, dict):
        raise ValueError("assessment is required")
    grade = str(assessment.get("commercial_value_grade") or "").strip().upper()
    if grade not in COMMERCIAL_GRADES:
        raise ValueError("commercial_value_grade must be a valid commercial grade")
    try:
        score = float(assessment.get("commercial_value_score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("commercial_value_score must be numeric") from exc
    if not 0 <= score <= 100:
        raise ValueError("commercial_value_score must be between 0 and 100")
    evidence_ids = sorted({str(v).strip() for v in assessment.get("commercial_evidence_ids", []) if str(v).strip()})
    if not evidence_ids:
        raise ValueError("commercial_evidence_ids must contain at least one evidence id")
    confidence = assessment.get("research_confidence")
    if confidence is not None:
        confidence = float(confidence)
        if not 0 <= confidence <= 100:
            raise ValueError("research_confidence must be between 0 and 100")
    lifecycle_target = assessment.get("lifecycle_target")
    if lifecycle_target is not None and lifecycle_target not in LIFECYCLE_STAGES:
        raise ValueError("lifecycle_target must be a canonical lifecycle stage")
    return {
        "investigation_id": str(payload.get("investigation_id") or "").strip() or None,
        "opportunity_id": opportunity_id,
        "commercial_value_grade": grade,
        "commercial_value_score": score,
        "commercial_evidence_ids": evidence_ids,
        "research_confidence": confidence,
        "lifecycle_target": lifecycle_target,
        "novelty_signals": sorted({str(v).strip() for v in assessment.get("novelty_signals", []) if str(v).strip()}),
        "decision_basis": str(assessment.get("decision_basis") or "").strip() or None,
        "derived_view": True,
        "persistent_mutation_performed": False,
    }

def validate_lifecycle_transition(current_stage: str, target_stage: str) -> dict[str, Any]:
    current = str(current_stage or "").strip().upper()
    target = str(target_stage or "").strip().upper()
    if current not in LIFECYCLE_STAGES or target not in LIFECYCLE_STAGES:
        raise ValueError("lifecycle transition requires canonical lifecycle stages")
    current_index = LIFECYCLE_STAGES.index(current)
    target_index = LIFECYCLE_STAGES.index(target)
    if target_index < current_index:
        raise ValueError(f"lifecycle regression forbidden: {current} -> {target}")
    direction = "IDEMPOTENT" if target_index == current_index else "FORWARD"
    return {
        "allowed": True,
        "current_stage": current,
        "target_stage": target,
        "direction": direction,
        "stage_delta": target_index - current_index,
    }


def _grade_delta(anchor_grade: str, candidate_grade: str) -> int:
    if anchor_grade not in _GRADE_RANK or candidate_grade not in _GRADE_RANK:
        raise ValueError("anchor_grade and candidate_grade must be valid commercial grades")
    return _TIER_RANK[anchor_grade] - _TIER_RANK[candidate_grade]


def relative_opportunity(
    anchor_score: float,
    candidate_score: float,
    anchor_grade: str,
    candidate_grade: str,
    strategic: bool = False,
) -> dict[str, Any]:
    anchor_score_f = float(anchor_score)
    candidate_score_f = float(candidate_score)
    score_delta = round(candidate_score_f - anchor_score_f, 4)
    grade_delta = _grade_delta(anchor_grade, candidate_grade)

    if grade_delta > 0:
        relative_class = "UPGRADE_TARGET"
    elif grade_delta == 0 and score_delta >= 2.0:
        relative_class = "SAME_TIER_HIGH"
    elif grade_delta == 0:
        relative_class = "SAME_TIER"
    elif strategic and grade_delta == -1:
        relative_class = "STRATEGIC_LOWER"
    elif grade_delta >= -1 and score_delta >= -5.0:
        relative_class = "SECONDARY"
    else:
        relative_class = "REJECT"

    return {
        "anchor_grade": anchor_grade,
        "candidate_grade": candidate_grade,
        "anchor_score": anchor_score_f,
        "candidate_score": candidate_score_f,
        "relative_score_delta": score_delta,
        "grade_delta": grade_delta,
        "strategic": bool(strategic),
        "relative_class": relative_class,
    }
