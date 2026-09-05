#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.exact_checkout_live_acceptance_producer_v63 import (
    ExactCheckoutAcceptanceConfig,
    run_v63_exact_checkout_live_acceptance,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    try:
        result = run_v63_exact_checkout_live_acceptance(
            ExactCheckoutAcceptanceConfig(
                repo_root=ROOT,
                expected_git_sha=args.expected_git_sha,
                output_dir=Path(args.output_dir),
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "verified": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    backend_verified = (
        isinstance(result.get("backend_validation"), dict)
        and result["backend_validation"].get("verified") is True
    )
    recovery_verified = (
        isinstance(result.get("recovery_validation"), dict)
        and result["recovery_validation"].get("verified") is True
    )
    exact_recovery_verified = (
        isinstance(result.get("exact_recovery_validation"), dict)
        and result["exact_recovery_validation"].get("verified") is True
    )
    nonproduction_boundary_preserved = (
        result.get("production_ready") is False
        and result.get("render_r2_acceptance_required") is True
        and result.get("execution_environment") == "EXACT_CHECKOUT_ISOLATED"
        and result.get("deployment_environment") == "NOT_RENDER_PRODUCTION"
    )
    return 0 if (
        backend_verified
        and recovery_verified
        and exact_recovery_verified
        and nonproduction_boundary_preserved
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
