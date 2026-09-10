from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_semantics_v63 import snapshot_sha256


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_crash_scenarios_v63"
TOOL = "create_product_opportunity"
EVENT = "V63_PRODUCT_OPPORTUNITY_CREATED"
SECRET = "v63-exact-opportunity-crash-0001"


class V63ExactCheckoutOpportunityCrashRestartTests(unittest.TestCase):
    def test_opportunity_crash_recovers_exact_persisted_result_without_second_event(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module.run_opportunity_crash_restart_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "opportunity_crash_restart")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["pre_restart_evidence"]["event_count"], 1)
        self.assertEqual(result["pre_restart_evidence"]["wal_record_count"], 1)
        self.assertEqual(
            result["pre_restart_evidence"]["wal_records"][0]["status"],
            "PREPARED",
        )
        self.assertTrue(result["reconciled_after_crash"])
        self.assertTrue(result["exact_result_snapshot_recovered"])
        self.assertTrue(result["no_duplicate_event_proven"])

        evidence = result["post_restart_evidence"]
        self.assertEqual(evidence["event_count"], 1)
        self.assertEqual(evidence["wal_record_count"], 1)
        self.assertEqual(evidence["events"][0]["event_type"], EVENT)
        self.assertEqual(evidence["wal_records"][0]["status"], "COMMITTED")

        snapshot = result["durable_result_snapshot"]
        self.assertEqual(snapshot["status"], "CREATED")
        self.assertEqual(snapshot["opportunity_id"], "OPP-V63-CRASH-001")
        self.assertEqual(result["recovered_business_result"], snapshot)
        self.assertEqual(result["durable_result_snapshot_sha256"], snapshot_sha256(snapshot))
        self.assertNotIn(SECRET, str(result))


if __name__ == "__main__":
    unittest.main()
