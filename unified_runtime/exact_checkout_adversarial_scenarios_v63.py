from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable

from .core import digest
from .exact_checkout_live_acceptance_producer_v63 import _start_synthetic_investigation
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256


_CANDIDATE_TOOL = "append_candidate_discovery"
_CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"
_WRONG_CORRELATION = "MUTCORR-000000000000000000000000"
_WRONG_REQUEST_SHA256 = "f" * 64


def wrong_correlation_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "candidate": {
            "candidate_id": "CAND-V63-ADVERSARIAL-CORR-001",
            "discovered_from_anchor_id": "ANCHOR-V63-ADVERSARIAL-CORR-001",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_product_hs_application_buyer",
            "company_name": "Synthetic Wrong Correlation Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": "v63-exact-adversarial-wrong-correlation-0001",
    }


def wrong_request_hash_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "candidate": {
            "candidate_id": "CAND-V63-ADVERSARIAL-HASH-001",
            "discovered_from_anchor_id": "ANCHOR-V63-ADVERSARIAL-HASH-001",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_product_hs_application_buyer",
            "company_name": "Synthetic Wrong Request Hash Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": "v63-exact-adversarial-wrong-hash-0001",
    }


def _rewrite_candidate_event(
    persistence_root: Path,
    investigation_id: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    path = Path(persistence_root) / "sessions" / f"{investigation_id}.jsonl"
    if not path.is_file():
        raise RuntimeError("ADVERSARIAL_SESSION_LOG_MISSING")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise RuntimeError("ADVERSARIAL_SESSION_EVENT_INVALID")
                rows.append(row)

    matches = [
        index
        for index, row in enumerate(rows)
        if row.get("event_type") == _CANDIDATE_EVENT
        and isinstance(row.get("mutation_correlation"), dict)
        and row["mutation_correlation"].get("tool") == _CANDIDATE_TOOL
    ]
    if len(matches) != 1:
        raise RuntimeError("ADVERSARIAL_CANDIDATE_EVENT_CARDINALITY_INVALID")
    index = matches[0]
    row = copy.deepcopy(rows[index])
    mutate(row)
    unsigned = {key: value for key, value in row.items() if key != "event_hash"}
    row["event_hash"] = digest(unsigned)
    rows[index] = row

    for next_index in range(index + 1, len(rows)):
        current = copy.deepcopy(rows[next_index])
        current["prev_hash"] = rows[next_index - 1]["event_hash"]
        unsigned = {key: value for key, value in current.items() if key != "event_hash"}
        current["event_hash"] = digest(unsigned)
        rows[next_index] = current

    tmp = path.with_suffix(path.suffix + ".adversarial.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for item in rows:
            handle.write(
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _rewrite_candidate_correlation(
    persistence_root: Path,
    investigation_id: str,
    *,
    wrong_correlation_id: str,
) -> None:
    def mutate(row: dict[str, Any]) -> None:
        correlation = copy.deepcopy(row["mutation_correlation"])
        correlation["correlation_id"] = wrong_correlation_id
        row["mutation_correlation"] = correlation

    _rewrite_candidate_event(persistence_root, investigation_id, mutate)


def _rewrite_candidate_request_hash(
    persistence_root: Path,
    investigation_id: str,
    *,
    wrong_request_sha256: str,
) -> None:
    def mutate(row: dict[str, Any]) -> None:
        payload = copy.deepcopy(row.get("payload"))
        if not isinstance(payload, dict):
            raise RuntimeError("ADVERSARIAL_CANDIDATE_PAYLOAD_INVALID")
        payload["request_sha256"] = wrong_request_sha256
        row["payload"] = payload

    _rewrite_candidate_event(persistence_root, investigation_id, mutate)


def _replay_is_rejected(
    root: Path,
    persistence: Path,
    arguments: dict[str, Any],
) -> bool:
    restarted = ExactCheckoutMcpHarness(root, persistence)
    restarted.start()
    rejected = False
    try:
        try:
            restarted.tool(2, _CANDIDATE_TOOL, arguments)
        except RuntimeError:
            rejected = True
    finally:
        restarted.stop()
    return rejected


def run_wrong_correlation_scenario(
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
            account_id="C-V63-ADVERSARIAL-CORR",
            name="Synthetic v6.3 Wrong Correlation Buyer",
            idempotency_key="v63-exact-adversarial-wrong-correlation-start-0001",
        )
        arguments = wrong_correlation_arguments(investigation_id)
        crashing.crash_tool(3, _CANDIDATE_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    before = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    if before.get("event_count") != 1 or before.get("wal_record_count") != 1:
        raise RuntimeError("WRONG_CORRELATION_PRECONDITION_CARDINALITY_FAILED")
    wal_before = before["wal_records"][0]
    event_before = before["events"][0]
    if wal_before.get("status") != "PREPARED":
        raise RuntimeError("WRONG_CORRELATION_PREPARED_WAL_MISSING")
    expected_request_sha = canonical_v63_wal_request_sha256(_CANDIDATE_TOOL, arguments)
    if wal_before.get("request_sha256") != expected_request_sha:
        raise RuntimeError("WRONG_CORRELATION_WAL_REQUEST_HASH_MISMATCH")
    if event_before.get("request_sha256") != expected_request_sha:
        raise RuntimeError("WRONG_CORRELATION_EVENT_REQUEST_HASH_MISMATCH")
    wal_correlation_id = str(wal_before.get("correlation_id") or "").strip()
    if not wal_correlation_id:
        raise RuntimeError("WRONG_CORRELATION_WAL_CORRELATION_MISSING")

    _rewrite_candidate_correlation(
        persistence,
        investigation_id,
        wrong_correlation_id=_WRONG_CORRELATION,
    )
    tampered = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    if tampered.get("event_count") != 1 or tampered.get("wal_record_count") != 1:
        raise RuntimeError("WRONG_CORRELATION_TAMPER_CARDINALITY_FAILED")
    durable_correlation_id = str(tampered["events"][0].get("correlation_id") or "").strip()
    if durable_correlation_id != _WRONG_CORRELATION or durable_correlation_id == wal_correlation_id:
        raise RuntimeError("WRONG_CORRELATION_TAMPER_NOT_PROVEN")

    recovery_rejected = _replay_is_rejected(root, persistence, arguments)
    after = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    event_count_before_replay = int(tampered.get("event_count") or 0)
    event_count_after_replay = int(after.get("event_count") or 0)
    wal_status_before_replay = str(tampered["wal_records"][0].get("status") or "")
    wal_status_after_replay = str(after["wal_records"][0].get("status") or "")
    reexecute_side_effect = event_count_after_replay != event_count_before_replay

    if not recovery_rejected:
        raise RuntimeError("WRONG_CORRELATION_RECOVERY_WAS_NOT_REJECTED")
    if reexecute_side_effect:
        raise RuntimeError("WRONG_CORRELATION_SIDE_EFFECT_REEXECUTED")
    if wal_status_after_replay != "PREPARED":
        raise RuntimeError("WRONG_CORRELATION_WAL_DID_NOT_REMAIN_PREPARED")
    if after.get("wal_record_count") != 1:
        raise RuntimeError("WRONG_CORRELATION_WAL_CARDINALITY_CHANGED")

    return {
        "scenario": "wrong_correlation",
        "tool": _CANDIDATE_TOOL,
        "recovery_status": "RECONCILIATION_REQUIRED",
        "recovery_rejected": recovery_rejected,
        "reexecute_side_effect": reexecute_side_effect,
        "event_count_before_replay": event_count_before_replay,
        "event_count_after_replay": event_count_after_replay,
        "wal_status_before_replay": wal_status_before_replay,
        "wal_status_after_replay": wal_status_after_replay,
        "durable_correlation_id": durable_correlation_id,
        "wal_correlation_id": wal_correlation_id,
    }


def run_wrong_request_hash_scenario(
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
            account_id="C-V63-ADVERSARIAL-HASH",
            name="Synthetic v6.3 Wrong Request Hash Buyer",
            idempotency_key="v63-exact-adversarial-wrong-hash-start-0001",
        )
        arguments = wrong_request_hash_arguments(investigation_id)
        crashing.crash_tool(3, _CANDIDATE_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    before = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    if before.get("event_count") != 1 or before.get("wal_record_count") != 1:
        raise RuntimeError("WRONG_HASH_PRECONDITION_CARDINALITY_FAILED")
    wal_before = before["wal_records"][0]
    event_before = before["events"][0]
    expected_request_sha = canonical_v63_wal_request_sha256(_CANDIDATE_TOOL, arguments)
    if wal_before.get("status") != "PREPARED":
        raise RuntimeError("WRONG_HASH_PREPARED_WAL_MISSING")
    if wal_before.get("request_sha256") != expected_request_sha:
        raise RuntimeError("WRONG_HASH_WAL_REQUEST_HASH_MISMATCH")
    if event_before.get("request_sha256") != expected_request_sha:
        raise RuntimeError("WRONG_HASH_EVENT_REQUEST_HASH_MISMATCH")
    wal_correlation_id = str(wal_before.get("correlation_id") or "").strip()
    if not wal_correlation_id or event_before.get("correlation_id") != wal_correlation_id:
        raise RuntimeError("WRONG_HASH_INITIAL_CORRELATION_MISMATCH")

    wrong_hash = _WRONG_REQUEST_SHA256
    if wrong_hash == expected_request_sha:
        wrong_hash = "e" * 64
    _rewrite_candidate_request_hash(
        persistence,
        investigation_id,
        wrong_request_sha256=wrong_hash,
    )
    tampered = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    if tampered.get("event_count") != 1 or tampered.get("wal_record_count") != 1:
        raise RuntimeError("WRONG_HASH_TAMPER_CARDINALITY_FAILED")
    durable_event = tampered["events"][0]
    durable_correlation_id = str(durable_event.get("correlation_id") or "").strip()
    durable_request_sha256 = str(durable_event.get("request_sha256") or "").strip()
    if durable_correlation_id != wal_correlation_id:
        raise RuntimeError("WRONG_HASH_CORRELATION_WAS_CHANGED")
    if durable_request_sha256 != wrong_hash or durable_request_sha256 == expected_request_sha:
        raise RuntimeError("WRONG_HASH_TAMPER_NOT_PROVEN")

    recovery_rejected = _replay_is_rejected(root, persistence, arguments)
    after = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    event_count_before_replay = int(tampered.get("event_count") or 0)
    event_count_after_replay = int(after.get("event_count") or 0)
    wal_status_before_replay = str(tampered["wal_records"][0].get("status") or "")
    wal_status_after_replay = str(after["wal_records"][0].get("status") or "")
    reexecute_side_effect = event_count_after_replay != event_count_before_replay

    if not recovery_rejected:
        raise RuntimeError("WRONG_HASH_RECOVERY_WAS_NOT_REJECTED")
    if reexecute_side_effect:
        raise RuntimeError("WRONG_HASH_SIDE_EFFECT_REEXECUTED")
    if wal_status_after_replay != "PREPARED":
        raise RuntimeError("WRONG_HASH_WAL_DID_NOT_REMAIN_PREPARED")
    if after.get("wal_record_count") != 1:
        raise RuntimeError("WRONG_HASH_WAL_CARDINALITY_CHANGED")

    return {
        "scenario": "wrong_request_hash",
        "tool": _CANDIDATE_TOOL,
        "recovery_status": "RECONCILIATION_REQUIRED",
        "recovery_rejected": recovery_rejected,
        "reexecute_side_effect": reexecute_side_effect,
        "event_count_before_replay": event_count_before_replay,
        "event_count_after_replay": event_count_after_replay,
        "wal_status_before_replay": wal_status_before_replay,
        "wal_status_after_replay": wal_status_after_replay,
        "durable_correlation_id": durable_correlation_id,
        "wal_correlation_id": wal_correlation_id,
        "durable_request_sha256": durable_request_sha256,
        "wal_request_sha256": str(tampered["wal_records"][0].get("request_sha256") or ""),
    }
