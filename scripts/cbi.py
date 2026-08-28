#!/usr/bin/env python3
"""Operator CLI for Customs Buyer Intelligence v6."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from unified_runtime import UnifiedRuntime  # noqa: E402


def emit(value: object) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="cbi", description="Customs Buyer Intelligence v6 operator CLI")
    parser.add_argument("--session-root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "resume", "claims", "pivots", "peers"):
        child = sub.add_parser(command)
        child.add_argument("investigation_id")
    health = sub.add_parser("health")
    health.add_argument("--investigation-id", default="")
    pending = sub.add_parser("pending")
    pending.add_argument("--limit", type=int, default=100)
    migrate = sub.add_parser("migrate")
    migrate.add_argument("target_root")
    migrate.add_argument("--source-session-root", default="")
    verify = sub.add_parser("verify")
    verify.add_argument("--investigation-id", default="")
    args = parser.parse_args()
    runtime = UnifiedRuntime(args.session_root)
    if args.command == "status":
        return emit(runtime.get_account_state({"investigation_id": args.investigation_id}))
    if args.command == "health":
        payload = {"investigation_id": args.investigation_id} if args.investigation_id else {}
        return emit(runtime.get_runtime_health(payload))
    if args.command == "resume":
        return emit(runtime.resume_investigation({"investigation_id": args.investigation_id}))
    if args.command == "claims":
        return emit(runtime.get_claims({"investigation_id": args.investigation_id}))
    if args.command == "pivots":
        return emit(runtime.get_material_pivots({"investigation_id": args.investigation_id}))
    if args.command == "peers":
        state = runtime._v6_state(args.investigation_id)
        return emit({"investigation_id": args.investigation_id, "peers": list(state["peers"].values())})
    if args.command == "pending":
        rows = runtime._v6_queue().entries()[: args.limit]
        return emit({"count": len(rows), "entries": rows})
    if args.command == "migrate":
        payload = {"target_root": args.target_root}
        if args.source_session_root:
            payload["source_session_root"] = args.source_session_root
        return emit(runtime.migrate_v5_4_1_to_v6(payload))
    if args.command == "verify":
        if args.investigation_id:
            return emit(runtime.get_investigation_health({"investigation_id": args.investigation_id}))
        return emit(runtime.get_runtime_health({}))
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

