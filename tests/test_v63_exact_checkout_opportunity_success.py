from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_semantics_v63 import (
    canonical_v63_wal_request_sha256,
    snapshot_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"
TOOL = "create_product_opportunity"
EVENT = "V63_PRODUCT_OPPORTUNITY_CREATED"
SECRET = "v63-exact-opportunity-success-0001"


class V63ExactCheckoutOpportunitySuccessTests(unittest.TestCase):
    def test_real_opportunity_success_binds_exact_result_snapshot_hash_and_request_evidence(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module._run_opportunity_success_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "opportunity_success")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["response"]["status"], "CREATED")
        self.assertEqual(result["response"]["opportunity_id"], "OPP-V63-EXACT-001")
        self.assertTrue(result["exact_correlation_proven"])
        self.assertTrue(result["exact_request_hash_proven"])
        self.assertTrue(result["exact_result_snapshot_proven"])

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

        args = module._opportunity_success_arguments(result["investigation_id"])
        expected_request_sha = canonical_v63_wal_request_sha256(TOOL, args)
        self.assertEqual(event["request_sha256"], expected_request_sha)
        self.assertEqual(wal["request_sha256"], expected_request_sha)

        snapshot = event["result_snapshot"]
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot["status"], "CREATED")
        self.assertEqual(snapshot["opportunity_id"], "OPP-V63-EXACT-001")
        self.assertEqual(event["result_snapshot_sha256"], snapshot_sha256(snapshot))
        self.assertEqual(result["durable_result_snapshot"], snapshot)
        self.assertNotIn(SECRET, str(result))


if __name__ == "__main__":
    unittest.main()
