from __future__ import annotations

from typing import Any

from .backend_correlation_acceptance_v63 import validate_v63_backend_correlation_acceptance
from .exact_recovery_acceptance_v63 import validate_v63_exact_recovery_acceptance
from .production_gate_v63 import evaluate_v63_production_gate
from .recovery_overlay_acceptance_v63 import validate_v63_recovery_overlay_acceptance
from .render_r2_pvc_acceptance_v63 import MUTATION_EVENT_TYPES
from .render_r2_pvc_acceptance_validator_v63 import (
    validate_v63_render_r2_pvc_acceptance,
)


def _validate_external_release_report(
    report: dict[str, Any] | None,
    *,
    schema: str,
    expected_production_source_snapshot_sha256: str,
    required_true_fields: tuple[str, ...],
    required_equal_fields: dict[str, Any] | None = None,
    required_false_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Legacy external-report validator retained for compatibility only.

    Task 11 no longer treats the former Render/R2/real-PVC report triplet as
    production-release authority. The authoritative external dependency is the
    real Render/R2/PVC acceptance receipt validated below.
    """
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


def _validate_render_r2_pvc_release_receipt(receipt: Any) -> dict[str, Any]:
    """Promote only a real deployed Render/R2/PVC receipt to release evidence."""
    base = validate_v63_render_r2_pvc_acceptance(receipt)
    blockers = list(base.get("blockers") or [])
    row = receipt if isinstance(receipt, dict) else {}

    if base.get("status") != "VERIFIED":
        if "RENDER_R2_PVC_BASE_VALIDATION_NOT_VERIFIED" not in blockers:
            blockers.append("RENDER_R2_PVC_BASE_VALIDATION_NOT_VERIFIED")
    if base.get("verified_mutation_count") != len(MUTATION_EVENT_TYPES):
        if "RENDER_R2_PVC_MUTATION_PROOF_INCOMPLETE" not in blockers:
            blockers.append("RENDER_R2_PVC_MUTATION_PROOF_INCOMPLETE")

    replacement = row.get("replacement") if isinstance(row.get("replacement"), dict) else {}
    instance_before = str(replacement.get("instance_before") or "").strip()
    instance_after = str(replacement.get("instance_after") or "").strip()
    if (
        not instance_before.startswith("dep-")
        or not instance_after.startswith("dep-")
        or instance_before == instance_after
    ):
        blockers.append("REAL_RENDER_INSTANCE_REPLACEMENT_NOT_PROVEN")

    identities: list[dict[str, Any]] = []
    for phase in ("health_before", "health_after"):
        health = row.get(phase) if isinstance(row.get(phase), dict) else {}
        identity = (
            health.get("deployment_identity")
            if isinstance(health.get("deployment_identity"), dict)
            else {}
        )
        identities.append(identity)
        if identity.get("remote_entrypoint") != "mcp/server_v61_remote.py":
            blockers.append(f"REAL_RENDER_REMOTE_ENTRYPOINT_NOT_PROVEN:{phase}")
        if identity.get("runtime_entrypoint") != "mcp/server_v61_backup_recovery.py":
            blockers.append(f"ACTIVE_RUNTIME_ENTRYPOINT_NOT_PROVEN:{phase}")

    deployment_git_sha = str(identities[0].get("git_sha") or "").strip().lower()
    after_git_sha = str(identities[1].get("git_sha") or "").strip().lower()
    protocol = row.get("protocol") if isinstance(row.get("protocol"), dict) else {}
    mutation_surface = (
        protocol.get("mutation_surface")
        if isinstance(protocol.get("mutation_surface"), dict)
        else {}
    )
    surface_git_sha = str(mutation_surface.get("deployment_git_sha") or "").strip().lower()
    if (
        not deployment_git_sha
        or deployment_git_sha != after_git_sha
        or deployment_git_sha != surface_git_sha
    ):
        blockers.append("DEPLOYMENT_GIT_SHA_BINDING_MISMATCH")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "cbi.v63-render-r2-pvc-release-evidence.v1",
        "verified": not blockers,
        "status": "VERIFIED" if not blockers else "BLOCKED",
        "deployment_git_sha": deployment_git_sha,
        "verified_mutation_count": base.get("verified_mutation_count"),
        "reference_local_mock_sufficient": False,
        "blockers": blockers,
        "base_validation": base,
    }


def evaluate_v63_release_evidence_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Assemble final production-release evidence from validated reports.

    Caller-supplied acceptance booleans are intentionally non-authoritative.
    Exact recovery, backend correlation, recovery overlay, and the real
    Render/R2/PVC deployment proof are derived from their underlying receipts.
    """
    payload = dict(bundle or {})
    current_snapshot = str(
        payload.get("current_production_source_snapshot_sha256") or ""
    ).lower()

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
    render_r2_pvc = _validate_render_r2_pvc_release_receipt(
        payload.get("render_r2_pvc_acceptance_report")
    )

    gate_payload = {
        "health": dict(payload.get("health") or {}),
        "contract": dict(payload.get("contract") or {}),
        "render_r2_pvc_acceptance_verified": bool(render_r2_pvc.get("verified")),
        "exact_v63_recovery_acceptance_verified": bool(exact.get("verified")),
        "live_v63_backend_correlation_acceptance_verified": bool(backend.get("verified")),
        "live_v63_backend_correlation_acceptance_snapshot_sha256": str(
            backend.get("production_source_snapshot_sha256") or ""
        ).lower(),
        "live_v63_recovery_overlay_acceptance_verified": bool(
            recovery_overlay.get("verified")
        ),
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
            "render_r2_pvc_acceptance": render_r2_pvc,
        },
        "derived_gate_payload": gate_payload,
        "production_gate": gate,
    }
