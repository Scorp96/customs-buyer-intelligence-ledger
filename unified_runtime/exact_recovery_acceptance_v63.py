from __future__ import annotations

from typing import Any


REQUIRED_V63_EXACT_RECOVERY_CASES = (
    "candidate_exact_event_recovers",
    "candidate_wrong_correlation_fails_closed",
    "same_payload_different_key_cannot_claim",
    "candidate_wrong_request_hash_fails_closed",
    "duplicate_exact_event_fails_closed",
    "opportunity_exact_snapshot_recovers",
    "opportunity_snapshot_hash_mismatch_fails_closed",
    "anchor_exact_event_recovers",
    "anchor_failed_cycle_gate_fails_closed",
    "raw_idempotency_key_persistence_is_rejected",
)


def _valid_sha256(value: str) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def validate_v63_exact_recovery_acceptance(
    report: dict[str, Any] | None,
    *,
    expected_production_source_snapshot_sha256: str,
) -> dict[str, Any]:
    payload = dict(report or {})
    blockers: list[str] = []

    if payload.get("schema") != "cbi.v63-recovery-acceptance.v1":
        blockers.append("EXACT_RECOVERY_ACCEPTANCE_SCHEMA_INVALID")
    if payload.get("execution_origin") != "LIVE_PRODUCTION_CHECKOUT":
        blockers.append("LIVE_PRODUCTION_EXACT_RECOVERY_NOT_EXERCISED")
    if payload.get("adapter_path_exercised") != "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH":
        blockers.append("ACTIVE_PRODUCTION_RECOVERY_PATH_NOT_EXERCISED")
    if payload.get("reference_runner_only") is not False:
        blockers.append("REFERENCE_EXACT_RECOVERY_IS_NOT_RELEASE_PROOF")

    snapshot_sha = str(payload.get("production_source_snapshot_sha256") or "").lower()
    expected_sha = str(expected_production_source_snapshot_sha256 or "").lower()
    if not _valid_sha256(snapshot_sha):
        blockers.append("PRODUCTION_SOURCE_SNAPSHOT_INVALID")
    if snapshot_sha != expected_sha:
        blockers.append("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH")

    cases = [dict(row or {}) for row in (payload.get("cases") or [])]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in cases:
        by_name.setdefault(str(row.get("case") or ""), []).append(row)
    expected_cases = set(REQUIRED_V63_EXACT_RECOVERY_CASES)
    actual_cases = {name for name in by_name if name}
    if actual_cases != expected_cases or any(len(by_name.get(name, [])) != 1 for name in expected_cases):
        blockers.append("EXACT_RECOVERY_ACCEPTANCE_CASE_SET_INVALID")

    passed_count = 0
    for name in REQUIRED_V63_EXACT_RECOVERY_CASES:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            continue
        row = matches[0]
        if row.get("passed") is not True:
            blockers.append("EXACT_RECOVERY_ACCEPTANCE_CASE_FAILED")
            continue
        passed_count += 1
        if row.get("reexecute_side_effect") is not False:
            blockers.append("EXACT_RECOVERY_SIDE_EFFECT_REEXECUTION_OBSERVED")

    if payload.get("passed") is not True:
        blockers.append("EXACT_RECOVERY_ACCEPTANCE_FAILED")
    if int(payload.get("failed_count") or 0) != 0:
        blockers.append("EXACT_RECOVERY_ACCEPTANCE_HAS_FAILED_CASES")
    if int(payload.get("case_count") or 0) != len(REQUIRED_V63_EXACT_RECOVERY_CASES):
        blockers.append("EXACT_RECOVERY_ACCEPTANCE_CASE_COUNT_INVALID")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "cbi.v63-exact-recovery-acceptance-validation.v1",
        "verified": not blockers,
        "status": "VERIFIED" if not blockers else "BLOCKED",
        "required_cases": list(REQUIRED_V63_EXACT_RECOVERY_CASES),
        "passed_count": passed_count,
        "production_source_snapshot_sha256": snapshot_sha,
        "blockers": blockers,
        "reference_runner_sufficient": False,
        "side_effect_reexecution_allowed": False,
    }
