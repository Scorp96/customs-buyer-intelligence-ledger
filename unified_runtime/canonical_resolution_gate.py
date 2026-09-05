from __future__ import annotations

from typing import Any


_ALLOWED_AUTHORITIES = {
    "EXACT_ACCOUNT_ID",
    "TAX_ID",
    "EXTERNAL_ID",
    "PRIMARY_LEGAL_NAME_COUNTRY",
    "EXPLICIT_NEW_ID",
}
_ALLOWED_STATUSES = {"CONFIRMED", "CREATED"}


def validate_canonical_resolution_proof(proof: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(proof, dict):
        raise ValueError("canonical resolution proof must be an object")

    status = str(proof.get("canonical_status") or "").strip().upper()
    account_id = str(proof.get("canonical_account_id") or "").strip()
    authority = str(proof.get("resolver_authority") or "").strip().upper()
    blockers: list[str] = []

    if not bool(proof.get("resolver_is_existing_production_authority")):
        blockers.append("PRODUCTION_CANONICAL_AUTHORITY_NOT_PROVEN")
    if status == "AMBIGUOUS" or bool(proof.get("ambiguous")):
        blockers.append("CANONICAL_RESOLUTION_AMBIGUOUS")
    elif status not in _ALLOWED_STATUSES:
        blockers.append("CANONICAL_STATUS_NOT_CONFIRMED")
    if not account_id:
        blockers.append("CANONICAL_ACCOUNT_ID_MISSING")
    if authority not in _ALLOWED_AUTHORITIES:
        blockers.append("RESOLUTION_AUTHORITY_NOT_ALLOWED")
    if bool(proof.get("address_only_match")):
        blockers.append("ADDRESS_ONLY_MATCH_FORBIDDEN")
    if bool(proof.get("alias_only_match")):
        blockers.append("ALIAS_ONLY_MATCH_FORBIDDEN")
    if bool(proof.get("tax_conflict")):
        blockers.append("TAX_ID_CONFLICT")
    if bool(proof.get("country_conflict")):
        blockers.append("COUNTRY_CONFLICT")

    return {
        "canonical_status": status or None,
        "canonical_account_id": account_id or None,
        "resolver_authority": authority or None,
        "opportunity_creation_allowed": not blockers,
        "existing_production_canonical_registry_is_authority": True,
        "address_only_match_allowed": False,
        "alias_only_match_allowed": False,
        "automatic_fuzzy_merge_allowed": False,
        "blockers": blockers,
    }
