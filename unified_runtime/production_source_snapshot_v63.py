from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from .mcp_entrypoint_v63 import resolve_active_mcp_entrypoint


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _mcp_module_path(root: Path, module_name: str) -> Path:
    return root / "mcp" / f"{module_name}.py"


def _server_v61_imports(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8", errors="strict")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return []

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # from . import server_v61_x as _base
            if node.level >= 1 and node.module is None:
                for alias in node.names:
                    if alias.name.startswith("server_v61") and alias.name not in names:
                        names.append(alias.name)
            # from .server_v61_x import something
            elif node.level >= 1 and str(node.module or "").startswith("server_v61"):
                module = str(node.module)
                if module not in names:
                    names.append(module)
            # from mcp import server_v61_x as _base
            elif str(node.module or "") == "mcp":
                for alias in node.names:
                    if alias.name.startswith("server_v61") and alias.name not in names:
                        names.append(alias.name)
            # from mcp.server_v61_x import something
            elif str(node.module or "").startswith("mcp.server_v61"):
                module = str(node.module).split(".")[-1]
                if module not in names:
                    names.append(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                full = alias.name
                if full.startswith("mcp.server_v61"):
                    module = full.split(".")[-1]
                    if module not in names:
                        names.append(module)
    return names


def _collect_active_overlay_chain(root: Path, entrypoint: str) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    queue: list[str] = [Path(entrypoint).stem]
    seen: set[str] = set()
    rels: list[str] = []

    while queue:
        module = queue.pop(0)
        if module in seen:
            continue
        seen.add(module)
        path = _mcp_module_path(root, module)
        rel = f"mcp/{module}.py"
        if not path.is_file():
            blockers.append("ACTIVE_OVERLAY_IMPORT_MISSING")
            continue
        rels.append(rel)
        for imported in _server_v61_imports(path):
            if imported not in seen:
                queue.append(imported)

    # The stable base adapter is always part of the source authority for Phase B.
    base_rel = "mcp/server_v61.py"
    if (root / base_rel).is_file():
        if base_rel not in rels:
            rels.append(base_rel)
    else:
        blockers.append("PRODUCTION_ADAPTER_MISSING")

    return sorted(set(rels)), list(dict.fromkeys(blockers))


def build_v63_production_source_snapshot(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    blockers: list[str] = []
    entrypoint = resolve_active_mcp_entrypoint(root)
    if entrypoint is None:
        blockers.append("ACTIVE_MCP_ENTRYPOINT_NOT_RESOLVED")
        overlay_files: list[str] = []
    else:
        overlay_files, overlay_blockers = _collect_active_overlay_chain(root, entrypoint)
        blockers.extend(overlay_blockers)

    required = [
        ".mcp.json",
        "unified_runtime/__init__.py",
        "unified_runtime/research_orchestration_hardening.py",
        "unified_runtime/v6.py",
        *overlay_files,
    ]
    for rel in ("unified_runtime/core.py", "unified_runtime/resilience.py"):
        if (root / rel).is_file():
            required.append(rel)
    required = list(dict.fromkeys(required))

    files: dict[str, dict[str, Any]] = {}
    for rel in sorted(required):
        path = root / rel
        if not path.is_file():
            blockers.append(f"PINNED_SOURCE_MISSING:{rel}")
            continue
        data = path.read_bytes()
        files[rel] = {
            "sha256": _sha256_bytes(data),
            "size_bytes": len(data),
        }

    manifest_material = {
        "active_mcp_entrypoint": entrypoint,
        "files": files,
    }
    digest = _sha256_bytes(_canonical_json_bytes(manifest_material))
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "cbi.v63-production-source-snapshot.v1",
        "status": "READY" if not blockers else "BLOCKED",
        "repo_root": str(root),
        "active_mcp_entrypoint": entrypoint,
        "files": files,
        "snapshot_sha256": digest,
        "blockers": blockers,
        "source_pins_complete": not blockers,
        "modifies_checkout": False,
    }


def validate_v63_production_source_snapshot(
    repo_root: str | Path,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    expected_files = dict(snapshot.get("files") or {})
    drifted: list[str] = []
    missing: list[str] = []

    for rel, expected in sorted(expected_files.items()):
        path = root / rel
        if not path.is_file():
            missing.append(rel)
            continue
        actual = _sha256_bytes(path.read_bytes())
        if actual.lower() != str(dict(expected or {}).get("sha256") or "").lower():
            drifted.append(rel)

    current_entrypoint = resolve_active_mcp_entrypoint(root)
    entrypoint_changed = current_entrypoint != snapshot.get("active_mcp_entrypoint")
    blockers: list[str] = []
    if missing:
        blockers.append("PINNED_SOURCE_MISSING")
    if drifted or entrypoint_changed:
        blockers.append("SOURCE_DRIFT_DETECTED")

    valid = not blockers
    return {
        "valid": valid,
        "blockers": blockers,
        "missing_files": missing,
        "drifted_files": drifted,
        "entrypoint_changed": entrypoint_changed,
        "expected_entrypoint": snapshot.get("active_mcp_entrypoint"),
        "current_entrypoint": current_entrypoint,
        "expected_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "modifies_checkout": False,
    }
