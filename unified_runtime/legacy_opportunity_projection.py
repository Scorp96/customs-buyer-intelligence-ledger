"""Read-only projection of v6.1 evidence into the v6.3 opportunity model.

This module deliberately does not append events, create anchors, or rewrite the
v6.1 event chain.  A projected row is an input for a later v6.3 requalification
step only; it is never durable opportunity authority.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from .demand_market import is_direct_procurement_source
from .opportunity_domain import build_opportunity_id, validate_product_opportunity
from .product_profiles import get_product_profile, list_product_profiles


BRIDGE_SCHEMA = "cbi.v61-to-v63-evidence-bridge.v1"
_PRODUCT_CLAIM = "product.fit"
_PROCUREMENT_CLAIMS = {"trade.import_activity", "commercial.procurement_need"}
_DIRECT_SOURCE_CATEGORIES = {
    "CUSTOMS",
    "TRADE_DATA",
    "SUPPLIER_BUYER_SHIPMENT",
    "PURCHASE_ORDER",
    "INVOICE",
}


def _source_categories(row: dict[str, Any]) -> set[str]:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    labels = [
        str(source.get(key) or "").strip().upper().replace("-", "_").replace(" ", "_")
        for key in ("source_type", "source_family")
    ]
    categories = {
        label
        for label in labels
        if is_direct_procurement_source(label)
    }
    if "TRADEDATA" in labels:
        categories.add("TRADE_DATA")
    if any(label in {"BILL_OF_LADING", "BOL"} for label in labels):
        categories.add("SUPPLIER_BUYER_SHIPMENT")
    if not categories:
        source_type = labels[0]
        if source_type:
            categories.add(source_type)
    return categories


def _positive_account_observations(state: dict[str, Any], account_id: str) -> list[dict[str, Any]]:
    observations = state.get("observations")
    if not isinstance(observations, dict):
        return []
    rows: list[dict[str, Any]] = []
    for raw in observations.values():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("result") or "").upper() != "POSITIVE":
            continue
        if str(raw.get("owner_type") or "").upper() != "ACCOUNT":
            continue
        if str(raw.get("owner_id") or "") != account_id:
            continue
        if not str(raw.get("evidence_id") or "").strip():
            continue
        rows.append(copy.deepcopy(raw))
    return rows


def project_legacy_v61_opportunities(
    state: dict[str, Any],
    *,
    evidence_matches_profile: Callable[[dict[str, Any], str], bool],
    source_categories: Callable[[dict[str, Any]], set[str]] | None = None,
    account_id: str | None = None,
    opportunity_id: str | None = None,
    product_profile_id: str | None = None,
) -> dict[str, Any]:
    """Project sufficiently evidenced v6.1 claims into read-only v6.3 rows.

    The bridge requires positive product-fit evidence and at least one positive
    procurement claim whose persisted source is a direct procurement category.
    Product identity is accepted only when the caller's evidence matcher can
    bind the evidence to one known profile.  Ambiguous or unsupported inputs are
    reported as blockers and produce no opportunity row.
    """

    start = state.get("start") if isinstance(state, dict) else None
    account = start.get("account") if isinstance(start, dict) else None
    account_value = str((account or {}).get("account_id") or "").strip()
    wanted_account = str(account_id or "").strip()
    if wanted_account and account_value != wanted_account:
        return {
            "schema": BRIDGE_SCHEMA,
            "status": "NOT_APPLICABLE",
            "investigation_id": str((start or {}).get("investigation_id") or "").strip(),
            "opportunities": [],
            "projected_opportunity_count": 0,
            "blockers": [],
            "projection_read_only": True,
            "durable_event_present": False,
            "persistent_mutation_performed": False,
        }
    if not account_value:
        return {
            "schema": BRIDGE_SCHEMA,
            "status": "BLOCKED",
            "investigation_id": str((start or {}).get("investigation_id") or "").strip(),
            "opportunities": [],
            "projected_opportunity_count": 0,
            "blockers": ["LEGACY_ACCOUNT_ID_MISSING"],
            "projection_read_only": True,
            "durable_event_present": False,
            "persistent_mutation_performed": False,
        }

    investigation_value = str(
        (start or {}).get("investigation_id")
        or state.get("investigation_id")
        or ""
    ).strip()
    rows = _positive_account_observations(state, account_value)
    categories_for = source_categories or _source_categories
    requested_profile = str(product_profile_id or "").strip().upper()
    profile_ids = [
        str(profile.get("profile_id") or "").strip().upper()
        for profile in list_product_profiles()
        if str(profile.get("profile_id") or "").strip()
        and (not requested_profile or str(profile.get("profile_id") or "").strip().upper() == requested_profile)
    ]
    blockers: set[str] = set()
    opportunities: list[dict[str, Any]] = []

    product_rows = [row for row in rows if str(row.get("claim_key") or "") == _PRODUCT_CLAIM]
    if not product_rows:
        blockers.add("LEGACY_PRODUCT_FIT_EVIDENCE_MISSING")

    for profile_id in profile_ids:
        profile_product_rows = [
            row for row in product_rows
            if evidence_matches_profile(row, profile_id)
        ]
        procurement_rows = [
            row for row in rows
            if str(row.get("claim_key") or "") in _PROCUREMENT_CLAIMS
            and evidence_matches_profile(row, profile_id)
            and bool(set(categories_for(row)) & _DIRECT_SOURCE_CATEGORIES)
        ]
        if not profile_product_rows:
            continue
        if not procurement_rows:
            blockers.add("LEGACY_DIRECT_PROCUREMENT_EVIDENCE_MISSING")
            continue

        profile = get_product_profile(profile_id)
        # Keep duplicate legacy investigations distinguishable until the
        # separate canonical-reconciliation phase resolves their identity.
        projected_id = build_opportunity_id(
            account_value,
            profile_id,
            f"LEGACY_BRIDGE_{investigation_value or 'UNKNOWN'}",
        )
        if opportunity_id and projected_id != str(opportunity_id).strip():
            continue
        product_evidence_ids = sorted({str(row["evidence_id"]).strip() for row in profile_product_rows})
        procurement_evidence_ids = sorted({str(row["evidence_id"]).strip() for row in procurement_rows})
        all_evidence_ids = sorted(set(product_evidence_ids) | set(procurement_evidence_ids))
        payload = validate_product_opportunity({
            "opportunity_id": projected_id,
            "account_id": account_value,
            "product_profile_id": profile_id,
            "product_profile_version": profile["profile_version"],
            "product_profile_sha256": profile["profile_sha256"],
            "lifecycle_stage": "DISCOVERED",
        })
        payload.update({
            "stage": "DISCOVERED",
            "investigation_id": investigation_value,
            "projection_source": "V61_LEGACY_EVIDENCE_PROJECTION",
            "projection_read_only": True,
            "durable_event_present": False,
            "requires_v63_requalification": True,
            "legacy_bridge_schema": BRIDGE_SCHEMA,
            "legacy_projection_discriminator": f"LEGACY_BRIDGE_{investigation_value or 'UNKNOWN'}",
            "legacy_claim_keys": [_PRODUCT_CLAIM, "trade.import_activity", "commercial.procurement_need"],
            "product_evidence_ids": product_evidence_ids,
            "procurement_evidence_ids": procurement_evidence_ids,
            "commercial_evidence_ids": all_evidence_ids,
            "source_observation_ids": sorted({
                str(row.get("observation_id") or "").strip()
                for row in profile_product_rows + procurement_rows
                if str(row.get("observation_id") or "").strip()
            }),
            "bridge_blockers": [],
            "derived_from_existing_evidence": True,
            "projection_rewrites_history": False,
            "persistent_mutation_performed": False,
        })
        opportunities.append(payload)

    if not opportunities and not product_rows:
        blockers.add("LEGACY_PRODUCT_PROFILE_UNRESOLVED")
    elif not opportunities and product_rows and not any(
        evidence_matches_profile(row, profile_id)
        for row in product_rows
        for profile_id in profile_ids
    ):
        blockers.add("LEGACY_PRODUCT_PROFILE_UNRESOLVED")
    if requested_profile and not profile_ids:
        blockers.add("LEGACY_PRODUCT_PROFILE_UNKNOWN")

    status = "PROJECTED" if opportunities else ("BLOCKED" if blockers else "NOT_APPLICABLE")
    return {
        "schema": BRIDGE_SCHEMA,
        "status": status,
        "investigation_id": investigation_value,
        "account_id": account_value,
        "opportunities": opportunities,
        "projected_opportunity_count": len(opportunities),
        "blockers": sorted(blockers),
        "projection_read_only": True,
        "durable_event_present": False,
        "projection_rewrites_history": False,
        "persistent_mutation_performed": False,
    }
