from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .mcp_entrypoint_v63 import resolve_active_mcp_entrypoint
from .production_source_snapshot_v63 import _collect_active_overlay_chain


_REQUIRED_PRECEDENTS = ("append_peer_discovery", "promote_anchor")


def _dict_string_to_handler_names(node: ast.AST) -> dict[str, str] | None:
    if not isinstance(node, ast.Dict) or not node.keys:
        return None
    mapping: dict[str, str] = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        if not isinstance(value, ast.Name):
            return None
        mapping[key.value] = value.id
    return mapping


def _assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        return node.targets[0].id
    return node.target.id if isinstance(node.target, ast.Name) else None


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]



def _subscript_keys_for_parameter(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter_name: str,
) -> list[str]:
    keys: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Subscript):
            continue
        if not isinstance(child.value, ast.Name) or child.value.id != parameter_name:
            continue
        key_node = child.slice
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            keys.add(key_node.value)
    return sorted(keys)



def _attribute_path(node: ast.AST) -> str | None:
    parts=[]; cur=node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr); cur=cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id); return ".".join(reversed(parts))
    return None


def _named_assignment(tree: ast.Module, name: str) -> ast.AST | None:
    rows=[]
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id==name: rows.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,ast.Name) and node.target.id==name and node.value is not None: rows.append(node.value)
    return rows[0] if len(rows)==1 else None


def _sync_recovery_proof(tree: ast.Module, source: str) -> dict[str, Any]:
    v61_ok=_attribute_path(_named_assignment(tree,"_v61"))=="_base._v61"
    runtime_ok=_attribute_path(_named_assignment(tree,"_RUNTIME")) in {"_base._RUNTIME","_v61._server.RUNTIME"}
    base_ok=_attribute_path(_named_assignment(tree,"_BASE_RECOVER_TARGET_RESULT"))=="_base._recover_target_result"
    inventory=next((n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=="_reconciliation_inventory"),None)
    inv_src=ast.get_source_segment(source,inventory) if inventory else ""
    inv_ok=bool(inv_src and "_v61._MUTATING_TOOLS" in inv_src and "_v61._AUTOMATIC_RECONCILIATION_TOOLS" in inv_src)
    return {"proven":bool(v61_ok and runtime_ok and base_ok and inv_ok),"v61_alias_proven":v61_ok,"runtime_alias_proven":runtime_ok,"base_recover_target_proven":base_ok,"reconciliation_inventory_proven":inv_ok}

def probe_v63_recovery_overlay(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    blockers: list[str] = []
    entrypoint = resolve_active_mcp_entrypoint(root)
    if entrypoint is None:
        return {
            "status": "BLOCKED",
            "blockers": ["ACTIVE_MCP_ENTRYPOINT_NOT_RESOLVED"],
            "recovery_overlay_codegen_allowed": False,
        }

    overlay_files, chain_blockers = _collect_active_overlay_chain(root, entrypoint)
    blockers.extend(chain_blockers)

    candidates: list[dict[str, Any]] = []
    parsed: dict[str, ast.Module] = {}
    for rel in overlay_files:
        path = root / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="strict"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            blockers.append(f"RECOVERY_OVERLAY_AST_INVALID:{rel}")
            continue
        parsed[rel] = tree
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            name = _assignment_name(node)
            if not name or node.value is None:
                continue
            mapping = _dict_string_to_handler_names(node.value)
            if mapping is None:
                continue
            if "RECOVERY" in name.upper() and set(_REQUIRED_PRECEDENTS) & set(mapping):
                candidates.append({
                    "file": rel,
                    "name": name,
                    "mapping": mapping,
                })

    sync_rel = "mcp/server_v61_sync_recovery.py"
    if sync_rel in parsed:
        sync_source=(root/sync_rel).read_text(encoding="utf-8",errors="strict")
        proof=_sync_recovery_proof(parsed[sync_rel],sync_source)
        sync_blockers=list(blockers)
        if not proof["proven"]: sync_blockers.append("SYNC_RECOVERY_EXTENSION_NOT_PROVEN")
        sync_blockers=list(dict.fromkeys(sync_blockers)); allowed=not sync_blockers
        return {
            "active_mcp_entrypoint":entrypoint,"active_overlay_chain":overlay_files,"recovery_codegen_mode":"SYNC_RECOVERY_EXTENSION",
            "recovery_registry_candidates":[],"recovery_registry_name":"_v61._reconcile_prepared","recovery_registry_file":sync_rel,
            "sync_recovery_extension_proof":proof,"intent_contract_proven":allowed,"status":"RECOVERY_OVERLAY_PRIMITIVE_PROVEN" if allowed else "BLOCKED",
            "blockers":sync_blockers,"recovery_overlay_codegen_allowed":allowed,"modifies_checkout":False,
        }

    if len(candidates) == 0:
        blockers.append("RECOVERY_REGISTRY_NOT_PROVEN")
    elif len(candidates) > 1:
        blockers.append("RECOVERY_REGISTRY_AMBIGUOUS")

    result: dict[str, Any] = {
        "active_mcp_entrypoint": entrypoint,
        "active_overlay_chain": overlay_files,
        "recovery_registry_candidates": candidates,
        "recovery_codegen_mode": "LEGACY_RECOVERY_REGISTRY",
    }

    if len(candidates) == 1:
        candidate = candidates[0]
        rel = str(candidate["file"])
        mapping = dict(candidate["mapping"])
        tree = parsed[rel]
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        peer_name = mapping.get("append_peer_discovery")
        anchor_name = mapping.get("promote_anchor")
        peer_fn = functions.get(str(peer_name or ""))
        anchor_fn = functions.get(str(anchor_name or ""))
        if not set(_REQUIRED_PRECEDENTS) <= set(mapping) or peer_fn is None or anchor_fn is None:
            blockers.append("PEER_ANCHOR_RECOVERY_PRECEDENTS_INCOMPLETE")
            peer_sig: list[str] = []
            anchor_sig: list[str] = []
        else:
            peer_sig = _function_signature(peer_fn)
            anchor_sig = _function_signature(anchor_fn)
            if peer_sig != anchor_sig:
                blockers.append("RECOVERY_HANDLER_SIGNATURE_MISMATCH")

        peer_intent_keys: list[str] = []
        anchor_intent_keys: list[str] = []
        shared_intent_keys: list[str] = []
        intent_contract_proven = False
        if peer_fn is not None and anchor_fn is not None and peer_sig and anchor_sig:
            peer_intent_keys = _subscript_keys_for_parameter(peer_fn, peer_sig[0])
            anchor_intent_keys = _subscript_keys_for_parameter(anchor_fn, anchor_sig[0])
            shared_intent_keys = sorted(set(peer_intent_keys) & set(anchor_intent_keys))
            intent_contract_proven = {"arguments", "correlation_id"} <= set(shared_intent_keys)
            if not intent_contract_proven:
                blockers.append("RECOVERY_INTENT_CONTRACT_NOT_PROVEN")

        result.update({
            "recovery_registry_name": candidate["name"],
            "recovery_registry_file": rel,
            "peer_handler": peer_name,
            "anchor_handler": anchor_name,
            "peer_handler_signature": peer_sig,
            "anchor_handler_signature": anchor_sig,
            "handler_signatures_compatible": bool(peer_sig and peer_sig == anchor_sig),
            "peer_intent_keys": peer_intent_keys,
            "anchor_intent_keys": anchor_intent_keys,
            "shared_intent_keys": shared_intent_keys,
            "intent_contract_proven": intent_contract_proven,
        })

    blockers = list(dict.fromkeys(blockers))
    allowed = not blockers
    result.update({
        "status": "RECOVERY_OVERLAY_PRIMITIVE_PROVEN" if allowed else "BLOCKED",
        "blockers": blockers,
        "recovery_overlay_codegen_allowed": allowed,
        "modifies_checkout": False,
    })
    return result
