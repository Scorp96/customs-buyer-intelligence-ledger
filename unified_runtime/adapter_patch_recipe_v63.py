from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .adapter_recovery_mapping_v63 import V63_PRODUCTION_RECOVERY_MAPPINGS
from .mcp_schema_v63 import (
    V63_MUTATION_TOOL_NAMES,
    V63_READ_ONLY_TOOL_NAMES,
    build_v63_tool_descriptors,
)
from .production_binding_plan import build_v63_production_binding_plan
from .wal_contract_v63 import V63_WAL_BINDINGS


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _handler_name(tool: str) -> str:
    return f"_v63_{tool}_handler"


def build_v63_adapter_patch_recipe(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    plan = build_v63_production_binding_plan(root)
    structure = dict(plan.get("adapter_structure") or {})

    blockers = list(plan.get("blockers") or [])
    if not structure.get("safe_for_adapter_codegen"):
        for blocker in structure.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(str(blocker))

    server = root / "mcp" / "server_v61.py"
    init_path = root / "unified_runtime" / "__init__.py"
    mcp_json = root / ".mcp.json"

    source_pins = {
        "mcp/server_v61.py": _sha256(server),
        "unified_runtime/__init__.py": _sha256(init_path),
        ".mcp.json": _sha256(mcp_json),
    }

    if blockers or not plan.get("can_apply_patch"):
        status = "BLOCKED"
        codegen_allowed = False
        next_gate = "RESOLVE_PRODUCTION_SOURCE_STRUCTURE_BLOCKERS"
    elif plan.get("post_patch_binding_complete"):
        status = "ADAPTER_BINDING_PRESENT_REQUIRES_EXACT_TESTS"
        codegen_allowed = False
        next_gate = "RUN_EXACT_ADAPTER_AND_WAL_RECOVERY_TESTS"
    elif plan.get("adapter_surface_complete"):
        status = "ADAPTER_SURFACE_PRESENT_BACKEND_PENDING"
        codegen_allowed = False
        next_gate = "BIND_RUNTIME_DURABLE_BACKEND_ON_EXACT_CHECKOUT"
    else:
        status = "READY_FOR_ADAPTER_CODEGEN"
        codegen_allowed = True
        next_gate = "GENERATE_PATCH_ONLY_AFTER_EXACT_CHECKOUT_RECHECK"

    mutation_registry_name = None
    candidates = list(structure.get("mutation_registry_candidates") or [])
    if len(candidates) == 1:
        mutation_registry_name = candidates[0]
    tool_registry_name = None
    candidates = list(structure.get("mcp_tool_registry_candidates") or [])
    if len(candidates) == 1:
        tool_registry_name = candidates[0]
    dispatch_registry_name = None
    candidates = list(structure.get("mcp_dispatch_registry_candidates") or [])
    if len(candidates) == 1:
        dispatch_registry_name = candidates[0]
    runtime_object = None
    candidates = list(structure.get("runtime_object_candidates") or [])
    if len(candidates) == 1:
        runtime_object = candidates[0]

    current_mutations: set[str] = set()
    if mutation_registry_name:
        current_mutations = set(
            (structure.get("mutation_registry_values") or {}).get(mutation_registry_name, [])
        )
    current_tools: set[str] = set()
    if tool_registry_name:
        current_tools = set(
            (structure.get("mcp_tool_registry_values") or {}).get(tool_registry_name, [])
        )
    current_dispatch: dict[str, str] = {}
    if dispatch_registry_name:
        current_dispatch = dict(
            (structure.get("mcp_dispatch_registry_values") or {}).get(dispatch_registry_name, {})
        )

    all_descriptors = build_v63_tool_descriptors()
    descriptor_by_name = {str(item["name"]): item for item in all_descriptors}
    all_v63_tools = tuple(V63_READ_ONLY_TOOL_NAMES) + tuple(V63_MUTATION_TOOL_NAMES)

    handler_plan: dict[str, dict[str, Any]] = {}
    for tool in V63_READ_ONLY_TOOL_NAMES:
        handler_plan[tool] = {
            "handler_name": _handler_name(tool),
            "invocation": "READ_ONLY_RUNTIME_DIRECT",
            "runtime_object": runtime_object,
            "runtime_target": tool,
            "uses_mutation_wal": False,
            "sends_message": False,
        }
    for tool in V63_MUTATION_TOOL_NAMES:
        handler_plan[tool] = {
            "handler_name": _handler_name(tool),
            "invocation": "EXISTING_PRODUCTION_INVOKE_MUTATION",
            "runtime_object": runtime_object,
            "runtime_target": tool,
            "uses_mutation_wal": True,
            "wal_binding": dict(V63_WAL_BINDINGS[tool]),
            "recovery_mapping": dict(V63_PRODUCTION_RECOVERY_MAPPINGS[tool]),
            "sends_message": False,
        }

    descriptors_to_add = [name for name in all_v63_tools if name not in current_tools]
    mutation_additions = [name for name in V63_MUTATION_TOOL_NAMES if name not in current_mutations]
    dispatch_additions = {
        name: _handler_name(name)
        for name in all_v63_tools
        if name not in current_dispatch
    }

    return {
        "status": status,
        "repo_root": str(root),
        "codegen_allowed": codegen_allowed,
        "modifies_checkout": False,
        "switches_production_entrypoint": False,
        "active_mcp_entrypoint": plan.get("active_mcp_entrypoint"),
        "target_adapter": "mcp/server_v61.py",
        "adapter_codegen_mode": structure.get("adapter_codegen_mode") or "LITERAL_REGISTRIES",
        "mutation_registry_name": mutation_registry_name,
        "tool_registry_name": tool_registry_name,
        "dispatch_registry_name": dispatch_registry_name,
        "runtime_object": runtime_object,
        "source_pins": source_pins,
        "source_pins_must_match_before_codegen": True,
        "mutation_registry_additions": mutation_additions,
        "tool_descriptors_to_add": descriptors_to_add,
        "tool_descriptor_payloads": {
            name: descriptor_by_name[name] for name in descriptors_to_add
        },
        "handler_plan": handler_plan,
        "dispatch_additions": dispatch_additions,
        "recovery_plan": {
            name: dict(V63_PRODUCTION_RECOVERY_MAPPINGS[name])
            for name in V63_MUTATION_TOOL_NAMES
        },
        "wal_plan": {
            name: dict(V63_WAL_BINDINGS[name])
            for name in V63_MUTATION_TOOL_NAMES
        },
        "postpatch_required_checks": [
            "ALL_V63_TOOL_DESCRIPTORS_PRESENT",
            "ALL_V63_DISPATCH_BINDINGS_PRESENT",
            "ALL_V63_READ_ONLY_HANDLERS_BIND_SAME_NAMED_RUNTIME_METHOD",
            "ALL_V63_MUTATION_HANDLERS_USE_EXISTING_PRODUCTION_INVOKE_MUTATION",
            "ALL_3_V63_MUTATIONS_IN_GUARDED_INVENTORY",
            "ALL_3_V63_MUTATIONS_IN_AUTOMATIC_RECONCILIATION_INVENTORY",
            "UNRECONCILED_V63_MUTATIONS_EMPTY",
            "EXACT_AUTOMATIC_RECONCILIATION_COMPLETE",
        ],
        "next_gate": next_gate,
        "blockers": blockers,
        "safety": {
            "parallel_wal_allowed": False,
            "rewrite_stable_mcp_server_allowed": False,
            "production_entrypoint_switch_in_same_patch": False,
            "private_customer_data_allowed_in_public_diff": False,
            "automatic_send_capability_added": False,
        },
        "binding_plan": plan,
    }
