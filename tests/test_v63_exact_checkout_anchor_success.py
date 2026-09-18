from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_semantics_v63 import canonical_v63_wal_request_sha256


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"
TOOL = "promote_opportunity_anchor"
EVENT = "V63_OPPORTUNITY_ANCHOR_PROMOTED"
SECRET = "v63-exact-anchor-success-0001"


class V63ExactCheckoutAnchorSuccessTests(unittest.TestCase):
    def test_real_anchor_success_binds_eligibility_cycle_dedup_correlation_and_request_hash(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module._run_anchor_success_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "anchor_success")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["response"]["status"], "PROMOTED")
        self.assertEqual(result["response"]["opportunity_id"], "OPP-V63-EXACT-ANCHOR-001")
        self.assertEqual(result["response"]["anchor_id"], "ANCHOR-OPP-V63-EXACT-ANCHOR-001")
        self.assertTrue(result["exact_correlation_proven"])
        self.assertTrue(result["exact_request_hash_proven"])
        self.assertTrue(result["exact_anchor_snapshots_proven"])

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

        args = module._anchor_success_arguments(result["investigation_id"])
        expected_request_sha = canonical_v63_wal_request_sha256(TOOL, args)
        self.assertEqual(event["request_sha256"], expected_request_sha)
        self.assertEqual(wal["request_sha256"], expected_request_sha)

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
            result["response"]["anchor_eligibility_snapshot"],
            snapshots["anchor_eligibility_snapshot"],
        )
        self.assertEqual(
            result["response"]["cycle_dedup_snapshot"],
            snapshots["cycle_dedup_snapshot"],
        )
        self.assertNotIn(SECRET, str(result))


if __name__ == "__main__":
    unittest.main()
