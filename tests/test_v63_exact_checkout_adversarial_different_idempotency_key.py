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
    def test_same_semantic_candidate_with_new_key_creates_new_wal_without_duplicate_side_effect(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module.run_different_idempotency_key_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "different_idempotency_key")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["event_type"], EVENT)
        self.assertEqual(result["wal_record_count"], 2)
        self.assertEqual(result["event_count"], 1)
        self.assertTrue(result["same_request_hash_proven"])
        self.assertTrue(result["distinct_correlations_proven"])
        self.assertTrue(result["single_side_effect_proven"])
        self.assertTrue(result["correlations_distinct_from_keys"])
        self.assertEqual(len(result["correlation_ids"]), 2)
        self.assertNotEqual(result["correlation_ids"][0], result["correlation_ids"][1])
        self.assertEqual(len(set(result["request_sha256_values"])), 1)
        self.assertNotIn(KEY_A, str(result))
        self.assertNotIn(KEY_B, str(result))


if __name__ == "__main__":
    unittest.main()
