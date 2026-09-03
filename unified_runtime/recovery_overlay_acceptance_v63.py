from __future__ import annotations

from typing import Any


REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS = (
    "CANDIDATE_EXACT_EVENT_RECOVERS",
    "CANDIDATE_WRONG_CORRELATION_FAILS_CLOSED",
    "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS",
    "OPPORTUNITY_SNAPSHOT_HASH_MISMATCH_FAILS_CLOSED",
    "ANCHOR_EXACT_EVENT_RECOVERS",
    "AMBIGUOUS_EVENT_FAILS_CLOSED",
    "RAW_IDEMPOTENCY_KEY_REJECTED",
)


def _valid_sha256(value: str) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def validate_v63_recovery_overlay_acceptance(
    report: dict[str, Any],
    *,
    expected_production_source_snapshot_sha256: str | None = None,
    expected_recovery_registry_file: str | None = None,
    expected_recovery_registry_name: str | None = None,
) -> dict[str, Any]:
    payload = dict(report or {})
    blockers: list[str] = []

    if payload.get("schema") != "cbi.v63-recovery-overlay-acceptance.v1":
        blockers.append("RECOVERY_OVERLAY_ACCEPTANCE_SCHEMA_INVALID")
    if payload.get("active_overlay_path_exercised") != "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN":
        blockers.append("ACTIVE_PRODUCTION_RECOVERY_OVERLAY_NOT_EXERCISED")
    if payload.get("reference_runner_only") is not False:
        blockers.append("REFERENCE_RECOVERY_RUNNER_IS_NOT_LIVE_OVERLAY_PROOF")

    snapshot_sha = str(payload.get("production_source_snapshot_sha256") or "").lower()
    if not _valid_sha256(snapshot_sha):
        blockers.append("PRODUCTION_SOURCE_SNAPSHOT_INVALID")
    if expected_production_source_snapshot_sha256 is not None:
        if snapshot_sha != str(expected_production_source_snapshot_sha256 or "").lower():
            blockers.append("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH")

    registry_file = str(payload.get("recovery_registry_file") or "")
    registry_name = str(payload.get("recovery_registry_name") or "")
    if expected_recovery_registry_file is not None and registry_file != expected_recovery_registry_file:
        blockers.append("RECOVERY_REGISTRY_MISMATCH")
    if expected_recovery_registry_name is not None and registry_name != expected_recovery_registry_name:
        blockers.append("RECOVERY_REGISTRY_MISMATCH")

    rows = [dict(v or {}) for v in (payload.get("scenarios") or [])]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(str(row.get("scenario") or ""), []).append(row)

    expected = set(REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS)
    actual = {name for name in by_name if name}
    if actual != expected or any(len(by_name.get(name, [])) != 1 for name in expected):
        blockers.append("RECOVERY_OVERLAY_SCENARIOS_INCOMPLETE")

    passed_count = 0
    for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            continue
        row = matches[0]
        if row.get("status") != "PASS":
            blockers.append("RECOVERY_OVERLAY_SCENARIO_FAILED")
            continue
        passed_count += 1
        if row.get("active_overlay_handler_exercised") is not True:
            blockers.append("ACTIVE_RECOVERY_HANDLER_NOT_EXERCISED")
        if row.get("reexecute_side_effect") is not False:
            blockers.append("SIDE_EFFECT_REEXECUTION_OBSERVED")
        if row.get("exact_correlation_proven") is not True:
            blockers.append("EXACT_CORRELATION_NOT_PROVEN")
        if row.get("exact_request_hash_proven") is not True:
            blockers.append("EXACT_REQUEST_HASH_NOT_PROVEN")
        if name == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS" and row.get("exact_result_snapshot_proven") is not True:
            blockers.append("EXACT_RESULT_SNAPSHOT_NOT_PROVEN")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "cbi.v63-recovery-overlay-acceptance-validation.v1",
        "verified": not blockers,
        "status": "VERIFIED" if not blockers else "BLOCKED",
        "required_scenarios": list(REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS),
        "passed_count": passed_count,
        "production_source_snapshot_sha256": snapshot_sha,
        "recovery_registry_file": registry_file,
        "recovery_registry_name": registry_name,
        "blockers": blockers,
        "side_effect_reexecution_allowed": False,
        "reference_or_synthetic_run_sufficient": False,
    }
