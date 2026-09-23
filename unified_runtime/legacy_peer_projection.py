from __future__ import annotations

import math
from typing import Any

from .candidate_research_gate import assess_candidate_researchability
from .product_profiles import get_product_profile


_ALLOWED_SOURCE_EVENT = "PEER_RECEIPT_APPENDED"
_DISCOVERED = "DISCOVERED_LEGACY_SIGNAL"
_ANCHOR_ELIGIBLE = "ANCHOR_ELIGIBLE_LEGACY_SIGNAL"


def _nonempty_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _evidence_ids(payload: dict[str, Any], direct_key: str, section_key: str) -> list[str]:
    direct = payload.get(direct_key)
    if isinstance(direct, (list, tuple, set)):
        values = direct
    else:
        section = payload.get(section_key)
        values = section.get("evidence_ids") if isinstance(section, dict) else []
    return sorted({str(value).strip() for value in values or [] if str(value).strip()})


def _legacy_candidate_projection(payload: dict[str, Any], peer_id: str) -> dict[str, Any]:
    """Build a bounded candidate read model from explicit legacy receipt facts.

    A Peer receipt is not a v6 candidate authority.  This helper therefore only
    exposes a research signal when the receipt explicitly carries a product
    profile and both product/procurement evidence references.  It never guesses
    a profile, EIV, canonical identity, or current procurement state.
    """
    profile_id = str(payload.get("product_profile_id") or "").strip().upper()
    product_ids = _evidence_ids(payload, "product_evidence_ids", "product")
    procurement_ids = _evidence_ids(payload, "procurement_evidence_ids", "trade_business")
    company_name = _nonempty_text(
        payload,
        "company_name",
        "name",
        "legal_name",
        "canonical_name",
        "canonical_key",
    )
    candidate_id = _nonempty_text(payload, "candidate_id") or f"LEGACY_PEER:{peer_id}"
    blockers: list[str] = []
    if not profile_id:
        blockers.append("PRODUCT_PROFILE_ID_MISSING")
    else:
        try:
            get_product_profile(profile_id)
        except KeyError:
            blockers.append("PRODUCT_PROFILE_ID_UNKNOWN")
    if not product_ids:
        blockers.append("PRODUCT_EVIDENCE_MISSING")
    if not procurement_ids:
        blockers.append("PROCUREMENT_EVIDENCE_MISSING")
    if not company_name:
        blockers.append("COMPANY_NAME_MISSING")

    defaulted_fields: list[str] = []
    canonical_status = str(payload.get("canonical_status") or "").strip().upper()
    if not canonical_status:
        canonical_status = "UNRESOLVED"
        defaulted_fields.append("canonical_status=UNRESOLVED_POLICY_DEFAULT")
    signal_tier = str(payload.get("signal_tier") or "").strip().upper()
    if not signal_tier:
        defaulted_fields.append("signal_tier=D4_POLICY_DEFAULT")
        signal_tier = "D4"
    eiv_value = payload.get("eiv")
    if eiv_value in (None, ""):
        eiv = 0.0
        defaulted_fields.append("eiv=0.0_POLICY_DEFAULT")
    else:
        try:
            eiv = float(eiv_value)
        except (TypeError, ValueError):
            blockers.append("EIV_INVALID")
            eiv = 0.0
        if not math.isfinite(eiv) or eiv < 0.0:
            blockers.append("EIV_INVALID")
            eiv = 0.0

    research_payload = {
        "candidate_id": candidate_id,
        "company_name": company_name,
        "product_profile_id": profile_id,
        "signal_tier": signal_tier,
        "eiv": eiv,
        "canonical_status": canonical_status,
        "procurement_proven": payload.get("procurement_proven") is True,
        "product_or_application_signal": (
            payload.get("product_or_application_signal") is True or bool(product_ids)
        ),
        "proven_negative": payload.get("proven_negative") is True,
        "duplicate_proven": payload.get("duplicate_proven") is True,
        "mismatch_proven": payload.get("mismatch_proven") is True,
        "legacy_peer_id": peer_id,
        "source_event": _ALLOWED_SOURCE_EVENT,
        "product_evidence_ids": product_ids,
        "procurement_evidence_ids": procurement_ids,
    }
    if not blockers:
        try:
            assessment = assess_candidate_researchability(research_payload)
        except (KeyError, ValueError):
            blockers.append("CANDIDATE_RESEARCH_GATE_INPUT_INVALID")
        else:
            return {
                "status": "PROJECTED",
                "candidate_id": candidate_id,
                "candidate_researchability": assessment,
                "evidence_ids": sorted(set(product_ids) | set(procurement_ids)),
                "product_evidence_ids": product_ids,
                "procurement_evidence_ids": procurement_ids,
                "defaulted_fields": defaulted_fields,
                "candidate_identity_source": "DERIVED_FROM_LEGACY_PEER_ID",
                "source_event": _ALLOWED_SOURCE_EVENT,
                "projection_is_read_only": True,
                "requires_v63_requalification": True,
                "persistent_mutation_performed": False,
            }

    return {
        "status": "BLOCKED",
        "candidate_id": candidate_id,
        "candidate_researchability": None,
        "evidence_ids": sorted(set(product_ids) | set(procurement_ids)),
        "product_evidence_ids": product_ids,
        "procurement_evidence_ids": procurement_ids,
        "blockers": sorted(set(blockers)),
        "defaulted_fields": defaulted_fields,
        "candidate_identity_source": "DERIVED_FROM_LEGACY_PEER_ID",
        "source_event": _ALLOWED_SOURCE_EVENT,
        "projection_is_read_only": True,
        "requires_v63_requalification": True,
        "persistent_mutation_performed": False,
    }


def project_legacy_peer_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Project a legacy v6.1 peer receipt into a read-only v6.3 compatibility view.

    Legacy peer state can inform discovery/qualification but can never create a
    v6.3 lifecycle mutation or grant recursive anchor authority. A historical
    PROMOTE decision is therefore capped at an anchor-eligible *signal* and must
    be requalified by v6.3 before any real promotion.
    """
    payload = dict(receipt or {})
    source_event = str(payload.get("source_event") or "").strip()
    if source_event != _ALLOWED_SOURCE_EVENT:
        raise ValueError(f"unsupported legacy peer source_event: {source_event!r}")

    peer_id = str(payload.get("peer_id") or "").strip()
    if not peer_id:
        raise ValueError("legacy peer receipt requires peer_id")

    promotion = str(payload.get("promotion_decision") or "").strip().upper()
    canonical = str(payload.get("canonical_status") or "").strip().upper()

    eligible_signal = promotion == "PROMOTE" and canonical == "NEW"
    maximum_stage = _ANCHOR_ELIGIBLE if eligible_signal else _DISCOVERED

    result = {
        "status": "PROJECTED",
        "peer_id": peer_id,
        "source_event": source_event,
        "legacy_promotion_decision": promotion or None,
        "legacy_canonical_status": canonical or None,
        "maximum_stage": maximum_stage,
        "grants_v63_anchor_authority": False,
        "creates_v63_lifecycle_event": False,
        "requires_v63_requalification": True,
        "projection_is_read_only": True,
        "persistent_mutation_performed": False,
    }
    result["candidate_projection"] = _legacy_candidate_projection(payload, peer_id)
    return result
