from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable

from .core import digest
from .exact_checkout_live_acceptance_producer_v63 import (
    _anchor_success_arguments,
    _candidate_success_arguments,
    _opportunity_success_arguments,
    _start_synthetic_investigation,
)
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader


_OPPORTUNITY_TOOL = "create_product_opportunity"
_OPPORTUNITY_EVENT = "V63_PRODUCT_OPPORTUNITY_CREATED"
_ANCHOR_TOOL = "promote_opportunity_anchor"
_ANCHOR_EVENT = "V63_OPPORTUNITY_ANCHOR_PROMOTED"
_CANDIDATE_TOOL = "append_candidate_discovery"
_CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"


def _rewrite_single_event(
    persistence_root: Path,
    investigation_id: str,
    *,
    tool_name: str,
    event_type: str,
    mutate_payload: Callable[[dict[str, Any]], None],
) -> None:
    path = Path(persistence_root) / "sessions" / f"{investigation_id}.jsonl"
    if not path.is_file():
        raise RuntimeError("LIVE_EXTRA_SESSION_LOG_MISSING")

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError("LIVE_EXTRA_SESSION_EVENT_INVALID")
        rows.append(row)

    matches = [
        index
        for index, row in enumerate(rows)
        if row.get("event_type") == event_type
        and isinstance(row.get("mutation_correlation"), dict)
        and row["mutation_correlation"].get("tool") == tool_name
    ]
    if len(matches) != 1:
        raise RuntimeError("LIVE_EXTRA_EVENT_CARDINALITY_INVALID")

    index = matches[0]
    row = copy.deepcopy(rows[index])
    payload = copy.deepcopy(row.get("payload"))
    if not isinstance(payload, dict):
        raise RuntimeError("LIVE_EXTRA_EVENT_PAYLOAD_INVALID")
    mutate_payload(payload)
    row["payload"] = payload
    unsigned = {key: value for key, value in row.items() if key != "event_hash"}
    row["event_hash"] = digest(unsigned)
    rows[index] = row

    for next_index in range(index + 1, len(rows)):
        current = copy.deepcopy(rows[next_index])
        current["prev_hash"] = rows[next_index - 1]["event_hash"]
        unsigned = {key: value for key, value in current.items() if key != "event_hash"}
        current["event_hash"] = digest(unsigned)
        rows[next_index] = current

    temporary = path.with_suffix(path.suffix + ".live-extra.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        for item in rows:
            handle.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _replay_rejected(
    repo_root: Path,
    persistence_root: Path,
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> bool:
    harness = ExactCheckoutMcpHarness(repo_root, persistence_root)
    harness.start()
    rejected = False
    try:
        try:
            harness.tool(2, tool_name, arguments)
        except RuntimeError:
            rejected = True
    finally:
        harness.stop()
    return rejected


def _assert_crash_evidence(
    reader: ExactCheckoutPersistenceReader,
    investigation_id: str,
    tool_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence = reader.normalize_mutation_evidence(investigation_id, tool_name)
    events = list(evidence.get("events") or [])
    wal_records = list(evidence.get("wal_records") or [])
    if len(events) != 1 or len(wal_records) != 1:
        raise RuntimeError("LIVE_EXTRA_CRASH_EVIDENCE_CARDINALITY_FAILED")
    wal = wal_records[0]
    event = events[0]
    if wal.get("status") != "PREPARED":
        raise RuntimeError("LIVE_EXTRA_PREPARED_WAL_MISSING")
    correlation = str(wal.get("correlation_id") or "").strip()
    request_sha = str(wal.get("request_sha256") or "").strip()
    if not correlation or event.get("correlation_id") != correlation:
        raise RuntimeError("LIVE_EXTRA_CORRELATION_NOT_BOUND")
    if not request_sha or event.get("request_sha256") != request_sha:
        raise RuntimeError("LIVE_EXTRA_REQUEST_HASH_NOT_BOUND")
    return evidence, event, wal


def _finish_fail_closed_case(
    *,
    case: str,
    tool_name: str,
    reader: ExactCheckoutPersistenceReader,
    investigation_id: str,
    before_replay: dict[str, Any],
    recovery_rejected: bool,
    blocker: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    after = reader.normalize_mutation_evidence(investigation_id, tool_name)
    event_count_before = int(before_replay.get("event_count") or 0)
    event_count_after = int(after.get("event_count") or 0)
    wal_records_after = list(after.get("wal_records") or [])
    wal_status_after = (
        str(wal_records_after[0].get("status") or "")
        if len(wal_records_after) == 1
        else ""
    )
    reexecute_side_effect = event_count_after != event_count_before
    passed = bool(
        recovery_rejected
        and not reexecute_side_effect
        and len(wal_records_after) == 1
        and wal_status_after == "PREPARED"
    )
    if not passed:
        raise RuntimeError(f"LIVE_EXTRA_FAIL_CLOSED_CASE_FAILED:{case}")
    return {
        "case": case,
        "tool": tool_name,
        "passed": True,
        "status": "MUTATION_RECONCILIATION_REQUIRED",
        "blockers": [blocker],
        "recovery_action": "MUTATION_RECONCILIATION_REQUIRED",
        "recovery_rejected": recovery_rejected,
        "reexecute_side_effect": reexecute_side_effect,
        "event_count_before_replay": event_count_before,
        "event_count_after_replay": event_count_after,
        "wal_status_after_replay": wal_status_after,
        **copy.deepcopy(extra),
    }


def run_opportunity_snapshot_hash_mismatch_scenario(
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
            account_id="C-V63-EXTRA-OPPORTUNITY-HASH",
            name="Synthetic v6.3 Opportunity Snapshot Hash Mismatch",
            idempotency_key="v63-exact-extra-opportunity-start-0001",
        )
        arguments = _opportunity_success_arguments(investigation_id)
        arguments["idempotency_key"] = "v63-exact-extra-opportunity-hash-0001"
        crashing.crash_tool(3, _OPPORTUNITY_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    _, event_before, wal_before = _assert_crash_evidence(
        reader, investigation_id, _OPPORTUNITY_TOOL
    )
    correlation_before = str(event_before.get("correlation_id") or "")
    request_sha_before = str(event_before.get("request_sha256") or "")
    original_snapshot_sha = str(event_before.get("result_snapshot_sha256") or "")
    wrong_snapshot_sha = "f" * 64
    if wrong_snapshot_sha == original_snapshot_sha:
        wrong_snapshot_sha = "e" * 64

    _rewrite_single_event(
        persistence,
        investigation_id,
        tool_name=_OPPORTUNITY_TOOL,
        event_type=_OPPORTUNITY_EVENT,
        mutate_payload=lambda payload: payload.__setitem__(
            "result_snapshot_sha256", wrong_snapshot_sha
        ),
    )
    tampered = reader.normalize_mutation_evidence(investigation_id, _OPPORTUNITY_TOOL)
    tampered_event = (tampered.get("events") or [{}])[0]
    correlation_and_request_hash_preserved = bool(
        tampered_event.get("correlation_id") == correlation_before
        and tampered_event.get("request_sha256") == request_sha_before
        and tampered_event.get("result_snapshot_sha256") == wrong_snapshot_sha
        and wal_before.get("correlation_id") == correlation_before
        and wal_before.get("request_sha256") == request_sha_before
    )
    if not correlation_and_request_hash_preserved:
        raise RuntimeError("LIVE_EXTRA_OPPORTUNITY_TAMPER_NOT_PROVEN")

    rejected = _replay_rejected(
        root,
        persistence,
        tool_name=_OPPORTUNITY_TOOL,
        arguments=arguments,
    )
    return _finish_fail_closed_case(
        case="opportunity_snapshot_hash_mismatch_fails_closed",
        tool_name=_OPPORTUNITY_TOOL,
        reader=reader,
        investigation_id=investigation_id,
        before_replay=tampered,
        recovery_rejected=rejected,
        blocker="RESULT_SNAPSHOT_HASH_MISMATCH",
        extra={
            "correlation_and_request_hash_preserved": correlation_and_request_hash_preserved,
        },
    )


def run_anchor_failed_cycle_gate_scenario(
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
            account_id="C-V63-EXTRA-ANCHOR-CYCLE",
            name="Synthetic v6.3 Anchor Failed Cycle Gate",
            idempotency_key="v63-exact-extra-anchor-start-0001",
        )
        arguments = _anchor_success_arguments(investigation_id)
        arguments["idempotency_key"] = "v63-exact-extra-anchor-cycle-0001"
        crashing.crash_tool(3, _ANCHOR_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    _assert_crash_evidence(reader, investigation_id, _ANCHOR_TOOL)
    _rewrite_single_event(
        persistence,
        investigation_id,
        tool_name=_ANCHOR_TOOL,
        event_type=_ANCHOR_EVENT,
        mutate_payload=lambda payload: payload.__setitem__(
            "cycle_dedup_snapshot", {"cycle_dedup_complete": False}
        ),
    )
    tampered = reader.normalize_mutation_evidence(investigation_id, _ANCHOR_TOOL)
    raw_events = reader.read_session_events(investigation_id)
    matches = [
        row
        for row in raw_events
        if row.get("event_type") == _ANCHOR_EVENT
        and isinstance(row.get("mutation_correlation"), dict)
        and row["mutation_correlation"].get("tool") == _ANCHOR_TOOL
    ]
    payload = matches[0].get("payload") if len(matches) == 1 else None
    cycle_gate_tamper_proven = bool(
        isinstance(payload, dict)
        and payload.get("cycle_dedup_snapshot") == {"cycle_dedup_complete": False}
    )
    if not cycle_gate_tamper_proven:
        raise RuntimeError("LIVE_EXTRA_ANCHOR_CYCLE_TAMPER_NOT_PROVEN")

    rejected = _replay_rejected(
        root,
        persistence,
        tool_name=_ANCHOR_TOOL,
        arguments=arguments,
    )
    return _finish_fail_closed_case(
        case="anchor_failed_cycle_gate_fails_closed",
        tool_name=_ANCHOR_TOOL,
        reader=reader,
        investigation_id=investigation_id,
        before_replay=tampered,
        recovery_rejected=rejected,
        blocker="EVENT_CONSTRAINT_FAILED:cycle_dedup_snapshot.cycle_dedup_complete",
        extra={"cycle_gate_tamper_proven": cycle_gate_tamper_proven},
    )


def run_raw_idempotency_persistence_rejected_scenario(
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
            account_id="C-V63-EXTRA-RAW-FLAG",
            name="Synthetic v6.3 Raw Persistence Rejection",
            idempotency_key="v63-exact-extra-raw-start-0001",
        )
        arguments = _candidate_success_arguments(investigation_id)
        arguments["idempotency_key"] = "v63-exact-extra-raw-key-0001"
        crashing.crash_tool(3, _CANDIDATE_TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    _assert_crash_evidence(reader, investigation_id, _CANDIDATE_TOOL)
    _rewrite_single_event(
        persistence,
        investigation_id,
        tool_name=_CANDIDATE_TOOL,
        event_type=_CANDIDATE_EVENT,
        mutate_payload=lambda payload: payload.__setitem__(
            "raw_idempotency_key_persisted", True
        ),
    )
    tampered = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    raw_events = reader.read_session_events(investigation_id)
    matches = [
        row
        for row in raw_events
        if row.get("event_type") == _CANDIDATE_EVENT
        and isinstance(row.get("mutation_correlation"), dict)
        and row["mutation_correlation"].get("tool") == _CANDIDATE_TOOL
    ]
    payload = matches[0].get("payload") if len(matches) == 1 else None
    raw_persistence_flag_tamper_proven = bool(
        isinstance(payload, dict)
        and payload.get("raw_idempotency_key_persisted") is True
        and "idempotency_key" not in payload
    )
    if not raw_persistence_flag_tamper_proven:
        raise RuntimeError("LIVE_EXTRA_RAW_PERSISTENCE_TAMPER_NOT_PROVEN")

    rejected = _replay_rejected(
        root,
        persistence,
        tool_name=_CANDIDATE_TOOL,
        arguments=arguments,
    )
    return _finish_fail_closed_case(
        case="raw_idempotency_key_persistence_is_rejected",
        tool_name=_CANDIDATE_TOOL,
        reader=reader,
        investigation_id=investigation_id,
        before_replay=tampered,
        recovery_rejected=rejected,
        blocker="RAW_IDEMPOTENCY_KEY_PERSISTED",
        extra={
            "raw_persistence_flag_tamper_proven": raw_persistence_flag_tamper_proven,
        },
    )
