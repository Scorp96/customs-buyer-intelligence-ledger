from __future__ import annotations

from typing import Any


_SCOPE_POLICY = {
    "M0": {
        "scope": "ANCHOR_VALIDATION_ONLY",
        "country_discovery_allowed": False,
        "competitor_network_priority": False,
    },
    "M1": {
        "scope": "CITY_AND_NEARBY",
        "country_discovery_allowed": False,
        "competitor_network_priority": False,
    },
    "M2": {
        "scope": "METRO_AND_REGION",
        "country_discovery_allowed": False,
        "competitor_network_priority": False,
    },
    "M3": {
        "scope": "REGION_AND_COUNTRY_DISCOVERY",
        "country_discovery_allowed": True,
        "competitor_network_priority": True,
    },
    "M4": {
        "scope": "COUNTRY_WIDE_PRIORITY_CLUSTERS",
        "country_discovery_allowed": True,
        "competitor_network_priority": True,
    },
    "M5": {
        "scope": "COUNTRY_WIDE_DENSE_COMPETITIVE_NETWORK",
        "country_discovery_allowed": True,
        "competitor_network_priority": True,
    },
}


def derive_market_expansion_scope(level: str, *, geography: str) -> dict[str, Any]:
    market_level = str(level or "").strip().upper()
    location = str(geography or "").strip()
    if market_level not in _SCOPE_POLICY:
        raise ValueError(f"invalid market acceptance level: {level}")
    if not location:
        raise ValueError("geography is required")
    policy = _SCOPE_POLICY[market_level]
    return {
        "market_acceptance": market_level,
        "geography": location,
        **policy,
        # A Market Cell supports discovery priority, not a factual claim that an
        # entire country (or neighboring country) has the same demand intensity.
        "country_wide_demand_proven": False,
        "evidence_scope": "MARKET_CELL_ONLY",
        "cross_country_requires_separate_market_cell": True,
        "adjacent_country_acceptance_inherited": False,
        "cross_country_requires_independent_demand_evidence": True,
    }
