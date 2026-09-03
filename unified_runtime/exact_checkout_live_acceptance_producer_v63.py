from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import production_source_snapshot_v63


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ExactCheckoutAcceptanceConfig:
    repo_root: Path
    expected_git_sha: str
    output_dir: Path


def _checkout_git_sha(repo_root: Path) -> str:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise RuntimeError("CHECKOUT_ROOT_NOT_FOUND")
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("CHECKOUT_GIT_SHA_UNAVAILABLE") from exc
    sha = str(completed.stdout or "").strip().lower()
    if completed.returncode != 0 or not _GIT_SHA_RE.fullmatch(sha):
        raise RuntimeError("CHECKOUT_GIT_SHA_UNAVAILABLE")
    return sha


def _assert_expected_git_sha(config: ExactCheckoutAcceptanceConfig) -> str:
    expected = str(config.expected_git_sha or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(expected):
        raise RuntimeError("EXPECTED_GIT_SHA_INVALID")
    actual = _checkout_git_sha(config.repo_root)
    if actual != expected:
        raise RuntimeError(f"GIT_SHA_MISMATCH expected={expected} actual={actual}")
    return actual


def _build_ready_source_snapshot(repo_root: Path) -> dict[str, Any]:
    snapshot = production_source_snapshot_v63.build_v63_production_source_snapshot(
        Path(repo_root).resolve()
    )
    if not isinstance(snapshot, dict):
        raise RuntimeError("SOURCE_SNAPSHOT_NOT_READY: invalid snapshot result")
    snapshot_sha = str(snapshot.get("snapshot_sha256") or "").strip().lower()
    if (
        snapshot.get("status") != "READY"
        or snapshot.get("source_pins_complete") is not True
        or not _SHA256_RE.fullmatch(snapshot_sha)
    ):
        blockers = ",".join(str(item) for item in snapshot.get("blockers") or [])
        detail = f":{blockers}" if blockers else ""
        raise RuntimeError(f"SOURCE_SNAPSHOT_NOT_READY{detail}")
    return snapshot


def run_v63_exact_checkout_live_acceptance(
    config: ExactCheckoutAcceptanceConfig,
) -> dict[str, Any]:
    if not isinstance(config, ExactCheckoutAcceptanceConfig):
        raise TypeError("config must be ExactCheckoutAcceptanceConfig")
    _assert_expected_git_sha(config)
    _build_ready_source_snapshot(config.repo_root)
    raise RuntimeError("ACCEPTANCE_EXECUTION_NOT_IMPLEMENTED")
