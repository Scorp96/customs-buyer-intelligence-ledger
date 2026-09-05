from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_live_recovery_extra_v63"


class V63ExactCheckoutLiveRecoveryExtraAdversarialTests(unittest.TestCase):
    def _run(self, function_name: str) -> dict:
        module = importlib.import_module(MODULE)
        with tempfile.TemporaryDirectory() as td:
            return getattr(module, function_name)(ROOT, Path(td))

    def test_opportunity_snapshot_hash_mismatch_fails_closed_without_reexecution(self):
        result = self._run("run_opportunity_snapshot_hash_mismatch_scenario")
        self.assertEqual(result["case"], "opportunity_snapshot_hash_mismatch_fails_closed")
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertFalse(result["reexecute_side_effect"])
        self.assertEqual(result["event_count_before_replay"], 1)
        self.assertEqual(result["event_count_after_replay"], 1)
        self.assertEqual(result["wal_status_after_replay"], "PREPARED")
        self.assertTrue(result["correlation_and_request_hash_preserved"])

    def test_anchor_failed_cycle_gate_fails_closed_without_reexecution(self):
        result = self._run("run_anchor_failed_cycle_gate_scenario")
        self.assertEqual(result["case"], "anchor_failed_cycle_gate_fails_closed")
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertFalse(result["reexecute_side_effect"])
        self.assertEqual(result["event_count_before_replay"], 1)
        self.assertEqual(result["event_count_after_replay"], 1)
        self.assertEqual(result["wal_status_after_replay"], "PREPARED")
        self.assertTrue(result["cycle_gate_tamper_proven"])

    def test_raw_idempotency_key_persistence_flag_is_rejected_without_leaking_key(self):
        result = self._run("run_raw_idempotency_persistence_rejected_scenario")
        self.assertEqual(result["case"], "raw_idempotency_key_persistence_is_rejected")
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertFalse(result["reexecute_side_effect"])
        self.assertEqual(result["event_count_before_replay"], 1)
        self.assertEqual(result["event_count_after_replay"], 1)
        self.assertEqual(result["wal_status_after_replay"], "PREPARED")
        self.assertTrue(result["raw_persistence_flag_tamper_proven"])
        self.assertNotIn("v63-exact-extra-raw-key-0001", str(result))


if __name__ == "__main__":
    unittest.main()
