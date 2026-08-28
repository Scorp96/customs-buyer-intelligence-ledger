#!/usr/bin/env python3
"""Offline-safe CLI for Customs Buyer Intelligence v5.4.1 receipts.

This is the local fallback boundary: it can queue and replay append-only
receipts when a remote MCP tunnel is unavailable. Replay is always an explicit
operator action; MCP initialization never triggers it. It does not perform web
research, create evidence, or claim that the tunnel is healthy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from unified_runtime import UnifiedRuntime, ValidationError  # noqa: E402


def read_json(path: str) -> dict[str, Any]:
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValidationError("payload JSON must be an object")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Queue, inspect and replay Customs Buyer Intelligence Pending Receipts.",
    )
    subcommands = result.add_subparsers(dest="command", required=True)

    queue = subcommands.add_parser("queue", help="Queue one append-only receipt from JSON.")
    queue.add_argument("--target", required=True, choices=sorted({
        "append_information_record",
        "append_execution_receipt",
        "append_provider_receipt",
        "append_peer_receipt",
        "append_crm_writeback_receipt",
    }))
    queue.add_argument("--payload", required=True, help="UTF-8 JSON path, or - for stdin.")
    queue.add_argument("--journal-id", default="")

    status = subcommands.add_parser("status", help="Read the append-only Pending Journal status.")
    status.add_argument("--investigation-id", default="")

    sync = subcommands.add_parser("sync", help="Replay pending receipts through Runtime validation.")
    sync.add_argument("--investigation-id", default="")
    sync.add_argument("--limit", type=int, default=100)
    sync.add_argument("--dry-run", action="store_true")

    health = subcommands.add_parser("health", help="Verify local Runtime hash chains.")
    health.add_argument("--investigation-id", default="")

    subcommands.add_parser("contract", help="Print the self-describing v5.4 Runtime contract.")
    return result


def main() -> int:
    arguments = parser().parse_args()
    runtime = UnifiedRuntime()
    try:
        if arguments.command == "queue":
            output = runtime.queue_pending_receipt({
                "target_tool": arguments.target,
                "payload": read_json(arguments.payload),
                "journal_id": arguments.journal_id,
            })
        elif arguments.command == "status":
            output = runtime.get_pending_journal_status({
                "investigation_id": arguments.investigation_id,
            })
        elif arguments.command == "sync":
            output = runtime.sync_pending_receipts({
                "investigation_id": arguments.investigation_id,
                "limit": arguments.limit,
                "dry_run": arguments.dry_run,
            })
        elif arguments.command == "health":
            output = runtime.get_runtime_health({
                "investigation_id": arguments.investigation_id,
            })
        else:
            output = runtime.get_runtime_contract({})
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
