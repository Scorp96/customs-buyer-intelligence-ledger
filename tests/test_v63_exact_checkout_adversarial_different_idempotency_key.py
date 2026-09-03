from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_adversarial_idempotency_v63"
TOOL = "append_candidate_discovery"
EVENT = "V63_CANDIDATE_DISCOVERED"
KEY_A = "v63-exact-adversarial-idem-a-0001"
KEY_B = "v63-exact-adversarial-idem-b-0001"


class V63ExactCheckoutDifferentIdempotencyKeyTests(unittest.TestCase):
    def test_second_key_cannot_claim_first_keys_durable_event_or_result(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module.run_different_idempotency_key_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "different_idempotency_key")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["event_type"], EVENT)
        self.assertEqual(result["recovery_status"], "RECONCILIATION_REQUIRED")
        self.assertTrue(result["recovery_rejected"])
        self.assertFalse(result["reexecute_side_effect"])
        self.assertEqual(result["wal_record_count_before_replay"], 2)
        self.assertEqual(result["wal_record_count_after_replay"], 2)
        self.assertEqual(result["event_count_before_replay"], 1)
        self.assertEqual(result["event_count_after_replay"], 1)
        self.assertEqual(result["wal_statuses_before_replay"], ["PREPARED", "PREPARED"])
        self.assertEqual(result["wal_statuses_after_replay"], ["PREPARED", "PREPARED"])
        self.assertTrue(result["same_request_hash_proven"])
        self.assertTrue(result["distinct_correlations_proven"])
        self.assertTrue(result["first_event_bound_only_to_first_correlation"])
        self.assertNotIn(KEY_A, str(result))
        self.assertNotIn(KEY_B, str(result))


if __name__ == "__main__":
    unittest.main()
