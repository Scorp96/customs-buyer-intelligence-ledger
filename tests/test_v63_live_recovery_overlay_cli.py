import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_overlay_acceptance_v63 import REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS


class V63LiveRecoveryOverlayCliTests(unittest.TestCase):
    def _envelope(self, *, live=True):
        receipts=[]
        for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS:
            receipts.append({
                "receipt_id": f"RCP-{name}",
                "scenario": name,
                "execution_origin": "LIVE_PRODUCTION_CHECKOUT" if live else "REFERENCE_RUNNER",
                "active_overlay_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
                "production_source_snapshot_sha256": "a"*64,
                "recovery_registry_file": "mcp/server_v61_peer_pivot_recovery.py",
                "recovery_registry_name": "RECOVERY_HANDLERS",
                "status": "PASS",
                "active_overlay_handler_exercised": True,
                "reexecute_side_effect": False,
                "exact_correlation_proven": True,
                "exact_request_hash_proven": True,
                "exact_result_snapshot_proven": True if name == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS" else None,
            })
        return {"schema":"cbi.v63-live-recovery-overlay-receipts.v1","receipts":receipts}

    def _run(self, envelope):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"receipts.json"
            path.write_text(json.dumps(envelope),encoding='utf-8')
            return subprocess.run([
                sys.executable,
                "scripts/run_v63_live_recovery_overlay_acceptance.py",
                "--receipts", str(path),
                "--expected-source-snapshot", "a"*64,
                "--expected-registry-file", "mcp/server_v61_peer_pivot_recovery.py",
                "--expected-registry-name", "RECOVERY_HANDLERS",
            ], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)

    def test_verified_live_receipts_exit_zero(self):
        proc=self._run(self._envelope())
        self.assertEqual(proc.returncode,0,proc.stderr)
        payload=json.loads(proc.stdout)
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["status"],"VERIFIED")

    def test_non_live_receipts_exit_nonzero(self):
        proc=self._run(self._envelope(live=False))
        self.assertNotEqual(proc.returncode,0)
        payload=json.loads(proc.stdout)
        self.assertFalse(payload["verified"])
        self.assertIn("NON_LIVE_RECOVERY_RECEIPT",payload["blockers"])


if __name__=='__main__': unittest.main()
