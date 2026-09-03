from __future__ import annotations

from typing import Any


_ALLOWED_SOURCE_EVENT = "PEER_RECEIPT_APPENDED"
_DISCOVERED = "DISCOVERED_LEGACY_SIGNAL"
_ANCHOR_ELIGIBLE = "ANCHOR_ELIGIBLE_LEGACY_SIGNAL"


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

    return {
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
