from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_adversarial_scenarios_v63"
TOOL = "append_candidate_discovery"


class V63ExactCheckoutWrongCorrelationTests(unittest.TestCase):
    def test_wrong_durable_correlation_stays_reconciliation_required_without_reexecution(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module.run_wrong_correlation_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "wrong_correlation")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["recovery_status"], "RECONCILIATION_REQUIRED")
        self.assertFalse(result["reexecute_side_effect"])
        self.assertTrue(result["recovery_rejected"])
        self.assertEqual(result["event_count_before_replay"], 1)
        self.assertEqual(result["event_count_after_replay"], 1)
        self.assertEqual(result["wal_status_before_replay"], "PREPARED")
        self.assertEqual(result["wal_status_after_replay"], "PREPARED")
        self.assertNotEqual(
            result["durable_correlation_id"],
            result["wal_correlation_id"],
        )
        self.assertNotIn("v63-exact-adversarial-wrong-correlation-0001", str(result))


if __name__ == "__main__":
    unittest.main()
