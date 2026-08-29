from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime
from unified_runtime.core import UnifiedRuntime as V54Runtime
from unified_runtime.migration_lineage_hardening import (
    MIGRATION_PROVENANCE_EVENT,
)


class V61MigrationLineageHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="cbi-v61-migration-lineage-"
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_root = self.root / "legacy-sessions"
        self.live_root = self.root / "controller-sessions"
        self.target_root = self.root / "migrated"
        self.source = V54Runtime(self.source_root)
        self.started = self.source.start_investigation({
            "account": {
                "account_id": "C-MIG-LINEAGE-001",
                "country": "Synthetic",
                "name": "Synthetic Migration Lineage Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "provider_policy": {"mode": "PUBLIC_ONLY"},
        })
        self.investigation_id = self.started["investigation_id"]
        self.controller = UnifiedRuntime(self.live_root)

    def migrate(self) -> dict:
        return self.controller.migrate_v5_4_1_to_v6({
            "source_session_root": str(self.source_root),
            "target_root": str(self.target_root),
        })

    def test_migration_records_exact_source_snapshot_in_target_chain(self) -> None:
        source_events_before = self.source.store.read(self.investigation_id)
        source_file = self.source_root / f"{self.investigation_id}.jsonl"
        source_bytes_before = source_file.read_bytes()

        report = self.migrate()
        self.assertTrue(report["verified"])
        self.assertTrue(report["switch_ready"])
        self.assertFalse(report["switched"])
        self.assertIn(self.investigation_id, report["session_provenance"])

        provenance = report["session_provenance"][self.investigation_id]
        self.assertEqual(
            provenance["source_event_count_at_migration"],
            len(source_events_before),
        )
        self.assertEqual(
            provenance["source_tail_event_hash_at_migration"],
            source_events_before[-1]["event_hash"],
        )

        target = UnifiedRuntime(self.target_root / "sessions")
        target_events = target.store.read(self.investigation_id)
        event_types = [row["event_type"] for row in target_events]
        self.assertIn("V6_RUNTIME_INITIALIZED", event_types)
        self.assertEqual(event_types[-1], MIGRATION_PROVENANCE_EVENT)

        health = target.get_investigation_health({
            "investigation_id": self.investigation_id,
        })
        lineage = health["migration_lineage"]
        self.assertEqual(
            lineage["status"],
            "SOURCE_UNCHANGED_SINCE_MIGRATION",
        )
        self.assertFalse(lineage["split_brain_risk"])
        self.assertEqual(health["status"], "READY")
        self.assertEqual(source_file.read_bytes(), source_bytes_before)

    def test_source_advance_after_migration_is_detected_read_only(self) -> None:
        self.migrate()
        target_file = (
            self.target_root
            / "sessions"
            / f"{self.investigation_id}.jsonl"
        )
        target_bytes_before = target_file.read_bytes()

        self.source.store.append(
            self.investigation_id,
            "LEGACY_POST_MIGRATION_TEST_EVENT",
            {"marker": "legacy source advanced after migration"},
        )

        target = UnifiedRuntime(self.target_root / "sessions")
        health = target.get_investigation_health({
            "investigation_id": self.investigation_id,
        })
        lineage = health["migration_lineage"]
        self.assertEqual(
            lineage["status"],
            "SOURCE_ADVANCED_AFTER_MIGRATION",
        )
        self.assertTrue(lineage["split_brain_risk"])
        self.assertTrue(lineage["source_advanced_after_migration"])
        self.assertEqual(lineage["release_gate"], "BLOCKED")
        self.assertEqual(health["status"], "SPLIT_BRAIN_RISK")
        self.assertTrue(health["migration_lineage_release_blocked"])
        self.assertFalse(
            health["automatic_history_reconciliation_allowed"]
        )
        self.assertEqual(target_file.read_bytes(), target_bytes_before)

    def test_unrecorded_pre_hardening_migration_requires_manual_lineage_gate(self) -> None:
        target_sessions = self.target_root / "sessions"
        target_sessions.mkdir(parents=True)
        source_file = self.source_root / f"{self.investigation_id}.jsonl"
        target_file = target_sessions / source_file.name
        target_file.write_bytes(source_file.read_bytes())

        target = UnifiedRuntime(target_sessions)
        target._ensure_v6(self.investigation_id)
        health = target.get_investigation_health({
            "investigation_id": self.investigation_id,
        })
        lineage = health["migration_lineage"]
        self.assertEqual(lineage["status"], "PROVENANCE_NOT_RECORDED")
        self.assertFalse(lineage["provenance_recorded"])
        self.assertFalse(lineage["automatic_reconciliation_allowed"])
        self.assertEqual(
            lineage["release_gate"],
            "MANUAL_LINEAGE_DIAGNOSTIC_REQUIRED_FOR_LEGACY_MIGRATIONS",
        )

    def test_migration_report_is_self_describing_and_no_auto_merge(self) -> None:
        report = self.migrate()
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertIn("source_must_remain_frozen_or_retired_after_switch", serialized)
        self.assertIn("source_event_count_at_migration", serialized)
        self.assertIn("source_tail_event_hash_at_migration", serialized)
        self.assertIn("source_session_sha256_at_migration", serialized)
        self.assertIn("automatic_history_merge_allowed", serialized)
        self.assertFalse(
            report["session_provenance"][self.investigation_id][
                "automatic_history_merge_allowed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
