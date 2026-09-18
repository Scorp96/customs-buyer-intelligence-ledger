from __future__ import annotations

import importlib
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class _FakeStateManager:
    def __init__(self) -> None:
        self.client = object()
        self.prefix = "cbi-test"


class BackupReplicaServerWiringTests(unittest.TestCase):
    def test_factory_reuses_current_recovery_manager_client_and_prefix(self) -> None:
        try:
            binding = importlib.import_module("mcp.backup_replica_binding_v64")
        except ModuleNotFoundError:
            self.fail("mcp.backup_replica_binding_v64 must exist")
        fake = _FakeStateManager()
        with mock.patch.object(
            binding.RecoveryObjectStoreStateManagerV63,
            "from_env",
            return_value=fake,
        ):
            with mock.patch.dict(os.environ, {"CBI_BACKUP_OBJECT_STORE_RETENTION": "17"}, clear=False):
                replica = binding.backup_replica_from_env()
        self.assertIsNotNone(replica)
        self.assertIs(replica.client, fake.client)
        self.assertEqual(replica.prefix, "cbi-test")
        self.assertEqual(replica.retention, 17)

    def test_factory_returns_none_when_object_store_is_disabled(self) -> None:
        try:
            binding = importlib.import_module("mcp.backup_replica_binding_v64")
        except ModuleNotFoundError:
            self.fail("mcp.backup_replica_binding_v64 must exist")
        with mock.patch.object(
            binding.RecoveryObjectStoreStateManagerV63,
            "from_env",
            return_value=None,
        ):
            self.assertIsNone(binding.backup_replica_from_env())

    def test_factory_rejects_invalid_backup_retention(self) -> None:
        try:
            binding = importlib.import_module("mcp.backup_replica_binding_v64")
        except ModuleNotFoundError:
            self.fail("mcp.backup_replica_binding_v64 must exist")
        fake = _FakeStateManager()
        with mock.patch.object(binding.RecoveryObjectStoreStateManagerV63, "from_env", return_value=fake):
            with mock.patch.dict(os.environ, {"CBI_BACKUP_OBJECT_STORE_RETENTION": "0"}, clear=False):
                with self.assertRaises(Exception):
                    binding.backup_replica_from_env()

    def test_production_backup_entrypoint_injects_external_replica_everywhere(self) -> None:
        source = (ROOT / "mcp" / "server_v61_backup_recovery.py").read_text(encoding="utf-8")
        self.assertIn("backup_replica_from_env", source)
        self.assertIn("_EXTERNAL_BACKUP = backup_replica_from_env()", source)
        self.assertIn("external_replica=_EXTERNAL_BACKUP", source)
        self.assertGreaterEqual(
            source.count("external_replica=_EXTERNAL_BACKUP"),
            2,
            "root and alternate migration backup managers must share external durability",
        )


if __name__ == "__main__":
    unittest.main()
