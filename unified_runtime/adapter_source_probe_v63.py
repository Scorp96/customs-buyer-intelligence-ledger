from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .adapter_recovery_mapping_v63 import required_production_precedent_tools
from .wal_contract_v63 import V63_WAL_BINDINGS
from .mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES


def _literal_strings(node: ast.AST) -> set[str] | None:
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        values: set[str] = set()
        for item in node.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            values.add(item.value)
        return values
    if isinstance(node, ast.Dict):
        values: set[str] = set()
        for key in node.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                return None
            values.add(key.value)
        return values
    return None



def _tool_descriptor_names(node: ast.AST) -> set[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    names: set[str] = set()
    if not node.elts:
        return None
    for item in node.elts:
        if not isinstance(item, ast.Dict):
            return None
        fields: dict[str, ast.AST] = {}
        for key, value in zip(item.keys, item.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                return None
            fields[key.value] = value
        name_node = fields.get("name")
        if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
            return None
        if "inputSchema" not in fields:
            return None
        names.add(name_node.value)
    return names


def _dispatch_mapping(node: ast.AST) -> dict[str, str] | None:
    if not isinstance(node, ast.Dict):
        return None
    mapping: dict[str, str] = {}
    if not node.keys:
        return None
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        if isinstance(value, ast.Name):
            target = value.id
        elif isinstance(value, ast.Attribute):
            target = value.attr
        else:
            return None
        mapping[key.value] = target
    return mapping



def _attribute_root_name(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def _invoke_binding_details(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, str | None]]:
    bindings: list[dict[str, str | None]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        is_invoke = (
            isinstance(called, ast.Name) and called.id == "_invoke_mutation"
        ) or (
            isinstance(called, ast.Attribute) and called.attr == "_invoke_mutation"
        )
        if not is_invoke or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        runtime_target: str | None = None
        runtime_object: str | None = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Attribute):
            runtime_target = node.args[1].attr
            runtime_object = _attribute_root_name(node.args[1])
        bindings.append({
            "tool": first.value,
            "runtime_target": runtime_target,
            "runtime_object": runtime_object,
        })
    return bindings


def _direct_runtime_targets(fn: ast.FunctionDef | ast.AsyncFunctionDef, runtime_object: str) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if _attribute_root_name(node.func) == runtime_object:
            targets.add(node.func.attr)
    return targets


def _assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        return node.targets[0].id
    if isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _assignment_value(node: ast.Assign | ast.AnnAssign) -> ast.AST | None:
    return node.value


def _invoke_bindings(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str | None]]:
    return [
        (str(item["tool"]), item.get("runtime_target"))
        for item in _invoke_binding_details(fn)
    ]




def _delegated_overlay_proven(source: str) -> bool:
    required_fragments = (
        "from mcp import server as _server",
        "_ORIGINAL_TOOL_DESCRIPTORS = _server.tool_descriptors",
        "_ORIGINAL_HANDLERS = dict(_server.TOOL_HANDLERS)",
        "_server.tool_descriptors =",
        "_server.TOOL_HANDLERS[",
        "def _wrap_handler(",
        "_invoke_mutation(tool_name, handler, arguments)",
        "return _server.main()",
    )
    return all(fragment in source for fragment in required_fragments)


def _delegated_dispatch_tools(source: str) -> set[str]:
    import re
    return set(re.findall(r'_server\.TOOL_HANDLERS\[[\"\']([^\"\']+)[\"\']\]', source))

def inspect_production_adapter_structure(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    server = root / "mcp" / "server_v61.py"
    blockers: list[str] = []
    if not server.is_file():
        return {
            "repo_root": str(root),
            "server_path": str(server),
            "python_ast_valid": False,
            "invoke_mutation_present": False,
            "invoke_mutation_signature": [],
            "mutation_registry_candidates": [],
            "mcp_tool_registry_candidates": [],
            "mcp_tool_registry_values": {},
            "mcp_tool_registry_proven": False,
            "mcp_dispatch_registry_candidates": [],
            "mcp_dispatch_registry_values": {},
            "mcp_dispatch_registry_proven": False,
            "precedent_handler_map": {},
            "runtime_object_candidates": [],
            "runtime_object_proven": False,
            "safe_for_adapter_codegen": False,
            "adapter_codegen_mode": None,
            "v63_handler_map": {},
            "v63_handler_binding_complete": False,
            "v63_tool_descriptor_complete": False,
            "v63_dispatch_binding_complete": False,
            "v63_read_only_handler_binding_complete": False,
            "v63_tool_surface_complete": False,
            "postpatch_blockers": ["V63_HANDLER_BINDING_INCOMPLETE", "V63_TOOL_DESCRIPTORS_INCOMPLETE", "V63_DISPATCH_BINDING_INCOMPLETE", "V63_READ_ONLY_HANDLER_BINDING_INCOMPLETE"],
            "blockers": ["PRODUCTION_ADAPTER_MISSING"],
        }

    try:
        source = server.read_text(encoding="utf-8", errors="strict")
        tree = ast.parse(source, filename=str(server))
    except (OSError, UnicodeError, SyntaxError):
        return {
            "repo_root": str(root),
            "server_path": str(server),
            "python_ast_valid": False,
            "invoke_mutation_present": False,
            "invoke_mutation_signature": [],
            "mutation_registry_candidates": [],
            "mcp_tool_registry_candidates": [],
            "mcp_tool_registry_values": {},
            "mcp_tool_registry_proven": False,
            "mcp_dispatch_registry_candidates": [],
            "mcp_dispatch_registry_values": {},
            "mcp_dispatch_registry_proven": False,
            "precedent_handler_map": {},
            "runtime_object_candidates": [],
            "runtime_object_proven": False,
            "safe_for_adapter_codegen": False,
            "adapter_codegen_mode": None,
            "v63_handler_map": {},
            "v63_handler_binding_complete": False,
            "v63_tool_descriptor_complete": False,
            "v63_dispatch_binding_complete": False,
            "v63_read_only_handler_binding_complete": False,
            "v63_tool_surface_complete": False,
            "postpatch_blockers": ["V63_HANDLER_BINDING_INCOMPLETE", "V63_TOOL_DESCRIPTORS_INCOMPLETE", "V63_DISPATCH_BINDING_INCOMPLETE", "V63_READ_ONLY_HANDLER_BINDING_INCOMPLETE"],
            "blockers": ["PRODUCTION_ADAPTER_AST_INVALID"],
        }

    delegated_mode = _delegated_overlay_proven(source)
    adapter_codegen_mode = "DELEGATED_SERVER_OVERLAY" if delegated_mode else "LITERAL_REGISTRIES"

    invoke_defs = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_invoke_mutation"
    ]
    invoke_present = len(invoke_defs) == 1
    if not invoke_present:
        blockers.append(
            "INVOKE_MUTATION_MISSING" if not invoke_defs else "INVOKE_MUTATION_AMBIGUOUS"
        )
    signature: list[str] = []
    if invoke_present:
        fn = invoke_defs[0]
        signature = [arg.arg for arg in (*fn.args.posonlyargs, *fn.args.args)]

    required = set(required_production_precedent_tools())
    registry_candidates: list[str] = []
    registry_values: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        name = _assignment_name(node)
        value = _assignment_value(node)
        if not name or value is None:
            continue
        if not isinstance(value, (ast.Set, ast.List, ast.Tuple)):
            continue
        strings = _literal_strings(value)
        if strings is None:
            continue
        if required <= strings:
            registry_candidates.append(name)
            registry_values[name] = sorted(strings)
    if len(registry_candidates) != 1:
        blockers.append(
            "MUTATION_REGISTRY_NOT_PROVEN"
            if not registry_candidates
            else "MUTATION_REGISTRY_AMBIGUOUS"
        )

    mcp_tool_registry_candidates: list[str] = []
    mcp_tool_registry_values: dict[str, list[str]] = {}
    mcp_dispatch_registry_candidates: list[str] = []
    mcp_dispatch_registry_values: dict[str, dict[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        name = _assignment_name(node)
        value = _assignment_value(node)
        if not name or value is None:
            continue
        descriptor_names = _tool_descriptor_names(value)
        if descriptor_names is not None and required <= descriptor_names:
            mcp_tool_registry_candidates.append(name)
            mcp_tool_registry_values[name] = sorted(descriptor_names)
        dispatch = _dispatch_mapping(value)
        if dispatch is not None and required <= set(dispatch):
            mcp_dispatch_registry_candidates.append(name)
            mcp_dispatch_registry_values[name] = dict(dispatch)

    if delegated_mode:
        mcp_tool_registry_candidates = ["_server.tool_descriptors"]
        delegated_names = set(required)
        if "build_v63_tool_descriptors" in source or "_build_v63_tool_descriptors" in source:
            delegated_names |= set(V63_MUTATION_TOOL_NAMES) | set(V63_READ_ONLY_TOOL_NAMES)
        mcp_tool_registry_values = {"_server.tool_descriptors": sorted(delegated_names)}
        dispatch_names = set(required) | _delegated_dispatch_tools(source)
        mcp_dispatch_registry_candidates = ["_server.TOOL_HANDLERS"]
        mcp_dispatch_registry_values = {
            "_server.TOOL_HANDLERS": {name: (f"_v63_{name}_handler" if name in set(V63_MUTATION_TOOL_NAMES)|set(V63_READ_ONLY_TOOL_NAMES) else "_wrap_handler") for name in sorted(dispatch_names)}
        }

    mcp_tool_registry_proven = len(mcp_tool_registry_candidates) == 1
    mcp_dispatch_registry_proven = len(mcp_dispatch_registry_candidates) == 1
    if not mcp_tool_registry_proven:
        blockers.append(
            "MCP_TOOL_REGISTRY_NOT_PROVEN"
            if not mcp_tool_registry_candidates
            else "MCP_TOOL_REGISTRY_AMBIGUOUS"
        )
    if not mcp_dispatch_registry_proven:
        blockers.append(
            "MCP_DISPATCH_REGISTRY_NOT_PROVEN"
            if not mcp_dispatch_registry_candidates
            else "MCP_DISPATCH_REGISTRY_AMBIGUOUS"
        )

    precedent_handler_map: dict[str, list[str]] = {}
    precedent_runtime_objects: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for detail in _invoke_binding_details(node):
            tool = str(detail["tool"])
            if tool in required:
                precedent_handler_map.setdefault(tool, []).append(node.name)
                runtime_object = detail.get("runtime_object")
                if runtime_object:
                    precedent_runtime_objects.add(str(runtime_object))

    if delegated_mode:
        precedent_handler_map = {tool: ["_wrap_handler"] for tool in sorted(required)}
        precedent_runtime_objects = {"_server.RUNTIME"}

    runtime_object_candidates = sorted(precedent_runtime_objects)
    runtime_object_proven = len(runtime_object_candidates) == 1
    if not runtime_object_proven:
        blockers.append(
            "RUNTIME_OBJECT_NOT_PROVEN"
            if not runtime_object_candidates
            else "RUNTIME_OBJECT_AMBIGUOUS"
        )

    missing_handlers = sorted(tool for tool in required if tool not in precedent_handler_map)
    ambiguous_handlers = sorted(
        tool for tool, handlers in precedent_handler_map.items() if len(handlers) != 1
    )
    if missing_handlers:
        blockers.append("PRECEDENT_HANDLER_MAPPING_INCOMPLETE")
    if ambiguous_handlers:
        blockers.append("PRECEDENT_HANDLER_MAPPING_AMBIGUOUS")

    v63_required = set(V63_WAL_BINDINGS)
    v63_handler_map: dict[str, list[dict[str, str | None]]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for tool, runtime_target in _invoke_bindings(node):
            if tool in v63_required:
                v63_handler_map.setdefault(tool, []).append({
                    "handler": node.name,
                    "runtime_target": runtime_target,
                })
    v63_handler_binding_complete = True
    for tool in sorted(v63_required):
        entries = v63_handler_map.get(tool, [])
        if len(entries) != 1 or entries[0].get("runtime_target") != tool:
            v63_handler_binding_complete = False
    all_v63_tools = set(V63_MUTATION_TOOL_NAMES) | set(V63_READ_ONLY_TOOL_NAMES)
    v63_tool_descriptor_complete = False
    if mcp_tool_registry_proven:
        names = set(mcp_tool_registry_values[mcp_tool_registry_candidates[0]])
        v63_tool_descriptor_complete = all_v63_tools <= names

    v63_dispatch_binding_complete = False
    dispatch: dict[str, str] = {}
    if mcp_dispatch_registry_proven:
        dispatch = mcp_dispatch_registry_values[mcp_dispatch_registry_candidates[0]]
        v63_dispatch_binding_complete = all_v63_tools <= set(dispatch)
        if v63_dispatch_binding_complete:
            for tool in sorted(v63_required):
                entries = v63_handler_map.get(tool, [])
                if len(entries) != 1 or dispatch.get(tool) != entries[0].get("handler"):
                    v63_dispatch_binding_complete = False
                    break

    v63_read_only_handler_binding_complete = False
    if v63_dispatch_binding_complete and runtime_object_proven:
        runtime_object = runtime_object_candidates[0]
        fn_by_name = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        v63_read_only_handler_binding_complete = True
        for tool in V63_READ_ONLY_TOOL_NAMES:
            handler_name = dispatch.get(tool)
            fn = fn_by_name.get(str(handler_name or ""))
            if fn is None or tool not in _direct_runtime_targets(fn, runtime_object):
                v63_read_only_handler_binding_complete = False
                break

    if delegated_mode:
        all_v63_tools = set(V63_MUTATION_TOOL_NAMES) | set(V63_READ_ONLY_TOOL_NAMES)
        delegated_dispatch = _delegated_dispatch_tools(source)
        v63_tool_descriptor_complete = bool(
            ("build_v63_tool_descriptors" in source or "_build_v63_tool_descriptors" in source)
            and "_server.tool_descriptors = _v63_tool_descriptors" in source
        )
        v63_dispatch_binding_complete = all_v63_tools <= delegated_dispatch
        v63_handler_map = {}
        for tool in V63_MUTATION_TOOL_NAMES:
            marker = f"_invoke_mutation({tool!r}, _server.RUNTIME.{tool}, arguments)"
            if marker in source:
                v63_handler_map[tool] = [{"handler": f"_v63_{tool}_handler", "runtime_target": tool}]
        v63_handler_binding_complete = all(
            len(v63_handler_map.get(tool, [])) == 1 for tool in V63_MUTATION_TOOL_NAMES
        )
        v63_read_only_handler_binding_complete = all(
            f"return _server.RUNTIME.{tool}(arguments)" in source
            for tool in V63_READ_ONLY_TOOL_NAMES
        )

    v63_tool_surface_complete = bool(
        v63_handler_binding_complete
        and v63_tool_descriptor_complete
        and v63_dispatch_binding_complete
        and v63_read_only_handler_binding_complete
    )

    postpatch_blockers: list[str] = []
    if not v63_handler_binding_complete:
        postpatch_blockers.append("V63_HANDLER_BINDING_INCOMPLETE")
    if not v63_tool_descriptor_complete:
        postpatch_blockers.append("V63_TOOL_DESCRIPTORS_INCOMPLETE")
    if not v63_dispatch_binding_complete:
        postpatch_blockers.append("V63_DISPATCH_BINDING_INCOMPLETE")
    if not v63_read_only_handler_binding_complete:
        postpatch_blockers.append("V63_READ_ONLY_HANDLER_BINDING_INCOMPLETE")

    safe = not blockers
    return {
        "repo_root": str(root),
        "server_path": str(server),
        "python_ast_valid": True,
        "invoke_mutation_present": invoke_present,
        "invoke_mutation_signature": signature,
        "mutation_registry_candidates": registry_candidates,
        "mutation_registry_values": registry_values,
        "mcp_tool_registry_candidates": mcp_tool_registry_candidates,
        "mcp_tool_registry_values": mcp_tool_registry_values,
        "mcp_tool_registry_proven": mcp_tool_registry_proven,
        "mcp_dispatch_registry_candidates": mcp_dispatch_registry_candidates,
        "mcp_dispatch_registry_values": mcp_dispatch_registry_values,
        "mcp_dispatch_registry_proven": mcp_dispatch_registry_proven,
        "required_precedent_tools": sorted(required),
        "precedent_handler_map": precedent_handler_map,
        "runtime_object_candidates": runtime_object_candidates,
        "runtime_object_proven": runtime_object_proven,
        "missing_precedent_handler_tools": missing_handlers,
        "ambiguous_precedent_handler_tools": ambiguous_handlers,
        "safe_for_adapter_codegen": safe,
        "adapter_codegen_mode": adapter_codegen_mode,
        "v63_handler_map": v63_handler_map,
        "v63_handler_binding_complete": v63_handler_binding_complete,
        "v63_tool_descriptor_complete": v63_tool_descriptor_complete,
        "v63_dispatch_binding_complete": v63_dispatch_binding_complete,
        "v63_read_only_handler_binding_complete": v63_read_only_handler_binding_complete,
        "v63_tool_surface_complete": v63_tool_surface_complete,
        "postpatch_blockers": postpatch_blockers,
        "blockers": blockers,
    }
