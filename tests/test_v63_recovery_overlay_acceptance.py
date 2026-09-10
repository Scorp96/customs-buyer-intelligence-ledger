import unittest

from unified_runtime.recovery_overlay_acceptance_v63 import (
    REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS,
    validate_v63_recovery_overlay_acceptance,
)


class V63RecoveryOverlayAcceptanceTests(unittest.TestCase):
    def _passing_report(self):
        return {
            "schema": "cbi.v63-recovery-overlay-acceptance.v1",
            "active_overlay_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
            "production_source_snapshot_sha256": "a" * 64,
            "recovery_registry_file": "mcp/server_v61_peer_pivot_recovery.py",
            "recovery_registry_name": "RECOVERY_HANDLERS",
            "reference_runner_only": False,
            "scenarios": [
                {
                    "scenario": name,
                    "status": "PASS",
                    "active_overlay_handler_exercised": True,
                    "reexecute_side_effect": False,
                    "exact_correlation_proven": True,
                    "exact_request_hash_proven": True,
                    "exact_result_snapshot_proven": True if name == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS" else None,
                }
                for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS
            ],
        }

    def test_complete_source_bound_live_overlay_acceptance_passes(self):
        result = validate_v63_recovery_overlay_acceptance(
            self._passing_report(),
            expected_production_source_snapshot_sha256="a" * 64,
            expected_recovery_registry_file="mcp/server_v61_peer_pivot_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["passed_count"], len(REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS))
        self.assertEqual(result["blockers"], [])

    def test_reference_runner_cannot_claim_live_overlay_acceptance(self):
        report = self._passing_report()
        report["reference_runner_only"] = True
        result = validate_v63_recovery_overlay_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("REFERENCE_RECOVERY_RUNNER_IS_NOT_LIVE_OVERLAY_PROOF", result["blockers"])

    def test_wrong_active_path_fails_closed(self):
        report = self._passing_report()
        report["active_overlay_path_exercised"] = "SYNTHETIC_OVERLAY"
        result = validate_v63_recovery_overlay_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("ACTIVE_PRODUCTION_RECOVERY_OVERLAY_NOT_EXERCISED", result["blockers"])

    def test_source_snapshot_mismatch_invalidates_acceptance(self):
        result = validate_v63_recovery_overlay_acceptance(
            self._passing_report(), expected_production_source_snapshot_sha256="b" * 64
        )
        self.assertFalse(result["verified"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH", result["blockers"])

    def test_registry_mismatch_invalidates_acceptance(self):
        result = validate_v63_recovery_overlay_acceptance(
            self._passing_report(),
            expected_recovery_registry_file="mcp/server_v61_other_recovery.py",
            expected_recovery_registry_name="RECOVERY_HANDLERS",
        )
        self.assertFalse(result["verified"])
        self.assertIn("RECOVERY_REGISTRY_MISMATCH", result["blockers"])

    def test_missing_or_duplicate_scenario_fails_closed(self):
        report = self._passing_report()
        report["scenarios"] = report["scenarios"][:-1]
        result = validate_v63_recovery_overlay_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("RECOVERY_OVERLAY_SCENARIOS_INCOMPLETE", result["blockers"])

    def test_side_effect_reexecution_or_unexercised_handler_is_rejected(self):
        report = self._passing_report()
        report["scenarios"][0]["reexecute_side_effect"] = True
        report["scenarios"][1]["active_overlay_handler_exercised"] = False
        result = validate_v63_recovery_overlay_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("SIDE_EFFECT_REEXECUTION_OBSERVED", result["blockers"])
        self.assertIn("ACTIVE_RECOVERY_HANDLER_NOT_EXERCISED", result["blockers"])

    def test_opportunity_snapshot_recovery_requires_exact_snapshot_proof(self):
        report = self._passing_report()
        for row in report["scenarios"]:
            if row["scenario"] == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS":
                row["exact_result_snapshot_proven"] = False
        result = validate_v63_recovery_overlay_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("EXACT_RESULT_SNAPSHOT_NOT_PROVEN", result["blockers"])


if __name__ == "__main__":
    unittest.main()
