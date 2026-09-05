from __future__ import annotations

import ast
import difflib
import hashlib
from pathlib import Path
from typing import Any

from .production_source_snapshot_v63 import (
    build_v63_production_source_snapshot,
    validate_v63_production_source_snapshot,
)
from .recovery_overlay_probe_v63 import probe_v63_recovery_overlay
from .wal_contract_v63 import V63_WAL_BINDINGS


_IMPORT_LINE = "from unified_runtime.recovery_semantics_v63 import recover_prepared_v63_mutation\n"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in source.splitlines(keepends=True):
        total += len(line)
        offsets.append(total)
    return offsets


def _span(node: ast.AST, offsets: list[int]) -> tuple[int, int]:
    return (
        offsets[int(node.lineno) - 1] + int(node.col_offset),
        offsets[int(node.end_lineno) - 1] + int(node.end_col_offset),
    )


def _assignment(tree: ast.Module, name: str) -> ast.Assign | ast.AnnAssign:
    matches: list[ast.Assign | ast.AnnAssign] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
                matches.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            matches.append(node)
    if len(matches) != 1:
        raise RuntimeError("RECOVERY_REGISTRY_ASSIGNMENT_NOT_UNIQUE")
    return matches[0]


def _function_segment(source: str, name: str) -> str:
    tree = ast.parse(source)
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"RECOVERY_HANDLER_NOT_UNIQUE:{name}")
    segment = ast.get_source_segment(source, matches[0])
    if not segment:
        raise RuntimeError(f"RECOVERY_HANDLER_SOURCE_UNAVAILABLE:{name}")
    return segment


def _render_registry(source: str, node: ast.AST) -> str:
    if not isinstance(node, ast.Dict):
        raise RuntimeError("RECOVERY_REGISTRY_NOT_LITERAL_DICT")
    entries: list[tuple[str, str]] = []
    existing: set[str] = set()
    for key, value in zip(node.keys, node.values):
        if key is None:
            raise RuntimeError("RECOVERY_REGISTRY_UNPACKING_UNSUPPORTED")
        key_src = ast.get_source_segment(source, key)
        value_src = ast.get_source_segment(source, value)
        if not key_src or not value_src:
            raise RuntimeError("RECOVERY_REGISTRY_SOURCE_UNAVAILABLE")
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            existing.add(key.value)
        entries.append((key_src, value_src))
    for tool in V63_WAL_BINDINGS:
        if tool not in existing:
            entries.append((repr(tool), f"_v63_recover_{tool}"))
    body = "".join(f"    {key}: {value},\n" for key, value in entries)
    return "{\n" + body + "}"


def _render_handlers(signature: list[str]) -> str:
    if len(signature) != 2:
        raise RuntimeError("RECOVERY_HANDLER_SIGNATURE_UNSUPPORTED")
    intent_name, events_name = signature
    chunks: list[str] = []
    for tool in V63_WAL_BINDINGS:
        chunks.append(
            f"def _v63_recover_{tool}({intent_name}, {events_name}):\n"
            f"    return recover_prepared_v63_mutation(\n"
            f"        {tool!r},\n"
            f"        {intent_name}[\"arguments\"],\n"
            f"        expected_correlation_id={intent_name}[\"correlation_id\"],\n"
            f"        durable_events={events_name},\n"
            f"    )\n"
        )
    return "\n".join(chunks) + "\n"


def _import_insert_offset(tree: ast.Module, source: str, offsets: list[int]) -> int:
    import_nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if import_nodes:
        return _span(import_nodes[-1], offsets)[1]
    return 0


def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    result = source
    for start, end, replacement in sorted(edits, key=lambda row: row[0], reverse=True):
        result = result[:start] + replacement + result[end:]
    return result




def _main_insert_offset(tree: ast.Module, source: str, offsets: list[int]) -> int:
    mains=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=="main"]
    return _span(mains[0],offsets)[0] if len(mains)==1 else len(source)


def _sync_extension_source() -> str:
    lines = [
        "from mcp import server_v61_production as _production",
        "from unified_runtime.recovery_semantics_v63 import recover_prepared_v63_mutation",
        "from unified_runtime.wal_contract_v63 import V63_WAL_BINDINGS as _V63_WAL_BINDINGS",
        "",
        "_BASE_V63_RECONCILE_PREPARED = _v61._reconcile_prepared",
        "",
        "def _v63_normalized_durable_events(arguments, stored):",
        "    investigation_id = str(arguments.get(\"investigation_id\") or \"\").strip()",
        "    if not investigation_id:",
        "        return []",
        "    try:",
        "        before = int(stored.get(\"state_version_before\") or 0)",
        "        events = _RUNTIME.store.read(investigation_id)",
        "    except Exception:",
        "        return []",
        "    normalized = []",
        "    for event in events:",
        "        seq = int(event.get(\"seq\") or 0)",
        "        if seq <= before:",
        "            continue",
        "        correlation = event.get(\"mutation_correlation\")",
        "        payload = event.get(\"payload\")",
        "        if not isinstance(correlation, dict) or not isinstance(payload, dict):",
        "            continue",
        "        row = dict(payload)",
        "        row[\"event_type\"] = str(event.get(\"event_type\") or \"\")",
        "        row[\"correlation_id\"] = str(correlation.get(\"correlation_id\") or \"\")",
        "        row[\"seq\"] = seq",
        "        normalized.append(row)",
        "    return normalized",
        "",
        "def _v63_reconcile_prepared(tool_name, args, stored, request_hash, path):",
        "    if tool_name not in _V63_WAL_BINDINGS:",
        "        return _BASE_V63_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)",
        "    correlation_id = str(stored.get(\"mutation_correlation_id\") or \"\").strip()",
        "    if not correlation_id:",
        "        return None",
        "    recovered = recover_prepared_v63_mutation(tool_name, args, expected_correlation_id=correlation_id, durable_events=_v63_normalized_durable_events(args, stored))",
        "    if recovered.get(\"status\") != \"RECOVERED\":",
        "        return None",
        "    event_seq = int(recovered.get(\"event_seq\") or 0)",
        "    raw_result = recovered.get(\"result\")",
        "    if event_seq <= int(stored.get(\"state_version_before\") or 0) or not isinstance(raw_result, dict):",
        "        return None",
        "    return _production._finish_reconciliation(tool_name, stored, request_hash, path, raw_result, event_seq, str(recovered.get(\"proof\") or \"V63_EXACT_CORRELATED_DURABLE_EVENT\"))",
        "",
        "_v61._reconcile_prepared = _v63_reconcile_prepared",
        "_v61._AUTOMATIC_RECONCILIATION_TOOLS.update(_V63_WAL_BINDINGS)",
        "",
    ]
    return "\n".join(lines) + "\n"

def compile_v63_recovery_overlay_patch_candidate(
    repo_root: str | Path,
    *,
    expected_production_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    snapshot = expected_production_snapshot or build_v63_production_source_snapshot(root)
    validation = validate_v63_production_source_snapshot(root, snapshot)
    if not validation["valid"]:
        return {
            "status": "BLOCKED_SOURCE_DRIFT",
            "codegen_performed": False,
            "modifies_checkout": False,
            "source_snapshot_validation": validation,
            "blockers": list(validation.get("blockers") or []),
            "production_ready": False,
        }

    probe = probe_v63_recovery_overlay(root)
    if not probe.get("recovery_overlay_codegen_allowed"):
        return {
            "status": "BLOCKED_RECOVERY_OVERLAY_STRUCTURE",
            "codegen_performed": False,
            "modifies_checkout": False,
            "source_snapshot_validation": validation,
            "probe": probe,
            "blockers": list(probe.get("blockers") or []),
            "production_ready": False,
        }

    target_rel = str(probe["recovery_registry_file"])
    target = root / target_rel
    original = target.read_text(encoding="utf-8", errors="strict")
    tree = ast.parse(original, filename=str(target))
    offsets = _line_offsets(original)
    if probe.get("recovery_codegen_mode") == "SYNC_RECOVERY_EXTENSION":
        insert_at=_main_insert_offset(tree,original,offsets)
        candidate=_apply_edits(original,[(insert_at,insert_at,_sync_extension_source()+"\n")])
        ast.parse(candidate,filename=f"{target}<v63-sync-candidate>")
        final_validation=validate_v63_production_source_snapshot(root,snapshot)
        if not final_validation["valid"]:
            return {"status":"BLOCKED_SOURCE_DRIFT","codegen_performed":False,"modifies_checkout":False,"source_snapshot_validation":final_validation,"blockers":list(final_validation.get("blockers") or []),"production_ready":False}
        diff="".join(difflib.unified_diff(original.splitlines(keepends=True),candidate.splitlines(keepends=True),fromfile=f"a/{target_rel}",tofile=f"b/{target_rel}"))
        return {
            "status":"RECOVERY_OVERLAY_PATCH_CANDIDATE_READY","scope":"SYNC_RECOVERY_EXTENSION_ONLY","target_file":target_rel,"candidate_source":candidate,"candidate_sha256":_sha256_text(candidate),
            "unified_diff":diff,"codegen_performed":True,"modifies_checkout":False,"switches_production_entrypoint":False,"validated_production_snapshot_sha256":snapshot.get("snapshot_sha256"),
            "source_snapshot_validation":final_validation,"durable_mutations":list(V63_WAL_BINDINGS),"recovery_overlay_binding_complete":False,"production_ready":False,"next_gate":"APPLY_ON_EXACT_CHECKOUT_AND_RUN_RECOVERY_ACCEPTANCE","probe":probe,
        }

    registry_assignment = _assignment(tree, str(probe["recovery_registry_name"]))
    registry_value = registry_assignment.value
    if registry_value is None:
        raise RuntimeError("RECOVERY_REGISTRY_HAS_NO_VALUE")

    peer_before = _function_segment(original, str(probe["peer_handler"]))
    anchor_before = _function_segment(original, str(probe["anchor_handler"]))

    registry_start, registry_end = _span(registry_value, offsets)
    assignment_start, _ = _span(registry_assignment, offsets)
    edits: list[tuple[int, int, str]] = [
        (registry_start, registry_end, _render_registry(original, registry_value)),
        (assignment_start, assignment_start, _render_handlers(list(probe["peer_handler_signature"])) + "\n"),
    ]
    if _IMPORT_LINE.strip() not in original:
        import_offset = _import_insert_offset(tree, original, offsets)
        prefix = "\n" if import_offset else ""
        edits.append((import_offset, import_offset, prefix + _IMPORT_LINE))

    candidate = _apply_edits(original, edits)
    ast.parse(candidate, filename=f"{target}<v63-candidate>")
    if _function_segment(candidate, str(probe["peer_handler"])) != peer_before:
        raise RuntimeError("PEER_RECOVERY_HANDLER_CHANGED")
    if _function_segment(candidate, str(probe["anchor_handler"])) != anchor_before:
        raise RuntimeError("ANCHOR_RECOVERY_HANDLER_CHANGED")

    final_validation = validate_v63_production_source_snapshot(root, snapshot)
    if not final_validation["valid"]:
        return {
            "status": "BLOCKED_SOURCE_DRIFT",
            "codegen_performed": False,
            "modifies_checkout": False,
            "source_snapshot_validation": final_validation,
            "blockers": list(final_validation.get("blockers") or []),
            "production_ready": False,
        }

    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        candidate.splitlines(keepends=True),
        fromfile=f"a/{target_rel}",
        tofile=f"b/{target_rel}",
    ))
    return {
        "status": "RECOVERY_OVERLAY_PATCH_CANDIDATE_READY",
        "scope": "RECOVERY_OVERLAY_ONLY",
        "target_file": target_rel,
        "candidate_source": candidate,
        "candidate_sha256": _sha256_text(candidate),
        "unified_diff": diff,
        "codegen_performed": True,
        "modifies_checkout": False,
        "switches_production_entrypoint": False,
        "validated_production_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "source_snapshot_validation": final_validation,
        "durable_mutations": list(V63_WAL_BINDINGS),
        "recovery_overlay_binding_complete": False,
        "production_ready": False,
        "next_gate": "APPLY_ON_EXACT_CHECKOUT_AND_RUN_RECOVERY_ACCEPTANCE",
        "probe": probe,
    }
