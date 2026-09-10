import unittest

from unified_runtime.backend_correlation_acceptance_v63 import (
    REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS,
    validate_v63_backend_correlation_acceptance,
)


class V63BackendCorrelationAcceptanceTests(unittest.TestCase):
    def _passing_report(self):
        scenarios = []
        for name in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS:
            scenarios.append({
                "scenario": name,
                "status": "PASS",
                "durable_event_count": 1 if "SUCCESS" in name or "RECOVERY" in name else 0,
                "reexecute_side_effect": False,
                "exact_correlation_proven": True,
                "exact_request_hash_proven": True,
                "cross_key_result_claimed": False,
            })
        return {
            "schema": "cbi.v63-backend-correlation-acceptance.v1",
            "adapter_path_exercised": "EXISTING_PRODUCTION_INVOKE_MUTATION",
            "runtime_store_exercised": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
            "production_source_snapshot_sha256": "a" * 64,
            "scenarios": scenarios,
        }

    def test_complete_live_backend_acceptance_passes(self):
        result = validate_v63_backend_correlation_acceptance(self._passing_report())
        self.assertTrue(result["verified"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["passed_count"], len(REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS))

    def test_missing_scenario_fails_closed(self):
        report = self._passing_report()
        report["scenarios"] = report["scenarios"][:-1]
        result = validate_v63_backend_correlation_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("BACKEND_CORRELATION_SCENARIOS_INCOMPLETE", result["blockers"])

    def test_side_effect_reexecution_is_never_accepted(self):
        report = self._passing_report()
        report["scenarios"][0]["reexecute_side_effect"] = True
        result = validate_v63_backend_correlation_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("SIDE_EFFECT_REEXECUTION_OBSERVED", result["blockers"])

    def test_cross_key_result_claiming_is_never_accepted(self):
        report = self._passing_report()
        report["scenarios"][0]["cross_key_result_claimed"] = True
        result = validate_v63_backend_correlation_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("CROSS_KEY_RESULT_CLAIMING_OBSERVED", result["blockers"])


    def test_acceptance_can_be_pinned_to_exact_production_source_snapshot(self):
        report = self._passing_report()
        result = validate_v63_backend_correlation_acceptance(
            report, expected_production_source_snapshot_sha256="a" * 64
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["production_source_snapshot_sha256"], "a" * 64)

    def test_source_snapshot_drift_invalidates_old_acceptance(self):
        report = self._passing_report()
        result = validate_v63_backend_correlation_acceptance(
            report, expected_production_source_snapshot_sha256="b" * 64
        )
        self.assertFalse(result["verified"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH", result["blockers"])

    def test_reference_or_synthetic_adapter_cannot_claim_live_acceptance(self):
        report = self._passing_report()
        report["adapter_path_exercised"] = "SYNTHETIC_REFERENCE_ADAPTER"
        result = validate_v63_backend_correlation_acceptance(report)
        self.assertFalse(result["verified"])
        self.assertIn("PRODUCTION_ADAPTER_NOT_EXERCISED", result["blockers"])


if __name__ == "__main__":
    unittest.main()
