from __future__ import annotations

import unittest

from scripts.run_v64_backup_retention_acceptance import evaluate_backup_retention_acceptance


SNAPSHOT_ID = "SNAP-20260909T104000Z-abcdef123456"
SOURCE_SHA = "b" * 64
LOCATOR = f"cbi-test/backups-v61/manifests/{SNAPSHOT_ID}.json"


def _health(
    *,
    snapshot_id: str = SNAPSHOT_ID,
    local: bool,
    external_verified: bool = True,
    persistence_mode: str = "OBJECT_STORE_REPLICATED",
    restore_overwrites_live_root: bool = False,
) -> dict:
    durable_latest = (
        {
            "snapshot_id": snapshot_id,
            "verified": True,
            "persistence_mode": persistence_mode,
            "archive_sha256": "a" * 64,
        }
        if external_verified and snapshot_id
        else None
    )
    return {
        "status": "READY",
        "backup_recovery": {
            "schema": "cbi.backup-status.v6.1",
            "backup_root": "/var/lib/cbi/live/backups-v61",
            "latest": ({"snapshot_id": snapshot_id} if local and snapshot_id else None),
            "durable_latest": durable_latest,
            "daily_snapshot_present": local and bool(snapshot_id),
            "external_replication_configured": True,
            "external_replication_verified": external_verified,
            "external_snapshot_locator": LOCATOR if external_verified else None,
            "backup_root_persistence_mode": persistence_mode,
            "restore_overwrites_live_root": restore_overwrites_live_root,
        },
    }


def _payload(**overrides) -> dict:
    value = {
        "pre_deploy_health": _health(local=True),
        "post_restart_health": _health(local=False),
        "post_deploy_health": _health(local=False),
        "production_source_snapshot_sha256": SOURCE_SHA,
        "backup_root_persistence_mode": "OBJECT_STORE_REPLICATED",
        "external_snapshot_locator": LOCATOR,
        "observed_at": "2026-09-09T10:45:00Z",
    }
    value.update(overrides)
    return value


class BackupRetentionAcceptanceTests(unittest.TestCase):
    def test_same_verified_external_snapshot_survives_restart_and_deploy(self) -> None:
        result = evaluate_backup_retention_acceptance(_payload())

        self.assertEqual(result["schema"], "cbi.v64-backup-retention-evidence.v1")
        self.assertTrue(result["verified"], result["blockers"])
        self.assertEqual(result["snapshot_id_before_deploy"], SNAPSHOT_ID)
        self.assertEqual(result["snapshot_id_after_restart"], SNAPSHOT_ID)
        self.assertEqual(result["snapshot_ids_after_deploy"], [SNAPSHOT_ID])
        self.assertTrue(result["external_replication_verified"])
        self.assertTrue(result["restore_target_isolated"])
        self.assertFalse(result["restore_overwrites_live_root"])

    def test_missing_external_snapshot_after_restart_fails_closed(self) -> None:
        result = evaluate_backup_retention_acceptance(
            _payload(post_restart_health=_health(snapshot_id="", local=False, external_verified=False))
        )

        self.assertFalse(result["verified"])
        self.assertIn("BACKUP_HISTORY_NOT_PRESERVED_AFTER_RESTART", result["blockers"])
        self.assertIn("EXTERNAL_BACKUP_REPLICATION_NOT_VERIFIED", result["blockers"])

    def test_changed_external_snapshot_after_deploy_fails_closed(self) -> None:
        result = evaluate_backup_retention_acceptance(
            _payload(post_deploy_health=_health(snapshot_id="SNAP-OTHER", local=False))
        )

        self.assertFalse(result["verified"])
        self.assertIn("PREDEPLOY_BACKUP_SNAPSHOT_NOT_PRESERVED", result["blockers"])
        self.assertIn("BACKUP_HISTORY_NOT_PRESERVED_AFTER_DEPLOY", result["blockers"])

    def test_ephemeral_or_local_only_mode_never_passes(self) -> None:
        result = evaluate_backup_retention_acceptance(
            _payload(backup_root_persistence_mode="LOCAL_ONLY")
        )

        self.assertFalse(result["verified"])
        self.assertIn("BACKUP_ROOT_NOT_DURABLE", result["blockers"])

    def test_external_replication_must_be_verified_in_all_three_observations(self) -> None:
        result = evaluate_backup_retention_acceptance(
            _payload(post_deploy_health=_health(local=False, external_verified=False))
        )

        self.assertFalse(result["verified"])
        self.assertIn("EXTERNAL_BACKUP_REPLICATION_NOT_VERIFIED", result["blockers"])

    def test_restore_safety_regression_fails_closed(self) -> None:
        result = evaluate_backup_retention_acceptance(
            _payload(post_restart_health=_health(local=False, restore_overwrites_live_root=True))
        )

        self.assertFalse(result["verified"])
        self.assertIn("BACKUP_RESTORE_MAY_OVERWRITE_LIVE_ROOT", result["blockers"])

    def test_invalid_source_sha_fails_closed(self) -> None:
        result = evaluate_backup_retention_acceptance(
            _payload(production_source_snapshot_sha256="not-a-sha")
        )

        self.assertFalse(result["verified"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_INVALID", result["blockers"])


if __name__ == "__main__":
    unittest.main()
