from __future__ import annotations

from typing import Any

from .product_profiles import get_product_profile


LOCALE_SEARCH_VOCABULARY_VERSION = "1"

# Curated discovery vocabulary only. These strings can expand search queries but
# never constitute evidence that a company buys or uses a product.
_LOCALE_PACKS: dict[str, dict[str, Any]] = {
    "vi-VN": {
        "language": "vi",
        "market": "Vietnam",
        "products": {
            "PVC": ["tấm PVC foam", "tấm nhựa PVC foam", "tấm Formex"],
            "WPC": ["gỗ nhựa WPC", "tấm WPC"],
            "SPC": ["sàn SPC", "sàn nhựa SPC"],
            "ACRYLIC_PMMA": ["tấm acrylic", "tấm mica"],
        },
        "applications": {
            "SIGNAGE": ["thiết kế quảng cáo", "biển quảng cáo", "vật liệu quảng cáo"],
            "CABINETRY": ["tủ bếp", "trang trí nội thất"],
            "BATHROOM_VANITY": ["tủ lavabo", "tủ phòng tắm"],
            "PARTITION_WET_AREA": ["vách ngăn", "vách ngăn vệ sinh"],
            "FLOORING": ["vật liệu sàn", "sàn nội thất"],
        },
        "archetypes": {
            "CABINET_MANUFACTURER": ["xưởng tủ bếp", "nhà sản xuất tủ"],
            "BUILDING_MATERIAL_DISTRIBUTOR": ["nhà phân phối vật liệu xây dựng"],
            "SIGN_MAKER": ["công ty quảng cáo", "sản xuất biển quảng cáo"],
        },
    },
    "es-MX": {
        "language": "es",
        "market": "Mexico",
        "products": {
            "PVC": ["PVC espumado", "lámina de PVC espumado", "trovicel"],
            "WPC": ["WPC", "madera plástica WPC"],
            "SPC": ["piso SPC", "piso rígido SPC"],
            "ACRYLIC_PMMA": ["lámina acrílica", "acrílico"],
        },
        "applications": {
            "SIGNAGE": ["señalización", "letreros", "anuncios", "comunicación visual"],
            "DISPLAY": ["exhibidores", "displays"],
            "EXHIBITION_DISPLAY": ["stands", "exhibidores"],
            "CABINETRY": ["gabinetes", "muebles"],
            "FLOORING": ["pisos", "distribuidor de pisos"],
        },
        "archetypes": {
            "SIGN_MAKER": ["fabricante de letreros"],
            "SIGN_MATERIAL_DISTRIBUTOR": ["distribuidor de materiales para señalización"],
            "PLASTIC_SHEET_DISTRIBUTOR": ["distribuidor de láminas plásticas"],
            "BUILDING_MATERIAL_DISTRIBUTOR": ["distribuidor de materiales de construcción"],
        },
    },
    "pt-BR": {
        "language": "pt",
        "market": "Brazil",
        "products": {
            "PVC": ["PVC expandido", "chapa de PVC expandido", "placa de PVC expandido"],
            "WPC": ["WPC", "madeira plástica WPC"],
            "SPC": ["piso SPC", "piso vinílico SPC"],
            "ACRYLIC_PMMA": ["chapa acrílica", "acrílico"],
        },
        "applications": {
            "SIGNAGE": ["comunicação visual", "sinalização", "placas"],
            "DISPLAY": ["displays", "expositores"],
            "EXHIBITION_DISPLAY": ["stands", "expositores"],
            "CABINETRY": ["móveis", "marcenaria"],
            "FLOORING": ["pisos", "distribuidor de pisos"],
        },
        "archetypes": {
            "SIGN_MAKER": ["empresa de comunicação visual"],
            "SIGN_MATERIAL_DISTRIBUTOR": ["distribuidor de materiais para comunicação visual"],
            "PLASTIC_SHEET_DISTRIBUTOR": ["distribuidor de chapas plásticas"],
            "BUILDING_MATERIAL_DISTRIBUTOR": ["distribuidor de materiais de construção"],
        },
    },
}


def _normalize_locale(locale: str) -> str:
    raw = str(locale or "").strip()
    if not raw:
        return ""
    parts = raw.replace("_", "-").split("-")
    if len(parts) == 1:
        language = parts[0].lower()
        for key in _LOCALE_PACKS:
            if key.lower().startswith(language + "-"):
                return key
        return language
    return f"{parts[0].lower()}-{parts[1].upper()}"


def get_localized_search_terms(
    *,
    locale: str,
    product_profile_id: str,
    applications: list[str] | None = None,
    buyer_archetypes: list[str] | None = None,
) -> dict[str, Any]:
    profile_id = str(product_profile_id or "").strip().upper()
    get_product_profile(profile_id)
    normalized_locale = _normalize_locale(locale)
    pack = _LOCALE_PACKS.get(normalized_locale)
    if pack is None:
        return {
            "status": "NO_CURATED_LOCALE_PACK",
            "locale": normalized_locale or None,
            "vocabulary_version": LOCALE_SEARCH_VOCABULARY_VERSION,
            "terms": [],
            "planning_only": True,
            "evidence_strength": None,
            "source_coverage_complete": False,
        }

    terms: list[str] = []
    terms.extend(pack.get("products", {}).get(profile_id, []))
    for application in applications or []:
        terms.extend(pack.get("applications", {}).get(str(application).upper(), []))
    for archetype in buyer_archetypes or []:
        terms.extend(pack.get("archetypes", {}).get(str(archetype).upper(), []))

    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = " ".join(str(term).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            unique.append(cleaned)

    return {
        "status": "CURATED",
        "locale": normalized_locale,
        "language": pack.get("language"),
        "market": pack.get("market"),
        "vocabulary_version": LOCALE_SEARCH_VOCABULARY_VERSION,
        "terms": unique,
        "planning_only": True,
        "evidence_strength": None,
        "source_coverage_complete": False,
    }
