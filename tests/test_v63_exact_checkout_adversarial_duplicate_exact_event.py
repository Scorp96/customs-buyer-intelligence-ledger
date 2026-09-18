from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_adversarial_duplicate_v63"
TOOL = "append_candidate_discovery"


class V63ExactCheckoutDuplicateExactEventTests(unittest.TestCase):
    def test_two_qualifying_exact_events_remain_ambiguous_without_reexecution(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module.run_duplicate_exact_event_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "duplicate_exact_event")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["recovery_status"], "RECONCILIATION_REQUIRED")
        self.assertTrue(result["recovery_rejected"])
        self.assertFalse(result["reexecute_side_effect"])
        self.assertEqual(result["qualifying_event_count_before_replay"], 2)
        self.assertEqual(result["qualifying_event_count_after_replay"], 2)
        self.assertEqual(result["wal_status_before_replay"], "PREPARED")
        self.assertEqual(result["wal_status_after_replay"], "PREPARED")
        self.assertTrue(result["same_correlation_proven"])
        self.assertTrue(result["same_request_hash_proven"])
        self.assertNotIn("v63-exact-adversarial-duplicate-0001", str(result))


if __name__ == "__main__":
    unittest.main()
