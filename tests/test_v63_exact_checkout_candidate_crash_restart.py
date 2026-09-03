from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"
TOOL = "append_candidate_discovery"
EVENT = "V63_CANDIDATE_DISCOVERED"
SECRET = "v63-exact-candidate-crash-0001"


class V63ExactCheckoutCandidateCrashRestartTests(unittest.TestCase):
    def test_candidate_crash_after_handler_recovers_without_duplicate_event(self):
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            result = module._run_candidate_crash_restart_scenario(ROOT, Path(td))

        self.assertEqual(result["scenario"], "candidate_crash_restart")
        self.assertEqual(result["tool"], TOOL)
        self.assertEqual(result["pre_restart_evidence"]["event_count"], 1)
        self.assertEqual(result["pre_restart_evidence"]["wal_record_count"], 1)
        self.assertEqual(
            result["pre_restart_evidence"]["wal_records"][0]["status"],
            "PREPARED",
        )

        self.assertEqual(result["response"]["status"], "DISCOVERED")
        self.assertEqual(result["response"]["candidate_id"], "CAND-V63-CRASH-001")
        self.assertTrue(result["reconciled_after_crash"])
        self.assertTrue(result["exact_correlation_proven"])
        self.assertTrue(result["exact_request_hash_proven"])
        self.assertTrue(result["no_duplicate_event_proven"])

        evidence = result["post_restart_evidence"]
        self.assertEqual(evidence["event_count"], 1)
        self.assertEqual(evidence["wal_record_count"], 1)
        self.assertEqual(evidence["events"][0]["event_type"], EVENT)
        self.assertEqual(evidence["wal_records"][0]["status"], "COMMITTED")
        self.assertEqual(
            evidence["events"][0]["correlation_id"],
            evidence["wal_records"][0]["correlation_id"],
        )
        self.assertEqual(
            evidence["events"][0]["request_sha256"],
            evidence["wal_records"][0]["request_sha256"],
        )
        self.assertNotIn(SECRET, str(result))


if __name__ == "__main__":
    unittest.main()
