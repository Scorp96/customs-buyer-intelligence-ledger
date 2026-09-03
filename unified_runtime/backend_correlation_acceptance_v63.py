from __future__ import annotations

from typing import Any


REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS = (
    "CANDIDATE_SUCCESS_EVENT_CORRELATED",
    "CANDIDATE_RECOVERY_NO_REEXECUTION",
    "OPPORTUNITY_SUCCESS_SNAPSHOT_CORRELATED",
    "OPPORTUNITY_RECOVERY_EXACT_SNAPSHOT",
    "ANCHOR_SUCCESS_EVENT_CORRELATED",
    "ANCHOR_RECOVERY_NO_REEXECUTION",
    "WRONG_CORRELATION_FAILS_CLOSED",
    "WRONG_REQUEST_HASH_FAILS_CLOSED",
    "AMBIGUOUS_DUPLICATE_EVENT_FAILS_CLOSED",
    "DIFFERENT_KEY_CANNOT_CLAIM_RESULT",
)


def validate_v63_backend_correlation_acceptance(
    report: dict[str, Any],
    *,
    expected_production_source_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    payload = dict(report or {})
    blockers: list[str] = []

    if payload.get("schema") != "cbi.v63-backend-correlation-acceptance.v1":
        blockers.append("BACKEND_CORRELATION_SCHEMA_INVALID")
    if payload.get("adapter_path_exercised") != "EXISTING_PRODUCTION_INVOKE_MUTATION":
        blockers.append("PRODUCTION_ADAPTER_NOT_EXERCISED")
    if payload.get("runtime_store_exercised") != "EXISTING_PRODUCTION_APPEND_ONLY_STORE":
        blockers.append("PRODUCTION_DURABLE_STORE_NOT_EXERCISED")

    snapshot_sha256 = str(payload.get("production_source_snapshot_sha256") or "").lower()
    if len(snapshot_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot_sha256):
        blockers.append("PRODUCTION_SOURCE_SNAPSHOT_INVALID")
    if expected_production_source_snapshot_sha256 is not None:
        expected = str(expected_production_source_snapshot_sha256 or "").lower()
        if snapshot_sha256 != expected:
            blockers.append("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH")

    rows = [dict(v or {}) for v in (payload.get("scenarios") or [])]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(str(row.get("scenario") or ""), []).append(row)

    expected = set(REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS)
    actual = {name for name in by_name if name}
    if actual != expected or any(len(by_name.get(name, [])) != 1 for name in expected):
        blockers.append("BACKEND_CORRELATION_SCENARIOS_INCOMPLETE")

    passed_count = 0
    for name in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            continue
        row = matches[0]
        if row.get("status") != "PASS":
            blockers.append("BACKEND_CORRELATION_SCENARIO_FAILED")
            continue
        passed_count += 1
        if row.get("reexecute_side_effect") is not False:
            blockers.append("SIDE_EFFECT_REEXECUTION_OBSERVED")
        if row.get("exact_correlation_proven") is not True:
            blockers.append("EXACT_CORRELATION_NOT_PROVEN")
        if row.get("exact_request_hash_proven") is not True:
            blockers.append("EXACT_REQUEST_HASH_NOT_PROVEN")
        if row.get("cross_key_result_claimed") is not False:
            blockers.append("CROSS_KEY_RESULT_CLAIMING_OBSERVED")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "cbi.v63-backend-correlation-acceptance-validation.v1",
        "verified": not blockers,
        "status": "VERIFIED" if not blockers else "BLOCKED",
        "required_scenarios": list(REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS),
        "passed_count": passed_count,
        "production_source_snapshot_sha256": snapshot_sha256,
        "blockers": blockers,
        "side_effect_reexecution_allowed": False,
        "synthetic_or_reference_run_sufficient": False,
    }
