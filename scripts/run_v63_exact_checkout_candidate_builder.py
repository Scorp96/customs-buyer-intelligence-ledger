from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_ops_v63.exact_checkout_candidate_builder import (
    EXPECTED_V62_PRODUCTION_COMMIT,
    build_exact_checkout_candidate_artifact,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a read-only CBI v6.3 exact-checkout integration candidate from the locally available reviewed v6.2 commit."
    )
    default_repo = Path(os.environ.get("USERPROFILE", r"C:\Users\scorp")) / "plugins" / "customs-buyer-intelligence"
    parser.add_argument("--repo-root", default=str(default_repo))
    parser.add_argument("--output", default=str(ROOT / "results" / "CBI_v63_Exact_Checkout_Candidate_Result.zip"))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    result = build_exact_checkout_candidate_artifact(
        args.repo_root,
        args.output,
        payload_root=ROOT,
        python_executable=args.python,
        expected_commit=EXPECTED_V62_PRODUCTION_COMMIT,
        run_validation=True,
    )
    summary = {
        "status": result.get("status"),
        "production_ready": result.get("production_ready"),
        "artifact": dict(result.get("artifact") or {}).get("path"),
        "next_gate": result.get("next_gate"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result.get("artifact_written"):
        print(f"RESULT_ZIP: {dict(result.get('artifact') or {}).get('path')}")
    return 0 if result.get("status") == "EXACT_CHECKOUT_STATIC_CANDIDATE_VERIFIED_LIVE_BINDING_PENDING" else 2


if __name__ == "__main__":
    raise SystemExit(main())
