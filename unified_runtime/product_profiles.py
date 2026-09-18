from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def product_profile_sha256(profile: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(profile)).hexdigest()


PRODUCT_PROFILE_REGISTRY: dict[str, dict[str, Any]] = {
    "PVC": {
        "profile_id": "PVC",
        "profile_version": "1",
        "portfolio_priority": "PRIMARY",
        "scheduler_weight": 1.00,
        "subfamilies": [
            "PVC_FOAM_BOARD",
            "RIGID_PVC",
            "STRUCTURED_PVC",
            "PVC_WALL_PANEL",
            "PVC_FLOORING",
            "PVC_DECORATIVE_PANEL",
        ],
        "variants": [
            "FREE_FOAM",
            "CELUKA",
            "CO_EXTRUDED",
            "CABINET_BOARD",
            "DECORATIVE_LAMINATED",
            "SOLID_SHEET",
            "PARTITION_BOARD",
            "WET_AREA_BOARD",
            "AQUARIUM_BOARD",
            "INDUSTRIAL_SHEET",
            "HOLLOW_BOARD",
            "SPACE_BOARD",
            "HONEYCOMB_BOARD",
        ],
        "variant_application_map": {
            "FREE_FOAM": {
                "applications": ["SIGNAGE", "UV_PRINTING", "CNC_ROUTING", "EXHIBITION_DISPLAY", "POP_DISPLAY"],
                "buyer_archetypes": ["SIGN_MAKER", "SIGN_MATERIAL_DISTRIBUTOR", "DISPLAY_MANUFACTURER", "UV_PRINTING_COMPANY", "CNC_FABRICATOR", "EXHIBITION_CONTRACTOR"],
            },
            "CELUKA": {
                "applications": ["CABINETRY", "BATHROOM_VANITY", "FURNITURE", "INTERIOR_FITOUT", "CNC_ROUTING"],
                "buyer_archetypes": ["CABINET_MANUFACTURER", "BATHROOM_VANITY_MANUFACTURER", "FURNITURE_MANUFACTURER", "INTERIOR_FITOUT_COMPANY", "CNC_FABRICATOR"],
            },
            "CO_EXTRUDED": {
                "applications": ["DISPLAY", "CABINETRY", "VEHICLE_INTERIOR", "FABRICATION"],
                "buyer_archetypes": ["DISPLAY_MANUFACTURER", "CABINET_MANUFACTURER", "CNC_FABRICATOR"],
            },
            "PARTITION_BOARD": {
                "applications": ["PARTITION_WET_AREA"],
                "buyer_archetypes": ["PARTITION_MANUFACTURER", "WET_AREA_FABRICATOR", "BUILDING_MATERIAL_DISTRIBUTOR"],
            },
            "WET_AREA_BOARD": {
                "applications": ["PARTITION_WET_AREA", "AQUARIUM_WET_AREA"],
                "buyer_archetypes": ["WET_AREA_FABRICATOR", "AQUARIUM_FABRICATOR", "PARTITION_MANUFACTURER"],
            },
            "AQUARIUM_BOARD": {
                "applications": ["AQUARIUM_WET_AREA"],
                "buyer_archetypes": ["AQUARIUM_FABRICATOR", "WET_AREA_FABRICATOR"],
            },
            "CABINET_BOARD": {
                "applications": ["CABINETRY", "BATHROOM_VANITY", "FURNITURE"],
                "buyer_archetypes": ["CABINET_MANUFACTURER", "BATHROOM_VANITY_MANUFACTURER", "FURNITURE_MANUFACTURER"],
            },
            "DECORATIVE_LAMINATED": {
                "applications": ["INTERIOR_FITOUT", "WALL_DECORATION", "CABINETRY"],
                "buyer_archetypes": ["INTERIOR_FITOUT_COMPANY", "BUILDING_MATERIAL_DISTRIBUTOR", "CABINET_MANUFACTURER"],
            },
            "HOLLOW_BOARD": {
                "applications": ["INTERIOR_FITOUT", "PARTITION_WET_AREA"],
                "buyer_archetypes": ["INTERIOR_FITOUT_COMPANY", "PARTITION_MANUFACTURER", "BUILDING_MATERIAL_DISTRIBUTOR"],
            },
            "SPACE_BOARD": {
                "applications": ["INTERIOR_FITOUT", "PARTITION_WET_AREA"],
                "buyer_archetypes": ["INTERIOR_FITOUT_COMPANY", "PARTITION_MANUFACTURER", "BUILDING_MATERIAL_DISTRIBUTOR"],
                "technical_identity_requires_verification": True,
            },
            "HONEYCOMB_BOARD": {
                "applications": ["INTERIOR_FITOUT", "VEHICLE_INTERIOR", "PARTITION_WET_AREA"],
                "buyer_archetypes": ["INTERIOR_FITOUT_COMPANY", "PARTITION_MANUFACTURER", "BUILDING_MATERIAL_DISTRIBUTOR"],
                "technical_identity_requires_verification": True,
            },
            "SOLID_SHEET": {
                "applications": ["INDUSTRIAL_FABRICATION", "PARTITION_WET_AREA"],
                "buyer_archetypes": ["PLASTIC_SHEET_DISTRIBUTOR", "INDUSTRIAL_FABRICATOR", "PARTITION_MANUFACTURER"],
            },
            "INDUSTRIAL_SHEET": {
                "applications": ["INDUSTRIAL_FABRICATION"],
                "buyer_archetypes": ["PLASTIC_SHEET_DISTRIBUTOR", "INDUSTRIAL_FABRICATOR"],
            },
            "PVC_WALL_PANEL": {
                "applications": ["WALL_DECORATION", "INTERIOR_FITOUT"],
                "buyer_archetypes": ["BUILDING_MATERIAL_DISTRIBUTOR", "INTERIOR_FITOUT_COMPANY", "WALL_PANEL_DISTRIBUTOR"],
            },
            "PVC_FLOORING": {
                "applications": ["FLOORING"],
                "buyer_archetypes": ["FLOORING_IMPORTER", "FLOORING_DISTRIBUTOR", "BUILDING_MATERIAL_DISTRIBUTOR"],
            },
            "PVC_DECORATIVE_PANEL": {
                "applications": ["WALL_DECORATION", "INTERIOR_FITOUT"],
                "buyer_archetypes": ["BUILDING_MATERIAL_DISTRIBUTOR", "INTERIOR_FITOUT_COMPANY", "WALL_PANEL_DISTRIBUTOR"],
            },
        },
        "applications": [
            "SIGNAGE",
            "UV_PRINTING",
            "CNC_ROUTING",
            "EXHIBITION_DISPLAY",
            "POP_DISPLAY",
            "CABINETRY",
            "BATHROOM_VANITY",
            "FURNITURE",
            "INTERIOR_FITOUT",
            "PARTITION_WET_AREA",
            "AQUARIUM_WET_AREA",
            "WALL_DECORATION",
            "VEHICLE_INTERIOR",
            "DISPLAY",
            "FABRICATION",
            "INDUSTRIAL_FABRICATION",
            "FLOORING",
        ],
        "buyer_archetypes": [
            "SIGN_MATERIAL_DISTRIBUTOR",
            "SIGN_MAKER",
            "ADVERTISING_FABRICATOR",
            "UV_PRINTING_COMPANY",
            "DISPLAY_MANUFACTURER",
            "EXHIBITION_CONTRACTOR",
            "CNC_FABRICATOR",
            "PLASTIC_SHEET_DISTRIBUTOR",
            "CABINET_MANUFACTURER",
            "BATHROOM_VANITY_MANUFACTURER",
            "FURNITURE_MANUFACTURER",
            "INTERIOR_FITOUT_COMPANY",
            "BUILDING_MATERIAL_DISTRIBUTOR",
            "PARTITION_MANUFACTURER",
            "WET_AREA_FABRICATOR",
            "AQUARIUM_FABRICATOR",
            "INDUSTRIAL_FABRICATOR",
            "WALL_PANEL_DISTRIBUTOR",
            "FLOORING_IMPORTER",
            "FLOORING_DISTRIBUTOR",
        ],
        "channels": [
            "IMPORTER",
            "DISTRIBUTOR",
            "WHOLESALER",
            "STOCKIST",
            "DEALER",
            "FABRICATOR",
            "MANUFACTURER",
            "PROJECT_SUPPLIER",
        ],
        "commercial_aliases": [
            "PVC foam board",
            "PVC foam sheet",
            "Celuka board",
            "Forex board",
            "PVC cabinet board",
            "rigid PVC sheet",
            "solid PVC board",
        ],
        "marketing_aliases": ["太空板", "碳晶板", "蜂窝板"],
        "positive_search_vocabulary": [
            "sign supplies",
            "sign materials",
            "display materials",
            "UV printing substrate",
            "CNC routing",
            "cabinet maker",
            "bathroom vanity manufacturer",
            "toilet partition",
            "building material distributor",
        ],
        "negative_exclusion_vocabulary": [
            "PVC pipe",
            "PVC film",
            "consumer DIY",
            "unrelated flexible vinyl",
        ],
        "cross_sell_profiles": ["ACRYLIC_PMMA", "WPC", "SPC"],
        "technical_claim_boundaries": [
            "marketing alias does not establish technical structure",
            "product family does not establish fire rating",
            "product family does not establish outdoor durability",
            "product family does not establish food-contact compliance",
        ],
    },
    "WPC": {
        "profile_id": "WPC",
        "profile_version": "1",
        "portfolio_priority": "SECONDARY_HIGH",
        "scheduler_weight": 0.75,
        "subfamilies": ["DECKING", "WALL_CLADDING", "FENCING", "SCREEN_GRILLE", "RAILING"],
        "variants": [],
        "variant_application_map": {
            "DECKING": {
                "applications": ["OUTDOOR_DECKING", "LANDSCAPE"],
                "buyer_archetypes": ["DECKING_DISTRIBUTOR", "BUILDING_MATERIAL_DISTRIBUTOR", "LANDSCAPE_CONTRACTOR"],
            },
            "WALL_CLADDING": {
                "applications": ["CLADDING"],
                "buyer_archetypes": ["CLADDING_SUPPLIER", "BUILDING_MATERIAL_DISTRIBUTOR"],
            },
            "FENCING": {
                "applications": ["FENCING"],
                "buyer_archetypes": ["FENCE_SUPPLIER", "BUILDING_MATERIAL_DISTRIBUTOR", "LANDSCAPE_CONTRACTOR"],
            },
            "SCREEN_GRILLE": {
                "applications": ["SCREENING", "LANDSCAPE"],
                "buyer_archetypes": ["BUILDING_MATERIAL_DISTRIBUTOR", "LANDSCAPE_CONTRACTOR"],
            },
            "RAILING": {
                "applications": ["LANDSCAPE"],
                "buyer_archetypes": ["BUILDING_MATERIAL_DISTRIBUTOR", "LANDSCAPE_CONTRACTOR"],
            },
        },
        "applications": ["OUTDOOR_DECKING", "CLADDING", "FENCING", "LANDSCAPE", "SCREENING"],
        "buyer_archetypes": [
            "DECKING_DISTRIBUTOR",
            "BUILDING_MATERIAL_DISTRIBUTOR",
            "LANDSCAPE_CONTRACTOR",
            "FENCE_SUPPLIER",
            "CLADDING_SUPPLIER",
        ],
        "channels": ["IMPORTER", "DISTRIBUTOR", "WHOLESALER", "PROJECT_SUPPLIER"],
        "commercial_aliases": ["WPC decking", "WPC wall cladding", "WPC fencing"],
        "marketing_aliases": [],
        "positive_search_vocabulary": ["composite decking distributor", "WPC cladding supplier", "WPC fence supplier"],
        "negative_exclusion_vocabulary": [],
        "cross_sell_profiles": ["PVC", "SPC"],
        "technical_claim_boundaries": ["WPC profile does not inherit PVC sheet evidence"],
    },
    "SPC": {
        "profile_id": "SPC",
        "profile_version": "1",
        "portfolio_priority": "SECONDARY",
        "scheduler_weight": 0.65,
        "subfamilies": ["SPC_FLOORING", "SPC_WALL_PANEL"],
        "variants": [],
        "variant_application_map": {
            "SPC_FLOORING": {
                "applications": ["FLOORING"],
                "buyer_archetypes": ["FLOORING_IMPORTER", "FLOORING_DISTRIBUTOR", "BUILDING_MATERIAL_DISTRIBUTOR"],
            },
            "SPC_WALL_PANEL": {
                "applications": ["INTERIOR_WALL"],
                "buyer_archetypes": ["BUILDING_MATERIAL_DISTRIBUTOR", "INTERIOR_FITOUT_COMPANY"],
            },
        },
        "applications": ["FLOORING", "INTERIOR_WALL"],
        "buyer_archetypes": ["FLOORING_IMPORTER", "FLOORING_DISTRIBUTOR", "BUILDING_MATERIAL_DISTRIBUTOR", "INTERIOR_FITOUT_COMPANY"],
        "channels": ["IMPORTER", "DISTRIBUTOR", "WHOLESALER", "DEALER"],
        "commercial_aliases": ["SPC flooring", "rigid core flooring"],
        "marketing_aliases": [],
        "positive_search_vocabulary": ["SPC flooring importer", "rigid core flooring distributor"],
        "negative_exclusion_vocabulary": ["generic PVC sheet"],
        "cross_sell_profiles": ["PVC", "WPC"],
        "technical_claim_boundaries": ["SPC flooring is separate from generic rigid PVC sheet"],
    },
    "ACRYLIC_PMMA": {
        "profile_id": "ACRYLIC_PMMA",
        "profile_version": "1",
        "portfolio_priority": "SECONDARY",
        "scheduler_weight": 0.65,
        "subfamilies": ["GENERAL_SHEET", "SIGNAGE_GRADE", "DISPLAY_GRADE", "FABRICATION_GRADE", "GLAZING", "SPECIALTY"],
        "variants": [],
        "variant_application_map": {
            "GENERAL_SHEET": {
                "applications": ["FABRICATION", "INTERIOR_FIXTURE"],
                "buyer_archetypes": ["ACRYLIC_FABRICATOR", "PLASTIC_SHEET_DISTRIBUTOR"],
            },
            "SIGNAGE_GRADE": {
                "applications": ["SIGNAGE"],
                "buyer_archetypes": ["SIGN_MATERIAL_DISTRIBUTOR", "ACRYLIC_FABRICATOR"],
            },
            "DISPLAY_GRADE": {
                "applications": ["DISPLAY"],
                "buyer_archetypes": ["DISPLAY_MANUFACTURER", "ACRYLIC_FABRICATOR"],
            },
            "FABRICATION_GRADE": {
                "applications": ["FABRICATION"],
                "buyer_archetypes": ["ACRYLIC_FABRICATOR", "PLASTIC_SHEET_DISTRIBUTOR"],
            },
            "GLAZING": {
                "applications": ["GLAZING"],
                "buyer_archetypes": ["ACRYLIC_FABRICATOR", "PLASTIC_SHEET_DISTRIBUTOR"],
            },
            "SPECIALTY": {
                "applications": ["FABRICATION"],
                "buyer_archetypes": ["ACRYLIC_FABRICATOR"],
                "technical_identity_requires_verification": True,
            },
        },
        "applications": ["SIGNAGE", "DISPLAY", "FABRICATION", "GLAZING", "INTERIOR_FIXTURE"],
        "buyer_archetypes": ["SIGN_MATERIAL_DISTRIBUTOR", "DISPLAY_MANUFACTURER", "ACRYLIC_FABRICATOR", "PLASTIC_SHEET_DISTRIBUTOR"],
        "channels": ["IMPORTER", "DISTRIBUTOR", "WHOLESALER", "FABRICATOR"],
        "commercial_aliases": ["acrylic sheet", "PMMA sheet", "plexiglass sheet"],
        "marketing_aliases": [],
        "positive_search_vocabulary": ["acrylic sheet distributor", "sign acrylic supplier", "display acrylic fabricator"],
        "negative_exclusion_vocabulary": [],
        "cross_sell_profiles": ["PVC"],
        "technical_claim_boundaries": ["acrylic application overlap does not establish PVC demand"],
    },
}


_MARKETING_ALIAS_INDEX = {
    alias.casefold(): profile_id
    for profile_id, profile in PRODUCT_PROFILE_REGISTRY.items()
    for alias in profile.get("marketing_aliases", [])
}

_COMMERCIAL_ALIAS_INDEX = {
    alias.casefold(): profile_id
    for profile_id, profile in PRODUCT_PROFILE_REGISTRY.items()
    for alias in profile.get("commercial_aliases", [])
}


def get_product_profile(profile_id: str, version: str | None = None) -> dict[str, Any]:
    key = str(profile_id).strip().upper()
    if key not in PRODUCT_PROFILE_REGISTRY:
        raise KeyError(f"unknown product profile: {profile_id}")
    profile = PRODUCT_PROFILE_REGISTRY[key]
    if version is not None and str(version) != str(profile["profile_version"]):
        raise KeyError(f"unknown product profile version: {profile_id}@{version}")
    result = copy.deepcopy(profile)
    result["profile_sha256"] = product_profile_sha256(profile)
    return result


def list_product_profiles() -> list[dict[str, Any]]:
    return [get_product_profile(profile_id) for profile_id in sorted(PRODUCT_PROFILE_REGISTRY)]


def portfolio_priority(profile_id: str) -> float:
    return float(get_product_profile(profile_id)["scheduler_weight"])


def classify_product_alias(alias: str) -> dict[str, Any]:
    normalized = str(alias or "").strip().casefold()
    if normalized in _MARKETING_ALIAS_INDEX:
        return {
            "alias": alias,
            "profile_id": _MARKETING_ALIAS_INDEX[normalized],
            "classification": "MARKETING_ALIAS",
            "technical_identity_verified": False,
        }
    if normalized in _COMMERCIAL_ALIAS_INDEX:
        return {
            "alias": alias,
            "profile_id": _COMMERCIAL_ALIAS_INDEX[normalized],
            "classification": "COMMERCIAL_ALIAS",
            "technical_identity_verified": False,
        }
    return {
        "alias": alias,
        "profile_id": None,
        "classification": "UNRESOLVED_ALIAS",
        "technical_identity_verified": False,
    }
