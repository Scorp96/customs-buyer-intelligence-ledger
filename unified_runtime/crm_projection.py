from __future__ import annotations

import copy
from typing import Any, Iterable

from .product_profiles import get_product_profile


_OPPORTUNITY_SUMMARY_FIELDS = (
    "opportunity_id",
    "product_variant",
    "applications",
    "relative_class",
    "market_cell_ids",
    "company_route_status",
    "named_route_status",
    "anchor_status",
)


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _opportunity_account_from_id(opportunity_id: str) -> str | None:
    # IDs are generated as OPP-<ACCOUNT>-<PROFILE>-<DISCRIMINATOR>.
    parts = opportunity_id.split("-")
    if len(parts) >= 4 and parts[0] == "OPP":
        return parts[1]
    return None


def _project_opportunity(account_id: str, opportunity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(opportunity, dict):
        raise ValueError("product opportunity must be an object")
    opportunity_id = _required_text(opportunity.get("opportunity_id"), "opportunity_id")
    explicit_account = str(opportunity.get("account_id") or "").strip()
    inferred_account = _opportunity_account_from_id(opportunity_id)
    owner = explicit_account or inferred_account
    if owner and owner != account_id:
        raise ValueError("product opportunity belongs to a different canonical account")

    profile_id = _required_text(opportunity.get("product_profile_id"), "product_profile_id").upper()
    try:
        get_product_profile(profile_id)
    except KeyError as exc:
        raise ValueError(f"unknown product profile: {profile_id}") from exc

    result = {
        "opportunity_id": opportunity_id,
        "product_family": profile_id,
        "product_variant": opportunity.get("product_variant"),
        "application": list(opportunity.get("applications") or []),
        "grade": opportunity.get("commercial_value_grade"),
        "relative_class": opportunity.get("relative_class"),
        "market_cell": list(opportunity.get("market_cell_ids") or []),
        "company_route_status": opportunity.get("company_route_status"),
        "named_route_status": opportunity.get("named_route_status"),
        "anchor_status": opportunity.get("anchor_status"),
    }
    return result


def project_account_opportunities(
    account: dict[str, Any],
    opportunities: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(account, dict):
        raise ValueError("account must be an object")
    account_id = _required_text(account.get("account_id"), "account_id")

    unique: dict[str, dict[str, Any]] = {}
    for opportunity in opportunities:
        projected = _project_opportunity(account_id, opportunity)
        unique.setdefault(projected["opportunity_id"], projected)

    return {
        "account_row_count": 1,
        "account": copy.deepcopy(account),
        "product_opportunities": list(unique.values()),
        "projection_policy": "ONE_CANONICAL_ACCOUNT_MANY_PRODUCT_OPPORTUNITIES",
    }
