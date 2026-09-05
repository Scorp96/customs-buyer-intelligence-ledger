from __future__ import annotations

from typing import Any

from .product_profiles import get_product_profile, portfolio_priority
from .buyer_archetypes import rank_buyer_archetypes
from .search_localization import get_localized_search_terms


BRANCH_GROUPS: dict[str, tuple[str, ...]] = {
    "TRADE_GRAPH": (
        "same_supplier_buyer",
        "same_product_buyer",
        "same_hs_application_buyer",
        "competing_supplier_buyer",
        "importer_network",
        "historical_supplier_network",
        "trade_cluster",
    ),
    "APPLICATION_GRAPH": (
        "direct_application_user",
        "downstream_manufacturer",
        "fabricator",
        "OEM_ODM_user",
        "project_user",
        "specialty_processor",
    ),
    "CHANNEL_GRAPH": (
        "importer",
        "distributor",
        "wholesaler",
        "stockist",
        "dealer",
        "building_material_supplier",
        "sign_material_supplier",
        "specialty_sheet_distributor",
    ),
    "MARKET_GRAPH": (
        "regional_peer",
        "industry_peer",
        "scale_peer",
        "adjacent_city",
        "industrial_cluster",
        "market_cluster",
    ),
    "COMPETITIVE_GRAPH": (
        "competing_supplier_buyer",
        "competitor_customer",
        "substitute_material_user",
        "second_source_candidate",
        "supplier_switching_candidate",
    ),
    "CROSS_SELL_GRAPH": (
        "same_company_other_product",
        "application_overlap",
        "portfolio_expansion",
        "channel_overlap",
    ),
}

_RELATIVE_MODIFIER = {
    "UPGRADE_TARGET": 1.30,
    "SAME_TIER_HIGH": 1.15,
    "SAME_TIER": 1.00,
    "STRATEGIC_LOWER": 0.90,
    "SECONDARY": 0.65,
    "REJECT": 0.00,
}

_MARKET_MODIFIER = {
    "M0": 0.70,
    "M1": 0.85,
    "M2": 1.00,
    "M3": 1.10,
    "M4": 1.20,
    "M5": 1.25,
}


def _market_branches(level: str) -> tuple[str, ...]:
    if level in {"M0", "M1"}:
        return ("regional_peer", "industry_peer", "scale_peer", "adjacent_city")
    if level == "M2":
        return ("regional_peer", "industry_peer", "scale_peer", "adjacent_city", "market_cluster")
    return BRANCH_GROUPS["MARKET_GRAPH"]


def _cross_sell_branches(level: str) -> tuple[str, ...]:
    if level in {"M0", "M1"}:
        return ("same_company_other_product", "application_overlap")
    return BRANCH_GROUPS["CROSS_SELL_GRAPH"]


def plan_expansion(context: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(context.get("product_profile_id") or "").upper()
    level = str(context.get("market_acceptance") or "M0").upper()
    if level not in _MARKET_MODIFIER:
        raise ValueError(f"invalid market acceptance level: {level}")
    # Validate the profile and obtain scheduling priority without changing evidence/grade.
    profile_weight = portfolio_priority(profile_id)
    branches = {name: list(values) for name, values in BRANCH_GROUPS.items()}
    branches["MARKET_GRAPH"] = list(_market_branches(level))
    branches["CROSS_SELL_GRAPH"] = list(_cross_sell_branches(level))
    return {
        "product_profile_id": profile_id,
        "market_acceptance": level,
        "portfolio_scheduler_weight": profile_weight,
        "branch_groups": list(BRANCH_GROUPS),
        "branches": branches,
        "policy": {
            "qualification_strategy": "RELATIVE_TO_ANCHOR",
            "fixed_depth_or_count_closes_expansion": False,
            "minimum_target_fit": None,
            "planning_is_execution_proof": False,
        },
        "anchor_grade": context.get("anchor_grade"),
        "anchor_score": context.get("anchor_score"),
        "applications": list(context.get("applications") or []),
        "buyer_archetypes": list(context.get("buyer_archetypes") or []),
        "geography": context.get("geography"),
    }


def compute_expansion_priority(candidate: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(candidate.get("product_profile_id") or "").upper()
    eiv = max(0.0, float(candidate.get("eiv") or 0.0))
    commercial_score = float(candidate.get("commercial_score") or 0.0)
    relative_class = str(candidate.get("relative_class") or "SECONDARY").upper()
    relative_modifier = _RELATIVE_MODIFIER.get(relative_class, 0.0)
    market_level = str(candidate.get("market_acceptance") or "M2").upper()
    market_modifier = _MARKET_MODIFIER.get(market_level, 0.7)
    scheduler_weight = portfolio_priority(profile_id)
    priority = eiv * relative_modifier * market_modifier * scheduler_weight
    return {
        **candidate,
        "product_profile_id": profile_id,
        "commercial_score": commercial_score,
        "portfolio_scheduler_weight": scheduler_weight,
        "relative_modifier": relative_modifier,
        "market_modifier": market_modifier,
        "priority": round(priority, 6),
    }


def evaluate_expansion_saturation(state: dict[str, Any]) -> dict[str, Any]:
    remaining = [
        row
        for row in state.get("remaining_material_work", [])
        if isinstance(row, dict) and float(row.get("eiv") or 0.0) > 0.0
    ]
    candidates = list(state.get("undispositioned_high_value_candidates") or [])
    unresolved_research_candidates = [
        row
        for row in (state.get("unresolved_research_candidates") or [])
        if isinstance(row, dict)
        and str(row.get("research_state") or "").upper() == "RESEARCH_ACTIVE"
        and float(row.get("eiv") or 0.0) > 0.0
    ]
    anchors = list(state.get("unexpanded_promoted_anchors") or [])
    pivots = list(state.get("open_high_yield_pivots") or [])
    dedup_complete = bool(state.get("cycle_dedup_complete"))
    blockers: list[str] = []
    if remaining:
        blockers.append("MATERIAL_EXPANSION_WORK_REMAINS")
    if candidates:
        blockers.append("UNDISPOSITIONED_HIGH_VALUE_CANDIDATES")
    if unresolved_research_candidates:
        blockers.append("UNRESOLVED_RESEARCH_CANDIDATES")
    if anchors:
        blockers.append("UNEXPANDED_PROMOTED_ANCHORS")
    if pivots:
        blockers.append("OPEN_HIGH_YIELD_PIVOTS")
    if not dedup_complete:
        blockers.append("CYCLE_DEDUP_INCOMPLETE")
    saturated = not blockers
    return {
        "expansion_saturated": saturated,
        "expansion_state": "EXPANSION_SATURATED" if saturated else "EXPANSION_ACTIVE",
        "blockers": blockers,
        "remaining_material_work_count": len(remaining),
        "unresolved_research_candidate_count": len(unresolved_research_candidates),
        "decision_saturation_overridden": False,
    }


def _readable_token(value: str) -> str:
    return str(value or "").replace("_", " ").strip()


def generate_discovery_queries(context: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(context.get("product_profile_id") or "").upper()
    profile = get_product_profile(profile_id)
    geography = str(context.get("geography") or "").strip()
    if not geography:
        raise ValueError("geography is required for discovery query generation")
    applications = [str(v).upper() for v in context.get("applications", []) if str(v).strip()]
    archetypes = [str(v).upper() for v in context.get("buyer_archetypes", []) if str(v).strip()]
    variant = str(context.get("product_variant") or "").upper()
    local_terms = [str(v).strip() for v in context.get("local_language_terms", []) if str(v).strip()]
    locale = str(context.get("locale") or "").strip()
    locale_pack_status = "NOT_REQUESTED"
    locale_pack_version = None
    limit = int(context.get("limit") or 100)
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, 1000)

    if variant:
        mapping = (profile.get("variant_application_map") or {}).get(variant)
        if mapping:
            if not applications:
                applications = list(mapping.get("applications") or [])
            if not archetypes:
                archetypes = list(mapping.get("buyer_archetypes") or [])

    archetype_priority_applied = False
    if archetypes:
        ranked_archetypes = rank_buyer_archetypes(profile_id, archetypes)
        archetypes = [row["archetype_id"] for row in ranked_archetypes]
        archetype_priority_applied = True

    if locale:
        localized = get_localized_search_terms(
            locale=locale,
            product_profile_id=profile_id,
            applications=applications,
            buyer_archetypes=archetypes,
        )
        locale_pack_status = localized["status"]
        locale_pack_version = localized.get("vocabulary_version")
        existing_local = {existing.casefold() for existing in local_terms}
        for term in localized.get("terms", []):
            if term.casefold() not in existing_local:
                local_terms.append(term)
                existing_local.add(term.casefold())

    product_terms: list[str] = []
    if variant:
        product_terms.append(f"{profile_id} {_readable_token(variant)}")
    product_terms.append(profile_id)
    product_terms.extend(str(v) for v in profile.get("commercial_aliases", [])[:5])

    commercial_terms = list(profile.get("positive_search_vocabulary", [])[:8])
    commercial_terms.extend(local_terms)
    if not commercial_terms:
        commercial_terms = [_readable_token(v) for v in archetypes] or [_readable_token(v) for v in applications]

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(query: str, basis: str) -> None:
        normalized = " ".join(query.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            return
        seen.add(key)
        rows.append({
            "query": normalized,
            "basis": basis,
            "product_profile_id": profile_id,
            "product_variant": variant or None,
            "geography": geography,
            "execution_required": True,
            "receipt_required": True,
            "search_execution_performed": False,
        })

    for product in product_terms:
        for archetype in archetypes or [""]:
            for application in applications or [""]:
                add(
                    f'{product} {_readable_token(archetype)} {_readable_token(application)} {geography}',
                    "PRODUCT_X_ARCHETYPE_X_APPLICATION_X_GEOGRAPHY",
                )
        for term in commercial_terms:
            add(f'{product} "{term}" {geography}', "PRODUCT_X_COMMERCIAL_TERM_X_GEOGRAPHY")

    for term in local_terms:
        add(f'{profile_id} "{term}" {geography}', "PRODUCT_X_LOCAL_TERM_X_GEOGRAPHY")
        add(f'"{term}" {geography}', "LOCAL_TERM_X_GEOGRAPHY")

    candidate_count = len(rows)
    returned = rows[:limit]
    return {
        "status": "PLANNED",
        "product_profile_id": profile_id,
        "query_candidate_count": candidate_count,
        "returned_count": len(returned),
        "truncated": candidate_count > len(returned),
        "queries": returned,
        "planning_is_execution_proof": False,
        "source_coverage_complete": False,
        "source_coverage_status": "UNPROVEN_UNTIL_REAL_RECEIPTS",
        "host_execution_required": True,
        "locale": locale or None,
        "locale_pack_status": locale_pack_status,
        "locale_pack_version": locale_pack_version,
        "localized_terms_are_planning_only": True,
        "archetype_priority_applied": archetype_priority_applied,
        "ordered_buyer_archetypes": list(archetypes),
    }
