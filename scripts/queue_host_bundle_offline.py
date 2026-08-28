#!/usr/bin/env python3
"""Persist one host research bundle while the MCP/Runtime transport is offline.

This writer deliberately does not construct ``UnifiedRuntime`` and does not
contact MCP. It only writes the v6.1 process-independent HostBundleQueue. The
normal Runtime can later replay the same durable envelope with
``sync_pending_research_bundles`` / ``sync_pending_bundles``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.v6 import HostBundleQueue  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist one CBI v6.1 research bundle without an MCP connection.",
    )
    parser.add_argument(
        "--queue-root",
        default=os.environ.get("CBI_HOST_PENDING_ROOT", ""),
        help="Durable HostBundleQueue directory. Defaults to CBI_HOST_PENDING_ROOT.",
    )
    parser.add_argument(
        "--payload",
        default="-",
        help="JSON file containing {investigation_id,bundle}; use '-' for stdin.",
    )
    return parser.parse_args(argv)


def load_payload(locator: str) -> dict[str, Any]:
    if locator == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(locator).read_text(encoding="utf-8-sig")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload root must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    queue_root = str(args.queue_root or "").strip()
    if not queue_root:
        raise SystemExit(
            "--queue-root or CBI_HOST_PENDING_ROOT is required; offline mode must know its durable host queue path"
        )
    payload = load_payload(args.payload)
    queued = HostBundleQueue(Path(queue_root)).queue(payload)
    # Never print raw research payloads or secrets. The receipt is sufficient
    # for the Host to prove durable persistence and later correlate replay.
    print(
        json.dumps(
            {
                "schema": "cbi.host-offline-queue-receipt.v6.1",
                "queued": queued["queued"],
                "deduplicated": queued["deduplicated"],
                "bundle_queue_id": queued["bundle_queue_id"],
                "request_sha256": queued["request_sha256"],
                "status": queued["status"],
                "transport": "LOCAL_FILESYSTEM_NO_MCP",
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
