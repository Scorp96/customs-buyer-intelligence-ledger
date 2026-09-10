from __future__ import annotations

from typing import Any

from .candidate_anchor import build_candidate_discovery, evaluate_anchor_eligibility
from .canonical_resolution_gate import validate_canonical_resolution_proof
from .contact_exhaustion import plan_contact_exhaustion
from .contact_source_execution import plan_contact_source_tasks
from .demand_market import derive_demand_anchor, derive_market_cell, evaluate_market_acceptance
from .expansion_planner import generate_discovery_queries, plan_expansion
from .market_scope import derive_market_expansion_scope
from .opportunity_domain import build_opportunity_id, relative_opportunity, validate_product_opportunity
from .product_profiles import get_product_profile


def _variant_mapping(profile: dict[str, Any], variant: str) -> tuple[list[str], list[str], bool]:
    variant = str(variant or "").strip().upper()
    if not variant:
        return [], [], True
    mapping = (profile.get("variant_application_map") or {}).get(variant)
    if not mapping:
        return [], [], True
    applications = list(mapping.get("applications") or [])
    archetypes = list(mapping.get("buyer_archetypes") or [])
    requires_research = bool(mapping.get("technical_identity_requires_verification", False))
    return applications, archetypes, requires_research


def plan_customs_seed_expansion(seed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(seed, dict):
        raise ValueError("customs seed must be an object")
    profile_id = str(seed.get("product_profile_id") or "").strip().upper()
    profile = get_product_profile(profile_id)
    variant = str(seed.get("product_variant") or "").strip().upper()
    applications, archetypes, mapping_requires_research = _variant_mapping(profile, variant)

    anchor_payload = dict(seed)
    anchor_payload["source_type"] = "CUSTOMS"
    anchor_payload["product_profile_id"] = profile_id
    anchor_payload["product_variant"] = variant or None
    anchor_payload["application_hypothesis"] = applications
    if applications and "application_confidence" not in anchor_payload:
        anchor_payload["application_confidence"] = "PROFILE_GUIDED_HYPOTHESIS"
    anchor = derive_demand_anchor(anchor_payload)
    market_acceptance = evaluate_market_acceptance([anchor])
    market_scope = derive_market_expansion_scope(market_acceptance["level"], geography=str(seed.get("geography") or ""))
    market_cell = derive_market_cell(
        anchor,
        applications,
        archetypes,
        channel=seed.get("channel"),
    )

    expansion_context = {
        "product_profile_id": profile_id,
        "market_acceptance": market_acceptance["level"],
        "anchor_grade": seed.get("anchor_grade"),
        "anchor_score": seed.get("anchor_score"),
        "applications": applications,
        "buyer_archetypes": archetypes,
        "geography": seed.get("geography"),
    }
    expansion_plan = plan_expansion(expansion_context)
    discovery_plan = generate_discovery_queries({
        **expansion_context,
        "product_variant": variant or None,
        "local_language_terms": list(seed.get("local_language_terms") or []),
        "locale": seed.get("locale"),
        "limit": seed.get("query_limit", 100),
    })
    return {
        "demand_anchor": anchor,
        "market_cell": market_cell,
        "market_acceptance": market_acceptance,
        "market_scope": market_scope,
        "expansion_plan": expansion_plan,
        "discovery_plan": discovery_plan,
        "product_mapping_requires_research": mapping_requires_research,
        "persistence_performed": False,
    }


def qualify_candidate_opportunity(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("candidate qualification must be an object")
    candidate = build_candidate_discovery(dict(payload.get("candidate") or {}))
    raw_resolution = payload.get("canonical_resolution")
    if not isinstance(raw_resolution, dict):
        raise ValueError("production canonical_resolution proof is required")
    canonical_resolution = validate_canonical_resolution_proof(raw_resolution)
    if not canonical_resolution["opportunity_creation_allowed"]:
        raise ValueError("canonical resolution blocked: " + ",".join(canonical_resolution["blockers"]))
    account_id = str(canonical_resolution["canonical_account_id"] or "").strip()
    requested_account_id = str(payload.get("candidate_account_id") or "").strip()
    if requested_account_id and requested_account_id != account_id:
        raise ValueError("candidate_account_id conflicts with canonical resolution")
    profile_id = candidate["product_profile_id"]
    opportunity_id = build_opportunity_id(account_id, profile_id)
    opportunity = validate_product_opportunity({
        "opportunity_id": opportunity_id,
        "account_id": account_id,
        "product_profile_id": profile_id,
        "product_variant": payload.get("product_variant"),
        "commercial_value_grade": payload.get("commercial_value_grade"),
        "commercial_score": payload.get("commercial_score"),
        "product_evidence_ids": [],
        "procurement_evidence_ids": [],
        "lifecycle_stage": "QUALIFIED_TARGET",
    })
    relative = relative_opportunity(
        float(payload.get("anchor_score") or 0.0),
        float(payload.get("commercial_score") or 0.0),
        str(payload.get("anchor_grade") or ""),
        str(payload.get("commercial_value_grade") or ""),
        strategic=bool(payload.get("strategic", False)),
    )
    contact_plan = plan_contact_exhaustion({
        **opportunity,
        "outreach_readiness": payload.get("outreach_readiness", "IDENTITY_ONLY"),
    }, {})
    contact_source_plan = plan_contact_source_tasks(
        opportunity_id,
        candidate["company_name"],
        contact_plan,
        named_route_material=bool(payload.get("named_route_material", False)),
    )
    anchor_eligibility = evaluate_anchor_eligibility({
        "commercial_value_grade": payload.get("commercial_value_grade"),
        "canonical_status": canonical_resolution["canonical_status"],
        "commercial_evidence_bound": payload.get("commercial_evidence_bound"),
        "novelty_signals": list(payload.get("novelty_signals") or []),
        "outreach_readiness": payload.get("outreach_readiness"),
    })
    return {
        "candidate": candidate,
        "opportunity": opportunity,
        "relative": relative,
        "contact_plan": contact_plan,
        "contact_source_plan": contact_source_plan,
        "anchor_eligibility": anchor_eligibility,
        "canonical_resolution": canonical_resolution,
        "anchor_procurement_evidence_inherited": False,
        "persistence_performed": False,
    }
