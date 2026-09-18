from __future__ import annotations

from typing import Any

from .product_profiles import get_product_profile


COMPANY_ROUTE_SOURCE_FAMILIES = (
    "official_home",
    "official_contact",
    "official_about_footer_mobile",
    "official_documents_media",
    "google_maps_business",
    "local_maps",
    "official_social",
    "local_directory",
    "association_exhibition_chamber",
)

NAMED_ROUTE_SOURCE_FAMILIES = (
    "official_team",
    "linkedin_people",
    "government_registry",
    "official_news_jobs",
    "association_exhibition_chamber",
    "public_professional_profiles",
    "supplier_peer_partner_referral",
    "reverse_phone_email",
)

_GENERAL_DECISION_ROLE_TOKENS = (
    "owner",
    "president",
    "ceo",
    "managing director",
    "general manager",
    "purchasing",
    "procurement",
    "sourcing",
    "supply chain",
    "import manager",
    "operations",
    "category manager",
)

_PRODUCT_ROLE_TOKENS = {
    "PVC": ("pvc", "foam board", "sheet", "panel", "sign", "cabinet", "partition"),
    "WPC": ("wpc", "decking", "cladding", "fencing", "composite"),
    "SPC": ("spc", "flooring", "rigid core"),
    "ACRYLIC_PMMA": ("acrylic", "pmma", "plexiglass"),
}


def _grade_policy(grade: str) -> dict[str, Any]:
    if grade == "A+":
        return {
            "deep_contact_research": True,
            "company_route_required": True,
            "named_route_policy": "EXHAUSTIVE",
            "named_route_exhaustive": True,
        }
    if grade in {"A", "A-"}:
        return {
            "deep_contact_research": True,
            "company_route_required": True,
            "named_route_policy": "HIGH_PRIORITY",
            "named_route_exhaustive": False,
        }
    if grade == "B+":
        return {
            "deep_contact_research": True,
            "company_route_required": True,
            "named_route_policy": "EIV_DRIVEN",
            "named_route_exhaustive": False,
        }
    if grade in {"B", "B-"}:
        return {
            "deep_contact_research": False,
            "company_route_required": False,
            "named_route_policy": "STRATEGIC_ONLY",
            "named_route_exhaustive": False,
        }
    return {
        "deep_contact_research": False,
        "company_route_required": False,
        "named_route_policy": "NONE",
        "named_route_exhaustive": False,
    }


def plan_contact_exhaustion(opportunity: dict[str, Any], current_routes: dict[str, Any]) -> dict[str, Any]:
    grade = str(opportunity.get("commercial_value_grade") or "NQ")
    profile_id = str(opportunity.get("product_profile_id") or "").upper()
    get_product_profile(profile_id)
    policy = _grade_policy(grade)
    company_ready = str(opportunity.get("outreach_readiness") or current_routes.get("outreach_readiness") or "") in {
        "COMPANY_ROUTE_READY",
        "NAMED_ROUTE_READY",
        "FOLLOW_UP_READY",
        "SEND_READY",
    }
    named_ready = str(opportunity.get("outreach_readiness") or current_routes.get("outreach_readiness") or "") in {
        "NAMED_ROUTE_READY",
        "FOLLOW_UP_READY",
        "SEND_READY",
    }
    return {
        "product_profile_id": profile_id,
        "commercial_value_grade": grade,
        **policy,
        "company_route_ready": company_ready,
        "named_route_ready": named_ready,
        "company_route_source_families": [] if company_ready else list(COMPANY_ROUTE_SOURCE_FAMILIES),
        "named_route_source_families": [] if named_ready or policy["named_route_policy"] == "NONE" else list(NAMED_ROUTE_SOURCE_FAMILIES),
        "commercial_grade_mutated": False,
    }


def named_role_relevant(product_profile_id: str, buyer_archetypes: list[str], role: str) -> bool:
    profile_id = str(product_profile_id or "").upper()
    get_product_profile(profile_id)
    role_text = str(role or "").strip().casefold()
    if not role_text:
        return False

    # Explicit product-specific roles for another product family fail closed.
    for other_profile, tokens in _PRODUCT_ROLE_TOKENS.items():
        if other_profile == profile_id:
            continue
        if any(token in role_text for token in tokens):
            own_tokens = _PRODUCT_ROLE_TOKENS.get(profile_id, ())
            if not any(token in role_text for token in own_tokens):
                return False

    if any(token in role_text for token in _GENERAL_DECISION_ROLE_TOKENS):
        return True

    own_tokens = _PRODUCT_ROLE_TOKENS.get(profile_id, ())
    return any(token in role_text for token in own_tokens) and any(
        authority in role_text for authority in ("manager", "director", "head", "buyer")
    )


def contact_exhaustion_complete(plan_state: dict[str, Any]) -> bool:
    if str(plan_state.get("named_route_status") or "") in {"NAMED_ROUTE_READY", "FOLLOW_UP_READY", "SEND_READY"}:
        return True
    if str(plan_state.get("company_route_status") or "") in {"COMPANY_ROUTE_READY", "FOLLOW_UP_READY", "SEND_READY"}:
        return True

    receipts = list(plan_state.get("applicable_material_source_receipts") or [])
    if not receipts:
        return False
    terminal = {"NEGATIVE_EXHAUSTED", "NOT_APPLICABLE_JUSTIFIED"}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            return False
        result = str(receipt.get("result") or "").upper()
        if result not in terminal:
            return False
    return True

_CURRENT_ROUTE_FRESHNESS = {
    "LIVE",
    "CURRENT",
    "CURRENT_CONFIRMED",
    "CURRENT_LIKELY",
    "RECENT",
}


def _route_is_current(route: dict[str, Any]) -> bool:
    return str(route.get("freshness") or "UNKNOWN").strip().upper() in _CURRENT_ROUTE_FRESHNESS


def recompute_outreach_readiness(route_state: dict[str, Any]) -> dict[str, Any]:
    """Recompute current route readiness without mutating commercial value.

    Lifecycle stage and commercial grade are deliberately outside this function.
    A stale route can reduce current outreach readiness while historical route
    evidence and lifecycle history remain append-only.
    """
    company_routes = list(route_state.get("company_routes") or [])
    named_routes = list(route_state.get("named_routes") or [])

    company_ready = any(
        isinstance(route, dict)
        and bool(route.get("verified"))
        and bool(route.get("route_eligible"))
        and str(route.get("owner_scope") or "").strip().upper() in {"ACCOUNT", "COMPANY", "BUYER"}
        and not bool(route.get("guessed"))
        and _route_is_current(route)
        for route in company_routes
    )

    named_ready = any(
        isinstance(route, dict)
        and bool(route.get("verified"))
        and bool(route.get("route_eligible"))
        and not bool(route.get("guessed"))
        and bool(route.get("current_company_association"))
        and bool(route.get("role_relevant"))
        and _route_is_current(route)
        for route in named_routes
    )

    if named_ready:
        readiness = "NAMED_ROUTE_READY"
    elif company_ready:
        readiness = "COMPANY_ROUTE_READY"
    else:
        readiness = "IDENTITY_ONLY"

    return {
        "outreach_readiness": readiness,
        "company_route_ready": company_ready,
        "named_route_ready": named_ready,
        "readiness_can_regress_when_routes_stale": True,
        "lifecycle_stage_mutated": False,
        "commercial_grade_mutated": False,
    }
