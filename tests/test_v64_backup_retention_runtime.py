from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from unified_runtime.backup_recovery_hardened import ProductionBackupRecoveryManager
from unified_runtime.backup_retention_evidence_v64 import build_backup_retention_evidence


class FakeReplica:
    def __init__(self, *, fail: bool = False, latest: dict | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self._latest = latest

    def replicate_snapshot(self, snapshot_dir: Path, snapshot_id: str):
        self.calls.append((str(snapshot_dir), snapshot_id))
        if self.fail:
            raise RuntimeError("synthetic external replication failure")
        row = {
            "verified": True,
            "snapshot_id": snapshot_id,
            "created_at": "2026-09-09T10:40:00Z",
            "reasons": ["DAILY"],
            "archive_sha256": "a" * 64,
            "manifest_key": f"cbi-test/backups-v61/manifests/{snapshot_id}.json",
            "persistence_mode": "OBJECT_STORE_REPLICATED",
        }
        self._latest = row
        return dict(row)

    def latest_snapshot(self):
        return dict(self._latest) if self._latest else None


class BackupRetentionRuntimeTests(unittest.TestCase):
    def _manager(self, root: Path, replica=None) -> ProductionBackupRecoveryManager:
        parameters = inspect.signature(ProductionBackupRecoveryManager.__init__).parameters
        self.assertIn(
            "external_replica",
            parameters,
            "backup manager must accept an external replica without owning cloud credentials",
        )
        sessions = root / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        return ProductionBackupRecoveryManager(
            session_root=sessions,
            canonical_root=root / "canonical",
            pending_root=root / "pending",
            host_root=root / "host",
            backup_root=root / "backups-v61",
            external_replica=replica,
        )

    def test_daily_snapshot_is_replicated_before_returning_to_mutation_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-retention-") as td:
            replica = FakeReplica()
            manager = self._manager(Path(td), replica)
            result = manager.ensure_daily_snapshot()

        self.assertEqual(len(replica.calls), 1)
        self.assertTrue(result["external_replicated"])
        self.assertEqual(result["backup_root_persistence_mode"], "OBJECT_STORE_REPLICATED")
        self.assertEqual(result["external_snapshot_id"], result["snapshot_id"])

    def test_replication_failure_fails_closed_but_same_local_snapshot_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-retention-retry-") as td:
            root = Path(td)
            failing = FakeReplica(fail=True)
            manager = self._manager(root, failing)
            with self.assertRaises(RuntimeError):
                manager.ensure_daily_snapshot()
            snapshot_dirs = [p for p in (root / "backups-v61").iterdir() if p.is_dir() and p.name.startswith("SNAP-")]
            self.assertEqual(len(snapshot_dirs), 1)

            healthy = FakeReplica()
            retry = self._manager(root, healthy).ensure_daily_snapshot()
            self.assertEqual(len(healthy.calls), 1)
            self.assertEqual(retry["snapshot_id"], snapshot_dirs[0].name)
            self.assertTrue(retry["external_replicated"])

    def test_status_distinguishes_empty_local_root_from_durable_external_history(self) -> None:
        snapshot_id = "SNAP-20260909T104000Z-abcdef123456"
        external = {
            "verified": True,
            "snapshot_id": snapshot_id,
            "created_at": "2026-09-09T10:40:00Z",
            "reasons": ["DAILY"],
            "archive_sha256": "a" * 64,
            "manifest_key": f"cbi-test/backups-v61/manifests/{snapshot_id}.json",
            "persistence_mode": "OBJECT_STORE_REPLICATED",
        }
        with tempfile.TemporaryDirectory(prefix="cbi-v64-retention-fresh-") as td:
            manager = self._manager(Path(td), FakeReplica(latest=external))
            status = manager.status(validate_latest=True)

        self.assertIsNone(status["latest"])
        self.assertEqual(status["durable_latest"]["snapshot_id"], snapshot_id)
        self.assertTrue(status["external_replication_configured"])
        self.assertTrue(status["external_replication_verified"])
        self.assertEqual(status["backup_root_persistence_mode"], "OBJECT_STORE_REPLICATED")
        self.assertEqual(status["external_snapshot_locator"], external["manifest_key"])
        self.assertFalse(status["restore_overwrites_live_root"])

    def test_status_without_external_replica_never_claims_durable_retention(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-retention-local-") as td:
            manager = self._manager(Path(td), None)
            manager.ensure_daily_snapshot()
            status = manager.status(validate_latest=True)

        self.assertFalse(status["external_replication_configured"])
        self.assertFalse(status["external_replication_verified"])
        self.assertIsNone(status["durable_latest"])
        self.assertNotEqual(status["backup_root_persistence_mode"], "OBJECT_STORE_REPLICATED")

    def test_retention_evidence_uses_durable_latest_after_fresh_instance(self) -> None:
        snapshot_id = "SNAP-20260909T104000Z-abcdef123456"

        def health(*, local: bool):
            status = {
                "schema": "cbi.backup-status.v6.1",
                "backup_root": "/var/lib/cbi/live/backups-v61",
                "latest": ({"snapshot_id": snapshot_id} if local else None),
                "durable_latest": {
                    "snapshot_id": snapshot_id,
                    "verified": True,
                    "persistence_mode": "OBJECT_STORE_REPLICATED",
                },
                "daily_snapshot_present": local,
                "restore_overwrites_live_root": False,
            }
            return {"status": "READY", "backup_recovery": status}

        result = build_backup_retention_evidence(
            pre_deploy_health=health(local=True),
            post_restart_health=health(local=False),
            post_deploy_health=health(local=False),
            production_source_snapshot_sha256="b" * 64,
            backup_root_persistence_mode="OBJECT_STORE_REPLICATED",
            external_replication_verified=True,
            external_snapshot_locator="cbi-test/backups-v61/manifests/" + snapshot_id + ".json",
            observed_at="2026-09-09T10:45:00Z",
        )

        self.assertTrue(result["verified"], result["blockers"])
        self.assertEqual(result["snapshot_id_after_restart"], snapshot_id)
        self.assertEqual(result["snapshot_ids_after_deploy"], [snapshot_id])


if __name__ == "__main__":
    unittest.main()
