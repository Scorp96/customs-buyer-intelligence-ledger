#!/usr/bin/env python3
"""Read-only offline V6.4 create-event diagnostic.

Input must be a previously authorized, isolated JSON export containing
normalized v6.3 opportunity events. Do not point this tool at the live
SessionStore or its WAL; it never opens either itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from unified_runtime.opportunity_duplicate_audit_v64 import diagnose_opportunity_create_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only duplicate-create event diagnostic")
    parser.add_argument("--normalized-events-json", type=Path, required=True)
    args = parser.parse_args(argv)
    file = args.normalized_events_json.expanduser().resolve(strict=True)
    if not file.is_file():
        parser.error("input must be an existing JSON file")
    # No production store access, no files created or modified.
    with file.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        parser.error("input must be a JSON array of normalized v6.3 events")
    result = diagnose_opportunity_create_events(raw)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "NO_DUPLICATE_CREATE_EVENTS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
