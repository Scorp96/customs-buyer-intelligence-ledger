import unittest

from unified_runtime.recovery_overlay_acceptance_v63 import (
    REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS,
    validate_v63_recovery_overlay_acceptance,
)


class V63RecoveryOverlayReportBuilderTests(unittest.TestCase):
    def _receipts(self):
        rows = []
        for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS:
            rows.append({
                "receipt_id": f"RCP-{name}",
                "scenario": name,
                "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
                "active_overlay_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
                "production_source_snapshot_sha256": "a" * 64,
                "recovery_registry_file": "mcp/server_v61_peer_pivot_recovery.py",
                "recovery_registry_name": "RECOVERY_HANDLERS",
                "status": "PASS",
                "active_overlay_handler_exercised": True,
                "reexecute_side_effect": False,
                "exact_correlation_proven": True,
                "exact_request_hash_proven": True,
                "exact_result_snapshot_proven": True if name == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS" else None,
            })
        return rows

    def test_complete_live_receipts_build_source_bound_report_but_not_self_verify(self):
        from unified_runtime.recovery_overlay_report_builder_v63 import build_v63_recovery_overlay_acceptance_report

        report = build_v63_recovery_overlay_acceptance_report(
            self._receipts(),
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(report["schema"], "cbi.v63-recovery-overlay-acceptance.v1")
        self.assertEqual(report["builder_status"], "REPORT_BUILT_UNVERIFIED")
        self.assertFalse(report["builder_claims_verified"])
        self.assertFalse(report["reference_runner_only"])
        self.assertEqual(len(report["scenarios"]), len(REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS))

        validation = validate_v63_recovery_overlay_acceptance(
            report,
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertTrue(validation["verified"])

    def test_synthetic_or_reference_receipt_is_rejected(self):
        from unified_runtime.recovery_overlay_report_builder_v63 import build_v63_recovery_overlay_acceptance_report

        receipts = self._receipts()
        receipts[0]["execution_origin"] = "REFERENCE_RUNNER"
        result = build_v63_recovery_overlay_acceptance_report(
            receipts,
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(result["builder_status"], "BLOCKED_INPUT")
        self.assertIn("NON_LIVE_RECOVERY_RECEIPT", result["builder_blockers"])
        self.assertNotIn("scenarios", result)

    def test_receipt_source_snapshot_drift_is_rejected(self):
        from unified_runtime.recovery_overlay_report_builder_v63 import build_v63_recovery_overlay_acceptance_report

        receipts = self._receipts()
        receipts[2]["production_source_snapshot_sha256"] = "b" * 64
        result = build_v63_recovery_overlay_acceptance_report(
            receipts,
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(result["builder_status"], "BLOCKED_INPUT")
        self.assertIn("RECOVERY_RECEIPT_SOURCE_SNAPSHOT_MISMATCH", result["builder_blockers"])

    def test_missing_or_duplicate_scenario_is_rejected_before_report_build(self):
        from unified_runtime.recovery_overlay_report_builder_v63 import build_v63_recovery_overlay_acceptance_report

        receipts = self._receipts()
        receipts.pop()
        receipts.append(dict(receipts[0], receipt_id="RCP-DUP"))
        result = build_v63_recovery_overlay_acceptance_report(
            receipts,
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(result["builder_status"], "BLOCKED_INPUT")
        self.assertIn("RECOVERY_RECEIPT_SCENARIO_SET_INVALID", result["builder_blockers"])

    def test_registry_mismatch_is_rejected(self):
        from unified_runtime.recovery_overlay_report_builder_v63 import build_v63_recovery_overlay_acceptance_report

        receipts = self._receipts()
        receipts[1]["recovery_registry_name"] = "OTHER_RECOVERY_HANDLERS"
        result = build_v63_recovery_overlay_acceptance_report(
            receipts,
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertEqual(result["builder_status"], "BLOCKED_INPUT")
        self.assertIn("RECOVERY_RECEIPT_REGISTRY_MISMATCH", result["builder_blockers"])


if __name__ == "__main__":
    unittest.main()
