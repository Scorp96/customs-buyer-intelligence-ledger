from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .exact_checkout_live_acceptance_producer_v63 import (
    _start_synthetic_investigation,
    _without_idempotency_keys,
)
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from .product_profiles import get_product_profile
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256, snapshot_sha256


_CANDIDATE_TOOL = "append_candidate_discovery"
_CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"
_OPPORTUNITY_TOOL = "create_product_opportunity"
_OPPORTUNITY_EVENT = "V63_PRODUCT_OPPORTUNITY_CREATED"
_ANCHOR_TOOL = "promote_opportunity_anchor"
_ANCHOR_EVENT = "V63_OPPORTUNITY_ANCHOR_PROMOTED"


def candidate_crash_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "candidate": {
            "candidate_id": "CAND-V63-CRASH-001",
            "discovered_from_anchor_id": "ANCHOR-V63-CRASH-SYNTH-001",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_product_hs_application_buyer",
            "company_name": "Synthetic Candidate Crash Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": "v63-exact-candidate-crash-0001",
    }


def opportunity_crash_arguments(investigation_id: str) -> dict[str, Any]:
    profile = get_product_profile("PVC")
    account_id = "C-V63-CRASH-OPPORTUNITY"
    return {
        "investigation_id": investigation_id,
        "canonical_resolution": {
            "canonical_status": "CONFIRMED",
            "canonical_account_id": account_id,
            "resolver_authority": "PRIMARY_LEGAL_NAME_COUNTRY",
            "resolver_is_existing_production_authority": True,
            "ambiguous": False,
            "address_only_match": False,
            "alias_only_match": False,
            "tax_conflict": False,
            "country_conflict": False,
        },
        "opportunity": {
            "opportunity_id": "OPP-V63-CRASH-001",
            "account_id": account_id,
            "product_profile_id": profile["profile_id"],
            "product_profile_version": profile["profile_version"],
            "product_profile_sha256": profile["profile_sha256"],
            "application_ids": ["CABINETRY"],
            "buyer_archetype_ids": ["CABINET_MANUFACTURER"],
            "market_cell_ids": ["SYNTHETIC-CRASH-CELL"],
        },
        "idempotency_key": "v63-exact-opportunity-crash-0001",
    }


def anchor_crash_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "opportunity_id": "OPP-V63-CRASH-ANCHOR-001",
        "promotion_reason": "Synthetic crash recovery B+ material novelty promotion",
        "anchor_eligibility": {
            "anchor_eligible": True,
            "commercial_value_grade": "B+",
            "canonical_status": "CONFIRMED",
            "commercial_evidence_bound": True,
            "material_novelty_signals": ["STRONG_CURRENT_PROCUREMENT"],
            "contact_readiness_is_gate": False,
            "blockers": [],
        },
        "cycle_dedup_complete": True,
        "idempotency_key": "v63-exact-anchor-crash-0001",
    }


def _single_evidence_pair(evidence: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    events = evidence.get("events") or []
    wal_records = evidence.get("wal_records") or []
    if len(events) != 1 or len(wal_records) != 1:
        raise RuntimeError("CRASH_EXACT_EVIDENCE_CARDINALITY_NOT_PROVEN")
    event = events[0]
    wal = wal_records[0]
    if not isinstance(event, dict) or not isinstance(wal, dict):
        raise RuntimeError("CRASH_EVIDENCE_INVALID")
    return event, wal


def _reconciled_meta(raw_response: dict[str, Any]) -> bool:
    mutation_meta = raw_response.get("mutation_meta") if isinstance(raw_response, dict) else None
    return bool(
        isinstance(mutation_meta, dict)
        and mutation_meta.get("reconciled_after_crash") is True
        and mutation_meta.get("replayed") is True
    )


def _raw_durable_event(
    reader: ExactCheckoutPersistenceReader,
    investigation_id: str,
    *,
    tool: str,
    event_type: str,
    correlation_id: str,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for event in reader.read_session_events(investigation_id):
        correlation = event.get("mutation_correlation")
        if (
            event.get("event_type") == event_type
            and isinstance(correlation, dict)
            and correlation.get("tool") == tool
            and correlation.get("correlation_id") == correlation_id
        ):
            matches.append(event)
    if len(matches) != 1:
        raise RuntimeError("CRASH_DURABLE_EVENT_CARDINALITY_NOT_PROVEN")
    return matches[0]


def run_candidate_crash_restart_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()

    crashing = ExactCheckoutMcpHarness(root, persistence)
    crashing.start(crash_after_handler=_CANDIDATE_TOOL)
    try:
        investigation_id = _start_synthetic_investigation(
            crashing,
            2,
            account_id="C-V63-CRASH-CANDIDATE",
            name="Synthetic v6.3 Crash Candidate Buyer",
            idempotency_key="v63-exact-candidate-crash-start-0001",
        )
        arguments = candidate_crash_arguments(investigation_id)
        crashing.crash_tool(3, _CANDIDATE_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    pre_restart = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    pre_event, pre_wal = _single_evidence_pair(pre_restart)
    expected_request_sha = canonical_v63_wal_request_sha256(_CANDIDATE_TOOL, arguments)
    if pre_event.get("event_type") != _CANDIDATE_EVENT:
        raise RuntimeError("CANDIDATE_CRASH_DURABLE_EVENT_MISSING")
    if pre_wal.get("status") != "PREPARED":
        raise RuntimeError("CANDIDATE_CRASH_PREPARED_WAL_MISSING")
    if pre_event.get("request_sha256") != expected_request_sha:
        raise RuntimeError("CANDIDATE_CRASH_PRE_RESTART_EVENT_HASH_MISMATCH")
    if pre_wal.get("request_sha256") != expected_request_sha:
        raise RuntimeError("CANDIDATE_CRASH_PRE_RESTART_WAL_HASH_MISMATCH")

    restarted = ExactCheckoutMcpHarness(root, persistence)
    restarted.start()
    try:
        raw_response = restarted.tool(2, _CANDIDATE_TOOL, arguments)
    finally:
        restarted.stop()

    reconciled_after_crash = _reconciled_meta(raw_response)
    response = _without_idempotency_keys(raw_response)

    post_restart = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    post_event, post_wal = _single_evidence_pair(post_restart)
    event_correlation = str(post_event.get("correlation_id") or "").strip()
    wal_correlation = str(post_wal.get("correlation_id") or "").strip()
    exact_correlation_proven = bool(
        event_correlation
        and event_correlation == wal_correlation
        and event_correlation == str(pre_event.get("correlation_id") or "").strip()
    )
    exact_request_hash_proven = bool(
        post_event.get("request_sha256") == expected_request_sha
        and post_wal.get("request_sha256") == expected_request_sha
        and pre_event.get("request_sha256") == expected_request_sha
        and pre_wal.get("request_sha256") == expected_request_sha
    )
    no_duplicate_event_proven = bool(
        pre_restart.get("event_count") == 1
        and post_restart.get("event_count") == 1
        and post_event.get("seq") == pre_event.get("seq")
        and post_event.get("event_type") == _CANDIDATE_EVENT
    )

    if post_wal.get("status") != "COMMITTED":
        raise RuntimeError("CANDIDATE_CRASH_RECOVERY_WAL_NOT_COMMITTED")
    if not reconciled_after_crash:
        raise RuntimeError("CANDIDATE_CRASH_RECONCILIATION_NOT_PROVEN")
    if not exact_correlation_proven:
        raise RuntimeError("CANDIDATE_CRASH_EXACT_CORRELATION_NOT_PROVEN")
    if not exact_request_hash_proven:
        raise RuntimeError("CANDIDATE_CRASH_EXACT_REQUEST_HASH_NOT_PROVEN")
    if not no_duplicate_event_proven:
        raise RuntimeError("CANDIDATE_CRASH_DUPLICATE_EVENT_DETECTED")
    if not isinstance(response, dict) or response.get("status") != "DISCOVERED":
        raise RuntimeError("CANDIDATE_CRASH_RECOVERED_RESPONSE_INVALID")

    return {
        "scenario": "candidate_crash_restart",
        "tool": _CANDIDATE_TOOL,
        "investigation_id": investigation_id,
        "response": response,
        "pre_restart_evidence": pre_restart,
        "post_restart_evidence": post_restart,
        "reconciled_after_crash": reconciled_after_crash,
        "exact_correlation_proven": exact_correlation_proven,
        "exact_request_hash_proven": exact_request_hash_proven,
        "no_duplicate_event_proven": no_duplicate_event_proven,
    }


def run_opportunity_crash_restart_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()

    crashing = ExactCheckoutMcpHarness(root, persistence)
    crashing.start(crash_after_handler=_OPPORTUNITY_TOOL)
    try:
        investigation_id = _start_synthetic_investigation(
            crashing,
            2,
            account_id="C-V63-CRASH-OPPORTUNITY",
            name="Synthetic v6.3 Crash Opportunity Buyer",
            idempotency_key="v63-exact-opportunity-crash-start-0001",
        )
        arguments = opportunity_crash_arguments(investigation_id)
        crashing.crash_tool(3, _OPPORTUNITY_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    pre_restart = reader.normalize_mutation_evidence(investigation_id, _OPPORTUNITY_TOOL)
    pre_event, pre_wal = _single_evidence_pair(pre_restart)
    expected_request_sha = canonical_v63_wal_request_sha256(_OPPORTUNITY_TOOL, arguments)
    durable_snapshot = copy.deepcopy(pre_event.get("result_snapshot"))
    durable_snapshot_sha = str(pre_event.get("result_snapshot_sha256") or "").strip().lower()

    if pre_event.get("event_type") != _OPPORTUNITY_EVENT:
        raise RuntimeError("OPPORTUNITY_CRASH_DURABLE_EVENT_MISSING")
    if pre_wal.get("status") != "PREPARED":
        raise RuntimeError("OPPORTUNITY_CRASH_PREPARED_WAL_MISSING")
    if pre_event.get("request_sha256") != expected_request_sha:
        raise RuntimeError("OPPORTUNITY_CRASH_PRE_RESTART_EVENT_HASH_MISMATCH")
    if pre_wal.get("request_sha256") != expected_request_sha:
        raise RuntimeError("OPPORTUNITY_CRASH_PRE_RESTART_WAL_HASH_MISMATCH")
    if not isinstance(durable_snapshot, dict):
        raise RuntimeError("OPPORTUNITY_CRASH_RESULT_SNAPSHOT_MISSING")
    if snapshot_sha256(durable_snapshot) != durable_snapshot_sha:
        raise RuntimeError("OPPORTUNITY_CRASH_RESULT_SNAPSHOT_HASH_MISMATCH")

    restarted = ExactCheckoutMcpHarness(root, persistence)
    restarted.start()
    try:
        raw_response = restarted.tool(2, _OPPORTUNITY_TOOL, arguments)
    finally:
        restarted.stop()

    reconciled_after_crash = _reconciled_meta(raw_response)
    response = _without_idempotency_keys(raw_response)
    recovered_business_result = copy.deepcopy(response)
    if isinstance(recovered_business_result, dict):
        recovered_business_result.pop("mutation_meta", None)

    post_restart = reader.normalize_mutation_evidence(investigation_id, _OPPORTUNITY_TOOL)
    post_event, post_wal = _single_evidence_pair(post_restart)
    no_duplicate_event_proven = bool(
        pre_restart.get("event_count") == 1
        and post_restart.get("event_count") == 1
        and post_event.get("seq") == pre_event.get("seq")
        and post_event.get("event_type") == _OPPORTUNITY_EVENT
    )
    exact_result_snapshot_recovered = bool(
        recovered_business_result == durable_snapshot
        and post_event.get("result_snapshot") == durable_snapshot
        and post_event.get("result_snapshot_sha256") == durable_snapshot_sha
        and snapshot_sha256(durable_snapshot) == durable_snapshot_sha
    )

    if post_wal.get("status") != "COMMITTED":
        raise RuntimeError("OPPORTUNITY_CRASH_RECOVERY_WAL_NOT_COMMITTED")
    if post_event.get("request_sha256") != expected_request_sha:
        raise RuntimeError("OPPORTUNITY_CRASH_POST_RESTART_EVENT_HASH_MISMATCH")
    if post_wal.get("request_sha256") != expected_request_sha:
        raise RuntimeError("OPPORTUNITY_CRASH_POST_RESTART_WAL_HASH_MISMATCH")
    if not reconciled_after_crash:
        raise RuntimeError("OPPORTUNITY_CRASH_RECONCILIATION_NOT_PROVEN")
    if not exact_result_snapshot_recovered:
        raise RuntimeError("OPPORTUNITY_CRASH_EXACT_RESULT_RECOVERY_NOT_PROVEN")
    if not no_duplicate_event_proven:
        raise RuntimeError("OPPORTUNITY_CRASH_DUPLICATE_EVENT_DETECTED")

    return {
        "scenario": "opportunity_crash_restart",
        "tool": _OPPORTUNITY_TOOL,
        "investigation_id": investigation_id,
        "response": response,
        "recovered_business_result": recovered_business_result,
        "durable_result_snapshot": durable_snapshot,
        "durable_result_snapshot_sha256": durable_snapshot_sha,
        "pre_restart_evidence": pre_restart,
        "post_restart_evidence": post_restart,
        "reconciled_after_crash": reconciled_after_crash,
        "exact_result_snapshot_recovered": exact_result_snapshot_recovered,
        "no_duplicate_event_proven": no_duplicate_event_proven,
    }


def run_anchor_crash_restart_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()

    crashing = ExactCheckoutMcpHarness(root, persistence)
    crashing.start(crash_after_handler=_ANCHOR_TOOL)
    try:
        investigation_id = _start_synthetic_investigation(
            crashing,
            2,
            account_id="C-V63-CRASH-ANCHOR",
            name="Synthetic v6.3 Crash Anchor Buyer",
            idempotency_key="v63-exact-anchor-crash-start-0001",
        )
        arguments = anchor_crash_arguments(investigation_id)
        crashing.crash_tool(3, _ANCHOR_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    pre_restart = reader.normalize_mutation_evidence(investigation_id, _ANCHOR_TOOL)
    pre_event, pre_wal = _single_evidence_pair(pre_restart)
    expected_request_sha = canonical_v63_wal_request_sha256(_ANCHOR_TOOL, arguments)
    correlation_id = str(pre_event.get("correlation_id") or "").strip()

    if pre_event.get("event_type") != _ANCHOR_EVENT:
        raise RuntimeError("ANCHOR_CRASH_DURABLE_EVENT_MISSING")
    if pre_wal.get("status") != "PREPARED":
        raise RuntimeError("ANCHOR_CRASH_PREPARED_WAL_MISSING")
    if pre_event.get("request_sha256") != expected_request_sha:
        raise RuntimeError("ANCHOR_CRASH_PRE_RESTART_EVENT_HASH_MISMATCH")
    if pre_wal.get("request_sha256") != expected_request_sha:
        raise RuntimeError("ANCHOR_CRASH_PRE_RESTART_WAL_HASH_MISMATCH")
    if not correlation_id or pre_wal.get("correlation_id") != correlation_id:
        raise RuntimeError("ANCHOR_CRASH_PRE_RESTART_CORRELATION_MISMATCH")

    durable_pre = _raw_durable_event(
        reader,
        investigation_id,
        tool=_ANCHOR_TOOL,
        event_type=_ANCHOR_EVENT,
        correlation_id=correlation_id,
    )
    pre_payload = durable_pre.get("payload")
    pre_payload = pre_payload if isinstance(pre_payload, dict) else {}
    durable_eligibility = _without_idempotency_keys(
        pre_payload.get("anchor_eligibility_snapshot")
    )
    durable_cycle = _without_idempotency_keys(pre_payload.get("cycle_dedup_snapshot"))
    if durable_eligibility != arguments["anchor_eligibility"]:
        raise RuntimeError("ANCHOR_CRASH_PRE_RESTART_ELIGIBILITY_SNAPSHOT_MISMATCH")
    if durable_cycle != {"cycle_dedup_complete": True}:
        raise RuntimeError("ANCHOR_CRASH_PRE_RESTART_CYCLE_SNAPSHOT_MISMATCH")

    restarted = ExactCheckoutMcpHarness(root, persistence)
    restarted.start()
    try:
        raw_response = restarted.tool(2, _ANCHOR_TOOL, arguments)
    finally:
        restarted.stop()

    reconciled_after_crash = _reconciled_meta(raw_response)
    response = _without_idempotency_keys(raw_response)
    recovered_business_result = copy.deepcopy(response)
    if isinstance(recovered_business_result, dict):
        recovered_business_result.pop("mutation_meta", None)

    post_restart = reader.normalize_mutation_evidence(investigation_id, _ANCHOR_TOOL)
    post_event, post_wal = _single_evidence_pair(post_restart)
    durable_post = _raw_durable_event(
        reader,
        investigation_id,
        tool=_ANCHOR_TOOL,
        event_type=_ANCHOR_EVENT,
        correlation_id=correlation_id,
    )
    post_payload = durable_post.get("payload")
    post_payload = post_payload if isinstance(post_payload, dict) else {}
    post_eligibility = _without_idempotency_keys(
        post_payload.get("anchor_eligibility_snapshot")
    )
    post_cycle = _without_idempotency_keys(post_payload.get("cycle_dedup_snapshot"))

    no_duplicate_event_proven = bool(
        pre_restart.get("event_count") == 1
        and post_restart.get("event_count") == 1
        and post_event.get("seq") == pre_event.get("seq")
        and post_event.get("event_type") == _ANCHOR_EVENT
        and durable_post.get("event_hash") == durable_pre.get("event_hash")
    )
    exact_anchor_snapshots_preserved = bool(
        durable_eligibility == arguments["anchor_eligibility"]
        and post_eligibility == durable_eligibility
        and durable_cycle == {"cycle_dedup_complete": True}
        and post_cycle == durable_cycle
        and isinstance(recovered_business_result, dict)
        and recovered_business_result.get("anchor_eligibility_snapshot") == durable_eligibility
        and recovered_business_result.get("cycle_dedup_snapshot") == durable_cycle
    )

    if post_wal.get("status") != "COMMITTED":
        raise RuntimeError("ANCHOR_CRASH_RECOVERY_WAL_NOT_COMMITTED")
    if post_event.get("request_sha256") != expected_request_sha:
        raise RuntimeError("ANCHOR_CRASH_POST_RESTART_EVENT_HASH_MISMATCH")
    if post_wal.get("request_sha256") != expected_request_sha:
        raise RuntimeError("ANCHOR_CRASH_POST_RESTART_WAL_HASH_MISMATCH")
    if post_event.get("correlation_id") != correlation_id:
        raise RuntimeError("ANCHOR_CRASH_POST_RESTART_EVENT_CORRELATION_MISMATCH")
    if post_wal.get("correlation_id") != correlation_id:
        raise RuntimeError("ANCHOR_CRASH_POST_RESTART_WAL_CORRELATION_MISMATCH")
    if not reconciled_after_crash:
        raise RuntimeError("ANCHOR_CRASH_RECONCILIATION_NOT_PROVEN")
    if not no_duplicate_event_proven:
        raise RuntimeError("ANCHOR_CRASH_DUPLICATE_EVENT_DETECTED")
    if not exact_anchor_snapshots_preserved:
        raise RuntimeError("ANCHOR_CRASH_EXACT_SNAPSHOTS_NOT_PRESERVED")
    if not isinstance(response, dict) or response.get("status") != "PROMOTED":
        raise RuntimeError("ANCHOR_CRASH_RECOVERED_RESPONSE_INVALID")

    return {
        "scenario": "anchor_crash_restart",
        "tool": _ANCHOR_TOOL,
        "investigation_id": investigation_id,
        "response": response,
        "recovered_business_result": recovered_business_result,
        "durable_anchor_snapshots": {
            "anchor_eligibility_snapshot": copy.deepcopy(durable_eligibility),
            "cycle_dedup_snapshot": copy.deepcopy(durable_cycle),
        },
        "pre_restart_evidence": pre_restart,
        "post_restart_evidence": post_restart,
        "reconciled_after_crash": reconciled_after_crash,
        "no_duplicate_event_proven": no_duplicate_event_proven,
        "exact_anchor_snapshots_preserved": exact_anchor_snapshots_preserved,
    }
