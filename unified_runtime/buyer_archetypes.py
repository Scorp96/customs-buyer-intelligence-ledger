from __future__ import annotations

import copy
from typing import Any

from .product_profiles import get_product_profile, list_product_profiles


_ROLE_POLICY: dict[str, dict[str, Any]] = {
    "IMPORTER": {
        "business_role": "CHANNEL",
        "demand_mode": "STOCK_AND_IMPORT",
        "discovery_priority": 1.30,
        "volume_potential": "HIGH",
    },
    "DISTRIBUTOR": {
        "business_role": "CHANNEL",
        "demand_mode": "STOCK_AND_RESELL",
        "discovery_priority": 1.25,
        "volume_potential": "HIGH",
    },
    "SUPPLIER": {
        "business_role": "CHANNEL",
        "demand_mode": "STOCK_AND_RESELL",
        "discovery_priority": 1.20,
        "volume_potential": "HIGH_VARIABLE",
    },
    "MANUFACTURER": {
        "business_role": "MANUFACTURER",
        "demand_mode": "PRODUCTION_CONSUMPTION",
        "discovery_priority": 1.15,
        "volume_potential": "MEDIUM_HIGH",
    },
    "FABRICATOR": {
        "business_role": "FABRICATOR",
        "demand_mode": "PRODUCTION_CONSUMPTION",
        "discovery_priority": 1.10,
        "volume_potential": "MEDIUM",
    },
    "MAKER": {
        "business_role": "FABRICATOR",
        "demand_mode": "PRODUCTION_CONSUMPTION",
        "discovery_priority": 1.10,
        "volume_potential": "MEDIUM",
    },
    "CONTRACTOR": {
        "business_role": "CONTRACTOR",
        "demand_mode": "PROJECT_PROCUREMENT",
        "discovery_priority": 0.95,
        "volume_potential": "PROJECT_VARIABLE",
    },
    "FITOUT": {
        "business_role": "CONTRACTOR",
        "demand_mode": "PROJECT_PROCUREMENT",
        "discovery_priority": 0.95,
        "volume_potential": "PROJECT_VARIABLE",
    },
    "PRINTING": {
        "business_role": "PROCESSOR",
        "demand_mode": "PROCESSING_SERVICE",
        "discovery_priority": 0.90,
        "volume_potential": "VARIABLE",
    },
}


def _policy_key(archetype_id: str) -> str | None:
    value = archetype_id.upper()
    if "IMPORTER" in value:
        return "IMPORTER"
    if "DISTRIBUTOR" in value:
        return "DISTRIBUTOR"
    if "SUPPLIER" in value:
        return "SUPPLIER"
    if "MANUFACTURER" in value:
        return "MANUFACTURER"
    if "FABRICATOR" in value:
        return "FABRICATOR"
    if value.endswith("_MAKER") or value == "SIGN_MAKER":
        return "MAKER"
    if "CONTRACTOR" in value:
        return "CONTRACTOR"
    if "FITOUT" in value:
        return "FITOUT"
    if "PRINTING" in value:
        return "PRINTING"
    return None


def _known_archetypes() -> set[str]:
    return {
        str(archetype).upper()
        for profile in list_product_profiles()
        for archetype in profile.get("buyer_archetypes", [])
    }


def get_buyer_archetype(archetype_id: str) -> dict[str, Any]:
    normalized = str(archetype_id or "").strip().upper()
    if normalized not in _known_archetypes():
        raise ValueError(f"unknown buyer archetype: {archetype_id}")
    key = _policy_key(normalized)
    if key is None:
        raise ValueError(f"unclassified buyer archetype: {archetype_id}")
    result = copy.deepcopy(_ROLE_POLICY[key])
    result.update({
        "archetype_id": normalized,
        "priority_is_discovery_only": True,
        "archetype_match_proves_product_fit": False,
        "archetype_match_proves_procurement": False,
        "requires_independent_company_verification": True,
        "requires_independent_product_or_application_evidence": True,
    })
    return result


def rank_buyer_archetypes(product_profile_id: str, archetype_ids: list[str]) -> list[dict[str, Any]]:
    profile_id = str(product_profile_id or "").strip().upper()
    profile = get_product_profile(profile_id)
    allowed = {str(value).upper() for value in profile.get("buyer_archetypes", [])}
    rows: list[dict[str, Any]] = []
    for archetype_id in archetype_ids:
        normalized = str(archetype_id or "").strip().upper()
        if normalized not in allowed:
            raise ValueError(f"buyer archetype {normalized} is not declared for product profile {profile_id}")
        row = get_buyer_archetype(normalized)
        row["product_profile_id"] = profile_id
        rows.append(row)
    rows.sort(key=lambda row: (float(row["discovery_priority"]), row["archetype_id"]), reverse=True)
    return rows
