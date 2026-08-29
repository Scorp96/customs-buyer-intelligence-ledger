from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unified_runtime import UnifiedRuntime, ValidationError


class V61CanonicalSnapshotEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-canonical-snapshot-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = UnifiedRuntime(self.root / "sessions")

    def test_resolve_and_create_reuse_one_verified_registry_snapshot_per_call(self) -> None:
        registry = self.runtime.canonical_registry
        with mock.patch.object(registry, "entries", wraps=registry.entries) as entries_spy:
            created = self.runtime.resolve_or_create_account({
                "candidate": {
                    "name": "Snapshot Efficiency Synthetic LLC",
                    "country": "United States",
                },
            })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(entries_spy.call_count, 1)

        with mock.patch.object(registry, "entries", wraps=registry.entries) as entries_spy:
            matched = self.runtime.resolve_or_create_account({
                "candidate": {
                    "name": "Snapshot Efficiency Synthetic LLC",
                    "country": "United States",
                },
                "create_if_missing": False,
            })
        self.assertEqual(matched["status"], "MATCHED")
        self.assertEqual(entries_spy.call_count, 1)

        contract = self.runtime.get_runtime_contract({})["canonical_identity_resolution_v6_1"]
        self.assertTrue(contract["one_verified_registry_snapshot_per_resolve_call"])
        self.assertTrue(contract["append_full_chain_verification_preserved"])

    def test_snapshot_reuse_does_not_bypass_hash_chain_tamper_detection(self) -> None:
        self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Snapshot Integrity Synthetic LLC",
                "country": "United States",
            },
        })
        path = self.runtime.canonical_registry.log.path
        original = path.read_text(encoding="utf-8")
        tampered = original.replace(
            "Snapshot Integrity Synthetic LLC",
            "Snapshot Integrity Tampered LLC",
            1,
        )
        self.assertNotEqual(original, tampered)
        path.write_text(tampered, encoding="utf-8")

        with self.assertRaises(ValidationError):
            self.runtime.resolve_or_create_account({
                "candidate": {
                    "name": "Another Synthetic LLC",
                    "country": "United States",
                },
            })


if __name__ == "__main__":
    unittest.main()
