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

    if route.get("verified") is not True:
        blockers.append("ROUTE_NOT_VERIFIED")
    if route.get("route_eligible") is not True:
        blockers.append("ROUTE_NOT_ELIGIBLE")
    if bool(route.get("guessed")):
        blockers.append("GUESSED_ROUTE_FORBIDDEN")
    if str(route.get("freshness") or "UNKNOWN").strip().upper() not in _CURRENT_FRESHNESS:
        blockers.append("ROUTE_NOT_CURRENT")

    # A route is never transferable across canonical Accounts merely because
    # it is verified or has an account-like route_id.  Only explicit account
    # owner bindings may authorize opportunity-level route reuse.
    target_account_id = str(opportunity.get("account_id") or "").strip()
    owner_scope = str(route.get("owner_scope") or "").strip().upper()
    claimed_account_id = str(route.get("account_id") or "").strip()
    owner_account_id = str(route.get("owner_account_id") or "").strip()
    # v6.4 Canonical Route View carries owner_entity_id/owned_by_account and
    # route_scope=BUYER_DIRECT, not the opportunity helper's account_id fields.
    # Accept it as an explicit account owner assertion ONLY when the scope is
    # account/company, the account-ownership flag is true and the route is
    # Buyer Direct. For PERSON, owner_entity_id might identify the person, so
    # person routes still require an explicit company account binding.
    canonical_owner_id = ""
    if (
        owner_scope in _COMPANY_SCOPES
        and str(route.get("route_scope") or "").strip().upper() == "BUYER_DIRECT"
        and route.get("owned_by_account") is True
    ):
        canonical_owner_id = str(route.get("owner_entity_id") or "").strip()

    if not target_account_id:
        blockers.append("OPPORTUNITY_ACCOUNT_ID_MISSING")
    # A malformed or forged string flag is never a proof of account ownership.
    # Legacy routes may omit the field but may not supply a non-boolean assertion.
    if ("owned_by_account" in route and type(route["owned_by_account"]) is not bool) or route.get("owned_by_account") is False:
        blockers.append("ROUTE_ACCOUNT_OWNERSHIP_UNVERIFIED")
    bindings = [value for value in (claimed_account_id, owner_account_id, canonical_owner_id) if value]
    if len(set(bindings)) > 1:
        blockers.append("ROUTE_ACCOUNT_BINDING_CONFLICT")
    bound_account_id = bindings[0] if bindings else ""
    if not bound_account_id:
        blockers.append("ROUTE_ACCOUNT_BINDING_MISSING")
    elif target_account_id and bound_account_id != target_account_id:
        blockers.append("ROUTE_ACCOUNT_OWNER_MISMATCH")

    reuse_scope = None
    if owner_scope in _COMPANY_SCOPES:
        reuse_scope = "ACCOUNT_LEVEL_COMPANY_ROUTE"
    elif owner_scope == "PERSON":
        if route.get("current_company_association") is not True:
            blockers.append("NAMED_ROUTE_COMPANY_ASSOCIATION_UNPROVEN")
        if route.get("role_relevant") is not True:
            blockers.append("NAMED_ROUTE_ROLE_RELEVANCE_UNPROVEN")
        # MCP public input must be a JSON array of strings. Never accept a
        # dictionary's keys as independent product/role evidence, and never
        # crash on explicit null or numeric content.
        raw_relevance = route.get("product_relevance", [])
        if not isinstance(raw_relevance, list) or not all(isinstance(value, str) for value in raw_relevance):
            blockers.append("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED")
            relevance: set[str] = set()
        else:
            relevance = {value.strip().upper() for value in raw_relevance if value.strip()}
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
