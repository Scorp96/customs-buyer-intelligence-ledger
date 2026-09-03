from __future__ import annotations

from typing import Any

from .recovery_overlay_acceptance_v63 import validate_v63_recovery_overlay_acceptance
from .recovery_overlay_report_builder_v63 import build_v63_recovery_overlay_acceptance_report


def run_live_recovery_overlay_acceptance(
    receipt_envelope: dict[str, Any],
    *,
    expected_production_source_snapshot_sha256: str,
    expected_recovery_registry_file: str,
    expected_recovery_registry_name: str,
) -> dict[str, Any]:
    payload = dict(receipt_envelope or {})
    if payload.get("schema") != "cbi.v63-live-recovery-overlay-receipts.v1":
        return {
            "schema": "cbi.v63-live-recovery-overlay-run.v1",
            "status": "BLOCKED",
            "verified": False,
            "blockers": ["LIVE_RECOVERY_RECEIPT_ENVELOPE_SCHEMA_INVALID"],
        }

    report = build_v63_recovery_overlay_acceptance_report(
        list(payload.get("receipts") or []),
        expected_production_source_snapshot_sha256=expected_production_source_snapshot_sha256,
        expected_recovery_registry_file=expected_recovery_registry_file,
        expected_recovery_registry_name=expected_recovery_registry_name,
    )
    if report.get("builder_status") != "REPORT_BUILT_UNVERIFIED":
        return {
            "schema": "cbi.v63-live-recovery-overlay-run.v1",
            "status": "BLOCKED",
            "verified": False,
            "blockers": list(report.get("builder_blockers") or []),
            "report_builder": report,
        }

    validation = validate_v63_recovery_overlay_acceptance(
        report,
        expected_production_source_snapshot_sha256=expected_production_source_snapshot_sha256,
        expected_recovery_registry_file=expected_recovery_registry_file,
        expected_recovery_registry_name=expected_recovery_registry_name,
    )
    return {
        "schema": "cbi.v63-live-recovery-overlay-run.v1",
        "status": "VERIFIED" if validation.get("verified") else "BLOCKED",
        "verified": bool(validation.get("verified")),
        "blockers": list(validation.get("blockers") or []),
        "report": report,
        "validation": validation,
    }
