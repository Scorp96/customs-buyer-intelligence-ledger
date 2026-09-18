from __future__ import annotations

from typing import Any

from .recovery_semantics_v63 import (
    canonical_v63_wal_request_sha256,
    recover_prepared_v63_mutation,
    snapshot_sha256,
)


def _case(name: str, condition: bool, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "case": name,
        "passed": bool(condition),
        "status": result.get("status"),
        "blockers": list(result.get("blockers") or []),
        "recovery_action": result.get("recovery_action"),
        "reexecute_side_effect": bool(result.get("reexecute_side_effect", False)),
    }


def run_v63_reference_recovery_acceptance() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    candidate_args = {
        "investigation_id": "INV-ACCEPT",
        "candidate_id": "CAND-001",
        "discovered_from_anchor_id": "ANCHOR-001",
        "branch_group": "APPLICATION_GRAPH",
        "branch": "downstream_manufacturer",
        "company_name": "Example Cabinet Co",
        "product_profile_id": "PVC",
        "idempotency_key": "candidate-key-0001",
    }
    candidate_event = {
        "event_type": "V63_CANDIDATE_DISCOVERED",
        "correlation_id": "CORR-CAND-1",
        "request_sha256": canonical_v63_wal_request_sha256("append_candidate_discovery", candidate_args),
        "candidate_id": "CAND-001",
        "discovered_from_anchor_id": "ANCHOR-001",
        "branch_group": "APPLICATION_GRAPH",
        "branch": "downstream_manufacturer",
        "company_name": "Example Cabinet Co",
        "product_profile_id": "PVC",
        "stage": "DISCOVERED",
        "inherited_anchor_facts": False,
        "raw_idempotency_key_persisted": False,
    }

    r = recover_prepared_v63_mutation(
        "append_candidate_discovery", candidate_args,
        expected_correlation_id="CORR-CAND-1", durable_events=[candidate_event],
    )
    cases.append(_case("candidate_exact_event_recovers", r["status"] == "RECOVERED", r))

    r = recover_prepared_v63_mutation(
        "append_candidate_discovery", candidate_args,
        expected_correlation_id="CORR-CAND-OTHER", durable_events=[candidate_event],
    )
    cases.append(_case("candidate_wrong_correlation_fails_closed", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    second_key_args = dict(candidate_args, idempotency_key="candidate-key-0002")
    r = recover_prepared_v63_mutation(
        "append_candidate_discovery", second_key_args,
        expected_correlation_id="CORR-KEY-2", durable_events=[candidate_event],
    )
    cases.append(_case("same_payload_different_key_cannot_claim", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    wrong_hash = dict(candidate_event, request_sha256="0" * 64)
    r = recover_prepared_v63_mutation(
        "append_candidate_discovery", candidate_args,
        expected_correlation_id="CORR-CAND-1", durable_events=[wrong_hash],
    )
    cases.append(_case("candidate_wrong_request_hash_fails_closed", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    r = recover_prepared_v63_mutation(
        "append_candidate_discovery", candidate_args,
        expected_correlation_id="CORR-CAND-1", durable_events=[candidate_event, dict(candidate_event)],
    )
    cases.append(_case("duplicate_exact_event_fails_closed", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    opportunity_args = {
        "investigation_id": "INV-ACCEPT",
        "account_id": "C500",
        "product_profile_id": "PVC",
        "product_profile_version": "1",
        "product_profile_sha256": "a" * 64,
        "canonical_resolution_proof": {"status": "CONFIRMED", "account_id": "C500"},
        "idempotency_key": "opportunity-key-0001",
    }
    snapshot = {
        "status": "CREATED",
        "opportunity_id": "OPP-C500-PVC-PRIMARY",
        "account_id": "C500",
        "product_profile_id": "PVC",
        "stage": "OPPORTUNITY_CREATED",
    }
    opportunity_event = {
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "correlation_id": "CORR-OPP-1",
        "request_sha256": canonical_v63_wal_request_sha256("create_product_opportunity", opportunity_args),
        "result_snapshot": snapshot,
        "result_snapshot_sha256": snapshot_sha256(snapshot),
        "raw_idempotency_key_persisted": False,
    }
    r = recover_prepared_v63_mutation(
        "create_product_opportunity", opportunity_args,
        expected_correlation_id="CORR-OPP-1", durable_events=[opportunity_event],
    )
    cases.append(_case("opportunity_exact_snapshot_recovers", r["status"] == "RECOVERED" and r["result"] == snapshot, r))

    bad_snapshot = dict(opportunity_event, result_snapshot_sha256="f" * 64)
    r = recover_prepared_v63_mutation(
        "create_product_opportunity", opportunity_args,
        expected_correlation_id="CORR-OPP-1", durable_events=[bad_snapshot],
    )
    cases.append(_case("opportunity_snapshot_hash_mismatch_fails_closed", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    anchor_args = {
        "investigation_id": "INV-ACCEPT",
        "opportunity_id": "OPP-C500-PVC-PRIMARY",
        "promotion_reason": "UPGRADE_TARGET",
        "idempotency_key": "anchor-key-000001",
    }
    anchor_event = {
        "event_type": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
        "correlation_id": "CORR-ANCHOR-1",
        "request_sha256": canonical_v63_wal_request_sha256("promote_opportunity_anchor", anchor_args),
        "opportunity_id": "OPP-C500-PVC-PRIMARY",
        "anchor_id": "ANCHOR-OPP-C500-PVC-PRIMARY",
        "promotion_reason": "UPGRADE_TARGET",
        "stage": "PROMOTED_ANCHOR",
        "anchor_eligibility_snapshot": {"anchor_eligible": True},
        "cycle_dedup_snapshot": {"cycle_dedup_complete": True},
        "raw_idempotency_key_persisted": False,
    }
    r = recover_prepared_v63_mutation(
        "promote_opportunity_anchor", anchor_args,
        expected_correlation_id="CORR-ANCHOR-1", durable_events=[anchor_event],
    )
    cases.append(_case("anchor_exact_event_recovers", r["status"] == "RECOVERED", r))

    invalid_anchor = dict(anchor_event, cycle_dedup_snapshot={"cycle_dedup_complete": False})
    r = recover_prepared_v63_mutation(
        "promote_opportunity_anchor", anchor_args,
        expected_correlation_id="CORR-ANCHOR-1", durable_events=[invalid_anchor],
    )
    cases.append(_case("anchor_failed_cycle_gate_fails_closed", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    leaked_key = dict(candidate_event, raw_idempotency_key_persisted=True)
    r = recover_prepared_v63_mutation(
        "append_candidate_discovery", candidate_args,
        expected_correlation_id="CORR-CAND-1", durable_events=[leaked_key],
    )
    cases.append(_case("raw_idempotency_key_persistence_is_rejected", r["status"] == "MUTATION_RECONCILIATION_REQUIRED", r))

    failed = [row for row in cases if not row["passed"]]
    return {
        "schema": "cbi.v63-recovery-acceptance.v1",
        "passed": not failed,
        "case_count": len(cases),
        "passed_count": len(cases) - len(failed),
        "failed_count": len(failed),
        "cases": cases,
    }
