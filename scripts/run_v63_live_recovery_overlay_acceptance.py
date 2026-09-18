#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.live_recovery_overlay_runner_v63 import run_live_recovery_overlay_acceptance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipts", required=True)
    parser.add_argument("--expected-source-snapshot", required=True)
    parser.add_argument("--expected-registry-file", required=True)
    parser.add_argument("--expected-registry-name", required=True)
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.receipts).read_text(encoding="utf-8"))
    result = run_live_recovery_overlay_acceptance(
        payload,
        expected_production_source_snapshot_sha256=args.expected_source_snapshot,
        expected_recovery_registry_file=args.expected_registry_file,
        expected_recovery_registry_name=args.expected_registry_name,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
