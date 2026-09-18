import json
import subprocess
import sys
import unittest
from pathlib import Path

from unified_runtime.recovery_acceptance_v63 import run_v63_reference_recovery_acceptance


class V63RecoveryAcceptanceRunnerTests(unittest.TestCase):
    def test_reference_acceptance_covers_positive_and_negative_recovery_paths(self):
        result = run_v63_reference_recovery_acceptance()
        self.assertEqual(result["schema"], "cbi.v63-recovery-acceptance.v1")
        self.assertTrue(result["passed"])
        self.assertEqual(result["failed_count"], 0)
        self.assertGreaterEqual(result["case_count"], 9)
        names = {row["case"] for row in result["cases"]}
        self.assertTrue({
            "candidate_exact_event_recovers",
            "candidate_wrong_correlation_fails_closed",
            "same_payload_different_key_cannot_claim",
            "duplicate_exact_event_fails_closed",
            "opportunity_exact_snapshot_recovers",
            "opportunity_snapshot_hash_mismatch_fails_closed",
            "anchor_exact_event_recovers",
        } <= names)

    def test_reference_acceptance_never_marks_side_effect_reexecution_as_allowed(self):
        result = run_v63_reference_recovery_acceptance()
        for row in result["cases"]:
            self.assertFalse(row["reexecute_side_effect"])


    def test_cli_runner_executes_from_repository_root(self):
        root = Path(__file__).resolve().parents[1]
        cp = subprocess.run(
            [sys.executable, str(root / "scripts" / "run_v63_recovery_acceptance.py")],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["failed_count"], 0)



if __name__ == "__main__":
    unittest.main()
