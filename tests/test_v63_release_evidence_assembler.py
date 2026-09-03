import copy
import unittest

from tests.test_v63_render_r2_pvc_acceptance import (
    _FakeAcceptanceClient,
    _FakeReplacementController,
)
from unified_runtime.backend_correlation_acceptance_v63 import REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
from unified_runtime.contract_v63 import build_v63_contract
from unified_runtime.recovery_acceptance_v63 import run_v63_reference_recovery_acceptance
from unified_runtime.recovery_overlay_acceptance_v63 import REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS
from unified_runtime.release_evidence_v63 import evaluate_v63_release_evidence_bundle
from unified_runtime.render_r2_pvc_acceptance_v63 import run_v63_render_r2_pvc_acceptance


V63_MUTATIONS = [
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
]


class V63ReleaseEvidenceAssemblerTests(unittest.TestCase):
    def _health(self):
        return {
            "status": "READY",
            "runtime_version": "6.1.0",
            "mutation_wal": {
                "prepared_count": 0,
                "reconciliation_required": False,
                "guarded_mutation_tools": [
                    *V63_MUTATIONS,
                    "append_peer_discovery",
                    "promote_anchor",
                    "resolve_or_create_account",
                    "append_information_record",
                ],
                "automatic_reconciliation_tools": [
                    *V63_MUTATIONS,
                    "append_peer_discovery",
                    "promote_anchor",
                    "resolve_or_create_account",
                    "append_information_record",
                ],
                "unreconciled_mutation_tools": [],
                "exact_automatic_reconciliation_complete": True,
                "automatic_reexecution_of_unproven_prepared": False,
            },
            "mutation_event_correlation": {
                "status": "ENABLED",
                "correlation_contains_raw_idempotency_key": False,
            },
            "peer_pivot_lifecycle_recovery": {
                "status": "ENABLED",
                "automatic_reconciliation_tools": ["append_peer_discovery", "promote_anchor"],
                "requires_event_correlation": True,
            },
        }

    def _contract(self):
        v63 = build_v63_contract()
        v63.update({
            "runtime_overlay_mutation_binding": "BOUND_EXISTING_PRODUCTION_WAL",
            "recovery_overlay_binding": "BOUND_ACTIVE_PRODUCTION_OVERLAY_CHAIN",
            "runtime_durable_backend_binding": "BOUND_EXISTING_DURABLE_STORE",
            "runtime_durable_backend_schema": "cbi.v63-production-durable-backend.v1",
            "runtime_durable_backend_parallel_store_allowed": False,
            "runtime_durable_backend_requires_existing_mutation_correlation": True,
            "runtime_durable_backend_raw_idempotency_key_persisted": False,
            "runtime_durable_backend_side_effect_reexecution_allowed": False,
        })
        return {
            "research_orchestration_v6_2": {"enabled": True},
            "production_adapter_mutation_wal": {
                "prepared_auto_replay_without_proof": False,
                "automatic_reconciliation_requires_durable_proof": True,
                "exact_automatic_reconciliation_complete": True,
                "durable_event_correlation": {
                    "enabled": True,
                    "correlation_contains_raw_idempotency_key": False,
                    "correlation_alone_authorizes_replay": False,
                },
                "peer_pivot_lifecycle_recovery": {
                    "enabled": True,
                    "tools": ["append_peer_discovery", "promote_anchor"],
                    "requires_exact_event_correlation": True,
                    "reexecutes_side_effect": False,
                },
            },
            "demand_expansion_v6_3": v63,
        }

    def _backend_report(self, sha="a" * 64):
        return {
            "schema": "cbi.v63-backend-correlation-acceptance.v1",
            "adapter_path_exercised": "EXISTING_PRODUCTION_INVOKE_MUTATION",
            "runtime_store_exercised": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
            "production_source_snapshot_sha256": sha,
            "scenarios": [
                {
                    "scenario": name,
                    "status": "PASS",
                    "reexecute_side_effect": False,
                    "exact_correlation_proven": True,
                    "exact_request_hash_proven": True,
                    "cross_key_result_claimed": False,
                }
                for name in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
            ],
        }

    def _recovery_overlay_report(self, sha="a" * 64):
        return {
            "schema": "cbi.v63-recovery-overlay-acceptance.v1",
            "active_overlay_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
            "production_source_snapshot_sha256": sha,
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

    def _render_r2_pvc_receipt(self, *, real_render=True):
        client = _FakeAcceptanceClient()
        controller = _FakeReplacementController(client)
        receipt = run_v63_render_r2_pvc_acceptance(client, controller)
        if real_render:
            receipt = copy.deepcopy(receipt)
            receipt["replacement"]["instance_before"] = "dep-render-release-a"
            receipt["replacement"]["instance_after"] = "dep-render-release-b"
            for phase in ("health_before", "health_after"):
                identity = receipt[phase]["deployment_identity"]
                identity["remote_entrypoint"] = "mcp/server_v61_remote.py"
                identity["runtime_entrypoint"] = "mcp/server_v61_backup_recovery.py"
        return receipt

    def _exact_live_report(self, sha="a" * 64):
        report = copy.deepcopy(run_v63_reference_recovery_acceptance())
        report.update({
            "execution_origin": "LIVE_PRODUCTION_CHECKOUT",
            "adapter_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH",
            "production_source_snapshot_sha256": sha,
            "reference_runner_only": False,
        })
        return report

    def _bundle(self):
        return {
            "health": self._health(),
            "contract": self._contract(),
            "current_production_source_snapshot_sha256": "a" * 64,
            "exact_recovery_acceptance_report": self._exact_live_report(),
            "backend_correlation_acceptance_report": self._backend_report(),
            "recovery_overlay_acceptance_report": self._recovery_overlay_report(),
            "render_r2_pvc_acceptance_report": self._render_r2_pvc_receipt(),
        }

    def test_complete_evidence_bundle_produces_production_ready(self):
        result = evaluate_v63_release_evidence_bundle(self._bundle())
        self.assertTrue(result["production_ready"], result)
        self.assertTrue(result["component_validations"]["exact_recovery"]["verified"])
        self.assertTrue(result["component_validations"]["backend_correlation"]["verified"])
        self.assertTrue(result["component_validations"]["recovery_overlay"]["verified"])
        self.assertTrue(result["component_validations"]["render_r2_pvc_acceptance"]["verified"])
        self.assertEqual(result["production_gate"]["status"], "PRODUCTION_READY")

    def test_user_supplied_verified_booleans_cannot_override_failed_backend_report(self):
        bundle = self._bundle()
        bundle["live_v63_backend_correlation_acceptance_verified"] = True
        bundle["backend_correlation_acceptance_report"]["scenarios"][0]["status"] = "FAIL"
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["component_validations"]["backend_correlation"]["verified"])
        self.assertIn("V63_LIVE_BACKEND_CORRELATION_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_stale_recovery_overlay_report_cannot_pass_current_snapshot_gate(self):
        bundle = self._bundle()
        bundle["recovery_overlay_acceptance_report"]["production_source_snapshot_sha256"] = "b" * 64
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH", result["component_validations"]["recovery_overlay"]["blockers"])
        self.assertIn("V63_LIVE_RECOVERY_OVERLAY_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_failed_reference_recovery_acceptance_cannot_be_promoted_by_flag(self):
        bundle = self._bundle()
        bundle["exact_v63_recovery_acceptance_verified"] = True
        bundle["exact_recovery_acceptance_report"] = copy.deepcopy(bundle["exact_recovery_acceptance_report"])
        bundle["exact_recovery_acceptance_report"]["passed"] = False
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["component_validations"]["exact_recovery"]["verified"])
        self.assertIn("V63_EXACT_RECOVERY_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_caller_verified_boolean_cannot_replace_missing_render_r2_pvc_receipt(self):
        bundle = self._bundle()
        bundle.pop("render_r2_pvc_acceptance_report")
        bundle["render_r2_pvc_acceptance_verified"] = True
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["component_validations"]["render_r2_pvc_acceptance"]["verified"])
        self.assertIn("V63_RENDER_R2_PVC_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_local_mock_render_r2_receipt_is_not_release_proof(self):
        bundle = self._bundle()
        bundle["render_r2_pvc_acceptance_report"] = self._render_r2_pvc_receipt(real_render=False)
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        validation = result["component_validations"]["render_r2_pvc_acceptance"]
        self.assertFalse(validation["verified"])
        self.assertIn("REAL_RENDER_INSTANCE_REPLACEMENT_NOT_PROVEN", validation["blockers"])
        self.assertIn("V63_RENDER_R2_PVC_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_failed_render_r2_base_validation_blocks_release(self):
        bundle = self._bundle()
        bundle["render_r2_pvc_acceptance_report"] = copy.deepcopy(bundle["render_r2_pvc_acceptance_report"])
        bundle["render_r2_pvc_acceptance_report"]["evidence_after"]["events"]["append_candidate_discovery"]["count"] = 2
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        validation = result["component_validations"]["render_r2_pvc_acceptance"]
        self.assertFalse(validation["verified"])
        self.assertTrue(any("DUPLICATE_BUSINESS_EVENT" in blocker for blocker in validation["blockers"]))

    def test_reference_runner_result_is_not_production_release_proof(self):
        bundle = self._bundle()
        bundle["exact_recovery_acceptance_report"] = run_v63_reference_recovery_acceptance()
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["component_validations"]["exact_recovery"]["verified"])
        self.assertIn("LIVE_PRODUCTION_EXACT_RECOVERY_NOT_EXERCISED", result["component_validations"]["exact_recovery"]["blockers"])
        self.assertIn("V63_EXACT_RECOVERY_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_stale_exact_recovery_report_cannot_pass_current_snapshot_gate(self):
        bundle = self._bundle()
        bundle["exact_recovery_acceptance_report"] = self._exact_live_report("b" * 64)
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH", result["component_validations"]["exact_recovery"]["blockers"])

    def test_missing_reports_fail_closed(self):
        bundle = self._bundle()
        bundle.pop("backend_correlation_acceptance_report")
        bundle.pop("recovery_overlay_acceptance_report")
        result = evaluate_v63_release_evidence_bundle(bundle)
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["component_validations"]["backend_correlation"]["verified"])
        self.assertFalse(result["component_validations"]["recovery_overlay"]["verified"])


if __name__ == "__main__":
    unittest.main()
