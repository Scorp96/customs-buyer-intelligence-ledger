from __future__ import annotations

import ast
import difflib
import hashlib
from pathlib import Path
from typing import Any

from .adapter_patch_recipe_v63 import build_v63_adapter_patch_recipe
from .mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES
from .production_source_snapshot_v63 import validate_v63_production_source_snapshot


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _node_span_bytes(source: str, node: ast.AST) -> tuple[int, int]:
    raw_lines = source.encode("utf-8").splitlines(keepends=True)
    start = sum(len(line) for line in raw_lines[: node.lineno - 1]) + int(node.col_offset)
    end = sum(len(line) for line in raw_lines[: node.end_lineno - 1]) + int(node.end_col_offset)
    return start, end


def _assignment_node(tree: ast.Module, name: str) -> ast.Assign | ast.AnnAssign:
    matches: list[ast.Assign | ast.AnnAssign] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
                matches.append(node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                matches.append(node)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one assignment for {name}, found {len(matches)}")
    return matches[0]


def _append_sequence_literal(segment: str, additions: list[str]) -> str:
    if not additions:
        return segment
    stripped = segment.rstrip()
    if not stripped or stripped[-1] not in "}])":
        raise ValueError("unsupported literal registry shape")
    close = stripped[-1]
    trailing = segment[len(stripped):]
    body = stripped[:-1]
    body_r = body.rstrip()
    opener = {"}": "{", "]": "[", ")": "("}[close]
    has_items = not body_r.endswith(opener)
    separator = ""
    if has_items and not body_r.endswith(","):
        separator = ","
    indent = "    "
    addition_text = ",\n".join(f"{indent}{item}" for item in additions)
    prefix_newline = "\n" if not body.endswith("\n") else ""
    return f"{body}{separator}{prefix_newline}{addition_text},\n{close}{trailing}"


def _handler_source(runtime_object: str) -> str:
    blocks: list[str] = []
    for tool in V63_READ_ONLY_TOOL_NAMES:
        blocks.append(
            f"def _v63_{tool}_handler(arguments):\n"
            f"    return {runtime_object}.{tool}(arguments)\n"
        )
    for tool in V63_MUTATION_TOOL_NAMES:
        blocks.append(
            f"def _v63_{tool}_handler(arguments):\n"
            f"    return _invoke_mutation({tool!r}, {runtime_object}.{tool}, arguments)\n"
        )
    return "\n".join(blocks) + "\n"




def _delegated_overlay_source(runtime_object: str) -> str:
    lines = [
        "from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors as _build_v63_tool_descriptors",
        "from unified_runtime.existing_production_store_backend_v63 import ExistingProductionStoreBackend",
        "from unified_runtime.runtime_durable_backend_v63 import bind_v63_runtime_durable_backend",
        "",
        "_BASE_V63_TOOL_DESCRIPTORS = _server.tool_descriptors",
        "",
        "def _v63_tool_descriptors():",
        "    tools = _BASE_V63_TOOL_DESCRIPTORS()",
        "    names = {str(item.get('name') or '') for item in tools if isinstance(item, dict)}",
        "    for item in _build_v63_tool_descriptors():",
        "        if str(item.get('name') or '') not in names:",
        "            tools.append(item)",
        "    return tools",
        "",
        "_V63_DURABLE_BACKEND = ExistingProductionStoreBackend()",
        f"bind_v63_runtime_durable_backend({runtime_object}, _V63_DURABLE_BACKEND)",
        "",
    ]
    lines.extend(_handler_source(runtime_object).rstrip().splitlines())
    lines.extend([
        "",
        f"_MUTATING_TOOLS.update({set(V63_MUTATION_TOOL_NAMES)!r})",
        "_server.tool_descriptors = _v63_tool_descriptors",
    ])
    for tool in (*V63_READ_ONLY_TOOL_NAMES, *V63_MUTATION_TOOL_NAMES):
        lines.append(f"_server.TOOL_HANDLERS[{tool!r}] = _v63_{tool}_handler")
    lines.append("")
    return "\n".join(lines) + "\n"


def _delegated_insert_offset(source: str, tree: ast.Module) -> int:
    mains = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'main']
    if len(mains) != 1:
        raise ValueError('delegated adapter main() ambiguity')
    start, _ = _node_span_bytes(source, mains[0])
    return start

def compile_v63_adapter_patch_candidate(
    repo_root: str | Path,
    *,
    expected_source_pins: dict[str, str | None] | None = None,
    expected_production_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    recipe = build_v63_adapter_patch_recipe(root)
    pins = dict(recipe.get("source_pins") or {})

    source_snapshot_validation = None
    validated_snapshot_sha256 = None
    if expected_production_snapshot is not None:
        source_snapshot_validation = validate_v63_production_source_snapshot(root, expected_production_snapshot)
        if not source_snapshot_validation.get("valid"):
            return {
                "status": "BLOCKED_SOURCE_DRIFT",
                "codegen_performed": False,
                "modifies_checkout": False,
                "switches_production_entrypoint": False,
                "source_snapshot_validation": source_snapshot_validation,
                "source_pins": pins,
                "scope": "BASE_ADAPTER_ONLY",
                "adapter_bound": False,
                "production_ready": False,
            }
        validated_snapshot_sha256 = expected_production_snapshot.get("snapshot_sha256")

    if expected_source_pins is not None:
        mismatches = [
            key
            for key, expected in expected_source_pins.items()
            if expected is not None and pins.get(key) != expected
        ]
        if mismatches:
            return {
                "status": "BLOCKED_SOURCE_PIN_MISMATCH",
                "codegen_performed": False,
                "modifies_checkout": False,
                "switches_production_entrypoint": False,
                "pin_mismatches": sorted(mismatches),
                "source_pins": pins,
                "scope": "BASE_ADAPTER_ONLY",
                "adapter_bound": False,
                "production_ready": False,
            }

    if recipe.get("status") != "READY_FOR_ADAPTER_CODEGEN" or not recipe.get("codegen_allowed"):
        return {
            "status": "BLOCKED_RECIPE_NOT_READY",
            "codegen_performed": False,
            "modifies_checkout": False,
            "switches_production_entrypoint": False,
            "blockers": list(recipe.get("blockers") or []),
            "source_pins": pins,
            "scope": "BASE_ADAPTER_ONLY",
            "adapter_bound": False,
            "production_ready": False,
        }

    server = root / "mcp" / "server_v61.py"
    original_bytes = server.read_bytes()
    original = original_bytes.decode("utf-8", errors="strict")
    tree = ast.parse(original, filename=str(server))

    runtime_object = str(recipe["runtime_object"])
    if recipe.get("adapter_codegen_mode") == "DELEGATED_SERVER_OVERLAY":
        insert_at = _delegated_insert_offset(original, tree)
        overlay = _delegated_overlay_source(runtime_object).encode("utf-8")
        candidate_bytes = original_bytes[:insert_at] + overlay + b"\n" + original_bytes[insert_at:]
        candidate = candidate_bytes.decode("utf-8")
        ast.parse(candidate, filename="mcp/server_v61.py.v63-delegated-candidate")
        original_tree = ast.parse(original)
        candidate_tree = ast.parse(candidate)
        original_invoke = [n for n in original_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_invoke_mutation"]
        candidate_invoke = [n for n in candidate_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_invoke_mutation"]
        if len(original_invoke) != 1 or len(candidate_invoke) != 1:
            raise ValueError("_invoke_mutation structural ambiguity")
        if ast.get_source_segment(original, original_invoke[0]) != ast.get_source_segment(candidate, candidate_invoke[0]):
            raise ValueError("compiler attempted to modify _invoke_mutation")
        diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), candidate.splitlines(keepends=True), fromfile="a/mcp/server_v61.py", tofile="b/mcp/server_v61.py"))
        return {
            "status": "PATCH_CANDIDATE_READY",
            "codegen_performed": True,
            "modifies_checkout": False,
            "switches_production_entrypoint": False,
            "scope": "BASE_ADAPTER_ONLY",
            "adapter_codegen_mode": "DELEGATED_SERVER_OVERLAY",
            "candidate_source": candidate,
            "candidate_sha256": _sha256_bytes(candidate_bytes),
            "unified_diff": diff,
            "source_pins": pins,
            "source_snapshot_validation": source_snapshot_validation,
            "validated_production_snapshot_sha256": validated_snapshot_sha256,
            "durable_mutations": list(V63_MUTATION_TOOL_NAMES),
            "read_only_tools": list(V63_READ_ONLY_TOOL_NAMES),
            "recovery_overlay_binding_required": True,
            "runtime_durable_backend_binding_required": True,
            "runtime_durable_backend_binding_candidate_proven": True,
            "runtime_durable_backend_binding_proven": False,
            "candidate_executable": False,
            "adapter_bound": False,
            "production_ready": False,
            "next_gate": "RUN_EXACT_BACKEND_CORRELATION_AND_RECOVERY_ACCEPTANCE",
            "recipe": recipe,
        }

    mutation_registry = str(recipe["mutation_registry_name"])
    tool_registry = str(recipe["tool_registry_name"])
    dispatch_registry = str(recipe["dispatch_registry_name"])

    mutation_node = _assignment_node(tree, mutation_registry)
    tool_node = _assignment_node(tree, tool_registry)
    dispatch_node = _assignment_node(tree, dispatch_registry)
    if mutation_node.value is None or tool_node.value is None or dispatch_node.value is None:
        raise ValueError("registry assignment without value")

    replacements: list[tuple[int, int, bytes]] = []

    # Extend only the existing literal registries proven by the AST probe.
    mut_start, mut_end = _node_span_bytes(original, mutation_node.value)
    mut_segment = original_bytes[mut_start:mut_end].decode("utf-8")
    mut_additions = [repr(name) for name in recipe["mutation_registry_additions"]]
    replacements.append((mut_start, mut_end, _append_sequence_literal(mut_segment, mut_additions).encode("utf-8")))

    tool_start, tool_end = _node_span_bytes(original, tool_node.value)
    tool_segment = original_bytes[tool_start:tool_end].decode("utf-8")
    descriptor_payloads = recipe["tool_descriptor_payloads"]
    tool_additions = [repr(descriptor_payloads[name]) for name in recipe["tool_descriptors_to_add"]]
    replacements.append((tool_start, tool_end, _append_sequence_literal(tool_segment, tool_additions).encode("utf-8")))

    dispatch_start, dispatch_end = _node_span_bytes(original, dispatch_node.value)
    dispatch_segment = original_bytes[dispatch_start:dispatch_end].decode("utf-8")
    dispatch_additions = [
        f"{tool!r}: {handler}"
        for tool, handler in recipe["dispatch_additions"].items()
    ]
    replacements.append((dispatch_start, dispatch_end, _append_sequence_literal(dispatch_segment, dispatch_additions).encode("utf-8")))

    # Insert new handlers immediately before the proven dispatch registry assignment.
    insert_at, _ = _node_span_bytes(original, dispatch_node)
    handlers = _handler_source(runtime_object).encode("utf-8")
    replacements.append((insert_at, insert_at, handlers + b"\n"))

    candidate_bytes = original_bytes
    for start, end, replacement in sorted(replacements, key=lambda x: x[0], reverse=True):
        candidate_bytes = candidate_bytes[:start] + replacement + candidate_bytes[end:]
    candidate = candidate_bytes.decode("utf-8")
    ast.parse(candidate, filename="mcp/server_v61.py.v63-candidate")

    # Hard guard: the central production mutation wrapper itself is not modified by this compiler.
    original_tree = ast.parse(original)
    candidate_tree = ast.parse(candidate)
    original_invoke = [n for n in original_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_invoke_mutation"]
    candidate_invoke = [n for n in candidate_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_invoke_mutation"]
    if len(original_invoke) != 1 or len(candidate_invoke) != 1:
        raise ValueError("_invoke_mutation structural ambiguity")
    if ast.get_source_segment(original, original_invoke[0]) != ast.get_source_segment(candidate, candidate_invoke[0]):
        raise ValueError("compiler attempted to modify _invoke_mutation")

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile="a/mcp/server_v61.py",
            tofile="b/mcp/server_v61.py",
        )
    )

    return {
        "status": "PATCH_CANDIDATE_READY",
        "codegen_performed": True,
        "modifies_checkout": False,
        "switches_production_entrypoint": False,
        "scope": "BASE_ADAPTER_ONLY",
        "adapter_codegen_mode": recipe.get("adapter_codegen_mode") or "LITERAL_REGISTRIES",
        "candidate_source": candidate,
        "candidate_sha256": _sha256_bytes(candidate_bytes),
        "unified_diff": diff,
        "source_pins": pins,
        "source_snapshot_validation": source_snapshot_validation,
        "validated_production_snapshot_sha256": validated_snapshot_sha256,
        "durable_mutations": list(V63_MUTATION_TOOL_NAMES),
        "read_only_tools": list(V63_READ_ONLY_TOOL_NAMES),
        "recovery_overlay_binding_required": True,
        "runtime_durable_backend_binding_required": True,
        "runtime_durable_backend_binding_proven": False,
        "candidate_executable": False,
        "adapter_bound": False,
        "production_ready": False,
        "next_gate": "BIND_RUNTIME_DURABLE_BACKEND_ON_EXACT_CHECKOUT",
        "recipe": recipe,
    }
