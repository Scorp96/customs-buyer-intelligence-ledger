import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_acceptance_v63 import run_v63_reference_recovery_acceptance


class V63LiveExactRecoveryAcceptanceTests(unittest.TestCase):
    def _envelope(self, *, live=True, sha="a" * 64):
        receipts = []
        for row in run_v63_reference_recovery_acceptance()["cases"]:
            receipts.append({
                "receipt_id": f"LIVE-{row['case']}",
                "case": row["case"],
                "execution_origin": "LIVE_PRODUCTION_CHECKOUT" if live else "REFERENCE_RUNNER",
                "adapter_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH",
                "production_source_snapshot_sha256": sha,
                "passed": row["passed"],
                "status": row["status"],
                "blockers": list(row.get("blockers") or []),
                "recovery_action": row["recovery_action"],
                "reexecute_side_effect": row["reexecute_side_effect"],
            })
        return {
            "schema": "cbi.v63-live-exact-recovery-receipts.v1",
            "receipts": receipts,
        }

    def test_complete_live_receipts_build_and_validate_exact_release_report(self):
        from unified_runtime.live_exact_recovery_runner_v63 import run_live_exact_recovery_acceptance

        result = run_live_exact_recovery_acceptance(
            self._envelope(),
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["report"]["schema"], "cbi.v63-recovery-acceptance.v1")
        self.assertEqual(result["report"]["execution_origin"], "LIVE_PRODUCTION_CHECKOUT")
        self.assertEqual(result["report"]["adapter_path_exercised"], "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH")
        self.assertFalse(result["report"]["reference_runner_only"])
        self.assertEqual(result["report"]["production_source_snapshot_sha256"], "a" * 64)

    def test_reference_receipts_are_rejected(self):
        from unified_runtime.live_exact_recovery_runner_v63 import run_live_exact_recovery_acceptance

        result = run_live_exact_recovery_acceptance(
            self._envelope(live=False),
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertFalse(result["verified"])
        self.assertIn("NON_LIVE_EXACT_RECOVERY_RECEIPT", result["blockers"])

    def test_source_snapshot_drift_is_rejected(self):
        from unified_runtime.live_exact_recovery_runner_v63 import run_live_exact_recovery_acceptance

        result = run_live_exact_recovery_acceptance(
            self._envelope(sha="b" * 64),
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertFalse(result["verified"])
        self.assertIn("EXACT_RECOVERY_RECEIPT_SOURCE_SNAPSHOT_MISMATCH", result["blockers"])

    def test_missing_case_is_rejected(self):
        from unified_runtime.live_exact_recovery_runner_v63 import run_live_exact_recovery_acceptance

        payload = self._envelope()
        payload["receipts"].pop()
        result = run_live_exact_recovery_acceptance(
            payload,
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertFalse(result["verified"])
        self.assertIn("EXACT_RECOVERY_RECEIPT_CASE_SET_INVALID", result["blockers"])

    def test_failed_case_is_not_promoted_to_verified(self):
        from unified_runtime.live_exact_recovery_runner_v63 import run_live_exact_recovery_acceptance

        payload = self._envelope()
        payload["receipts"][0]["passed"] = False
        result = run_live_exact_recovery_acceptance(
            payload,
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertFalse(result["verified"])
        self.assertIn("EXACT_RECOVERY_ACCEPTANCE_CASE_FAILED", result["blockers"])

    def _run_cli(self, envelope):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "receipts.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    "scripts/run_v63_live_exact_recovery_acceptance.py",
                    "--receipts", str(path),
                    "--expected-source-snapshot", "a" * 64,
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_cli_verified_live_receipts_exit_zero(self):
        proc = self._run_cli(self._envelope())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["verified"])

    def test_cli_reference_receipts_exit_nonzero(self):
        proc = self._run_cli(self._envelope(live=False))
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)["verified"])


if __name__ == "__main__":
    unittest.main()
