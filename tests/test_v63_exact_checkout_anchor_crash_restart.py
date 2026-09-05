from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_crash_scenarios_v63"
TOOL = "promote_opportunity_anchor"
EVENT = "V63_OPPORTUNITY_ANCHOR_PROMOTED"
SECRET = "v63-exact-anchor-crash-0001"


class V63ExactCheckoutAnchorCrashRestartTests(unittest.TestCase):
    def test_anchor_crash_recovers_once_and_preserves_eligibility_and_cycle_snapshots(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module.run_anchor_crash_restart_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "anchor_crash_restart")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["pre_restart_evidence"]["event_count"], 1)
        self.assertEqual(result["pre_restart_evidence"]["wal_record_count"], 1)
        self.assertEqual(
            result["pre_restart_evidence"]["wal_records"][0]["status"],
            "PREPARED",
        )
        self.assertEqual(result["response"]["status"], "PROMOTED")
        self.assertEqual(result["response"]["opportunity_id"], "OPP-V63-CRASH-ANCHOR-001")
        self.assertEqual(
            result["response"]["anchor_id"],
            "ANCHOR-OPP-V63-CRASH-ANCHOR-001",
        )
        self.assertTrue(result["reconciled_after_crash"])
        self.assertTrue(result["no_duplicate_event_proven"])
        self.assertTrue(result["exact_anchor_snapshots_preserved"])

        evidence = result["post_restart_evidence"]
        self.assertEqual(evidence["event_count"], 1)
        self.assertEqual(evidence["wal_record_count"], 1)
        self.assertEqual(evidence["events"][0]["event_type"], EVENT)
        self.assertEqual(evidence["wal_records"][0]["status"], "COMMITTED")

        snapshots = result["durable_anchor_snapshots"]
        self.assertTrue(snapshots["anchor_eligibility_snapshot"]["anchor_eligible"])
        self.assertEqual(
            snapshots["anchor_eligibility_snapshot"]["commercial_value_grade"],
            "B+",
        )
        self.assertEqual(
            snapshots["cycle_dedup_snapshot"],
            {"cycle_dedup_complete": True},
        )
        self.assertEqual(
            result["recovered_business_result"]["anchor_eligibility_snapshot"],
            snapshots["anchor_eligibility_snapshot"],
        )
        self.assertEqual(
            result["recovered_business_result"]["cycle_dedup_snapshot"],
            snapshots["cycle_dedup_snapshot"],
        )
        self.assertNotIn(SECRET, str(result))


if __name__ == "__main__":
    unittest.main()
