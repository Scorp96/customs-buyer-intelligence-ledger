from __future__ import annotations

import copy
from typing import Any

from .opportunity_domain import validate_product_opportunity
from .recovery_semantics_v63 import snapshot_sha256
from .wal_contract_v63 import V63_WAL_BINDINGS, validate_v63_durable_event_proof


def _validated_create_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    proof = validate_v63_durable_event_proof(V63_WAL_BINDINGS["create_product_opportunity"], event)
    if not proof["valid"]:
        raise RuntimeError("V63_PRODUCT_OPPORTUNITY_CREATE_EVENT_INVALID:" + ",".join(proof["blockers"]))
    snapshot = copy.deepcopy(event.get("result_snapshot"))
    if not isinstance(snapshot, dict):
        raise RuntimeError("V63_PRODUCT_OPPORTUNITY_CREATE_SNAPSHOT_INVALID")
    expected = str(event.get("result_snapshot_sha256") or "").lower()
    actual = snapshot_sha256(snapshot).lower()
    if expected != actual:
        raise RuntimeError("V63_PRODUCT_OPPORTUNITY_CREATE_SNAPSHOT_HASH_MISMATCH")
    required = ("opportunity_id", "account_id", "product_profile_id")
    missing = [name for name in required if not str(snapshot.get(name) or "").strip()]
    if missing:
        raise RuntimeError("V63_PRODUCT_OPPORTUNITY_CREATE_SNAPSHOT_MISSING:" + ",".join(missing))
    row = validate_product_opportunity({
        **snapshot,
        "lifecycle_stage": str(snapshot.get("stage") or snapshot.get("lifecycle_stage") or "OPPORTUNITY_CREATED").upper(),
    })
    row["stage"] = row["lifecycle_stage"]
    row["projection_create_correlation_id"] = str(event.get("correlation_id") or "")
    row["projection_source"] = "V63_PRODUCT_OPPORTUNITY_CREATED"
    if str(event.get("investigation_id") or "").strip():
        row["investigation_id"] = str(event.get("investigation_id")).strip()
    return row


def _apply_promotion(row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    proof = validate_v63_durable_event_proof(V63_WAL_BINDINGS["promote_opportunity_anchor"], event)
    if not proof["valid"]:
        raise RuntimeError("V63_OPPORTUNITY_ANCHOR_PROMOTION_EVENT_INVALID:" + ",".join(proof["blockers"]))
    result = copy.deepcopy(row)
    result["stage"] = "PROMOTED_ANCHOR"
    result["lifecycle_stage"] = "PROMOTED_ANCHOR"
    result["anchor_id"] = str(event.get("anchor_id") or "")
    result["promotion_reason"] = str(event.get("promotion_reason") or "")
    result["anchor_eligibility_snapshot"] = copy.deepcopy(event.get("anchor_eligibility_snapshot") or {})
    result["cycle_dedup_snapshot"] = copy.deepcopy(event.get("cycle_dedup_snapshot") or {})
    result["projection_promotion_correlation_id"] = str(event.get("correlation_id") or "")
    return result


def project_product_opportunities(
    durable_events: list[dict[str, Any]],
    *,
    account_id: str | None = None,
    opportunity_id: str | None = None,
    product_profile_id: str | None = None,
) -> dict[str, Any]:
    opportunities: dict[str, dict[str, Any]] = {}
    promotions: list[dict[str, Any]] = []

    for raw in durable_events or []:
        if not isinstance(raw, dict):
            continue
        event_type = str(raw.get("event_type") or "")
        if event_type == "V63_PRODUCT_OPPORTUNITY_CREATED":
            row = _validated_create_snapshot(raw)
            key = str(row["opportunity_id"])
            if key in opportunities:
                raise RuntimeError("V63_DUPLICATE_PRODUCT_OPPORTUNITY_CREATE_EVENT:" + key)
            opportunities[key] = row
        elif event_type == "V63_OPPORTUNITY_ANCHOR_PROMOTED":
            promotions.append(copy.deepcopy(raw))

    for event in promotions:
        key = str(event.get("opportunity_id") or "")
        if not key or key not in opportunities:
            raise RuntimeError("V63_ANCHOR_PROMOTION_WITHOUT_CREATED_OPPORTUNITY:" + key)
        event_inv = str(event.get("investigation_id") or "").strip()
        row_inv = str(opportunities[key].get("investigation_id") or "").strip()
        if event_inv and row_inv and event_inv != row_inv:
            raise RuntimeError("V63_ANCHOR_PROMOTION_INVESTIGATION_MISMATCH:" + key)
        opportunities[key] = _apply_promotion(opportunities[key], event)

    rows = list(opportunities.values())
    if account_id:
        wanted = str(account_id)
        rows = [row for row in rows if str(row.get("account_id") or "") == wanted]
    if opportunity_id:
        wanted = str(opportunity_id)
        rows = [row for row in rows if str(row.get("opportunity_id") or "") == wanted]
    if product_profile_id:
        wanted = str(product_profile_id).upper()
        rows = [row for row in rows if str(row.get("product_profile_id") or "").upper() == wanted]

    rows.sort(key=lambda row: (str(row.get("account_id") or ""), str(row.get("opportunity_id") or "")))
    return {
        "status": "READY",
        "opportunities": rows,
        "projected_opportunity_count": len(rows),
        "projection_source": "EXISTING_APPEND_ONLY_INVESTIGATION_EVENT_CHAIN",
        "projection_rewrites_history": False,
        "persistent_mutation_performed": False,
    }
