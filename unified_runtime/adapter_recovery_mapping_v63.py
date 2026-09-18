from __future__ import annotations

from typing import Any


_BASE = {
    "requires_event_correlation": True,
    "requires_exact_result_snapshot": True,
    "automatic_reexecution_without_proof": False,
    "unproven_prepared_result": "MUTATION_RECONCILIATION_REQUIRED",
    "parallel_wal_allowed": False,
}

V63_PRODUCTION_RECOVERY_MAPPINGS: dict[str, dict[str, Any]] = {
    "append_candidate_discovery": {
        **_BASE,
        "requires_exact_result_snapshot": False,
        "recovery_family": "PEER_PIVOT_LIFECYCLE",
        "production_precedent_tools": ["append_peer_discovery"],
        "event_type": "V63_CANDIDATE_DISCOVERED",
        "candidate_owned_evidence_required": True,
    },
    "create_product_opportunity": {
        **_BASE,
        "recovery_family": "CANONICAL_OPPORTUNITY_CREATE",
        "production_precedent_tools": ["resolve_or_create_account", "append_information_record"],
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "canonical_resolution_proof_required": True,
    },
    "promote_opportunity_anchor": {
        **_BASE,
        "requires_exact_result_snapshot": False,
        "recovery_family": "PEER_PIVOT_LIFECYCLE",
        "production_precedent_tools": ["promote_anchor"],
        "event_type": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
        "anchor_eligibility_snapshot_required": True,
        "cycle_dedup_snapshot_required": True,
    },
}


def required_production_precedent_tools() -> list[str]:
    return sorted({
        tool
        for mapping in V63_PRODUCTION_RECOVERY_MAPPINGS.values()
        for tool in mapping["production_precedent_tools"]
    })


def validate_recovery_precedents(runtime_wal_contract: dict[str, Any]) -> dict[str, Any]:
    guarded = {str(v) for v in runtime_wal_contract.get("guarded_mutation_tools", [])}
    automatic = {str(v) for v in runtime_wal_contract.get("automatic_reconciliation_tools", [])}
    required = set(required_production_precedent_tools())
    available = guarded & automatic
    missing = sorted(required - available)
    return {
        "ready": not missing,
        "required_precedent_tools": sorted(required),
        "available_exact_reconciliation_precedents": sorted(available),
        "missing_precedent_tools": missing,
        "new_v63_durable_mutations": sorted(V63_PRODUCTION_RECOVERY_MAPPINGS),
        "parallel_wal_allowed": False,
    }
