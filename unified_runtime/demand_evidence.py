from __future__ import annotations

from typing import Any


_D1_DIRECT_PROCUREMENT = {
    "CUSTOMS",
    "TRADE_DATA",
    "SUPPLIER_BUYER_SHIPMENT",
    "PURCHASE_ORDER",
    "INVOICE",
}
_D2_STRONG_COMMERCE = {
    "OFFICIAL_STOCKING_PAGE",
    "OFFICIAL_DISTRIBUTION_CATALOG",
    "OFFICIAL_PRODUCT_COMMERCE_PAGE",
    "VERIFIED_CURRENT_PROJECT",
    "VERIFIED_PUBLIC_STORE_INVENTORY",
}
_D3_APPLICATION_PROOF = {
    "OFFICIAL_APPLICATION_PAGE",
    "OFFICIAL_MANUFACTURING_PAGE",
    "VERIFIED_APPLICATION_PROFILE",
    "OFFICIAL_SERVICE_PAGE",
}
_D4_DISCOVERY = {
    "SEARCH_SIMILARITY",
    "MAPS_CATEGORY_MATCH",
    "INDUSTRY_DIRECTORY_MATCH",
    "GEOGRAPHIC_ADJACENCY",
    "CROSS_SELL_HYPOTHESIS",
}


def _base_result(source_type: str, evidence_ids: list[str]) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "evidence_ids": evidence_ids,
        "tier": "D4",
        "supports_procurement": False,
        "supports_product_involvement": False,
        "supports_current_commerce": False,
        "supports_application_fit": False,
        "discovery_only": True,
        "requires_further_verification": True,
        "boundary": "DISCOVERY_HYPOTHESIS_ONLY",
    }


def classify_demand_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("demand evidence payload must be an object")
    source_type = str(payload.get("source_type") or "").strip().upper()
    if not source_type:
        raise ValueError("source_type is required")
    evidence_ids = sorted({str(value).strip() for value in payload.get("evidence_ids", []) if str(value).strip()})
    verified = bool(payload.get("verified"))
    result = _base_result(source_type, evidence_ids)

    if not verified or not evidence_ids:
        result["boundary"] = "UNVERIFIED_DISCOVERY_SIGNAL" if not verified else "UNBOUND_DISCOVERY_SIGNAL"
        return result

    if source_type in _D1_DIRECT_PROCUREMENT:
        result.update({
            "tier": "D1",
            "supports_procurement": True,
            "supports_product_involvement": True,
            "supports_current_commerce": True,
            "supports_application_fit": False,
            "discovery_only": False,
            "requires_further_verification": False,
            "boundary": "DIRECT_PROCUREMENT_PROOF",
        })
        return result

    if source_type in _D2_STRONG_COMMERCE:
        result.update({
            "tier": "D2",
            "supports_product_involvement": True,
            "supports_current_commerce": True,
            "discovery_only": False,
            "requires_further_verification": False,
            "boundary": "STRONG_COMMERCE_PROOF_NOT_DIRECT_PROCUREMENT",
        })
        return result

    if source_type in _D3_APPLICATION_PROOF:
        result.update({
            "tier": "D3",
            "supports_application_fit": True,
            "discovery_only": False,
            "requires_further_verification": True,
            "boundary": "APPLICATION_FIT_ONLY_NOT_PROCUREMENT_PROOF",
        })
        return result

    # Known D4 sources and unknown source types both fail closed to discovery-only.
    if source_type in _D4_DISCOVERY:
        result["boundary"] = "DISCOVERY_HYPOTHESIS_ONLY"
    else:
        result["boundary"] = "UNKNOWN_SOURCE_REQUIRES_VERIFICATION"
    return result
