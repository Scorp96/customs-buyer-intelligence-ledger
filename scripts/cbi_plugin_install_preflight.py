#!/usr/bin/env python3
"""Fail-closed, offline preflight for the currently supported CBI cloud plugin.

This validates a plugin CHECKOUT or packaged source tree. It does not connect,
install, refresh a ChatGPT connector, inspect credentials, or change Runtime.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_PLUGIN_NAME = "customs-buyer-intelligence"
EXPECTED_SERVER_NAME = "buyer-outreach-actions"
EXPECTED_URL = "https://cbi-v61-preview.onrender.com/mcp"
NEEDED_JSON = (
    "plugin.json",
    ".codex-plugin/plugin.json",
    "mcp.json",
    ".mcp.json",
)
NEEDED_TEXT = ("skills/investigate-customs-buyers/SKILL.md",)
LOCAL_EXECUTION_FIELDS = frozenset({"command", "args", "cwd", "env", "environment", "stdio", "shell"})


def _read_json(root: Path, path: str, errors: list[str]) -> dict[str, Any] | None:
    candidate = root / path
    if candidate.is_symlink():
        errors.append("SYMLINK_MANIFEST_FORBIDDEN:" + path)
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        errors.append("MISSING_REQUIRED_FILE:" + path)
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append("INVALID_REQUIRED_JSON:" + path)
        return None
    if not isinstance(data, dict):
        errors.append("JSON_ROOT_NOT_OBJECT:" + path)
        return None
    return data


def _check_mcp(
    *,
    name: str,
    payload: dict[str, Any] | None,
    expected_type: str,
    errors: list[str],
) -> None:
    if payload is None:
        return
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict) or set(servers) != {EXPECTED_SERVER_NAME}:
        errors.append("MCP_SERVER_SET_MISMATCH:" + name)
        return
    server = servers[EXPECTED_SERVER_NAME]
    if not isinstance(server, dict):
        errors.append("MCP_SERVER_NOT_OBJECT:" + name)
        return
    for key in sorted(set(server) & LOCAL_EXECUTION_FIELDS):
        errors.append("LOCAL_MCP_EXECUTION_FORBIDDEN:" + name + ":" + key)
    if server.get("type") != expected_type:
        errors.append("MCP_TRANSPORT_TYPE_MISMATCH:" + name)
    if server.get("url") != EXPECTED_URL:
        errors.append("MCP_TARGET_NOT_CANONICAL_RENDER:" + name)


def validate_checkout(root: str | Path) -> dict[str, Any]:
    """Return conservative, deterministic offline packaging diagnostics."""
    root = Path(root).expanduser().resolve()
    errors: list[str] = []
    docs = {path: _read_json(root, path, errors) for path in NEEDED_JSON}
    portable = docs["plugin.json"]
    codex = docs[".codex-plugin/plugin.json"]
    if portable is not None and codex is not None:
        if portable.get("name") != EXPECTED_PLUGIN_NAME or codex.get("name") != EXPECTED_PLUGIN_NAME:
            errors.append("PACKAGE_IDENTITY_MISMATCH")
        pv, cv = portable.get("version"), codex.get("version")
        if not isinstance(pv, str) or pv != cv:
            errors.append("PACKAGE_VERSION_MISMATCH")
        else:
            match = re.fullmatch(r"6\.4\.(\d+)\+codex\.\d{8}\.r\d+", pv)
            if not match or int(match.group(1)) < 2:
                errors.append("OBSOLETE_OR_INVALID_PACKAGE_VERSION")
        if codex.get("mcpServers") != "./.mcp.json":
            errors.append("CODEX_COMPATIBILITY_REFERENCE_INVALID")
        if codex.get("skills") != "./skills/":
            errors.append("CODEX_SKILL_ROOT_INVALID")
        prompts = (codex.get("interface") or {}).get("defaultPrompt")
        if not isinstance(prompts, list) or not prompts or any(
            not isinstance(p, str) for p in prompts
        ):
            errors.append("CODEX_DEFAULT_PROMPTS_INVALID")
        else:
            if any("$customs-buyer-one-shot" in p for p in prompts):
                errors.append("RETIRED_ONE_SHOT_MODE_REFERENCED")
    _check_mcp(name="mcp.json", payload=docs["mcp.json"], expected_type="streamable-http", errors=errors)
    _check_mcp(name=".mcp.json", payload=docs[".mcp.json"], expected_type="http", errors=errors)
    compat = docs[".mcp.json"]
    if compat is not None and "mcp_servers" in compat:
        errors.append("UNSUPPORTED_SNAKE_CASE_COMPATIBILITY")

    for path in NEEDED_TEXT:
        target = root / path
        if target.is_symlink():
            errors.append("SYMLINK_SKILL_FORBIDDEN:" + path)
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("MISSING_OR_UNREADABLE_SKILL:" + path)
            continue
        for keyword in (
            "Mandatory host-side MCP authority preflight",
            "ROUTE_IDENTITY_CONFLICT",
            "FULL_AUDIT",
            "EXHAUSTIVE",
            "external_replication_verified",
        ):
            if keyword not in content:
                errors.append("MANDATORY_SAFETY_SKILL_CONTRACT_MISSING:" + keyword)
    return {
        "schema": "cbi.plugin-install-preflight.v1",
        "status": "PASS" if not errors else "BLOCKED",
        "package_version": portable.get("version") if portable else None,
        "canonical_endpoint": EXPECTED_URL,
        "blockers": sorted(set(errors)),
        "local_runtime_started": False,
        "network_access_performed": False,
        "installed_connector_validated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CBI plugin source before install/release")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    report = validate_checkout(args.root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
