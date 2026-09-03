from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExactCheckoutAcceptanceConfig:
    repo_root: Path
    expected_git_sha: str
    output_dir: Path


def run_v63_exact_checkout_live_acceptance(
    config: ExactCheckoutAcceptanceConfig,
) -> dict[str, Any]:
    if not isinstance(config, ExactCheckoutAcceptanceConfig):
        raise TypeError("config must be ExactCheckoutAcceptanceConfig")
    raise RuntimeError("ACCEPTANCE_EXECUTION_NOT_IMPLEMENTED")
