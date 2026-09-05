from __future__ import annotations

from typing import Any

from .recovery_acceptance_v63 import run_v63_reference_recovery_acceptance


def _required_cases() -> tuple[str, ...]:
    # The reference runner defines the deterministic semantic case inventory only;
    # its results are not production release proof.
    return tuple(str(row["case"]) for row in run_v63_reference_recovery_acceptance()["cases"])


def run_live_exact_recovery_acceptance(
    receipt_envelope: dict[str, Any],
    *,
    expected_production_source_snapshot_sha256: str,
) -> dict[str, Any]:
    payload = dict(receipt_envelope or {})
    blockers: list[str] = []
    if payload.get("schema") != "cbi.v63-live-exact-recovery-receipts.v1":
        blockers.append("LIVE_EXACT_RECOVERY_RECEIPT_ENVELOPE_SCHEMA_INVALID")

    rows = [dict(row or {}) for row in (payload.get("receipts") or [])]
    required = set(_required_cases())
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(str(row.get("case") or ""), []).append(row)
    actual = {name for name in by_case if name}
    if actual != required or any(len(by_case.get(name, [])) != 1 for name in required):
        blockers.append("EXACT_RECOVERY_RECEIPT_CASE_SET_INVALID")

    expected_sha = str(expected_production_source_snapshot_sha256 or "").lower()
    for row in rows:
        if row.get("execution_origin") != "LIVE_PRODUCTION_CHECKOUT":
            blockers.append("NON_LIVE_EXACT_RECOVERY_RECEIPT")
        if row.get("adapter_path_exercised") != "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH":
            blockers.append("ACTIVE_PRODUCTION_RECOVERY_PATH_NOT_EXERCISED")
        if str(row.get("production_source_snapshot_sha256") or "").lower() != expected_sha:
            blockers.append("EXACT_RECOVERY_RECEIPT_SOURCE_SNAPSHOT_MISMATCH")
        if row.get("passed") is not True:
            blockers.append("EXACT_RECOVERY_ACCEPTANCE_CASE_FAILED")
        if row.get("reexecute_side_effect") is not False:
            blockers.append("EXACT_RECOVERY_SIDE_EFFECT_REEXECUTION_OBSERVED")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        return {
            "schema": "cbi.v63-live-exact-recovery-run.v1",
            "status": "BLOCKED",
            "verified": False,
            "blockers": blockers,
        }

    cases: list[dict[str, Any]] = []
    for name in _required_cases():
        row = by_case[name][0]
        cases.append({
            "case": name,
            "passed": True,
            "status": row.get("status"),
            "blockers": list(row.get("blockers") or []),
            "recovery_action": row.get("recovery_action"),
            "reexecute_side_effect": False,
            "receipt_id": row.get("receipt_id"),
        })

    report = {
        "schema": "cbi.v63-recovery-acceptance.v1",
        "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
        "adapter_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH",
        "production_source_snapshot_sha256": expected_sha,
        "reference_runner_only": False,
        "passed": True,
        "case_count": len(cases),
        "passed_count": len(cases),
        "failed_count": 0,
        "cases": cases,
    }
    return {
        "schema": "cbi.v63-live-exact-recovery-run.v1",
        "status": "VERIFIED",
        "verified": True,
        "blockers": [],
        "report": report,
    }
