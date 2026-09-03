from __future__ import annotations

from pathlib import Path
from typing import Any

from .exact_checkout_live_acceptance_producer_v63 import (
    _start_synthetic_investigation,
    _without_idempotency_keys,
)
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256


_CANDIDATE_TOOL = "append_candidate_discovery"
_CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"


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


def _single_evidence_pair(evidence: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    events = evidence.get("events") or []
    wal_records = evidence.get("wal_records") or []
    if len(events) != 1 or len(wal_records) != 1:
        raise RuntimeError("CANDIDATE_CRASH_EXACT_EVIDENCE_CARDINALITY_NOT_PROVEN")
    event = events[0]
    wal = wal_records[0]
    if not isinstance(event, dict) or not isinstance(wal, dict):
        raise RuntimeError("CANDIDATE_CRASH_EVIDENCE_INVALID")
    return event, wal


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

    mutation_meta = raw_response.get("mutation_meta") if isinstance(raw_response, dict) else None
    reconciled_after_crash = bool(
        isinstance(mutation_meta, dict)
        and mutation_meta.get("reconciled_after_crash") is True
        and mutation_meta.get("replayed") is True
    )
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
