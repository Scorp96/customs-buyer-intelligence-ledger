import unittest

from unified_runtime.recovery_overlay_acceptance_v63 import REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS


class V63LiveRecoveryOverlayRunnerTests(unittest.TestCase):
    def _envelope(self):
        receipts=[]
        for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS:
            receipts.append({
                "receipt_id": f"RCP-{name}",
                "scenario": name,
                "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
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
        return {
            "schema": "cbi.v63-live-recovery-overlay-receipts.v1",
            "receipts": receipts,
        }

    def test_complete_live_receipts_build_and_validate_to_verified(self):
        from unified_runtime.live_recovery_overlay_runner_v63 import run_live_recovery_overlay_acceptance
        result=run_live_recovery_overlay_acceptance(
            self._envelope(),
            expected_production_source_snapshot_sha256="a"*64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["verified"])
        self.assertEqual(result["report"]["builder_status"], "REPORT_BUILT_UNVERIFIED")
        self.assertTrue(result["validation"]["verified"])

    def test_receipt_envelope_schema_is_required(self):
        from unified_runtime.live_recovery_overlay_runner_v63 import run_live_recovery_overlay_acceptance
        payload=self._envelope(); payload["schema"]="wrong"
        result=run_live_recovery_overlay_acceptance(
            payload,
            expected_production_source_snapshot_sha256="a"*64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertFalse(result["verified"])
        self.assertIn("LIVE_RECOVERY_RECEIPT_ENVELOPE_SCHEMA_INVALID", result["blockers"])

    def test_expected_source_snapshot_is_external_authority(self):
        from unified_runtime.live_recovery_overlay_runner_v63 import run_live_recovery_overlay_acceptance
        result=run_live_recovery_overlay_acceptance(
            self._envelope(),
            expected_production_source_snapshot_sha256="b"*64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertFalse(result["verified"])
        self.assertIn("RECOVERY_RECEIPT_SOURCE_SNAPSHOT_MISMATCH", result["blockers"])

    def test_builder_blocked_input_never_reaches_verified(self):
        from unified_runtime.live_recovery_overlay_runner_v63 import run_live_recovery_overlay_acceptance
        payload=self._envelope(); payload["receipts"][0]["execution_origin"]="REFERENCE_RUNNER"
        result=run_live_recovery_overlay_acceptance(
            payload,
            expected_production_source_snapshot_sha256="a"*64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("NON_LIVE_RECOVERY_RECEIPT", result["blockers"])
        self.assertNotIn("validation", result)


if __name__ == '__main__': unittest.main()
