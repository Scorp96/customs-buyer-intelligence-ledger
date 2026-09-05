from __future__ import annotations

from typing import Any

from .recovery_overlay_acceptance_v63 import REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS


def _blocked(*blockers: str) -> dict[str, Any]:
    return {
        "schema": "cbi.v63-recovery-overlay-acceptance-builder.v1",
        "builder_status": "BLOCKED_INPUT",
        "builder_claims_verified": False,
        "builder_blockers": list(dict.fromkeys(blockers)),
    }


def build_v63_recovery_overlay_acceptance_report(
    receipts: list[dict[str, Any]],
    *,
    expected_production_source_snapshot_sha256: str,
    expected_recovery_registry_file: str,
    expected_recovery_registry_name: str,
) -> dict[str, Any]:
    rows = [dict(row or {}) for row in (receipts or [])]
    blockers: list[str] = []

    expected = set(REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(str(row.get("scenario") or ""), []).append(row)
    actual = {name for name in by_name if name}
    if actual != expected or any(len(by_name.get(name, [])) != 1 for name in expected):
        blockers.append("RECOVERY_RECEIPT_SCENARIO_SET_INVALID")

    for row in rows:
        if row.get("execution_origin") != "LIVE_PRODUCTION_CHECKOUT":
            blockers.append("NON_LIVE_RECOVERY_RECEIPT")
        if row.get("active_overlay_path_exercised") != "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN":
            blockers.append("RECOVERY_RECEIPT_ACTIVE_OVERLAY_PATH_INVALID")
        if str(row.get("production_source_snapshot_sha256") or "").lower() != str(expected_production_source_snapshot_sha256 or "").lower():
            blockers.append("RECOVERY_RECEIPT_SOURCE_SNAPSHOT_MISMATCH")
        if (
            str(row.get("recovery_registry_file") or "") != str(expected_recovery_registry_file or "")
            or str(row.get("recovery_registry_name") or "") != str(expected_recovery_registry_name or "")
        ):
            blockers.append("RECOVERY_RECEIPT_REGISTRY_MISMATCH")

    if blockers:
        return _blocked(*blockers)

    scenarios: list[dict[str, Any]] = []
    for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS:
        row = by_name[name][0]
        scenarios.append({
            "scenario": name,
            "status": row.get("status"),
            "active_overlay_handler_exercised": row.get("active_overlay_handler_exercised"),
            "reexecute_side_effect": row.get("reexecute_side_effect"),
            "exact_correlation_proven": row.get("exact_correlation_proven"),
            "exact_request_hash_proven": row.get("exact_request_hash_proven"),
            "exact_result_snapshot_proven": row.get("exact_result_snapshot_proven"),
            "receipt_id": row.get("receipt_id"),
        })

    return {
        "schema": "cbi.v63-recovery-overlay-acceptance.v1",
        "builder_status": "REPORT_BUILT_UNVERIFIED",
        "builder_claims_verified": False,
        "builder_blockers": [],
        "active_overlay_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
        "production_source_snapshot_sha256": str(expected_production_source_snapshot_sha256 or "").lower(),
        "recovery_registry_file": str(expected_recovery_registry_file or ""),
        "recovery_registry_name": str(expected_recovery_registry_name or ""),
        "reference_runner_only": False,
        "scenarios": scenarios,
    }
