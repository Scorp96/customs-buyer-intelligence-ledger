from __future__ import annotations

from pathlib import Path
from typing import Any

from .wal_contract_v63 import V63_WAL_BINDINGS
from .adapter_recovery_mapping_v63 import required_production_precedent_tools


_REQUIRED_WAL_MARKERS = (
    "_invoke_mutation",
    "PREPARED",
    "COMMITTED",
    "MUTATION_RECONCILIATION_REQUIRED",
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _collect_mcp_source(root: Path) -> tuple[list[str], str]:
    files = sorted(str(path.relative_to(root)).replace("\\", "/") for path in (root / "mcp").glob("*.py")) if (root / "mcp").is_dir() else []
    chunks: list[str] = []
    for rel in files:
        chunks.append(_read_text(root / rel))
    return files, "\n".join(chunks)


def probe_production_checkout(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    init_path = root / "unified_runtime" / "__init__.py"
    v62_path = root / "unified_runtime" / "research_orchestration_hardening.py"
    adapter_path = root / "mcp" / "server_v61.py"

    init_text = _read_text(init_path)
    adapter_text = _read_text(adapter_path)
    mcp_files, mcp_text = _collect_mcp_source(root)

    v62_present = (
        v62_path.is_file()
        and "V61ResearchOrchestrationHardeningMixin" in init_text
        and "research_orchestration_hardening" in init_text
    )
    adapter_present = adapter_path.is_file()
    required_wal_markers_present = all(marker in mcp_text for marker in _REQUIRED_WAL_MARKERS)
    correlation_marker_present = any(marker in mcp_text for marker in ("MUTCORR", "correlation_id", "mutation_correlation"))
    production_wal_pattern_detected = adapter_present and required_wal_markers_present and correlation_marker_present

    required_mutations = sorted(V63_WAL_BINDINGS)
    missing_mutations = [name for name in required_mutations if name not in mcp_text]
    inventory_complete = not missing_mutations

    required_precedents = required_production_precedent_tools()
    missing_precedents = [name for name in required_precedents if name not in mcp_text]
    recovery_precedents_present = not missing_precedents

    blockers: list[str] = []
    if not init_path.is_file():
        blockers.append("UNIFIED_RUNTIME_INIT_MISSING")
    if not v62_present:
        blockers.append("V62_ORCHESTRATION_NOT_PRESENT")
    if not adapter_present:
        blockers.append("PRODUCTION_ADAPTER_MISSING")
    if not production_wal_pattern_detected:
        blockers.append("PRODUCTION_WAL_PATTERN_NOT_PROVEN")
    if missing_mutations:
        blockers.append("V63_MUTATION_INVENTORY_INCOMPLETE")
    if missing_precedents:
        blockers.append("V63_RECOVERY_PRECEDENTS_NOT_PROVEN")

    safe_for_mro = init_path.is_file() and v62_present
    safe_to_apply_adapter_patch = safe_for_mro and production_wal_pattern_detected and recovery_precedents_present
    post_patch_binding_complete = safe_to_apply_adapter_patch and inventory_complete
    ready_for_adapter_tests = post_patch_binding_complete

    return {
        "repo_root": str(root),
        "unified_runtime_init_present": init_path.is_file(),
        "v62_orchestration_present": v62_present,
        "production_adapter_present": adapter_present,
        "mcp_python_files": mcp_files,
        "production_wal_pattern_detected": production_wal_pattern_detected,
        "correlation_marker_present": correlation_marker_present,
        "v63_required_mutation_names": required_mutations,
        "missing_v63_mutation_names": missing_mutations,
        "v63_mutation_inventory_complete": inventory_complete,
        "required_recovery_precedent_tools": required_precedents,
        "missing_recovery_precedent_tools": missing_precedents,
        "recovery_precedents_present": recovery_precedents_present,
        "safe_for_v63_mro_patch": safe_for_mro,
        "safe_to_apply_v63_adapter_patch": safe_to_apply_adapter_patch,
        "post_patch_binding_complete": post_patch_binding_complete,
        "ready_for_exact_adapter_integration_tests": ready_for_adapter_tests,
        "production_ready": False,
        "production_ready_reason": "PREFLIGHT_ONLY_REQUIRES_CI_RENDER_R2_AND_LIVE_ACCEPTANCE",
        "blockers": blockers,
    }
