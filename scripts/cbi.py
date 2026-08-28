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
from unified_runtime.backup_recovery_hardened import ProductionBackupRecoveryManager  # noqa: E402
from unified_runtime.resilience import digest  # noqa: E402


def emit(value: object) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def backup_public(value: dict) -> dict:
    return {
        "snapshot_id": value.get("snapshot_id"),
        "created_at": value.get("created_at"),
        "reasons": list(value.get("reasons") or []),
        "path": value.get("path"),
        "deduplicated": value.get("deduplicated") is True,
        "warnings": list(value.get("warnings") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cbi",
        description="Customs Buyer Intelligence v6 operator CLI",
    )
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

    backup = sub.add_parser("backup")
    backup.add_argument("--reason", default="MANUAL_OPERATOR")
    backup.add_argument(
        "--daily",
        action="store_true",
        help="Create or reuse the UTC-day automatic snapshot.",
    )

    sub.add_parser("backups")

    restore = sub.add_parser("restore")
    restore.add_argument("target_root")
    restore.add_argument("--snapshot-id", default="")
    restore.add_argument(
        "--no-replay-live-tail",
        action="store_true",
        help="Restore the validated snapshot without replaying later proven live events.",
    )

    args = parser.parse_args()
    runtime = UnifiedRuntime(args.session_root)

    if args.command == "status":
        return emit(runtime.get_account_state({"investigation_id": args.investigation_id}))
    if args.command == "health":
        payload = (
            {"investigation_id": args.investigation_id}
            if args.investigation_id
            else {}
        )
        return emit(runtime.get_runtime_health(payload))
    if args.command == "resume":
        return emit(
            runtime.resume_investigation({"investigation_id": args.investigation_id})
        )
    if args.command == "claims":
        return emit(runtime.get_claims({"investigation_id": args.investigation_id}))
    if args.command == "pivots":
        return emit(
            runtime.get_material_pivots({"investigation_id": args.investigation_id})
        )
    if args.command == "peers":
        state = runtime._v6_state(args.investigation_id)
        return emit(
            {
                "investigation_id": args.investigation_id,
                "peers": list(state["peers"].values()),
            }
        )
    if args.command == "pending":
        rows = runtime._v6_queue().entries()[: args.limit]
        return emit({"count": len(rows), "entries": rows})
    if args.command == "migrate":
        payload = {"target_root": args.target_root}
        if args.source_session_root:
            payload["source_session_root"] = args.source_session_root
        source_root = Path(
            payload.get("source_session_root") or runtime.store.root
        ).expanduser().resolve()
        if source_root == Path(runtime.store.root).resolve():
            manager = ProductionBackupRecoveryManager.from_runtime(runtime)
        else:
            manager = ProductionBackupRecoveryManager.for_session_root(source_root)
        backup = manager.ensure_guard_snapshot(
            ["BEFORE_MIGRATION", "BEFORE_SCHEMA_UPGRADE"],
            digest(payload),
        )
        result = runtime.migrate_v5_4_1_to_v6(payload)
        return emit(
            {
                **result,
                "pre_migration_backup": backup_public(backup),
            }
        )
    if args.command == "verify":
        if args.investigation_id:
            return emit(
                runtime.get_investigation_health(
                    {"investigation_id": args.investigation_id}
                )
            )
        return emit(runtime.get_runtime_health({}))
    if args.command == "backup":
        manager = ProductionBackupRecoveryManager.from_runtime(runtime)
        result = (
            manager.ensure_daily_snapshot()
            if args.daily
            else manager.create_snapshot(args.reason)
        )
        return emit(backup_public(result))
    if args.command == "backups":
        manager = ProductionBackupRecoveryManager.from_runtime(runtime)
        return emit(manager.status(validate_latest=True))
    if args.command == "restore":
        manager = ProductionBackupRecoveryManager.from_runtime(runtime)
        return emit(
            manager.restore_latest_valid_snapshot(
                args.target_root,
                snapshot_id=args.snapshot_id,
                replay_live_tail=not args.no_replay_live_tail,
            )
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
