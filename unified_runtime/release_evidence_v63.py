from __future__ import annotations

from typing import Any

from .backend_correlation_acceptance_v63 import validate_v63_backend_correlation_acceptance
from .exact_recovery_acceptance_v63 import validate_v63_exact_recovery_acceptance
from .production_gate_v63 import evaluate_v63_production_gate
from .recovery_overlay_acceptance_v63 import validate_v63_recovery_overlay_acceptance



def _validate_external_release_report(
    report: dict[str, Any] | None,
    *,
    schema: str,
    expected_production_source_snapshot_sha256: str,
    required_true_fields: tuple[str, ...],
    required_equal_fields: dict[str, Any] | None = None,
    required_false_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload = dict(report or {})
    blockers: list[str] = []
    if payload.get("schema") != schema:
        blockers.append("EXTERNAL_EVIDENCE_SCHEMA_INVALID")
    if payload.get("verified") is not True:
        blockers.append("EXTERNAL_EVIDENCE_NOT_VERIFIED")
    snapshot = str(payload.get("production_source_snapshot_sha256") or "").lower()
    expected = str(expected_production_source_snapshot_sha256 or "").lower()
    if snapshot != expected or len(snapshot) != 64:
        blockers.append("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH")
    for field in required_true_fields:
        if payload.get(field) is not True:
            blockers.append(f"REQUIRED_TRUE_FIELD_MISSING:{field}")
    for field in required_false_fields:
        if payload.get(field) is not False:
            blockers.append(f"REQUIRED_FALSE_FIELD_MISMATCH:{field}")
    for field, value in dict(required_equal_fields or {}).items():
        if payload.get(field) != value:
            blockers.append(f"REQUIRED_VALUE_MISMATCH:{field}")
    blockers = list(dict.fromkeys(blockers))
    return {
        "verified": not blockers,
        "status": "VERIFIED" if not blockers else "BLOCKED",
        "schema": schema,
        "production_source_snapshot_sha256": snapshot,
        "blockers": blockers,
    }

def evaluate_v63_release_evidence_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Assemble final production-release evidence from validated reports.

    Caller-supplied acceptance booleans are intentionally non-authoritative. The
    exact-recovery, live backend-correlation and live recovery-overlay flags sent
    to the production gate are derived only from the corresponding reports.
    """
    payload = dict(bundle or {})
    current_snapshot = str(payload.get("current_production_source_snapshot_sha256") or "").lower()

    exact = validate_v63_exact_recovery_acceptance(
        payload.get("exact_recovery_acceptance_report"),
        expected_production_source_snapshot_sha256=current_snapshot,
    )
    backend = validate_v63_backend_correlation_acceptance(
        payload.get("backend_correlation_acceptance_report") or {},
        expected_production_source_snapshot_sha256=current_snapshot,
    )
    recovery_overlay = validate_v63_recovery_overlay_acceptance(
        payload.get("recovery_overlay_acceptance_report") or {},
        expected_production_source_snapshot_sha256=current_snapshot,
    )
    render_deploy = _validate_external_release_report(
        payload.get("render_deploy_evidence_report"),
        schema="cbi.v63-render-deploy-evidence.v1",
        expected_production_source_snapshot_sha256=current_snapshot,
        required_true_fields=("production_service_observed", "runtime_contract_observed"),
    )
    r2_restore = _validate_external_release_report(
        payload.get("r2_restore_evidence_report"),
        schema="cbi.v63-r2-restore-evidence.v1",
        expected_production_source_snapshot_sha256=current_snapshot,
        required_true_fields=("restore_roundtrip_passed", "append_only_state_preserved"),
    )
    real_pvc = _validate_external_release_report(
        payload.get("real_pvc_acceptance_evidence_report"),
        schema="cbi.v63-real-pvc-acceptance-evidence.v1",
        expected_production_source_snapshot_sha256=current_snapshot,
        required_true_fields=("real_customs_seed", "demand_expansion_pipeline_exercised"),
        required_equal_fields={"product_profile_id": "PVC"},
        required_false_fields=("synthetic_seed",),
    )

    gate_payload = {
        "health": dict(payload.get("health") or {}),
        "contract": dict(payload.get("contract") or {}),
        "render_deploy_verified": bool(render_deploy.get("verified")),
        "r2_restore_verified": bool(r2_restore.get("verified")),
        "real_pvc_acceptance_verified": bool(real_pvc.get("verified")),
        "exact_v63_recovery_acceptance_verified": bool(exact.get("verified")),
        "live_v63_backend_correlation_acceptance_verified": bool(backend.get("verified")),
        "live_v63_backend_correlation_acceptance_snapshot_sha256": str(
            backend.get("production_source_snapshot_sha256") or ""
        ).lower(),
        "live_v63_recovery_overlay_acceptance_verified": bool(recovery_overlay.get("verified")),
        "live_v63_recovery_overlay_acceptance_snapshot_sha256": str(
            recovery_overlay.get("production_source_snapshot_sha256") or ""
        ).lower(),
        "current_production_source_snapshot_sha256": current_snapshot,
    }
    gate = evaluate_v63_production_gate(gate_payload)

    return {
        "schema": "cbi.v63-release-evidence-assembly.v1",
        "status": gate.get("status"),
        "production_ready": bool(gate.get("production_ready")),
        "caller_verified_flags_ignored": True,
        "component_validations": {
            "exact_recovery": exact,
            "backend_correlation": backend,
            "recovery_overlay": recovery_overlay,
            "render_deploy": render_deploy,
            "r2_restore": r2_restore,
            "real_pvc_acceptance": real_pvc,
        },
        "derived_gate_payload": gate_payload,
        "production_gate": gate,
    }
