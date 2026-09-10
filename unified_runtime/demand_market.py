from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from .product_profiles import get_product_profile


_DIRECT_PROCUREMENT_SOURCES = {
    "CUSTOMS",
    "TRADE_DATA",
    "SUPPLIER_BUYER_SHIPMENT",
    "PURCHASE_ORDER",
    "INVOICE",
}


def _canonical_hash(payload: dict[str, Any], prefix: str) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:20].upper()}"


def derive_demand_anchor(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("demand anchor payload must be an object")
    required = ("account_id", "opportunity_id", "source_type", "source_evidence_ids", "product_profile_id", "geography")
    missing = [k for k in required if payload.get(k) in (None, "", [])]
    if missing:
        raise ValueError("missing demand anchor fields: " + ", ".join(missing))
    profile_id = str(payload["product_profile_id"]).upper()
    get_product_profile(profile_id)
    source_type = str(payload["source_type"]).upper()
    evidence_ids = sorted({str(x) for x in payload.get("source_evidence_ids", []) if str(x).strip()})
    if not evidence_ids:
        raise ValueError("source_evidence_ids must contain at least one evidence id")
    normalized = {
        "account_id": str(payload["account_id"]),
        "opportunity_id": str(payload["opportunity_id"]),
        "source_type": source_type,
        "source_evidence_ids": evidence_ids,
        "shipment_date": payload.get("shipment_date"),
        "shipment_weight_kg": payload.get("shipment_weight_kg"),
        "shipment_quantity": payload.get("shipment_quantity"),
        "container_or_teu": payload.get("container_or_teu"),
        "product_profile_id": profile_id,
        "product_variant": payload.get("product_variant"),
        "geography": str(payload["geography"]),
        "destination_port": payload.get("destination_port"),
        "supplier_ids": sorted({str(x) for x in payload.get("supplier_ids", []) if str(x).strip()}),
        "origin_country": payload.get("origin_country"),
        "application_hypothesis": sorted({str(x) for x in payload.get("application_hypothesis", []) if str(x).strip()}),
        "application_confidence": payload.get("application_confidence"),
        "procurement_proven": source_type in _DIRECT_PROCUREMENT_SOURCES,
        "channel_signal": bool(payload.get("channel_signal", False)),
        "supplier_signal": bool(payload.get("supplier_signal", bool(payload.get("supplier_ids")))),
    }
    identity = {
        "account_id": normalized["account_id"],
        "opportunity_id": normalized["opportunity_id"],
        "source_type": normalized["source_type"],
        "source_evidence_ids": normalized["source_evidence_ids"],
        "shipment_date": normalized["shipment_date"],
        "product_profile_id": normalized["product_profile_id"],
        "geography": normalized["geography"],
    }
    normalized["demand_anchor_id"] = _canonical_hash(identity, "DA")
    return normalized


def derive_market_cell(
    anchor: dict[str, Any],
    application_ids: list[str],
    buyer_archetype_ids: list[str],
    channel: str | None = None,
) -> dict[str, Any]:
    for field in ("geography", "product_profile_id"):
        if not anchor.get(field):
            raise ValueError(f"anchor missing {field}")
    payload = {
        "geography": str(anchor["geography"]),
        "product_profile_id": str(anchor["product_profile_id"]).upper(),
        "application_ids": sorted({str(x).upper() for x in application_ids if str(x).strip()}),
        "buyer_archetype_ids": sorted({str(x).upper() for x in buyer_archetype_ids if str(x).strip()}),
        "channel": str(channel or "UNSPECIFIED").upper(),
    }
    return {"market_cell_id": _canonical_hash(payload, "MC"), **payload}


def _unique_procurement_events(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for signal in signals:
        if not isinstance(signal, dict) or not signal.get("procurement_proven"):
            continue
        evidence_ids = tuple(sorted(str(x) for x in signal.get("source_evidence_ids", []) if str(x).strip()))
        event_key = json.dumps(
            {
                "account_id": signal.get("account_id"),
                "source_type": signal.get("source_type"),
                "evidence_ids": evidence_ids,
                "shipment_date": signal.get("shipment_date"),
                "opportunity_id": signal.get("opportunity_id"),
            },
            sort_keys=True,
            default=str,
        )
        unique[event_key] = signal
    return list(unique.values())


def evaluate_market_acceptance(signals: list[dict[str, Any]]) -> dict[str, Any]:
    events = _unique_procurement_events(signals)
    if not events:
        return {
            "level": "M0",
            "canonical_buyer_count": 0,
            "procurement_event_count": 0,
            "reason": "NO_VERIFIED_PROCUREMENT",
        }

    buyer_counts = Counter(str(row.get("account_id")) for row in events if row.get("account_id"))
    buyer_count = len(buyer_counts)
    repeated_buyer = any(count >= 2 for count in buyer_counts.values())
    supplier_networks = {
        supplier
        for row in events
        for supplier in row.get("supplier_ids", [])
        if supplier
    }
    channel_count = sum(1 for row in events if row.get("channel_signal"))
    supplier_signal_count = sum(1 for row in events if row.get("supplier_signal"))

    # Conservative escalation: direct multi-buyer demand is M3; M4/M5 need additional
    # independent supply/channel density and do not arise from shipment count alone.
    if buyer_count >= 4 and len(supplier_networks) >= 3 and channel_count >= 2 and len(events) >= 8:
        level = "M5"
        reason = "DENSE_MULTI_BUYER_MULTI_SUPPLIER_CHANNEL_MARKET"
    elif buyer_count >= 3 and (len(supplier_networks) >= 2 or supplier_signal_count >= 2) and len(events) >= 4:
        level = "M4"
        reason = "ESTABLISHED_MULTI_BUYER_SUPPLY_MARKET"
    elif buyer_count >= 2:
        level = "M3"
        reason = "MULTI_BUYER_VERIFIED_DEMAND"
    elif repeated_buyer:
        level = "M2"
        reason = "REPEATED_SINGLE_BUYER_VERIFIED_DEMAND"
    else:
        level = "M1"
        reason = "SINGLE_CONFIRMED_DEMAND"

    return {
        "level": level,
        "canonical_buyer_count": buyer_count,
        "procurement_event_count": len(events),
        "supplier_network_count": len(supplier_networks),
        "reason": reason,
    }
