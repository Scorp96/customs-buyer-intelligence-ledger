from __future__ import annotations

from pathlib import Path
from typing import Any

from .production_checkout_probe import probe_production_checkout
from .wal_contract_v63 import V63_WAL_BINDINGS
from .mcp_entrypoint_v63 import resolve_active_mcp_entrypoint
from .adapter_source_probe_v63 import inspect_production_adapter_structure
from .runtime_backend_binding_plan_v63 import build_v63_runtime_backend_binding_plan
from .recovery_overlay_probe_v63 import probe_v63_recovery_overlay
from .recovery_overlay_acceptance_v63 import validate_v63_recovery_overlay_acceptance


_resolve_active_mcp_entrypoint = resolve_active_mcp_entrypoint
_EXPECTED_PREPATCH_GAPS = {"V63_MUTATION_INVENTORY_INCOMPLETE"}

# Explicit v6.3-owned payload boundary; never infer ownership from directory contents.
V63_RUNTIME_PAYLOAD_NAMES = (
    "adapter_patch_compiler_v63.py",
    "adapter_patch_recipe_v63.py",
    "adapter_recovery_mapping_v63.py",
    "adapter_source_probe_v63.py",
    "backend_correlation_acceptance_v63.py",
    "branch_signal_policy.py",
    "buyer_archetypes.py",
    "candidate_anchor.py",
    "candidate_research_gate.py",
    "canonical_resolution_gate.py",
    "capability_profile.py",
    "contact_exhaustion.py",
    "contact_source_execution.py",
    "contract_v63.py",
    "crm_projection.py",
    "demand_evidence.py",
    "demand_expansion.py",
    "demand_market.py",
    "demand_pipeline.py",
    "exact_recovery_acceptance_v63.py",
    "existing_production_store_backend_v63.py",
    "expansion_planner.py",
    "legacy_peer_projection.py",
    "live_contract_validator_v63.py",
    "live_exact_recovery_runner_v63.py",
    "live_recovery_overlay_runner_v63.py",
    "local_context_resolution.py",
    "local_outreach_policy.py",
    "market_scope.py",
    "mcp_entrypoint_v63.py",
    "mcp_schema_v63.py",
    "mro_integration_patch.py",
    "opportunity_domain.py",
    "portfolio_metrics.py",
    "product_profiles.py",
    "production_binding_plan.py",
    "production_checkout_probe.py",
    "production_correlation_source_probe_v63.py",
    "production_gate_v63.py",
    "production_integration_runner.py",
    "production_source_snapshot_v63.py",
    "recovery_acceptance_v63.py",
    "recovery_overlay_acceptance_v63.py",
    "recovery_overlay_patch_compiler_v63.py",
    "recovery_overlay_probe_v63.py",
    "recovery_overlay_report_builder_v63.py",
    "recovery_semantics_v63.py",
    "recursive_expansion.py",
    "reference_backend_correlation_runner_v63.py",
    "release_evidence_v63.py",
    "research_scheduler.py",
    "route_reuse.py",
    "runtime_backend_binding_plan_v63.py",
    "runtime_durable_backend_v63.py",
    "runtime_event_primitive_probe_v63.py",
    "sales_readiness.py",
    "search_localization.py",
    "source_execution.py",
    "wal_contract_v63.py",
)


def _runtime_payload_files() -> list[str]:
    return [f"unified_runtime/{name}" for name in V63_RUNTIME_PAYLOAD_NAMES]


def build_v63_production_binding_plan(
    repo_root: str | Path,
    *,
    backend_correlation_acceptance_report: dict[str, Any] | None = None,
    recovery_overlay_acceptance_report: dict[str, Any] | None = None,
    expected_production_source_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    preflight = probe_production_checkout(root)
    adapter_structure = inspect_production_adapter_structure(root)
    runtime_backend_binding_plan = build_v63_runtime_backend_binding_plan(
        root,
        backend_correlation_acceptance_report=backend_correlation_acceptance_report,
        expected_production_source_snapshot_sha256=expected_production_source_snapshot_sha256,
    )
    recovery_overlay_probe = probe_v63_recovery_overlay(root)
    if recovery_overlay_acceptance_report is None:
        recovery_overlay_acceptance = {
            "verified": False,
            "status": "BLOCKED",
            "blockers": ["LIVE_RECOVERY_OVERLAY_ACCEPTANCE_REQUIRED"],
        }
    else:
        recovery_overlay_acceptance = validate_v63_recovery_overlay_acceptance(
            recovery_overlay_acceptance_report,
            expected_production_source_snapshot_sha256=expected_production_source_snapshot_sha256,
            expected_recovery_registry_file=recovery_overlay_probe.get("recovery_registry_file"),
            expected_recovery_registry_name=recovery_overlay_probe.get("recovery_registry_name"),
        )
    recovery_overlay_binding_proven = bool(
        recovery_overlay_probe.get("recovery_overlay_codegen_allowed")
        and recovery_overlay_acceptance.get("verified")
    )
    entrypoint = resolve_active_mcp_entrypoint(root)
    entrypoint_exists = bool(entrypoint and (root / entrypoint).is_file())

    blockers = [
        blocker
        for blocker in preflight.get("blockers", [])
        if blocker not in _EXPECTED_PREPATCH_GAPS
    ]
    if entrypoint is None:
        blockers.append("ACTIVE_MCP_ENTRYPOINT_NOT_RESOLVED")
    elif not entrypoint_exists:
        blockers.append("ACTIVE_MCP_ENTRYPOINT_MISSING")

    can_apply_patch = bool(preflight.get("safe_to_apply_v63_adapter_patch")) and not blockers
    adapter_surface_complete = bool(
        can_apply_patch
        and preflight.get("post_patch_binding_complete")
        and adapter_structure.get("v63_tool_surface_complete")
    )
    # Staging can mechanically prove the MCP/WAL-facing surface, but it does not
    # invent the checkout-specific bridge from v6.3 Runtime mutations into the
    # existing append-only production event store. That backend must be bound
    # from the exact production checkout and separately proven.
    runtime_durable_backend_binding_proven = bool(
        runtime_backend_binding_plan.get("runtime_durable_backend_binding_proven")
    )
    post_patch_binding_complete = bool(
        adapter_surface_complete
        and runtime_durable_backend_binding_proven
        and recovery_overlay_binding_proven
    )

    init_text = ""
    init_path = root / "unified_runtime" / "__init__.py"
    if init_path.is_file():
        try:
            init_text = init_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    runtime_mro_patch_required = "V63DemandExpansionMixin" not in init_text
    adapter_patch_required = not adapter_surface_complete

    if not can_apply_patch:
        status = "BLOCKED_PREPATCH"
    elif post_patch_binding_complete:
        status = "READY_FOR_EXACT_ADAPTER_TESTS"
    elif adapter_surface_complete and runtime_durable_backend_binding_proven:
        status = "BACKEND_READY_RECOVERY_OVERLAY_PENDING"
    elif adapter_surface_complete:
        status = "ADAPTER_SURFACE_READY_BACKEND_PENDING"
    else:
        status = "READY_FOR_PATCH_APPLICATION"

    return {
        "status": status,
        "repo_root": str(root),
        "can_apply_patch": can_apply_patch,
        "active_mcp_entrypoint": entrypoint,
        "active_mcp_entrypoint_exists": entrypoint_exists,
        "runtime_payload_files": _runtime_payload_files(),
        "durable_mutations": sorted(V63_WAL_BINDINGS),
        "runtime_mro_patch_required": runtime_mro_patch_required,
        "adapter_patch_required": adapter_patch_required,
        "adapter_surface_complete": adapter_surface_complete,
        "runtime_durable_backend_binding_required": True,
        "runtime_durable_backend_binding_proven": runtime_durable_backend_binding_proven,
        "runtime_backend_binding_plan": runtime_backend_binding_plan,
        "recovery_overlay_codegen_ready": bool(recovery_overlay_probe.get("recovery_overlay_codegen_allowed")),
        "recovery_overlay_probe": recovery_overlay_probe,
        "recovery_overlay_binding_required": True,
        "recovery_overlay_binding_proven": recovery_overlay_binding_proven,
        "recovery_overlay_acceptance": recovery_overlay_acceptance,
        "post_patch_binding_complete": post_patch_binding_complete,
        "exact_adapter_tests_required": post_patch_binding_complete,
        "adapter_codegen_ready": bool(adapter_structure.get("safe_for_adapter_codegen")),
        "adapter_structure": adapter_structure,
        "preflight": preflight,
        "blockers": blockers,
        "postpatch_gaps": [
            *list(preflight.get("missing_v63_mutation_names") or []),
            *list(adapter_structure.get("postpatch_blockers") or []),
            *([] if runtime_durable_backend_binding_proven else ["V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND"]),
            *([] if recovery_overlay_binding_proven else ["V63_RECOVERY_OVERLAY_NOT_BOUND"]),
        ],
        "safety": {
            "modifies_checkout": False,
            "requires_exact_existing_wal": True,
            "parallel_wal_allowed": False,
            "production_entrypoint_switch_in_same_step": False,
        },
    }
