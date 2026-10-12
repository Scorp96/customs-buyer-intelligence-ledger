"""Evidence boundaries for machinery / HS-driven buyer qualification.

This is a pure discovery and proof assessor, not a classifier, customs
declaration authority, factory capability certification or a write path.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

# Purchase orders and invoices show procurement, not a customs frontier crossing.
_IMPORT_PROOF_SOURCES = {"CUSTOMS", "TRADE_DATA", "SUPPLIER_BUYER_SHIPMENT", "BOL", "BILL_OF_LADING"}


_ALLOWED_ROLES = {"BUYER", "IMPORTER_OF_RECORD", "CONSIGNEE", "ULTIMATE_BUYER"}
_NON_BUYER_ROLES = {
    "SHIPPER", "EXPORTER", "SUPPLIER_GROUP",
    "CUSTOMS_BROKER", "FORWARDER", "TRADING_INTERMEDIARY",
}
_COMPLETE_MACHINE = {"COMPLETE_MACHINE", "COMPLETE_LINE"}
_UNKNOWN = ("", "UNKNOWN", "UNVERIFIED", "NONE")
_HS6 = re.compile(r"^[0-9]{6}$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _real_date(value: str) -> bool:
    if not _ISO_DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def assess_machinery_trade_buyer(
    *,
    hs: dict[str, Any] | None = None,
    shipment: dict[str, Any] | None = None,
    buyer: dict[str, Any] | None = None,
    seller_capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate supplied evidence shape, without independently reading its sources.

    This pure preflight NEVER certifies actual trade, a national ruling or
    a seller model from caller-provided booleans/URLs alone. Independent
    Runtime/Host source verification and buyer adjudication must follow.
    """
    hs = dict(hs or {})
    shipment = dict(shipment or {})
    buyer = dict(buyer or {})
    seller_capability = dict(seller_capability or {})
    blockers: list[str] = []

    code = _text(hs, "hs6_candidate")
    valid_hs = bool(_HS6.fullmatch(code))
    country = _text(hs, "destination_country")
    national_code = _text(hs, "national_tariff_code")
    national_source = _text(hs, "national_official_locator")
    national_verified = bool(
        valid_hs and country and national_source
        and national_code.isdigit() and len(national_code) > 6
        and national_code.startswith(code)
    )
    if code and not valid_hs:
        blockers.append("HS6_CANDIDATE_FORMAT_INVALID")
    if national_code and not national_verified:
        blockers.append("NATIONAL_TARIFF_NOT_OFFICIALLY_BOUND")

    goods_kind = _text(shipment, "goods_kind").upper()
    direct_source = _text(shipment, "source_type").upper() in _IMPORT_PROOF_SOURCES
    shipment_locator = _text(shipment, "source_locator")
    shipment_key = _text(shipment, "bill_of_lading") or _text(shipment, "shipment_id")
    shipment_date = _text(shipment, "shipment_date")
    machine_evidence_locator = _text(shipment, "machine_identity_locator")
    exact_machine = (
        goods_kind in _COMPLETE_MACHINE
        and _text(shipment, "machine_identity_status").upper() == "EXACT_MATCH"
        and bool(machine_evidence_locator)
        and bool(_text(shipment, "goods_description"))
    )
    if goods_kind in {"PARTS", "SPARE_PARTS", "CONSUMABLES", "EMPTY_PACKAGING"}:
        blockers.append("SHIPMENT_IS_NOT_COMPLETE_MACHINE")
    elif not exact_machine:
        blockers.append("COMPLETE_MACHINE_PRODUCT_IDENTITY_UNVERIFIED")

    if not direct_source:
        blockers.append("DIRECT_PROCUREMENT_SOURCE_MISSING")
    if not shipment_locator:
        blockers.append("TRADE_SOURCE_LOCATOR_MISSING")
    if not shipment_key:
        blockers.append("SHIPMENT_UNIQUE_IDENTIFIER_MISSING")
    if not _real_date(shipment_date):
        blockers.append("SHIPMENT_DATE_INVALID_OR_MISSING")

    account_id = _text(buyer, "canonical_account_id")
    shipment_owner = _text(shipment, "buyer_account_id")
    role = _text(buyer, "trade_role").upper()
    legal_source = _text(buyer, "identity_evidence_locator")
    identity_bound = bool(
        account_id and shipment_owner == account_id
        and role in _ALLOWED_ROLES
        and _text(buyer, "legal_entity_name")
        and legal_source
    )
    if role in _NON_BUYER_ROLES:
        blockers.append("PARTY_IS_NOT_BUYER")
    if not identity_bound:
        blockers.append("BUYER_LEGAL_IDENTITY_OR_TRADE_ROLE_UNVERIFIED")

    shipment_supported = bool(
        direct_source and shipment_locator and shipment_key
        and _real_date(shipment_date) and exact_machine and identity_bound
    )
    ultimate_buyer_supported = bool(
        shipment_supported
        and role in {"BUYER", "ULTIMATE_BUYER"}
        and _text(buyer, "ultimate_buyer_evidence_locator")
    )
    if ultimate_buyer_supported:
        stage = "CLAIMED_ULTIMATE_MACHINE_BUYER_REQUIRES_INDEPENDENT_SOURCE_CHECK"
    elif shipment_supported and role == "IMPORTER_OF_RECORD":
        stage = "CLAIMED_MACHINE_IMPORTER_OF_RECORD_REQUIRES_INDEPENDENT_SOURCE_CHECK"
    elif shipment_supported and role == "CONSIGNEE":
        stage = "CLAIMED_MACHINE_CONSIGNEE_NOT_NECESSARILY_BUYER"
    elif shipment_supported:
        stage = "CLAIMED_MACHINE_TRADE_BUYER_ULTIMATE_UNRESOLVED"
    elif identity_bound and (
        exact_machine or _text(buyer, "industry_product_evidence_locator")
    ):
        stage = "PROSPECT_UNVERIFIED_MACHINE_IMPORT"
    else:
        stage = "DISCOVERY_CANDIDATE"

    capability_verified = bool(
        _text(seller_capability, "validation_status").upper() == "VERIFIED"
        and _text(seller_capability, "seller_identity")
        and _text(seller_capability, "model_id")
        and _text(seller_capability, "model_evidence_locator")
    )
    return {
        "schema": "cbi.machinery-customs-buyer-evidence.v6.4",
        "stage": stage,
        "classification_status": "NATIONAL_TARIFF_SOURCE_BOUND" if national_verified
                                 else ("HS6_CANDIDATE_ONLY" if valid_hs else "UNCLASSIFIED"),
        "hs6_candidate": code if valid_hs else None,
        "national_tariff_verified_as_source_claim": national_verified,
        "shipment_supported": shipment_supported,
        "shipment_provenance_structurally_complete": shipment_supported,
        "actual_import_independently_verified": False,
        "independent_source_check_required": True,
        "import_provenance_type": _text(shipment, "source_type").upper() if direct_source else None,
        "ultimate_buyer_supported": ultimate_buyer_supported,
        "ultimate_buyer_independently_verified": False,
        "machine_identity_supported": exact_machine,
        "seller_capability_supported_for_model": capability_verified,
        "seller_capability_independently_verified": False,
        "commercial_value_grade": None,
        "outreach_readiness": "SEPARATE_ROUTE_AUDIT_REQUIRED",
        "negative_trade_index_proves_no_purchase": False,
        "hs_only_proves_machine_purchase": False,
        "missing_contact_rejects_research_candidate": False,
        "blockers": sorted(set(blockers)),
        "persistent_mutation_performed": False,
        "sends_message": False,
    }
