from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .exact_checkout_live_acceptance_producer_v63 import _start_synthetic_investigation
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256


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
            "company_name": "Synthetic Cross-Key Claim Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": key,
    }


def _wal_path(persistence_root: Path, key: str) -> Path:
    key_sha = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Path(persistence_root) / "mcp-idempotency-v61" / f"{_TOOL}-{key_sha}.json"


def _correlation_id(key: str) -> str:
    return "MUTCORR-" + hashlib.sha256(f"{_TOOL}:{key}".encode("utf-8")).hexdigest()[:24]


def _write_cross_key_prepared_claim(
    persistence_root: Path,
    *,
    source_key: str,
    claim_key: str,
) -> None:
    source_path = _wal_path(persistence_root, source_key)
    claim_path = _wal_path(persistence_root, claim_key)
    if not source_path.is_file():
        raise RuntimeError("DIFFERENT_KEY_SOURCE_WAL_MISSING")
    if claim_path.exists():
        raise RuntimeError("DIFFERENT_KEY_CLAIM_WAL_ALREADY_EXISTS")

    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict) or source.get("status") != "PREPARED":
        raise RuntimeError("DIFFERENT_KEY_SOURCE_WAL_NOT_PREPARED")
    if source.get("tool") != _TOOL:
        raise RuntimeError("DIFFERENT_KEY_SOURCE_WAL_TOOL_MISMATCH")

    claim = copy.deepcopy(source)
    claim["idempotency_key"] = claim_key
    claim["mutation_correlation_id"] = _correlation_id(claim_key)
    for terminal_field in (
        "completed_at",
        "state_version_after",
        "result_sha256",
        "result",
        "error",
    ):
        claim.pop(terminal_field, None)
    claim["status"] = "PREPARED"

    claim_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = claim_path.with_suffix(claim_path.suffix + ".adversarial.tmp")
    payload = json.dumps(
        claim,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, claim_path)


def _replay_claim_is_rejected(
    root: Path,
    persistence: Path,
    arguments: dict[str, Any],
) -> bool:
    harness = ExactCheckoutMcpHarness(root, persistence)
    harness.start()
    rejected = False
    try:
        try:
            harness.tool(2, _TOOL, arguments)
        except RuntimeError:
            rejected = True
    finally:
        harness.stop()
    return rejected


def run_different_idempotency_key_scenario(repo_root: Path, persistence_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()

    crashing = ExactCheckoutMcpHarness(root, persistence)
    crashing.start(crash_after_handler=_TOOL)
    try:
        investigation_id = _start_synthetic_investigation(
            crashing,
            2,
            account_id="C-V63-ADVERSARIAL-IDEM",
            name="Synthetic v6.3 Cross-Key Claim Buyer",
            idempotency_key="v63-exact-adversarial-idem-start-0001",
        )
        arguments_a = _arguments(investigation_id, _KEY_A)
        arguments_b = _arguments(investigation_id, _KEY_B)
        crashing.crash_tool(3, _TOOL, arguments_a)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    initial = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    if initial.get("event_count") != 1 or initial.get("wal_record_count") != 1:
        raise RuntimeError("DIFFERENT_KEY_INITIAL_CARDINALITY_FAILED")
    initial_event = initial["events"][0]
    initial_wal = initial["wal_records"][0]
    if initial_wal.get("status") != "PREPARED":
        raise RuntimeError("DIFFERENT_KEY_INITIAL_WAL_NOT_PREPARED")

    request_sha_a = canonical_v63_wal_request_sha256(_TOOL, arguments_a)
    request_sha_b = canonical_v63_wal_request_sha256(_TOOL, arguments_b)
    if request_sha_a != request_sha_b:
        raise RuntimeError("DIFFERENT_KEY_CANONICAL_REQUEST_HASH_CHANGED")
    if initial_wal.get("request_sha256") != request_sha_a:
        raise RuntimeError("DIFFERENT_KEY_INITIAL_WAL_REQUEST_HASH_MISMATCH")
    if initial_event.get("request_sha256") != request_sha_a:
        raise RuntimeError("DIFFERENT_KEY_INITIAL_EVENT_REQUEST_HASH_MISMATCH")

    correlation_a = str(initial_wal.get("correlation_id") or "").strip()
    if not correlation_a or initial_event.get("correlation_id") != correlation_a:
        raise RuntimeError("DIFFERENT_KEY_INITIAL_CORRELATION_NOT_BOUND")

    _write_cross_key_prepared_claim(
        persistence,
        source_key=_KEY_A,
        claim_key=_KEY_B,
    )

    before_replay = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    wal_records_before = before_replay.get("wal_records") or []
    events_before = before_replay.get("events") or []
    if len(wal_records_before) != 2 or len(events_before) != 1:
        raise RuntimeError("DIFFERENT_KEY_FIXTURE_CARDINALITY_FAILED")

    request_hashes_before = [str(row.get("request_sha256") or "") for row in wal_records_before]
    correlations_before = [str(row.get("correlation_id") or "") for row in wal_records_before]
    correlation_b = _correlation_id(_KEY_B)
    same_request_hash_proven = (
        len(set(request_hashes_before)) == 1
        and request_hashes_before[0] == request_sha_a
    )
    distinct_correlations_proven = (
        len(set(correlations_before)) == 2
        and correlation_a in correlations_before
        and correlation_b in correlations_before
        and correlation_a != correlation_b
    )
    first_event_bound_only_to_first_correlation = (
        str(events_before[0].get("correlation_id") or "") == correlation_a
        and str(events_before[0].get("correlation_id") or "") != correlation_b
    )
    if not same_request_hash_proven:
        raise RuntimeError("DIFFERENT_KEY_FIXTURE_REQUEST_HASH_NOT_SHARED")
    if not distinct_correlations_proven:
        raise RuntimeError("DIFFERENT_KEY_FIXTURE_CORRELATIONS_NOT_DISTINCT")
    if not first_event_bound_only_to_first_correlation:
        raise RuntimeError("DIFFERENT_KEY_FIRST_EVENT_CROSS_BOUND")

    recovery_rejected = _replay_claim_is_rejected(root, persistence, arguments_b)

    after_replay = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    wal_records_after = after_replay.get("wal_records") or []
    events_after = after_replay.get("events") or []
    event_count_before = len(events_before)
    event_count_after = len(events_after)
    reexecute_side_effect = event_count_after != event_count_before
    statuses_before = sorted(str(row.get("status") or "") for row in wal_records_before)
    statuses_after = sorted(str(row.get("status") or "") for row in wal_records_after)

    if not recovery_rejected:
        raise RuntimeError("DIFFERENT_KEY_CROSS_KEY_CLAIM_WAS_NOT_REJECTED")
    if reexecute_side_effect:
        raise RuntimeError("DIFFERENT_KEY_SIDE_EFFECT_REEXECUTED")
    if len(wal_records_after) != 2:
        raise RuntimeError("DIFFERENT_KEY_WAL_CARDINALITY_CHANGED")
    if statuses_after != ["PREPARED", "PREPARED"]:
        raise RuntimeError("DIFFERENT_KEY_CLAIM_WAL_DID_NOT_REMAIN_PREPARED")

    return {
        "scenario": "different_idempotency_key",
        "tool": _TOOL,
        "event_type": _EVENT,
        "recovery_status": "RECONCILIATION_REQUIRED",
        "recovery_rejected": recovery_rejected,
        "reexecute_side_effect": reexecute_side_effect,
        "wal_record_count_before_replay": len(wal_records_before),
        "wal_record_count_after_replay": len(wal_records_after),
        "event_count_before_replay": event_count_before,
        "event_count_after_replay": event_count_after,
        "wal_statuses_before_replay": statuses_before,
        "wal_statuses_after_replay": statuses_after,
        "same_request_hash_proven": same_request_hash_proven,
        "distinct_correlations_proven": distinct_correlations_proven,
        "first_event_bound_only_to_first_correlation": first_event_bound_only_to_first_correlation,
        "correlation_ids": [correlation_a, correlation_b],
        "request_sha256": request_sha_a,
    }
