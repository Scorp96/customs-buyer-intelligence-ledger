from __future__ import annotations

from typing import Any

from .adapter_recovery_mapping_v63 import required_production_precedent_tools


def validate_live_phase_b_preconditions(
    health: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    health = dict(health or {})
    contract = dict(contract or {})
    blockers: list[str] = []

    if health.get("status") != "READY":
        blockers.append("LIVE_RUNTIME_NOT_READY")

    v62_present = isinstance(contract.get("research_orchestration_v6_2"), dict)
    if not v62_present:
        blockers.append("V62_LIVE_CONTRACT_NOT_PRESENT")

    wal = dict(health.get("mutation_wal") or {})
    prepared_count = int(wal.get("prepared_count") or 0)
    reconciliation_required = bool(wal.get("reconciliation_required"))
    unreconciled = {str(v) for v in wal.get("unreconciled_mutation_tools", [])}
    wal_quiescent = prepared_count == 0 and not reconciliation_required and not unreconciled
    if not wal_quiescent:
        blockers.append("PRODUCTION_WAL_NOT_QUIESCENT")

    exact_complete = bool(wal.get("exact_automatic_reconciliation_complete"))
    if not exact_complete:
        blockers.append("EXACT_AUTOMATIC_RECONCILIATION_INCOMPLETE")
    if bool(wal.get("automatic_reexecution_of_unproven_prepared")):
        blockers.append("UNPROVEN_PREPARED_REPLAY_NOT_FAIL_CLOSED")

    required = set(required_production_precedent_tools())
    guarded = {str(v) for v in wal.get("guarded_mutation_tools", [])}
    automatic = {str(v) for v in wal.get("automatic_reconciliation_tools", [])}
    missing_precedents = sorted(required - (guarded & automatic))
    recovery_precedents_ready = not missing_precedents
    if missing_precedents:
        blockers.append("RECOVERY_PRECEDENTS_INCOMPLETE")

    health_corr = dict(health.get("mutation_event_correlation") or {})
    prod_wal_contract = dict(contract.get("production_adapter_mutation_wal") or {})
    contract_corr = dict(prod_wal_contract.get("durable_event_correlation") or {})
    correlation_safe = bool(
        health_corr.get("status") == "ENABLED"
        and not health_corr.get("correlation_contains_raw_idempotency_key")
        and contract_corr.get("enabled") is True
        and contract_corr.get("correlation_contains_raw_idempotency_key") is False
        and contract_corr.get("correlation_alone_authorizes_replay") is False
    )
    if not correlation_safe:
        blockers.append("MUTATION_CORRELATION_POLICY_UNSAFE")

    if prod_wal_contract.get("prepared_auto_replay_without_proof") is not False:
        blockers.append("UNPROVEN_PREPARED_REPLAY_NOT_FAIL_CLOSED")
    if prod_wal_contract.get("automatic_reconciliation_requires_durable_proof") is not True:
        blockers.append("DURABLE_PROOF_REQUIREMENT_NOT_CONFIRMED")
    if prod_wal_contract.get("exact_automatic_reconciliation_complete") is not True:
        blockers.append("CONTRACT_EXACT_RECONCILIATION_INCOMPLETE")

    health_peer = dict(health.get("peer_pivot_lifecycle_recovery") or {})
    contract_peer = dict(prod_wal_contract.get("peer_pivot_lifecycle_recovery") or {})
    peer_precedent_safe = bool(
        health_peer.get("status") == "ENABLED"
        and {"append_peer_discovery", "promote_anchor"}
        <= {str(v) for v in health_peer.get("automatic_reconciliation_tools", [])}
        and health_peer.get("requires_event_correlation") is True
        and contract_peer.get("enabled") is True
        and {"append_peer_discovery", "promote_anchor"}
        <= {str(v) for v in contract_peer.get("tools", [])}
        and contract_peer.get("requires_exact_event_correlation") is True
        and contract_peer.get("reexecutes_side_effect") is False
    )
    if not peer_precedent_safe:
        blockers.append("PEER_LIFECYCLE_RECOVERY_PRECEDENT_UNSAFE")

    # Keep diagnostics stable and deduplicated while preserving first-failure order.
    blockers = list(dict.fromkeys(blockers))
    ready = not blockers
    return {
        "runtime_version_reported": health.get("runtime_version"),
        "runtime_build_id_reported": health.get("build_id"),
        "v62_live_contract_present": v62_present,
        "wal_quiescent": wal_quiescent,
        "prepared_count": prepared_count,
        "unreconciled_mutation_tools": sorted(unreconciled),
        "exact_automatic_reconciliation_complete": exact_complete,
        "recovery_precedents_ready": recovery_precedents_ready,
        "required_precedent_tools": sorted(required),
        "missing_precedent_tools": missing_precedents,
        "mutation_correlation_safe": correlation_safe,
        "peer_lifecycle_recovery_precedent_safe": peer_precedent_safe,
        "ready_for_v63_phase_b_live": ready,
        "version_string_is_release_authority": False,
        "blockers": blockers,
    }
