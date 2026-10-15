"""Opt-in, read-only in-process Git-blob attestation for isolated CBI CI.

No network, secrets or arbitrary file paths; default production state is disabled.
Authenticated transport is required, but separate operator RBAC is NOT proven.
Caller must independently pin GitHub blobs and deployed commit.
"""
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path
from typing import Any

TOOL_NAME = "get_runtime_source_attestation"
_SCHEMA = "cbi.runtime-source-attestation.isolated.v1"
_ALLOWED = {
    "mcp.server_v61_remote": "mcp/server_v61_remote.py",
    "mcp.server": "mcp/server.py",
    "mcp.server_v61_backup_recovery": "mcp/server_v61_backup_recovery.py",
    "mcp.cloud_runtime_startup_guard": "mcp/cloud_runtime_startup_guard.py",
    "mcp.object_store_recovery_v63": "mcp/object_store_recovery_v63.py",
    "unified_runtime.route_reuse": "unified_runtime/route_reuse.py",
    "unified_runtime.backup_recovery_hardened": "unified_runtime/backup_recovery_hardened.py",
    "unified_runtime.existing_production_store_backend_v63": "unified_runtime/existing_production_store_backend_v63.py",
}

def _hex40(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value.lower())

def _blocked(reason: str) -> dict[str, Any]:
    return {"schema": _SCHEMA, "status": "BLOCKED", "blockers": [reason],
            "read_only": True, "production_write_performed": False,
            "external_pin_independence_proven": False}

def measure_loaded_sources(*, root: Path, git_commit: str,
                           expected_blobs: dict[str, str],
                           loaded: dict[str, Any]) -> dict[str, Any]:
    """Measure only literal allowlisted paths. File bytes never leave the process."""
    if not _hex40(git_commit):
        return _blocked("EXPECTED_COMMIT_INVALID")
    if not isinstance(expected_blobs, dict) or set(expected_blobs) != set(_ALLOWED):
        return _blocked("EXPECTED_BLOB_INVENTORY_INVALID")
    if any(not _hex40(v) for v in expected_blobs.values()):
        return _blocked("EXPECTED_BLOB_HASH_INVALID")
    try:
        basedir = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return _blocked("APPLICATION_ROOT_NOT_ACCESSIBLE")
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for mod, relative in _ALLOWED.items():
        row: dict[str, Any] = {"module": mod, "relative_path": relative,
            "expected_git_blob_sha1": expected_blobs[mod].lower(),
            "observed_git_blob_sha1": None, "observed_sha256": None,
            "result": "BLOCKED"}
        imported = loaded.get(mod)
        location = getattr(imported, "__file__", None) if imported is not None else None
        if not isinstance(location, str) or not location:
            blockers.append("MODULE_NOT_LOADED:" + mod)
            rows.append(row)
            continue
        try:
            absolute = Path(location).resolve(strict=True)
            pinned_path = (basedir / relative).resolve(strict=True)
            if absolute != pinned_path or not absolute.is_relative_to(basedir) or absolute.suffix != ".py":
                blockers.append("MODULE_ORIGIN_MISMATCH:" + mod)
                rows.append(row)
                continue
            if not absolute.is_file():
                raise OSError("not a regular file")
            payload = absolute.read_bytes()
        except (OSError, RuntimeError, ValueError) as e:
            blockers.append("MODULE_FILE_UNREADABLE:" + mod + ":" + type(e).__name__)
            rows.append(row)
            continue
        sha1 = hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\x00" + payload).hexdigest()
        row["observed_git_blob_sha1"] = sha1
        row["observed_sha256"] = hashlib.sha256(payload).hexdigest()
        if sha1 != expected_blobs[mod].lower():
            blockers.append("MODULE_GIT_BLOB_MISMATCH:" + mod)
        else:
            row["result"] = "MATCH"
        rows.append(row)
    return {"schema": _SCHEMA, "status": "MATCH" if not blockers else "BLOCKED",
        "blockers": blockers, "expected_git_commit": git_commit.lower(),
        "measurements": rows, "measurement_count": len(rows),
        "read_only": True, "production_write_performed": False,
        "in_process_execution_observed": True,
        "external_pin_independence_proven": False,
        "warning": "External authority of supplied blob pins must be independently verified; no production runtime attestation is implied by CI."}

def install_isolated_attestation(*, server_module: Any, app_root: Path,
                                 deployment_git_sha: str | None,
                                 enabled: bool) -> bool:
    if not enabled:
        return False
    original_descriptors = server_module.tool_descriptors
    def descriptors() -> list[dict[str, Any]]:
        rows = copy.deepcopy(original_descriptors())
        rows.append({"name": TOOL_NAME,
            "description": "[ISOLATED_OPT_IN_ONLY] Authenticated read-only loaded-module Git blob comparison; not independent operator authorization or production proof.",
            "inputSchema": {"type": "object", "additionalProperties": False,
                "required": ["expected_git_commit", "expected_blobs"],
                "properties": {
                    "expected_git_commit": {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"},
                    "expected_blobs": {"type": "object", "additionalProperties":
                        {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"},
                        "minProperties": len(_ALLOWED), "maxProperties": len(_ALLOWED)},
                }}})
        return rows
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            return _blocked("ARGUMENTS_INVALID")
        supplied = args.get("expected_git_commit")
        if not deployment_git_sha or not isinstance(supplied, str) or supplied.lower() != deployment_git_sha:
            return _blocked("DEPLOYMENT_GIT_SHA_NOT_PINNED_OR_MISMATCH")
        blobs = args.get("expected_blobs")
        if not isinstance(blobs, dict):
            return _blocked("EXPECTED_BLOB_INVENTORY_INVALID")
        modules = {key: sys.modules.get(key) for key in _ALLOWED}
        if modules["mcp.server_v61_remote"] is None:
            modules["mcp.server_v61_remote"] = sys.modules.get("__main__")
        return measure_loaded_sources(root=app_root, git_commit=supplied,
                                      expected_blobs=blobs, loaded=modules)
    server_module.tool_descriptors = descriptors
    server_module.TOOL_HANDLERS[TOOL_NAME] = handler
    return True
