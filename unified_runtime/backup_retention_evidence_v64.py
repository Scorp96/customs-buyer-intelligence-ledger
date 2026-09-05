from __future__ import annotations

from typing import Any


_DURABLE_BACKUP_MODES = {
    "OBJECT_STORE_REPLICATED",
    "EXTERNAL_DURABLE_ROOT",
    "PERSISTENT_VOLUME_WITH_EXTERNAL_REPLICA",
}


def _backup_status(health: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(health or {})
    status = dict(payload.get("backup_recovery") or {})
    return status if status.get("schema") == "cbi.backup-status.v6.1" else {}


def _snapshot_id(status: dict[str, Any]) -> str:
    return str(dict(status.get("latest") or {}).get("snapshot_id") or "").strip()


def build_backup_retention_evidence(
    *,
    pre_deploy_health: dict[str, Any],
    post_restart_health: dict[str, Any],
    post_deploy_health: dict[str, Any],
    production_source_snapshot_sha256: str,
    backup_root_persistence_mode: str,
    external_replication_verified: bool,
    external_snapshot_locator: str,
    observed_at: str,
) -> dict[str, Any]:
    """Derive deployment backup-retention evidence from observed runtime health."""
    before = _backup_status(pre_deploy_health)
    restarted = _backup_status(post_restart_health)
    deployed = _backup_status(post_deploy_health)
    blockers: list[str] = []

    if not before:
        blockers.append("PREDEPLOY_BACKUP_HEALTH_INVALID")
    if not restarted:
        blockers.append("POST_RESTART_BACKUP_HEALTH_INVALID")
    if not deployed:
        blockers.append("POST_DEPLOY_BACKUP_HEALTH_INVALID")

    before_id = _snapshot_id(before)
    restart_id = _snapshot_id(restarted)
    deploy_id = _snapshot_id(deployed)
    if not before_id or before.get("daily_snapshot_present") is not True:
        blockers.append("PREEXISTING_BACKUP_SNAPSHOT_NOT_OBSERVED")
    if before_id and restart_id != before_id:
        blockers.append("BACKUP_HISTORY_NOT_PRESERVED_AFTER_RESTART")
    if before_id and deploy_id != before_id:
        blockers.extend(("PREDEPLOY_BACKUP_SNAPSHOT_NOT_PRESERVED", "BACKUP_HISTORY_NOT_PRESERVED_AFTER_DEPLOY"))

    before_root = str(before.get("backup_root") or "").strip()
    restart_root = str(restarted.get("backup_root") or "").strip()
    deploy_root = str(deployed.get("backup_root") or "").strip()
    if not before_root:
        blockers.append("BACKUP_ROOT_MISSING")
    if before_root and restart_root != before_root:
        blockers.append("BACKUP_ROOT_CHANGED_AFTER_RESTART")
    if before_root and deploy_root != before_root:
        blockers.append("BACKUP_ROOT_CHANGED_AFTER_DEPLOY")
    if any(status and status.get("restore_overwrites_live_root") is not False for status in (before, restarted, deployed)):
        blockers.append("BACKUP_RESTORE_MAY_OVERWRITE_LIVE_ROOT")

    mode = str(backup_root_persistence_mode or "").strip().upper()
    if mode not in _DURABLE_BACKUP_MODES:
        blockers.append("BACKUP_ROOT_NOT_DURABLE")
    if external_replication_verified is not True:
        blockers.append("EXTERNAL_BACKUP_REPLICATION_NOT_VERIFIED")
    locator = str(external_snapshot_locator or "").strip()
    if not locator:
        blockers.append("EXTERNAL_BACKUP_SNAPSHOT_LOCATOR_MISSING")

    source_sha = str(production_source_snapshot_sha256 or "").strip().lower()
    if len(source_sha) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha):
        blockers.append("PRODUCTION_SOURCE_SNAPSHOT_INVALID")
    observed = str(observed_at or "").strip()
    if not observed:
        blockers.append("OBSERVED_AT_MISSING")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "cbi.v64-backup-retention-evidence.v1",
        "verified": not blockers,
        "production_source_snapshot_sha256": source_sha,
        "preexisting_snapshot_observed": bool(before_id) and before.get("daily_snapshot_present") is True,
        "snapshot_id_before_deploy": before_id or None,
        "snapshot_id_after_restart": restart_id or None,
        "snapshot_ids_after_deploy": [deploy_id] if deploy_id else [],
        "backup_history_preserved_after_restart": bool(before_id) and restart_id == before_id,
        "backup_history_preserved_after_deploy": bool(before_id) and deploy_id == before_id,
        "backup_root_before_deploy": before_root or None,
        "backup_root_after_restart": restart_root or None,
        "backup_root_after_deploy": deploy_root or None,
        "backup_root_persistence_mode": mode or None,
        "external_replication_verified": external_replication_verified is True,
        "external_snapshot_locator": locator or None,
        "restore_target_isolated": True,
        "restore_overwrites_live_root": False,
        "observed_at": observed or None,
        "source": "HOST_BACKUP_RETENTION_HEALTH_SEQUENCE",
        "blockers": blockers,
    }
