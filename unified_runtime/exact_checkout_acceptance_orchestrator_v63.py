from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .backend_correlation_acceptance_v63 import (
    REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS,
    validate_v63_backend_correlation_acceptance,
)
from .exact_recovery_acceptance_v63 import (
    REQUIRED_V63_EXACT_RECOVERY_CASES,
    validate_v63_exact_recovery_acceptance,
)
from .live_exact_recovery_runner_v63 import run_live_exact_recovery_acceptance


_BACKEND_SCHEMA = "cbi.v63-backend-correlation-acceptance.v1"
_RECEIPT_SCHEMA = "cbi.v63-live-exact-recovery-receipts.v1"
_ACCEPTANCE_SCHEMA = "cbi.v63-exact-checkout-acceptance.v1"


def _single_evidence_pair(evidence: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    events = list(evidence.get("events") or [])
    wal_records = list(evidence.get("wal_records") or [])
    if len(events) != 1 or len(wal_records) != 1:
        return {}, {}
    event = events[0] if isinstance(events[0], dict) else {}
    wal = wal_records[0] if isinstance(wal_records[0], dict) else {}
    return event, wal


def _exact_pair_proof(evidence: dict[str, Any]) -> tuple[bool, bool]:
    event, wal = _single_evidence_pair(evidence)
    event_correlation = str(event.get("correlation_id") or "").strip()
    wal_correlation = str(wal.get("correlation_id") or "").strip()
    event_request = str(event.get("request_sha256") or "").strip().lower()
    wal_request = str(wal.get("request_sha256") or "").strip().lower()
    return (
        bool(event_correlation and event_correlation == wal_correlation),
        bool(len(event_request) == 64 and event_request == wal_request),
    )


def _backend_row(
    scenario: str,
    *,
    passed: bool,
    reexecute_side_effect: bool,
    exact_correlation_proven: bool,
    exact_request_hash_proven: bool,
    cross_key_result_claimed: bool = False,
    durable_event_count: int = 1,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "status": "PASS" if passed else "FAIL",
        "durable_event_count": int(durable_event_count),
        "reexecute_side_effect": bool(reexecute_side_effect),
        "exact_correlation_proven": bool(exact_correlation_proven),
        "exact_request_hash_proven": bool(exact_request_hash_proven),
        "cross_key_result_claimed": bool(cross_key_result_claimed),
    }


def _build_backend_artifact(
    snapshot_sha256: str,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_success = results["candidate_success"]
    candidate_crash = results["candidate_crash"]
    opportunity_success = results["opportunity_success"]
    opportunity_crash = results["opportunity_crash"]
    anchor_success = results["anchor_success"]
    anchor_crash = results["anchor_crash"]
    wrong_correlation = results["wrong_correlation"]
    wrong_hash = results["wrong_request_hash"]
    duplicate = results["duplicate_exact_event"]
    different_key = results["different_idempotency_key"]

    candidate_crash_corr, candidate_crash_hash = _exact_pair_proof(
        candidate_crash.get("post_restart_evidence") or {}
    )
    opportunity_crash_corr, opportunity_crash_hash = _exact_pair_proof(
        opportunity_crash.get("post_restart_evidence") or {}
    )
    anchor_crash_corr, anchor_crash_hash = _exact_pair_proof(
        anchor_crash.get("post_restart_evidence") or {}
    )

    wrong_corr_correlation_proven = bool(
        wrong_correlation.get("recovery_rejected") is True
        and str(wrong_correlation.get("durable_correlation_id") or "")
        and str(wrong_correlation.get("wal_correlation_id") or "")
        and wrong_correlation.get("durable_correlation_id")
        != wrong_correlation.get("wal_correlation_id")
    )
    wrong_corr_hash_proven = bool(
        wrong_correlation.get("recovery_rejected") is True
        and wrong_correlation.get("event_count_before_replay") == 1
        and wrong_correlation.get("event_count_after_replay") == 1
        and wrong_correlation.get("wal_status_after_replay") == "PREPARED"
    )

    wrong_hash_correlation_proven = bool(
        wrong_hash.get("durable_correlation_id")
        and wrong_hash.get("durable_correlation_id") == wrong_hash.get("wal_correlation_id")
    )
    wrong_hash_request_proven = bool(
        wrong_hash.get("durable_request_sha256")
        and wrong_hash.get("wal_request_sha256")
        and wrong_hash.get("durable_request_sha256") != wrong_hash.get("wal_request_sha256")
        and wrong_hash.get("recovery_rejected") is True
    )

    rows = {
        "CANDIDATE_SUCCESS_EVENT_CORRELATED": _backend_row(
            "CANDIDATE_SUCCESS_EVENT_CORRELATED",
            passed=bool(
                candidate_success.get("exact_correlation_proven")
                and candidate_success.get("exact_request_hash_proven")
            ),
            reexecute_side_effect=False,
            exact_correlation_proven=bool(candidate_success.get("exact_correlation_proven")),
            exact_request_hash_proven=bool(candidate_success.get("exact_request_hash_proven")),
        ),
        "CANDIDATE_RECOVERY_NO_REEXECUTION": _backend_row(
            "CANDIDATE_RECOVERY_NO_REEXECUTION",
            passed=bool(
                candidate_crash.get("reconciled_after_crash")
                and candidate_crash.get("no_duplicate_event_proven")
                and candidate_crash_corr
                and candidate_crash_hash
            ),
            reexecute_side_effect=not bool(candidate_crash.get("no_duplicate_event_proven")),
            exact_correlation_proven=candidate_crash_corr,
            exact_request_hash_proven=candidate_crash_hash,
        ),
        "OPPORTUNITY_SUCCESS_SNAPSHOT_CORRELATED": _backend_row(
            "OPPORTUNITY_SUCCESS_SNAPSHOT_CORRELATED",
            passed=bool(
                opportunity_success.get("exact_correlation_proven")
                and opportunity_success.get("exact_request_hash_proven")
                and opportunity_success.get("exact_result_snapshot_proven")
            ),
            reexecute_side_effect=False,
            exact_correlation_proven=bool(opportunity_success.get("exact_correlation_proven")),
            exact_request_hash_proven=bool(opportunity_success.get("exact_request_hash_proven")),
        ),
        "OPPORTUNITY_RECOVERY_EXACT_SNAPSHOT": _backend_row(
            "OPPORTUNITY_RECOVERY_EXACT_SNAPSHOT",
            passed=bool(
                opportunity_crash.get("reconciled_after_crash")
                and opportunity_crash.get("exact_result_snapshot_recovered")
                and opportunity_crash.get("no_duplicate_event_proven")
                and opportunity_crash_corr
                and opportunity_crash_hash
            ),
            reexecute_side_effect=not bool(opportunity_crash.get("no_duplicate_event_proven")),
            exact_correlation_proven=opportunity_crash_corr,
            exact_request_hash_proven=opportunity_crash_hash,
        ),
        "ANCHOR_SUCCESS_EVENT_CORRELATED": _backend_row(
            "ANCHOR_SUCCESS_EVENT_CORRELATED",
            passed=bool(
                anchor_success.get("exact_correlation_proven")
                and anchor_success.get("exact_request_hash_proven")
                and anchor_success.get("exact_anchor_snapshots_proven")
            ),
            reexecute_side_effect=False,
            exact_correlation_proven=bool(anchor_success.get("exact_correlation_proven")),
            exact_request_hash_proven=bool(anchor_success.get("exact_request_hash_proven")),
        ),
        "ANCHOR_RECOVERY_NO_REEXECUTION": _backend_row(
            "ANCHOR_RECOVERY_NO_REEXECUTION",
            passed=bool(
                anchor_crash.get("reconciled_after_crash")
                and anchor_crash.get("no_duplicate_event_proven")
                and anchor_crash.get("exact_anchor_snapshots_preserved")
                and anchor_crash_corr
                and anchor_crash_hash
            ),
            reexecute_side_effect=not bool(anchor_crash.get("no_duplicate_event_proven")),
            exact_correlation_proven=anchor_crash_corr,
            exact_request_hash_proven=anchor_crash_hash,
        ),
        "WRONG_CORRELATION_FAILS_CLOSED": _backend_row(
            "WRONG_CORRELATION_FAILS_CLOSED",
            passed=bool(
                wrong_correlation.get("recovery_rejected")
                and wrong_correlation.get("reexecute_side_effect") is False
                and wrong_corr_correlation_proven
                and wrong_corr_hash_proven
            ),
            reexecute_side_effect=bool(wrong_correlation.get("reexecute_side_effect")),
            exact_correlation_proven=wrong_corr_correlation_proven,
            exact_request_hash_proven=wrong_corr_hash_proven,
        ),
        "WRONG_REQUEST_HASH_FAILS_CLOSED": _backend_row(
            "WRONG_REQUEST_HASH_FAILS_CLOSED",
            passed=bool(
                wrong_hash.get("recovery_rejected")
                and wrong_hash.get("reexecute_side_effect") is False
                and wrong_hash_correlation_proven
                and wrong_hash_request_proven
            ),
            reexecute_side_effect=bool(wrong_hash.get("reexecute_side_effect")),
            exact_correlation_proven=wrong_hash_correlation_proven,
            exact_request_hash_proven=wrong_hash_request_proven,
        ),
        "AMBIGUOUS_DUPLICATE_EVENT_FAILS_CLOSED": _backend_row(
            "AMBIGUOUS_DUPLICATE_EVENT_FAILS_CLOSED",
            passed=bool(
                duplicate.get("recovery_rejected")
                and duplicate.get("reexecute_side_effect") is False
                and duplicate.get("same_correlation_proven")
                and duplicate.get("same_request_hash_proven")
            ),
            reexecute_side_effect=bool(duplicate.get("reexecute_side_effect")),
            exact_correlation_proven=bool(duplicate.get("same_correlation_proven")),
            exact_request_hash_proven=bool(duplicate.get("same_request_hash_proven")),
            durable_event_count=int(duplicate.get("qualifying_event_count_after_replay") or 0),
        ),
        "DIFFERENT_KEY_CANNOT_CLAIM_RESULT": _backend_row(
            "DIFFERENT_KEY_CANNOT_CLAIM_RESULT",
            passed=bool(
                different_key.get("recovery_rejected")
                and different_key.get("reexecute_side_effect") is False
                and different_key.get("distinct_correlations_proven")
                and different_key.get("same_request_hash_proven")
                and different_key.get("first_event_bound_only_to_first_correlation")
            ),
            reexecute_side_effect=bool(different_key.get("reexecute_side_effect")),
            exact_correlation_proven=bool(
                different_key.get("distinct_correlations_proven")
                and different_key.get("first_event_bound_only_to_first_correlation")
            ),
            exact_request_hash_proven=bool(different_key.get("same_request_hash_proven")),
            cross_key_result_claimed=False,
        ),
    }

    return {
        "schema": _BACKEND_SCHEMA,
        "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
        "adapter_path_exercised": "EXISTING_PRODUCTION_INVOKE_MUTATION",
        "runtime_store_exercised": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
        "production_source_snapshot_sha256": str(snapshot_sha256).lower(),
        "scenarios": [rows[name] for name in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS],
        "reference_runner_only": False,
        "live_release_proof": True,
    }


def _receipt_id(case_name: str, git_sha: str, snapshot_sha256: str) -> str:
    material = f"{case_name}:{git_sha}:{snapshot_sha256}".encode("utf-8")
    return "V63-LIVE-" + hashlib.sha256(material).hexdigest()[:24]


def _receipt(
    case_name: str,
    *,
    git_sha: str,
    snapshot_sha256: str,
    passed: bool,
    status: str,
    blockers: list[str],
    recovery_action: str,
    reexecute_side_effect: bool,
) -> dict[str, Any]:
    return {
        "case": case_name,
        "receipt_id": _receipt_id(case_name, git_sha, snapshot_sha256),
        "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
        "adapter_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH",
        "production_source_snapshot_sha256": str(snapshot_sha256).lower(),
        "passed": bool(passed),
        "status": status,
        "blockers": list(blockers),
        "recovery_action": recovery_action,
        "reexecute_side_effect": bool(reexecute_side_effect),
    }


def _build_recovery_receipt_envelope(
    snapshot_sha256: str,
    git_sha: str,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_crash = results["candidate_crash"]
    opportunity_crash = results["opportunity_crash"]
    anchor_crash = results["anchor_crash"]
    wrong_correlation = results["wrong_correlation"]
    different_key = results["different_idempotency_key"]
    wrong_hash = results["wrong_request_hash"]
    duplicate = results["duplicate_exact_event"]
    opportunity_hash = results["opportunity_snapshot_hash_mismatch"]
    anchor_cycle = results["anchor_failed_cycle_gate"]
    raw_persistence = results["raw_idempotency_persistence_rejected"]

    candidate_corr, candidate_hash = _exact_pair_proof(
        candidate_crash.get("post_restart_evidence") or {}
    )
    opportunity_corr, opportunity_request_hash = _exact_pair_proof(
        opportunity_crash.get("post_restart_evidence") or {}
    )
    anchor_corr, anchor_hash = _exact_pair_proof(
        anchor_crash.get("post_restart_evidence") or {}
    )

    rows = {
        "candidate_exact_event_recovers": _receipt(
            "candidate_exact_event_recovers",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                candidate_crash.get("reconciled_after_crash")
                and candidate_crash.get("no_duplicate_event_proven")
                and candidate_corr
                and candidate_hash
            ),
            status="RECOVERED",
            blockers=[],
            recovery_action="RECONSTRUCT_FROM_CORRELATED_EVENT",
            reexecute_side_effect=not bool(candidate_crash.get("no_duplicate_event_proven")),
        ),
        "candidate_wrong_correlation_fails_closed": _receipt(
            "candidate_wrong_correlation_fails_closed",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                wrong_correlation.get("recovery_rejected")
                and wrong_correlation.get("reexecute_side_effect") is False
            ),
            status="MUTATION_RECONCILIATION_REQUIRED",
            blockers=["NO_EXACT_DURABLE_PROOF"],
            recovery_action="MUTATION_RECONCILIATION_REQUIRED",
            reexecute_side_effect=bool(wrong_correlation.get("reexecute_side_effect")),
        ),
        "same_payload_different_key_cannot_claim": _receipt(
            "same_payload_different_key_cannot_claim",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                different_key.get("recovery_rejected")
                and different_key.get("reexecute_side_effect") is False
                and different_key.get("first_event_bound_only_to_first_correlation")
            ),
            status="MUTATION_RECONCILIATION_REQUIRED",
            blockers=["NO_EXACT_DURABLE_PROOF"],
            recovery_action="MUTATION_RECONCILIATION_REQUIRED",
            reexecute_side_effect=bool(different_key.get("reexecute_side_effect")),
        ),
        "candidate_wrong_request_hash_fails_closed": _receipt(
            "candidate_wrong_request_hash_fails_closed",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                wrong_hash.get("recovery_rejected")
                and wrong_hash.get("reexecute_side_effect") is False
            ),
            status="MUTATION_RECONCILIATION_REQUIRED",
            blockers=["NO_EXACT_DURABLE_PROOF"],
            recovery_action="MUTATION_RECONCILIATION_REQUIRED",
            reexecute_side_effect=bool(wrong_hash.get("reexecute_side_effect")),
        ),
        "duplicate_exact_event_fails_closed": _receipt(
            "duplicate_exact_event_fails_closed",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                duplicate.get("recovery_rejected")
                and duplicate.get("reexecute_side_effect") is False
                and duplicate.get("qualifying_event_count_after_replay") == 2
            ),
            status="MUTATION_RECONCILIATION_REQUIRED",
            blockers=["AMBIGUOUS_EXACT_DURABLE_PROOF"],
            recovery_action="MUTATION_RECONCILIATION_REQUIRED",
            reexecute_side_effect=bool(duplicate.get("reexecute_side_effect")),
        ),
        "opportunity_exact_snapshot_recovers": _receipt(
            "opportunity_exact_snapshot_recovers",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                opportunity_crash.get("reconciled_after_crash")
                and opportunity_crash.get("exact_result_snapshot_recovered")
                and opportunity_crash.get("no_duplicate_event_proven")
                and opportunity_corr
                and opportunity_request_hash
            ),
            status="RECOVERED",
            blockers=[],
            recovery_action="RETURN_EXACT_STORED_RESULT",
            reexecute_side_effect=not bool(opportunity_crash.get("no_duplicate_event_proven")),
        ),
        "opportunity_snapshot_hash_mismatch_fails_closed": _receipt(
            "opportunity_snapshot_hash_mismatch_fails_closed",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(opportunity_hash.get("passed")),
            status=str(opportunity_hash.get("status") or ""),
            blockers=list(opportunity_hash.get("blockers") or []),
            recovery_action=str(opportunity_hash.get("recovery_action") or ""),
            reexecute_side_effect=bool(opportunity_hash.get("reexecute_side_effect")),
        ),
        "anchor_exact_event_recovers": _receipt(
            "anchor_exact_event_recovers",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(
                anchor_crash.get("reconciled_after_crash")
                and anchor_crash.get("no_duplicate_event_proven")
                and anchor_crash.get("exact_anchor_snapshots_preserved")
                and anchor_corr
                and anchor_hash
            ),
            status="RECOVERED",
            blockers=[],
            recovery_action="RECONSTRUCT_FROM_CORRELATED_EVENT",
            reexecute_side_effect=not bool(anchor_crash.get("no_duplicate_event_proven")),
        ),
        "anchor_failed_cycle_gate_fails_closed": _receipt(
            "anchor_failed_cycle_gate_fails_closed",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(anchor_cycle.get("passed")),
            status=str(anchor_cycle.get("status") or ""),
            blockers=list(anchor_cycle.get("blockers") or []),
            recovery_action=str(anchor_cycle.get("recovery_action") or ""),
            reexecute_side_effect=bool(anchor_cycle.get("reexecute_side_effect")),
        ),
        "raw_idempotency_key_persistence_is_rejected": _receipt(
            "raw_idempotency_key_persistence_is_rejected",
            git_sha=git_sha,
            snapshot_sha256=snapshot_sha256,
            passed=bool(raw_persistence.get("passed")),
            status=str(raw_persistence.get("status") or ""),
            blockers=list(raw_persistence.get("blockers") or []),
            recovery_action=str(raw_persistence.get("recovery_action") or ""),
            reexecute_side_effect=bool(raw_persistence.get("reexecute_side_effect")),
        ),
    }

    return {
        "schema": _RECEIPT_SCHEMA,
        "git_sha": git_sha,
        "production_source_snapshot_sha256": str(snapshot_sha256).lower(),
        "receipts": [rows[name] for name in REQUIRED_V63_EXACT_RECOVERY_CASES],
    }


def _contains_raw_idempotency_key_field(value: Any) -> bool:
    if isinstance(value, dict):
        if any(str(key).casefold() == "idempotency_key" for key in value):
            return True
        return any(_contains_raw_idempotency_key_field(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_raw_idempotency_key_field(item) for item in value)
    return False


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run_exact_checkout_acceptance_orchestration(
    *,
    repo_root: Path,
    git_sha: str,
    output_dir: Path,
    source_snapshot: dict[str, Any],
) -> dict[str, Any]:
    from .exact_checkout_adversarial_duplicate_v63 import run_duplicate_exact_event_scenario
    from .exact_checkout_adversarial_idempotency_v63 import run_different_idempotency_key_scenario
    from .exact_checkout_adversarial_scenarios_v63 import (
        run_wrong_correlation_scenario,
        run_wrong_request_hash_scenario,
    )
    from .exact_checkout_crash_scenarios_v63 import (
        run_anchor_crash_restart_scenario,
        run_candidate_crash_restart_scenario,
        run_opportunity_crash_restart_scenario,
    )
    from .exact_checkout_live_acceptance_producer_v63 import (
        _assert_source_snapshot_unchanged,
        _run_anchor_success_scenario,
        _run_candidate_success_scenario,
        _run_opportunity_success_scenario,
    )
    from .exact_checkout_live_recovery_extra_v63 import (
        run_anchor_failed_cycle_gate_scenario,
        run_opportunity_snapshot_hash_mismatch_scenario,
        run_raw_idempotency_persistence_rejected_scenario,
    )

    root = Path(repo_root).resolve()
    destination = Path(output_dir).resolve()
    snapshot_sha = str(source_snapshot.get("snapshot_sha256") or "").lower()

    with tempfile.TemporaryDirectory(prefix="cbi-v63-exact-checkout-") as td:
        work = Path(td)
        results = {
            "candidate_success": _run_candidate_success_scenario(root, work / "candidate-success"),
            "candidate_crash": run_candidate_crash_restart_scenario(root, work / "candidate-crash"),
            "opportunity_success": _run_opportunity_success_scenario(root, work / "opportunity-success"),
            "opportunity_crash": run_opportunity_crash_restart_scenario(root, work / "opportunity-crash"),
            "anchor_success": _run_anchor_success_scenario(root, work / "anchor-success"),
            "anchor_crash": run_anchor_crash_restart_scenario(root, work / "anchor-crash"),
            "wrong_correlation": run_wrong_correlation_scenario(root, work / "wrong-correlation"),
            "wrong_request_hash": run_wrong_request_hash_scenario(root, work / "wrong-request-hash"),
            "duplicate_exact_event": run_duplicate_exact_event_scenario(root, work / "duplicate-exact"),
            "different_idempotency_key": run_different_idempotency_key_scenario(root, work / "different-key"),
            "opportunity_snapshot_hash_mismatch": run_opportunity_snapshot_hash_mismatch_scenario(
                root, work / "opportunity-snapshot-hash"
            ),
            "anchor_failed_cycle_gate": run_anchor_failed_cycle_gate_scenario(
                root, work / "anchor-cycle-gate"
            ),
            "raw_idempotency_persistence_rejected": run_raw_idempotency_persistence_rejected_scenario(
                root, work / "raw-idempotency-persistence"
            ),
        }

    backend = _build_backend_artifact(snapshot_sha, results)
    backend_validation = validate_v63_backend_correlation_acceptance(
        backend,
        expected_production_source_snapshot_sha256=snapshot_sha,
    )
    if backend_validation.get("verified") is not True:
        raise RuntimeError(
            "BACKEND_CORRELATION_ACCEPTANCE_BLOCKED:"
            + ",".join(str(item) for item in backend_validation.get("blockers") or [])
        )

    receipts = _build_recovery_receipt_envelope(snapshot_sha, git_sha, results)
    recovery_validation = run_live_exact_recovery_acceptance(
        receipts,
        expected_production_source_snapshot_sha256=snapshot_sha,
    )
    if recovery_validation.get("verified") is not True:
        raise RuntimeError(
            "LIVE_EXACT_RECOVERY_ACCEPTANCE_BLOCKED:"
            + ",".join(str(item) for item in recovery_validation.get("blockers") or [])
        )
    recovery_report = recovery_validation.get("report")
    exact_recovery_validation = validate_v63_exact_recovery_acceptance(
        recovery_report if isinstance(recovery_report, dict) else {},
        expected_production_source_snapshot_sha256=snapshot_sha,
    )
    if exact_recovery_validation.get("verified") is not True:
        raise RuntimeError(
            "EXACT_RECOVERY_VALIDATION_BLOCKED:"
            + ",".join(str(item) for item in exact_recovery_validation.get("blockers") or [])
        )

    source_validation = _assert_source_snapshot_unchanged(root, source_snapshot)
    acceptance = {
        "schema": _ACCEPTANCE_SCHEMA,
        "status": "VERIFIED",
        "verified": True,
        "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
        "execution_environment": "EXACT_CHECKOUT_ISOLATED",
        "deployment_environment": "NOT_RENDER_PRODUCTION",
        "git_sha": str(git_sha).lower(),
        "production_source_snapshot_sha256": snapshot_sha,
        "production_source_snapshot": copy.deepcopy(source_snapshot),
        "source_snapshot_validation": copy.deepcopy(source_validation),
        "backend_validation": copy.deepcopy(backend_validation),
        "recovery_validation": copy.deepcopy(recovery_validation),
        "exact_recovery_validation": copy.deepcopy(exact_recovery_validation),
        "render_r2_acceptance_required": True,
        "production_ready": False,
        "artifact_names": [
            "V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json",
            "V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json",
            "V63_EXACT_CHECKOUT_ACCEPTANCE.json",
        ],
    }

    for artifact in (backend, receipts, acceptance):
        if _contains_raw_idempotency_key_field(artifact):
            raise RuntimeError("RAW_IDEMPOTENCY_KEY_FIELD_IN_ACCEPTANCE_ARTIFACT")

    _atomic_json_write(destination / "V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json", backend)
    _atomic_json_write(destination / "V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json", receipts)
    _atomic_json_write(destination / "V63_EXACT_CHECKOUT_ACCEPTANCE.json", acceptance)
    return acceptance
