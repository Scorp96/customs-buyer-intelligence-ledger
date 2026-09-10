from __future__ import annotations

from typing import Any

from .expansion_planner import generate_discovery_queries, plan_expansion
from .product_profiles import get_product_profile


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _normalized_set(values: Any) -> set[str]:
    return {str(value).strip() for value in (values or []) if str(value).strip()}


def prepare_recursive_expansion(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("recursive expansion payload must be an object")
    anchor = dict(payload.get("promoted_anchor") or {})
    market_cell = dict(payload.get("market_cell") or {})

    opportunity_id = _required_str(anchor, "opportunity_id")
    account_id = _required_str(anchor, "account_id")
    profile_id = _required_str(anchor, "product_profile_id").upper()
    if str(anchor.get("stage") or "").strip().upper() != "PROMOTED_ANCHOR":
        raise ValueError("recursive expansion requires a PROMOTED_ANCHOR")
    get_product_profile(profile_id)

    market_cell_id = _required_str(market_cell, "market_cell_id")
    geography = _required_str(market_cell, "geography")
    cell_profile = _required_str(market_cell, "product_profile_id").upper()
    if cell_profile != profile_id:
        raise ValueError("market cell product profile must match promoted anchor")

    expansion_key = f"{account_id}|{profile_id}|{market_cell_id}"
    visited_anchor_ids = _normalized_set(payload.get("visited_anchor_ids"))
    visited_expansion_keys = _normalized_set(payload.get("visited_expansion_keys"))

    common = {
        "anchor_opportunity_id": opportunity_id,
        "account_id": account_id,
        "product_profile_id": profile_id,
        "market_cell_id": market_cell_id,
        "expansion_key": expansion_key,
        "planning_is_execution_proof": False,
        "persistent_mutation_performed": False,
        "candidate_inheritance_policy": {
            "account_identity": "CANONICAL_RESOLUTION_REQUIRED",
            "procurement_evidence": "FORBIDDEN",
            "product_evidence": "FORBIDDEN",
            "commercial_grade": "FORBIDDEN",
            "contact_readiness": "FORBIDDEN",
        },
    }

    if opportunity_id in visited_anchor_ids:
        return {
            **common,
            "status": "SKIPPED_CYCLE_DUPLICATE",
            "reason": "ANCHOR_ALREADY_EXPANDED_IN_CYCLE",
            "expansion_plan": None,
            "discovery_plan": None,
        }
    if expansion_key in visited_expansion_keys:
        return {
            **common,
            "status": "SKIPPED_CYCLE_DUPLICATE",
            "reason": "EXPANSION_KEY_ALREADY_VISITED",
            "expansion_plan": None,
            "discovery_plan": None,
        }

    applications = list(market_cell.get("application_ids") or [])
    buyer_archetypes = list(market_cell.get("buyer_archetype_ids") or [])
    market_acceptance = str(
        market_cell.get("market_acceptance")
        or payload.get("market_acceptance")
        or "M0"
    ).upper()
    anchor_grade = str(anchor.get("commercial_value_grade") or "")
    anchor_score = float(anchor.get("commercial_value_score") or 0.0)

    context = {
        "product_profile_id": profile_id,
        "market_acceptance": market_acceptance,
        "anchor_grade": anchor_grade,
        "anchor_score": anchor_score,
        "applications": applications,
        "buyer_archetypes": buyer_archetypes,
        "geography": geography,
        "product_variant": anchor.get("product_variant") or market_cell.get("product_variant"),
        "local_language_terms": list(payload.get("local_language_terms") or []),
        "limit": int(payload.get("query_limit") or 100),
    }
    expansion_plan = plan_expansion(context)
    discovery_plan = generate_discovery_queries(context)
    return {
        **common,
        "status": "PLANNED",
        "reason": None,
        "expansion_plan": expansion_plan,
        "discovery_plan": discovery_plan,
        "next_cycle_state": {
            "visited_anchor_ids": sorted(visited_anchor_ids | {opportunity_id}),
            "visited_expansion_keys": sorted(visited_expansion_keys | {expansion_key}),
        },
    }
