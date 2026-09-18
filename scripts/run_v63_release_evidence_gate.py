#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.release_evidence_v63 import evaluate_v63_release_evidence_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    result = evaluate_v63_release_evidence_bundle(payload)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("production_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
