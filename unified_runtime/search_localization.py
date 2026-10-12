from __future__ import annotations

from typing import Any

from .product_profiles import get_product_profile


LOCALE_SEARCH_VOCABULARY_VERSION = "2"

# Observed public terminology expands discovery; it proves no model, buyer,
# import transaction, current national customs code or manufacturer capability.
_MACHINERY_TERM_SOURCE_HINTS = {
    "id-ID": ("https://www.fabrikasi.co.id/mesin-filling/", "https://gemindo.co.id/product/filling-machine/mesin-pengisi-cairan-otomatis-minyak-goreng-sabun-cair-pestisida-kecap-dll/", "https://marui.co.id/proses-pembuatan-skincare-dari-riset-hingga-produk-jadi/"),
    "vi-VN": ("https://gmpgroups.com.vn/thiet-bi-san-xuat/day-chuyen-san-xuat-my-pham/", "https://ilab.com.vn/product-category/yekeey/"),
    "es-MX": ("https://forzaprocessequipment.com/es/", "https://kosmixpro.com/es/industrias/"),
    "pt-BR": ("https://www.honemachine.com/pt/products.html", "https://www.maxwellmixing.com/pt/p-vacuum-emulsifying-mixer-machine-by-maxwell-2.html"),
}


# Curated discovery vocabulary only. These strings can expand search queries but
# never constitute evidence that a company buys or uses a product.
_LOCALE_PACKS: dict[str, dict[str, Any]] = {
    "id-ID": {
        "language": "id",
        "market": "Indonesia",
        "products": {
            "SOAP_MACHINERY": ["mesin pengisi cairan", "mesin filling cairan", "mesin pengaduk sabun cair", "mesin vacuum homogenizer"],
        },
        "applications": {
            "LIQUID_DETERGENT_PRODUCTION": ["produksi sabun cair"],
            "COSMETICS_EMULSION": ["proses pembuatan kosmetik"],
            "LIQUID_FILLING_PACKAGING": ["pengisian cairan otomatis"],
        },
        "archetypes": {
            "COSMETICS_MANUFACTURER": ["pabrik kosmetik"],
            "DETERGENT_MANUFACTURER": ["produsen sabun cair"],
        },
    },
    "vi-VN": {
        "language": "vi",
        "market": "Vietnam",
        "products": {
            "PVC": ["tấm PVC foam", "tấm nhựa PVC foam", "tấm Formex"],
            "WPC": ["gỗ nhựa WPC", "tấm WPC"],
            "SPC": ["sàn SPC", "sàn nhựa SPC"],
            "ACRYLIC_PMMA": ["tấm acrylic", "tấm mica"],
            "SOAP_MACHINERY": ["máy nhũ hóa chân không", "máy chiết rót mỹ phẩm", "máy trộn mỹ phẩm"],
        },
        "applications": {
            "SIGNAGE": ["thiết kế quảng cáo", "biển quảng cáo", "vật liệu quảng cáo"],
            "CABINETRY": ["tủ bếp", "trang trí nội thất"],
            "BATHROOM_VANITY": ["tủ lavabo", "tủ phòng tắm"],
            "PARTITION_WET_AREA": ["vách ngăn", "vách ngăn vệ sinh"],
            "FLOORING": ["vật liệu sàn", "sàn nội thất"],
            "COSMETICS_EMULSION": ["sản xuất mỹ phẩm"],
            "LIQUID_FILLING_PACKAGING": ["dây chuyền chiết rót mỹ phẩm"],
        },
        "archetypes": {
            "CABINET_MANUFACTURER": ["xưởng tủ bếp", "nhà sản xuất tủ"],
            "BUILDING_MATERIAL_DISTRIBUTOR": ["nhà phân phối vật liệu xây dựng"],
            "SIGN_MAKER": ["công ty quảng cáo", "sản xuất biển quảng cáo"],
            "COSMETICS_MANUFACTURER": ["nhà máy sản xuất mỹ phẩm"],
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
            "SOAP_MACHINERY": ["emulsionador al vacío", "mezclador emulsionador al vacío", "máquina llenadora de líquidos"],
        },
        "applications": {
            "SIGNAGE": ["señalización", "letreros", "anuncios", "comunicación visual"],
            "DISPLAY": ["exhibidores", "displays"],
            "EXHIBITION_DISPLAY": ["stands", "exhibidores"],
            "CABINETRY": ["gabinetes", "muebles"],
            "FLOORING": ["pisos", "distribuidor de pisos"],
            "COSMETICS_EMULSION": ["fabricación de cosméticos"],
        },
        "archetypes": {
            "SIGN_MAKER": ["fabricante de letreros"],
            "SIGN_MATERIAL_DISTRIBUTOR": ["distribuidor de materiales para señalización"],
            "PLASTIC_SHEET_DISTRIBUTOR": ["distribuidor de láminas plásticas"],
            "BUILDING_MATERIAL_DISTRIBUTOR": ["distribuidor de materiales de construcción"],
            "COSMETICS_MANUFACTURER": ["fabricante de cosméticos"],
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
            "SOAP_MACHINERY": ["misturador emulsificador a vácuo", "misturador homogeneizador a vácuo", "máquina de envase de cosméticos"],
        },
        "applications": {
            "SIGNAGE": ["comunicação visual", "sinalização", "placas"],
            "DISPLAY": ["displays", "expositores"],
            "EXHIBITION_DISPLAY": ["stands", "expositores"],
            "CABINETRY": ["móveis", "marcenaria"],
            "FLOORING": ["pisos", "distribuidor de pisos"],
            "COSMETICS_EMULSION": ["fabricação de cosméticos"],
        },
        "archetypes": {
            "SIGN_MAKER": ["empresa de comunicação visual"],
            "SIGN_MATERIAL_DISTRIBUTOR": ["distribuidor de materiais para comunicação visual"],
            "PLASTIC_SHEET_DISTRIBUTOR": ["distribuidor de chapas plásticas"],
            "BUILDING_MATERIAL_DISTRIBUTOR": ["distribuidor de materiais de construção"],
            "COSMETICS_MANUFACTURER": ["fabricante de cosméticos"],
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
        "source_hint_urls": list(_MACHINERY_TERM_SOURCE_HINTS.get(normalized_locale, ())) if profile_id == "SOAP_MACHINERY" else [],
        "planning_only": True,
        "evidence_strength": None,
        "source_coverage_complete": False,
    }
