from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .core import digest
from .exact_checkout_adversarial_scenarios_v63 import _replay_is_rejected
from .exact_checkout_live_acceptance_producer_v63 import _start_synthetic_investigation
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256


_TOOL = "append_candidate_discovery"
_EVENT = "V63_CANDIDATE_DISCOVERED"


def duplicate_exact_event_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "candidate": {
            "candidate_id": "CAND-V63-ADVERSARIAL-DUP-001",
            "discovered_from_anchor_id": "ANCHOR-V63-ADVERSARIAL-DUP-001",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_product_hs_application_buyer",
            "company_name": "Synthetic Duplicate Exact Event Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": "v63-exact-adversarial-duplicate-0001",
    }


def _append_duplicate_exact_event(persistence_root: Path, investigation_id: str) -> None:
    path = Path(persistence_root) / "sessions" / f"{investigation_id}.jsonl"
    if not path.is_file():
        raise RuntimeError("DUPLICATE_EVENT_SESSION_LOG_MISSING")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise RuntimeError("DUPLICATE_EVENT_SESSION_ROW_INVALID")
                rows.append(row)
    matches = [
        row
        for row in rows
        if row.get("event_type") == _EVENT
        and isinstance(row.get("mutation_correlation"), dict)
        and row["mutation_correlation"].get("tool") == _TOOL
    ]
    if len(matches) != 1 or not rows:
        raise RuntimeError("DUPLICATE_EVENT_SOURCE_CARDINALITY_INVALID")

    duplicate = copy.deepcopy(matches[0])
    duplicate["seq"] = int(rows[-1].get("seq") or 0) + 1
    duplicate["prev_hash"] = str(rows[-1].get("event_hash") or "")
    unsigned = {key: value for key, value in duplicate.items() if key != "event_hash"}
    duplicate["event_hash"] = digest(unsigned)

    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(duplicate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def _qualifying_events(evidence: dict[str, Any], correlation_id: str, request_sha: str) -> list[dict[str, Any]]:
    return [
        event
        for event in evidence.get("events") or []
        if event.get("event_type") == _EVENT
        and event.get("correlation_id") == correlation_id
        and event.get("request_sha256") == request_sha
    ]


def run_duplicate_exact_event_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()

    crashing = ExactCheckoutMcpHarness(root, persistence)
    crashing.start(crash_after_handler=_TOOL)
    try:
        investigation_id = _start_synthetic_investigation(
            crashing,
            2,
            account_id="C-V63-ADVERSARIAL-DUP",
            name="Synthetic v6.3 Duplicate Exact Event Buyer",
            idempotency_key="v63-exact-adversarial-duplicate-start-0001",
        )
        arguments = duplicate_exact_event_arguments(investigation_id)
        crashing.crash_tool(3, _TOOL, arguments)
    finally:
        crashing.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    before = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    if before.get("event_count") != 1 or before.get("wal_record_count") != 1:
        raise RuntimeError("DUPLICATE_EVENT_PRECONDITION_CARDINALITY_FAILED")
    wal = before["wal_records"][0]
    event = before["events"][0]
    if wal.get("status") != "PREPARED":
        raise RuntimeError("DUPLICATE_EVENT_PREPARED_WAL_MISSING")
    request_sha = canonical_v63_wal_request_sha256(_TOOL, arguments)
    correlation_id = str(wal.get("correlation_id") or "").strip()
    if (
        not correlation_id
        or event.get("correlation_id") != correlation_id
        or wal.get("request_sha256") != request_sha
        or event.get("request_sha256") != request_sha
    ):
        raise RuntimeError("DUPLICATE_EVENT_INITIAL_EXACT_BINDING_FAILED")

    _append_duplicate_exact_event(persistence, investigation_id)
    duplicated = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    qualifying_before = _qualifying_events(duplicated, correlation_id, request_sha)
    same_correlation_proven = len(qualifying_before) == 2 and all(
        item.get("correlation_id") == correlation_id for item in qualifying_before
    )
    same_request_hash_proven = len(qualifying_before) == 2 and all(
        item.get("request_sha256") == request_sha for item in qualifying_before
    )
    if not same_correlation_proven or not same_request_hash_proven:
        raise RuntimeError("DUPLICATE_EVENT_EXACT_DUPLICATE_NOT_PROVEN")

    recovery_rejected = _replay_is_rejected(root, persistence, arguments)
    after = reader.normalize_mutation_evidence(investigation_id, _TOOL)
    qualifying_after = _qualifying_events(after, correlation_id, request_sha)
    count_before = len(qualifying_before)
    count_after = len(qualifying_after)
    wal_status_before = str(duplicated["wal_records"][0].get("status") or "")
    wal_status_after = str(after["wal_records"][0].get("status") or "")
    reexecute_side_effect = count_after != count_before

    if not recovery_rejected:
        raise RuntimeError("DUPLICATE_EVENT_RECOVERY_WAS_NOT_REJECTED")
    if reexecute_side_effect:
        raise RuntimeError("DUPLICATE_EVENT_SIDE_EFFECT_REEXECUTED")
    if wal_status_before != "PREPARED" or wal_status_after != "PREPARED":
        raise RuntimeError("DUPLICATE_EVENT_WAL_DID_NOT_REMAIN_PREPARED")
    if after.get("wal_record_count") != 1:
        raise RuntimeError("DUPLICATE_EVENT_WAL_CARDINALITY_CHANGED")

    return {
        "scenario": "duplicate_exact_event",
        "tool": _TOOL,
        "recovery_status": "RECONCILIATION_REQUIRED",
        "recovery_rejected": recovery_rejected,
        "reexecute_side_effect": reexecute_side_effect,
        "qualifying_event_count_before_replay": count_before,
        "qualifying_event_count_after_replay": count_after,
        "wal_status_before_replay": wal_status_before,
        "wal_status_after_replay": wal_status_after,
        "same_correlation_proven": same_correlation_proven,
        "same_request_hash_proven": same_request_hash_proven,
    }
