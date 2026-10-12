#!/usr/bin/env python3
"""Validate a user-approved machinery HS candidate JSON export offline.

No network, no writes, no mutation WAL, no uploads, and no customer promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.machinery_catalog_seed_v64 import (
    validate_machinery_catalog_candidates,
    plan_catalog_customs_queries,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-json", type=Path, required=True)
    p.add_argument("--expected-rows", type=int, default=99)
    p.add_argument("--expected-coded", type=int, default=85)
    p.add_argument("--target-country", default="Indonesia")
    p.add_argument("--query-limit", type=int, default=50)
    args = p.parse_args(argv)
    path = args.input_json.expanduser().resolve(strict=True)
    if not path.is_file():
        p.error("--input-json must reference a file")
    payload = path.read_bytes()
    try:
        rows = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        p.error(f"UTF8 JSON required: {type(exc).__name__}")
    report = validate_machinery_catalog_candidates(
        rows, expected_row_count=args.expected_rows,
        expected_hs6_candidate_count=args.expected_coded,
    )
    plan = plan_catalog_customs_queries(
        report, target_country=args.target_country, limit=args.query_limit,
    )
    print(json.dumps({
        "status": "VALIDATED_SEARCH_SEEDS_ONLY",
        "schema": report["schema"],
        "input_sha256": hashlib.sha256(payload).hexdigest(),
        "source_document_sha256_set": report["source_sha256_set"],
        "row_count": report["row_count"],
        "hs6_candidate_count": report["hs6_candidate_count"],
        "pending_classification_count": report["pending_classification_count"],
        "national_tariff_codes_confirmed": 0,
        "seller_capability": report["seller_capability"],
        "actual_import_records_verified": 0,
        "planned_query_count": plan["candidate_query_count"],
        "query_sample": [row["query"] for row in plan["queries"][:8]],
        "queries_executed": False,
        "production_write_performed": False,
    }, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
