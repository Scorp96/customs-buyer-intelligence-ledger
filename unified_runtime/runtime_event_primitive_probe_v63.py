from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


_PRECEDENT_METHODS = (
    "append_peer_discovery",
    "promote_anchor",
    "append_information_record",
)
_EVENT_LITERAL_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")


def _call_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    else:
        return None
    return ".".join(reversed(parts))


def _event_literals(call: ast.Call) -> list[str]:
    values: list[str] = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            value = arg.value
            if _EVENT_LITERAL_RE.match(value) and "_" in value:
                values.append(value)
    for kw in call.keywords:
        value = kw.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            text = value.value
            if _EVENT_LITERAL_RE.match(text) and "_" in text:
                values.append(text)
    return list(dict.fromkeys(values))


def _method_candidates(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[dict[str, list[str]], list[str]]:
    primitive_events: dict[str, list[str]] = {}
    all_events: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = _call_name(child.func)
        if not name or not name.startswith("self."):
            continue
        events = _event_literals(child)
        if not events:
            continue
        primitive_events.setdefault(name, [])
        for event in events:
            if event not in primitive_events[name]:
                primitive_events[name].append(event)
            if event not in all_events:
                all_events.append(event)
    return primitive_events, all_events


def probe_v63_runtime_event_primitives(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    runtime_dir = root / "unified_runtime"
    sources = sorted(runtime_dir.glob("*.py")) if runtime_dir.is_dir() else []
    if not sources:
        return {
            "status": "BLOCKED",
            "blockers": ["RUNTIME_SOURCE_NOT_FOUND"],
            "precedent_methods": [],
            "method_sources": {},
            "primitive_candidates": {},
            "event_literals": {},
            "shared_primitive": None,
            "backend_codegen_allowed": False,
            "remaining_blockers": ["RUNTIME_SOURCE_NOT_FOUND"],
        }

    found: dict[str, list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]] = {
        name: [] for name in _PRECEDENT_METHODS
    }
    parse_errors: list[str] = []
    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="strict"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            parse_errors.append(str(path.relative_to(root)).replace("\\", "/"))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
                found[node.name].append((path, node))

    blockers: list[str] = []
    if any(len(found[name]) != 1 for name in _PRECEDENT_METHODS):
        blockers.append("PRECEDENT_METHODS_INCOMPLETE")

    method_sources: dict[str, str] = {}
    primitive_candidates: dict[str, list[str]] = {}
    event_literals: dict[str, list[str]] = {}
    primitive_sets: list[set[str]] = []
    for name in _PRECEDENT_METHODS:
        matches = found[name]
        if len(matches) != 1:
            primitive_candidates[name] = []
            event_literals[name] = []
            continue
        path, node = matches[0]
        method_sources[name] = str(path.relative_to(root)).replace("\\", "/")
        candidates, events = _method_candidates(node)
        primitive_candidates[name] = sorted(candidates)
        event_literals[name] = sorted(events)
        primitive_sets.append(set(candidates))

    shared: set[str] = set.intersection(*primitive_sets) if len(primitive_sets) == len(_PRECEDENT_METHODS) else set()
    if len(shared) != 1:
        blockers.append("NO_UNIQUE_SHARED_DURABLE_PRIMITIVE")
    shared_primitive = next(iter(shared)) if len(shared) == 1 else None

    if parse_errors:
        blockers.append("RUNTIME_SOURCE_PARSE_ERRORS")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        status = "BLOCKED"
        remaining = list(blockers)
    else:
        status = "SHARED_DURABLE_PRIMITIVE_PROVEN"
        # Finding the append primitive is necessary but not sufficient. The
        # exact checkout must still prove how the production adapter's MUTCORR
        # context reaches this primitive before backend codegen is allowed.
        remaining = ["CORRELATION_PROPAGATION_NOT_YET_PROVEN"]

    return {
        "status": status,
        "blockers": blockers,
        "precedent_methods": list(_PRECEDENT_METHODS),
        "method_sources": method_sources,
        "primitive_candidates": primitive_candidates,
        "event_literals": event_literals,
        "shared_primitive": shared_primitive,
        "parse_error_files": parse_errors,
        "backend_codegen_allowed": False,
        "remaining_blockers": remaining,
        "modifies_checkout": False,
    }
