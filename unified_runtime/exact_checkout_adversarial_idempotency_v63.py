from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .exact_checkout_live_acceptance_producer_v63 import _start_synthetic_investigation
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader


_TOOL = "append_candidate_discovery"
_EVENT = "V63_CANDIDATE_DISCOVERED"
_KEY_A = "v63-exact-adversarial-idem-a-0001"
_KEY_B = "v63-exact-adversarial-idem-b-0001"


def _arguments(investigation_id: str, key: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "candidate": {
            "candidate_id": "CAND-V63-ADVERSARIAL-IDEM-001",
            "discovered_from_anchor_id": "ANCHOR-V63-ADVERSARIAL-IDEM-001",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_product_hs_application_buyer",
            "company_name": "Synthetic Semantic Replay Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": key,
    }


def run_different_idempotency_key_scenario(repo_root: Path, persistence_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()
    harness = ExactCheckoutMcpHarness(root, persistence)
    harness.start()
    try:
        investigation_id = _start_synthetic_investigation(
            harness,
            2,
            account_id="C-V63-ADVERSARIAL-IDEM",
            name="Synthetic v6.3 Semantic Replay Buyer",
            idempotency_key="v63-exact-adversarial-idem-start-0001",
        )
        response_a = harness.tool(3, _TOOL, _arguments(investigation_id, _KEY_A))
        response_b = harness.tool(4, _TOOL, _arguments(investigation_id, _KEY_B))
    finally:
        harness.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    evidence = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    wal_records = evidence.get("wal_records") or []
    events = evidence.get("events") or []
    request_hashes = [str(row.get("request_sha256") or "") for row in wal_records]
    correlations = [str(row.get("correlation_id") or "") for row in wal_records]
    same_request_hash_proven = len(wal_records) == 2 and len(set(request_hashes)) == 1 and bool(request_hashes[0])
    distinct_correlations_proven = len(wal_records) == 2 and len(set(correlations)) == 2 and all(correlations)
    single_side_effect_proven = len(events) == 1 and events[0].get("event_type") == _EVENT
    correlations_distinct_from_keys = all(c not in {_KEY_A, _KEY_B} for c in correlations)

    if len(wal_records) != 2:
        raise RuntimeError("DIFFERENT_IDEMPOTENCY_KEY_NEW_WAL_NOT_PROVEN")
    if not same_request_hash_proven:
        raise RuntimeError("DIFFERENT_IDEMPOTENCY_KEY_SEMANTIC_HASH_NOT_PROVEN")
    if not distinct_correlations_proven:
        raise RuntimeError("DIFFERENT_IDEMPOTENCY_KEY_DISTINCT_CORRELATION_NOT_PROVEN")
    if not single_side_effect_proven:
        raise RuntimeError("DIFFERENT_IDEMPOTENCY_KEY_DUPLICATED_SIDE_EFFECT")
    if not correlations_distinct_from_keys:
        raise RuntimeError("DIFFERENT_IDEMPOTENCY_KEY_CORRELATION_LEAK")

    return {
        "scenario": "different_idempotency_key",
        "tool": _TOOL,
        "event_type": _EVENT,
        "wal_record_count": len(wal_records),
        "event_count": len(events),
        "same_request_hash_proven": same_request_hash_proven,
        "distinct_correlations_proven": distinct_correlations_proven,
        "single_side_effect_proven": single_side_effect_proven,
        "correlations_distinct_from_keys": correlations_distinct_from_keys,
        "correlation_ids": correlations,
        "request_sha256_values": request_hashes,
        "response_statuses": [str(response_a.get("status") or ""), str(response_b.get("status") or "")],
    }
