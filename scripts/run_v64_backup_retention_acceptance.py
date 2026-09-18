#!/usr/bin/env python3
"""Evaluate v6.4 durable backup retention evidence from sanitized observations.

This runner is deliberately side-effect free: it does not call Render, object
storage, or the production Runtime.  An external orchestrator supplies the
three sanitized health observations captured before restart, after restart,
and after deploy.  The runner then delegates the policy decision to the
canonical v6.4 backup-retention evidence builder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from unified_runtime.backup_retention_evidence_v64 import build_backup_retention_evidence


_BACKUP_STATUS_SCHEMA = "cbi.backup-status.v6.1"


def _backup_status(health: Any) -> dict[str, Any]:
    if not isinstance(health, dict):
        return {}
    value = health.get("backup_recovery")
    if not isinstance(value, dict) or value.get("schema") != _BACKUP_STATUS_SCHEMA:
        return {}
    return dict(value)


def _observation_has_verified_external_snapshot(status: dict[str, Any]) -> bool:
    if not status:
        return False
    durable = status.get("durable_latest")
    return bool(
        status.get("external_replication_configured") is True
        and status.get("external_replication_verified") is True
        and isinstance(durable, dict)
        and durable.get("verified") is True
        and str(durable.get("snapshot_id") or "").strip()
    )


def evaluate_backup_retention_acceptance(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return fail-closed v6.4 backup-retention evidence for three observations."""
    source = dict(payload) if isinstance(payload, dict) else {}
    pre = source.get("pre_deploy_health")
    restarted = source.get("post_restart_health")
    deployed = source.get("post_deploy_health")

    statuses = (
        _backup_status(pre),
        _backup_status(restarted),
        _backup_status(deployed),
    )
    external_replication_verified = all(
        _observation_has_verified_external_snapshot(status) for status in statuses
    )

    return build_backup_retention_evidence(
        pre_deploy_health=pre if isinstance(pre, dict) else {},
        post_restart_health=restarted if isinstance(restarted, dict) else {},
        post_deploy_health=deployed if isinstance(deployed, dict) else {},
        production_source_snapshot_sha256=str(
            source.get("production_source_snapshot_sha256") or ""
        ),
        backup_root_persistence_mode=str(source.get("backup_root_persistence_mode") or ""),
        external_replication_verified=external_replication_verified,
        external_snapshot_locator=str(source.get("external_snapshot_locator") or ""),
        observed_at=str(source.get("observed_at") or ""),
    )


def _read_payload(input_path: str) -> dict[str, Any]:
    if input_path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(input_path).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("acceptance input must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate sanitized v6.4 backup retention observations."
    )
    parser.add_argument(
        "--input",
        default="-",
        help="JSON input file, or '-' for stdin (default).",
    )
    args = parser.parse_args(argv)

    try:
        evidence = evaluate_backup_retention_acceptance(_read_payload(args.input))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        evidence = {
            "schema": "cbi.v64-backup-retention-evidence.v1",
            "verified": False,
            "blockers": ["ACCEPTANCE_INPUT_INVALID"],
            "error_type": type(exc).__name__,
        }

    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence.get("verified") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
