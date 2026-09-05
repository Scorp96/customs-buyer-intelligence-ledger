from __future__ import annotations

from typing import Any

from .product_profiles import get_product_profile


_CURRENT_FRESHNESS = {"LIVE", "CURRENT", "CURRENT_CONFIRMED", "CURRENT_LIKELY", "RECENT"}
_COMPANY_SCOPES = {"ACCOUNT", "COMPANY", "BUYER"}


def reuse_route_for_opportunity(route: dict[str, Any], opportunity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(route, dict) or not isinstance(opportunity, dict):
        raise ValueError("route and opportunity must be objects")
    profile_id = str(opportunity.get("product_profile_id") or "").strip().upper()
    get_product_profile(profile_id)
    blockers: list[str] = []

    if not bool(route.get("verified")):
        blockers.append("ROUTE_NOT_VERIFIED")
    if not bool(route.get("route_eligible")):
        blockers.append("ROUTE_NOT_ELIGIBLE")
    if bool(route.get("guessed")):
        blockers.append("GUESSED_ROUTE_FORBIDDEN")
    if str(route.get("freshness") or "UNKNOWN").strip().upper() not in _CURRENT_FRESHNESS:
        blockers.append("ROUTE_NOT_CURRENT")

    owner_scope = str(route.get("owner_scope") or "").strip().upper()
    reuse_scope = None
    if owner_scope in _COMPANY_SCOPES:
        reuse_scope = "ACCOUNT_LEVEL_COMPANY_ROUTE"
    elif owner_scope == "PERSON":
        if not bool(route.get("current_company_association")):
            blockers.append("NAMED_ROUTE_COMPANY_ASSOCIATION_UNPROVEN")
        if not bool(route.get("role_relevant")):
            blockers.append("NAMED_ROUTE_ROLE_RELEVANCE_UNPROVEN")
        relevance = {str(value).strip().upper() for value in route.get("product_relevance", []) if str(value).strip()}
        if profile_id in relevance:
            reuse_scope = "NAMED_ROUTE_PRODUCT_SPECIFIC"
        elif "GENERAL_PROCUREMENT" in relevance:
            reuse_scope = "NAMED_ROUTE_GENERAL_PROCUREMENT"
        else:
            blockers.append("NAMED_ROUTE_PRODUCT_RELEVANCE_UNPROVEN")
    else:
        blockers.append("ROUTE_OWNER_SCOPE_NOT_REUSABLE")

    reusable = not blockers
    return {
        "route_id": route.get("route_id"),
        "account_id": opportunity.get("account_id"),
        "product_profile_id": profile_id,
        "route_reusable": reusable,
        "reuse_scope": reuse_scope if reusable else None,
        "route_proves_product_interest": False,
        "route_proves_procurement": False,
        "commercial_grade_mutated": False,
        "blockers": blockers,
    }
