#!/usr/bin/env python3
"""Seed an S3-compatible CBI object store from a trusted migration export.

Run this once from the Windows workstation that holds the already-validated
CBI_Cloud_Runtime_Export_*.tar.gz. Credentials are read only from environment
variables and are never written into the repository or archive.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.object_store_persistence import ObjectStorePersistenceError, ObjectStoreStateManager


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed CBI object-store generation zero")
    parser.add_argument("archive", type=Path, help="Trusted CBI_Cloud_Runtime_Export_*.tar.gz")
    parser.add_argument("--expected-sha256", required=True, help="Exact SHA-256 emitted by exporter")
    return parser


def main() -> int:
    args = _parser().parse_args()
    manager = ObjectStoreStateManager.from_env()
    if manager is None:
        raise SystemExit("CBI_OBJECT_STORE_MODE must be s3 or r2")
    try:
        pointer = manager.seed_migration_archive(args.archive, args.expected_sha256)
    except ObjectStorePersistenceError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({
        "status": "PASS",
        "generation": pointer.generation,
        "archive_format": pointer.archive_format,
        "archive_key": pointer.archive_key,
        "archive_sha256": pointer.archive_sha256,
        "sessions_fingerprint_sha256": pointer.sessions_fingerprint_sha256,
        "pointer_key": manager.pointer_key,
        "cas_fail_closed": True,
        "instruction": "Restart/redeploy the Render service after configuring the same object-store environment variables there.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
