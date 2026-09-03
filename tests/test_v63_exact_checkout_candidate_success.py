from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_semantics_v63 import canonical_v63_wal_request_sha256


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"
TOOL = "append_candidate_discovery"
EVENT = "V63_CANDIDATE_DISCOVERED"


class V63ExactCheckoutCandidateSuccessTests(unittest.TestCase):
    def test_real_candidate_success_binds_one_event_one_wal_correlation_and_request_hash(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module._run_candidate_success_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "candidate_success")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["response"]["status"], "DISCOVERED")
        self.assertEqual(result["response"]["candidate_id"], "CAND-V63-EXACT-001")
        self.assertTrue(result["exact_correlation_proven"])
        self.assertTrue(result["exact_request_hash_proven"])

        evidence = result["evidence"]
        self.assertEqual(evidence["event_count"], 1)
        self.assertEqual(evidence["wal_record_count"], 1)
        self.assertFalse(evidence["raw_idempotency_key_exposed"])

        event = evidence["events"][0]
        wal = evidence["wal_records"][0]
        self.assertEqual(event["event_type"], EVENT)
        self.assertEqual(wal["status"], "COMMITTED")
        self.assertTrue(event["correlation_id"])
        self.assertEqual(event["correlation_id"], wal["correlation_id"])

        candidate_args = module._candidate_success_arguments(result["investigation_id"])
        expected_request_sha = canonical_v63_wal_request_sha256(TOOL, candidate_args)
        self.assertEqual(event["request_sha256"], expected_request_sha)
        self.assertEqual(wal["request_sha256"], expected_request_sha)
        self.assertNotIn("idempotency_key", str(result["evidence"]).casefold())
        self.assertNotIn("idempotency_key", str(result["response"]).casefold())


if __name__ == "__main__":
    unittest.main()
