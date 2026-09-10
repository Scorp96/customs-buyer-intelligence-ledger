from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .mro_integration_patch import adapt_runtime_init_text
from .production_binding_plan import (
    V63_RUNTIME_PAYLOAD_NAMES,
    build_v63_production_binding_plan,
)
from .production_source_snapshot_v63 import build_v63_production_source_snapshot


def _source_runtime_root() -> Path:
    return Path(__file__).resolve().parent



def _payload_paths() -> list[Path]:
    root = _source_runtime_root()
    return [root / name for name in V63_RUNTIME_PAYLOAD_NAMES]


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def apply_v63_runtime_phase(repo_root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    """Apply only the mechanically safe v6.3 Runtime phase to a real checkout.

    This intentionally does *not* bind MCP mutation handlers, alter the active MCP
    entrypoint, or claim production readiness. Adapter/WAL binding is a separate
    phase that requires the exact production checkout and exact recovery tests.
    """
    root = Path(repo_root).resolve()
    plan = build_v63_production_binding_plan(root)
    blockers = list(plan.get("blockers") or [])
    if not plan.get("can_apply_patch"):
        return {
            **plan,
            "status": "BLOCKED_PREPATCH",
            "modified_checkout": False,
            "adapter_bound": False,
            "production_ready": False,
            "next_gate": "RESOLVE_PREPATCH_BLOCKERS",
        }

    init_path = root / "unified_runtime" / "__init__.py"
    original_init = init_path.read_bytes()
    original_text = original_init.decode("utf-8")
    adapted_text = adapt_runtime_init_text(original_text)
    init_changed = adapted_text.encode("utf-8") != original_init

    payload = _payload_paths()
    to_create: list[tuple[Path, Path]] = []
    for source in payload:
        target = root / "unified_runtime" / source.name
        if target.exists():
            if not _same_bytes(source, target):
                blockers.append(f"V63_RUNTIME_FILE_CONFLICT:{source.name}")
        else:
            to_create.append((source, target))

    if blockers:
        return {
            **plan,
            "status": "BLOCKED_PREPATCH",
            "blockers": blockers,
            "modified_checkout": False,
            "adapter_bound": False,
            "production_ready": False,
            "next_gate": "RESOLVE_PREPATCH_BLOCKERS",
        }

    already_present = not init_changed and not to_create
    if dry_run:
        return {
            **plan,
            "status": (
                "RUNTIME_PATCH_ALREADY_PRESENT_ADAPTER_PENDING"
                if already_present
                else "READY_TO_APPLY_RUNTIME_PATCH"
            ),
            "modified_checkout": False,
            "adapter_bound": False,
            "production_ready": False,
            "runtime_files_to_create": [target.name for _, target in to_create],
            "runtime_mro_would_change": init_changed,
            "next_gate": (
                "BIND_EXISTING_PRODUCTION_WAL_AND_MCP"
                if already_present
                else "APPLY_RUNTIME_PATCH"
            ),
        }

    created: list[Path] = []
    try:
        for source, target in to_create:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            created.append(target)
        if init_changed:
            init_path.write_text(adapted_text, encoding="utf-8", newline="")
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        if init_changed:
            try:
                init_path.write_bytes(original_init)
            except OSError:
                pass
        raise

    modified = bool(created or init_changed)
    phase_b_source_snapshot = build_v63_production_source_snapshot(root)
    return {
        **plan,
        "status": (
            "RUNTIME_PATCH_APPLIED_ADAPTER_PENDING"
            if modified
            else "RUNTIME_PATCH_ALREADY_PRESENT_ADAPTER_PENDING"
        ),
        "modified_checkout": modified,
        "phase_b_source_snapshot": phase_b_source_snapshot,
        "created_runtime_files": [str(path.relative_to(root)).replace("\\", "/") for path in created],
        "runtime_mro_changed": init_changed,
        "adapter_bound": False,
        "production_ready": False,
        "next_gate": "BIND_EXISTING_PRODUCTION_WAL_AND_MCP",
        "safety": {
            **dict(plan.get("safety") or {}),
            "mcp_entrypoint_modified": False,
            "production_wal_modified": False,
            "automatic_send_enabled": False,
        },
    }
