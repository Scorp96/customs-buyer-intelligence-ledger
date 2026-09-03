from __future__ import annotations

from typing import Any

from .adapter_recovery_mapping_v63 import V63_PRODUCTION_RECOVERY_MAPPINGS
from .live_contract_validator_v63 import validate_live_phase_b_preconditions


_REQUIRED_MUTATIONS = {
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
}


def evaluate_v63_production_gate(payload: dict[str, Any]) -> dict[str, Any]:
    health = dict(payload.get("health") or {})
    contract = dict(payload.get("contract") or {})
    wal = dict(health.get("mutation_wal") or {})
    blockers: list[str] = []

    live_phase_b = validate_live_phase_b_preconditions(health, contract)
    if not live_phase_b.get("ready_for_v63_phase_b_live"):
        blockers.append("LIVE_PHASE_B_PRECONDITIONS_FAILED")

    if not isinstance(contract.get("research_orchestration_v6_2"), dict):
        blockers.append("V62_ORCHESTRATION_NOT_LIVE")

    v63 = contract.get("demand_expansion_v6_3")
    if not isinstance(v63, dict):
        blockers.append("V63_DEMAND_EXPANSION_NOT_LIVE")
        v63 = {}

    if int(wal.get("prepared_count") or 0) != 0:
        blockers.append("MUTATION_WAL_PREPARED_INTENTS")
    if bool(wal.get("reconciliation_required")):
        blockers.append("MUTATION_WAL_RECONCILIATION_REQUIRED")

    guarded = {str(v) for v in (wal.get("guarded_mutation_tools") or [])}
    if not _REQUIRED_MUTATIONS.issubset(guarded):
        blockers.append("V63_MUTATION_WAL_INVENTORY_INCOMPLETE")

    automatic = {str(v) for v in (wal.get("automatic_reconciliation_tools") or [])}
    if not _REQUIRED_MUTATIONS.issubset(automatic):
        blockers.append("V63_AUTOMATIC_RECONCILIATION_INVENTORY_INCOMPLETE")

    unreconciled = {str(v) for v in (wal.get("unreconciled_mutation_tools") or [])}
    if _REQUIRED_MUTATIONS & unreconciled:
        blockers.append("V63_MUTATION_RECONCILIATION_INCOMPLETE")
    if not bool(wal.get("exact_automatic_reconciliation_complete")):
        blockers.append("EXACT_AUTOMATIC_RECONCILIATION_INCOMPLETE")

    if str(v63.get("runtime_overlay_mutation_binding") or "") != "BOUND_EXISTING_PRODUCTION_WAL":
        blockers.append("V63_PRODUCTION_WAL_NOT_BOUND")

    if str(v63.get("recovery_overlay_binding") or "") != "BOUND_ACTIVE_PRODUCTION_OVERLAY_CHAIN":
        blockers.append("V63_RECOVERY_OVERLAY_NOT_BOUND")

    if str(v63.get("runtime_durable_backend_binding") or "") != "BOUND_EXISTING_DURABLE_STORE":
        blockers.append("V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND")
    backend_policy_safe = (
        str(v63.get("runtime_durable_backend_schema") or "") == "cbi.v63-production-durable-backend.v1"
        and v63.get("runtime_durable_backend_parallel_store_allowed") is False
        and v63.get("runtime_durable_backend_requires_existing_mutation_correlation") is True
        and v63.get("runtime_durable_backend_raw_idempotency_key_persisted") is False
        and v63.get("runtime_durable_backend_side_effect_reexecution_allowed") is False
    )
    if not backend_policy_safe:
        blockers.append("V63_RUNTIME_DURABLE_BACKEND_POLICY_UNSAFE")

    v63_wal = dict(v63.get("mutation_wal_v6_3") or {})
    if v63_wal.get("binding_strategy") != "EXTEND_EXISTING_PRODUCTION_WAL":
        blockers.append("V63_WAL_BINDING_STRATEGY_UNPROVEN")
    if bool(v63_wal.get("parallel_wal_allowed", True)):
        blockers.append("PARALLEL_WAL_NOT_ALLOWED")

    recovery_mapping = dict(v63.get("production_recovery_mapping_v6_3") or {})
    if set(recovery_mapping) != _REQUIRED_MUTATIONS:
        blockers.append("V63_PRODUCTION_RECOVERY_MAPPING_INCOMPLETE")
    else:
        invalid_mapping = False
        for tool in sorted(_REQUIRED_MUTATIONS):
            expected = V63_PRODUCTION_RECOVERY_MAPPINGS[tool]
            actual = dict(recovery_mapping.get(tool) or {})
            if actual.get("recovery_family") != expected.get("recovery_family"):
                invalid_mapping = True
                break
        if invalid_mapping:
            blockers.append("V63_PRODUCTION_RECOVERY_MAPPING_INVALID")

    if not bool(payload.get("render_deploy_verified")):
        blockers.append("RENDER_DEPLOY_NOT_VERIFIED")
    if not bool(payload.get("r2_restore_verified")):
        blockers.append("R2_RESTORE_NOT_VERIFIED")
    if not bool(payload.get("real_pvc_acceptance_verified")):
        blockers.append("REAL_PVC_ACCEPTANCE_NOT_VERIFIED")

    if not bool(payload.get("exact_v63_recovery_acceptance_verified")):
        blockers.append("V63_EXACT_RECOVERY_ACCEPTANCE_NOT_VERIFIED")
    if not bool(payload.get("live_v63_backend_correlation_acceptance_verified")):
        blockers.append("V63_LIVE_BACKEND_CORRELATION_ACCEPTANCE_NOT_VERIFIED")
    if not bool(payload.get("live_v63_recovery_overlay_acceptance_verified")):
        blockers.append("V63_LIVE_RECOVERY_OVERLAY_ACCEPTANCE_NOT_VERIFIED")
    acceptance_snapshot = str(payload.get("live_v63_backend_correlation_acceptance_snapshot_sha256") or "").lower()
    recovery_acceptance_snapshot = str(payload.get("live_v63_recovery_overlay_acceptance_snapshot_sha256") or "").lower()
    current_snapshot = str(payload.get("current_production_source_snapshot_sha256") or "").lower()
    if (
        len(acceptance_snapshot) != 64
        or len(current_snapshot) != 64
        or acceptance_snapshot != current_snapshot
    ):
        blockers.append("V63_BACKEND_CORRELATION_ACCEPTANCE_SOURCE_DRIFT")
    if (
        len(recovery_acceptance_snapshot) != 64
        or len(current_snapshot) != 64
        or recovery_acceptance_snapshot != current_snapshot
    ):
        blockers.append("V63_RECOVERY_OVERLAY_ACCEPTANCE_SOURCE_DRIFT")

    return {
        "production_ready": not blockers,
        "status": "PRODUCTION_READY" if not blockers else "NOT_PRODUCTION_READY",
        "blockers": blockers,
        "required_v63_mutations": sorted(_REQUIRED_MUTATIONS),
        "checked_render_deploy": bool(payload.get("render_deploy_verified")),
        "checked_r2_restore": bool(payload.get("r2_restore_verified")),
        "checked_real_pvc_acceptance": bool(payload.get("real_pvc_acceptance_verified")),
        "checked_exact_v63_recovery_acceptance": bool(payload.get("exact_v63_recovery_acceptance_verified")),
        "checked_live_v63_backend_correlation_acceptance": bool(payload.get("live_v63_backend_correlation_acceptance_verified")),
        "checked_live_v63_recovery_overlay_acceptance": bool(payload.get("live_v63_recovery_overlay_acceptance_verified")),
        "live_backend_correlation_acceptance_snapshot_sha256": acceptance_snapshot,
        "live_recovery_overlay_acceptance_snapshot_sha256": recovery_acceptance_snapshot,
        "current_production_source_snapshot_sha256": current_snapshot,
        "live_phase_b_ready": bool(live_phase_b.get("ready_for_v63_phase_b_live")),
        "live_phase_b_blockers": list(live_phase_b.get("blockers") or []),
        "live_phase_b_diagnostics": live_phase_b,
    }
