from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES
from .production_source_snapshot_v63 import (
    build_v63_production_source_snapshot,
    validate_v63_production_source_snapshot,
)


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_REQUIRED_ACTIVE_MCP_TOOLS = set(V63_READ_ONLY_TOOL_NAMES) | set(V63_MUTATION_TOOL_NAMES)


def _checkout_git_sha(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(repo_root).resolve(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=10,
    )
    sha = str(completed.stdout or "").strip().lower()
    if completed.returncode != 0 or not _GIT_SHA_RE.fullmatch(sha):
        raise RuntimeError("CHECKOUT_GIT_SHA_UNAVAILABLE")
    return sha


def capture_v63_active_mcp_surface_evidence(
    repo_root: Path,
    *,
    expected_git_sha: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    expected = str(expected_git_sha or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(expected):
        raise RuntimeError("EXPECTED_GIT_SHA_INVALID")
    actual = _checkout_git_sha(root)
    if actual != expected:
        raise RuntimeError(f"GIT_SHA_MISMATCH expected={expected} actual={actual}")

    snapshot = build_v63_production_source_snapshot(root)
    snapshot_sha = str(snapshot.get("snapshot_sha256") or "").strip().lower()
    if (
        snapshot.get("status") != "READY"
        or snapshot.get("source_pins_complete") is not True
        or not _SHA256_RE.fullmatch(snapshot_sha)
    ):
        raise RuntimeError("SOURCE_SNAPSHOT_NOT_READY")

    with tempfile.TemporaryDirectory(prefix="cbi-v63-mcp-surface-") as td:
        harness = ExactCheckoutMcpHarness(root, Path(td))
        entrypoint = harness.active_entrypoint()
        harness.start()
        try:
            observed = harness.list_tool_names()
        finally:
            harness.stop()

    missing = sorted(_REQUIRED_ACTIVE_MCP_TOOLS - set(observed))
    if missing:
        raise RuntimeError("V63_ACTIVE_MCP_SURFACE_INCOMPLETE:" + ",".join(missing))

    validation = validate_v63_production_source_snapshot(root, snapshot)
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise RuntimeError("SOURCE_SNAPSHOT_DRIFT")

    return {
        "schema": "cbi.v63-mcp-surface-evidence.v1",
        "verified": True,
        "git_sha": actual,
        "production_source_snapshot_sha256": snapshot_sha,
        "active_entrypoint": entrypoint,
        "active_entrypoint_observed": True,
        "tools_list_observed": True,
        "tool_names": sorted(observed),
        "required_tool_names": sorted(_REQUIRED_ACTIVE_MCP_TOOLS),
        "missing_tools": [],
        "source_snapshot_validation": validation,
    }
