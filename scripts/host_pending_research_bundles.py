#!/usr/bin/env python3
"""Offline host queue for v6 research bundles; no MCP connection is required."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from unified_runtime import UnifiedRuntime  # noqa: E402
from unified_runtime.v6 import HostBundleQueue  # noqa: E402


def default_queue_root() -> Path:
    configured = os.environ.get("CBI_HOST_PENDING_ROOT")
    if configured:
        return Path(configured)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "XingHuai" / "CustomsBuyerIntelligence" / "host-pending-v6"


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue or synchronize Customs Buyer Intelligence v6 research bundles.")
    parser.add_argument("--root", default=str(default_queue_root()))
    sub = parser.add_subparsers(dest="command", required=True)
    queue_parser = sub.add_parser("queue")
    queue_parser.add_argument("payload", help="UTF-8 JSON file containing investigation_id and bundle")
    sub.add_parser("status")
    sync_parser = sub.add_parser("sync")
    sync_parser.add_argument("--investigation-id", default="")
    sync_parser.add_argument("--limit", type=int, default=100)
    sync_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    queue = HostBundleQueue(Path(args.root))
    if args.command == "queue":
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        result = queue.queue(payload)
    elif args.command == "status":
        rows = queue.entries()
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        result = {"count": len(rows), "counts": counts, "entries": rows}
    else:
        os.environ["CBI_HOST_PENDING_ROOT"] = str(Path(args.root).resolve())
        runtime = UnifiedRuntime()
        result = runtime.sync_pending_bundles({
            "investigation_id": args.investigation_id,
            "limit": args.limit,
            "dry_run": args.dry_run,
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

