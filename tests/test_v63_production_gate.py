import unittest

from unified_runtime.production_gate_v63 import evaluate_v63_production_gate


V63_MUTATIONS = [
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
]


class V63ProductionGateTests(unittest.TestCase):
    def healthy_payload(self):
        return {
            "health": {
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
            },
            "contract": {
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
                "demand_expansion_v6_3": {
                    "primary_product_profile": "PVC",
                    "runtime_overlay_mutation_binding": "BOUND_EXISTING_PRODUCTION_WAL",
                    "recovery_overlay_binding": "BOUND_ACTIVE_PRODUCTION_OVERLAY_CHAIN",
                    "runtime_durable_backend_binding": "BOUND_EXISTING_DURABLE_STORE",
                    "runtime_durable_backend_schema": "cbi.v63-production-durable-backend.v1",
                    "runtime_durable_backend_parallel_store_allowed": False,
                    "runtime_durable_backend_requires_existing_mutation_correlation": True,
                    "runtime_durable_backend_raw_idempotency_key_persisted": False,
                    "runtime_durable_backend_side_effect_reexecution_allowed": False,
                    "mutation_wal_v6_3": {
                        "binding_strategy": "EXTEND_EXISTING_PRODUCTION_WAL",
                        "parallel_wal_allowed": False,
                    },
                    "production_recovery_mapping_v6_3": {
                        "append_candidate_discovery": {"recovery_family": "PEER_PIVOT_LIFECYCLE"},
                        "create_product_opportunity": {"recovery_family": "CANONICAL_OPPORTUNITY_CREATE"},
                        "promote_opportunity_anchor": {"recovery_family": "PEER_PIVOT_LIFECYCLE"},
                    },
                },
            },
            "render_r2_pvc_acceptance_verified": True,
            "exact_v63_recovery_acceptance_verified": True,
            "live_v63_backend_correlation_acceptance_verified": True,
            "live_v63_backend_correlation_acceptance_snapshot_sha256": "a" * 64,
            "live_v63_recovery_overlay_acceptance_verified": True,
            "live_v63_recovery_overlay_acceptance_snapshot_sha256": "a" * 64,
            "current_production_source_snapshot_sha256": "a" * 64,
        }

    def test_current_v61_runtime_is_not_v63_production_ready(self):
        result = evaluate_v63_production_gate({
            "health": {"status": "READY", "runtime_version": "6.1.0", "mutation_wal": {"prepared_count": 0, "reconciliation_required": False, "guarded_mutation_tools": []}},
            "contract": {},
            "render_r2_pvc_acceptance_verified": False,
        })
        self.assertFalse(result["production_ready"])
        self.assertIn("V62_ORCHESTRATION_NOT_LIVE", result["blockers"])
        self.assertIn("V63_DEMAND_EXPANSION_NOT_LIVE", result["blockers"])

    def test_pending_wal_blocks_release(self):
        payload = self.healthy_payload()
        payload["health"]["mutation_wal"]["prepared_count"] = 1
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("MUTATION_WAL_PREPARED_INTENTS", result["blockers"])

    def test_missing_v63_guarded_mutation_blocks_release(self):
        payload = self.healthy_payload()
        payload["health"]["mutation_wal"]["guarded_mutation_tools"].remove("create_product_opportunity")
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_MUTATION_WAL_INVENTORY_INCOMPLETE", result["blockers"])

    def test_v63_mutation_in_unreconciled_inventory_blocks_release(self):
        payload = self.healthy_payload()
        payload["health"]["mutation_wal"]["unreconciled_mutation_tools"] = ["promote_opportunity_anchor"]
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_MUTATION_RECONCILIATION_INCOMPLETE", result["blockers"])

    def test_exact_automatic_reconciliation_must_be_complete(self):
        payload = self.healthy_payload()
        payload["health"]["mutation_wal"]["exact_automatic_reconciliation_complete"] = False
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("EXACT_AUTOMATIC_RECONCILIATION_INCOMPLETE", result["blockers"])

    def test_fail_closed_pending_binding_is_not_production_binding(self):
        payload = self.healthy_payload()
        payload["contract"]["demand_expansion_v6_3"]["runtime_overlay_mutation_binding"] = "FAIL_CLOSED_PENDING_PRODUCTION_WAL"
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_PRODUCTION_WAL_NOT_BOUND", result["blockers"])

    def test_runtime_durable_backend_must_be_bound_to_existing_store(self):
        payload = self.healthy_payload()
        payload["contract"]["demand_expansion_v6_3"]["runtime_durable_backend_binding"] = "UNBOUND_FAIL_CLOSED"
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND", result["blockers"])

    def test_runtime_durable_backend_policy_must_forbid_parallel_store_and_reexecution(self):
        payload = self.healthy_payload()
        v63 = payload["contract"]["demand_expansion_v6_3"]
        v63["runtime_durable_backend_parallel_store_allowed"] = True
        v63["runtime_durable_backend_side_effect_reexecution_allowed"] = True
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_RUNTIME_DURABLE_BACKEND_POLICY_UNSAFE", result["blockers"])

    def test_missing_recovery_mapping_blocks_release(self):
        payload = self.healthy_payload()
        del payload["contract"]["demand_expansion_v6_3"]["production_recovery_mapping_v6_3"]["create_product_opportunity"]
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_PRODUCTION_RECOVERY_MAPPING_INCOMPLETE", result["blockers"])

    def test_v63_mutations_must_be_automatic_reconciliation_tools(self):
        payload = self.healthy_payload()
        payload["health"]["mutation_wal"]["automatic_reconciliation_tools"].remove("append_candidate_discovery")
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_AUTOMATIC_RECONCILIATION_INVENTORY_INCOMPLETE", result["blockers"])

    def test_recovery_family_must_match_verified_mapping(self):
        payload = self.healthy_payload()
        payload["contract"]["demand_expansion_v6_3"]["production_recovery_mapping_v6_3"]["create_product_opportunity"]["recovery_family"] = "GENERIC_REPLAY"
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_PRODUCTION_RECOVERY_MAPPING_INVALID", result["blockers"])

    def test_exact_v63_recovery_acceptance_is_required(self):
        payload = self.healthy_payload()
        payload["exact_v63_recovery_acceptance_verified"] = False
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_EXACT_RECOVERY_ACCEPTANCE_NOT_VERIFIED", result["blockers"])

    def test_live_backend_correlation_acceptance_is_required(self):
        payload = self.healthy_payload()
        payload["live_v63_backend_correlation_acceptance_verified"] = False
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_LIVE_BACKEND_CORRELATION_ACCEPTANCE_NOT_VERIFIED", result["blockers"])

    def test_live_backend_correlation_acceptance_must_match_current_source_snapshot(self):
        payload = self.healthy_payload()
        payload["current_production_source_snapshot_sha256"] = "b" * 64
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_BACKEND_CORRELATION_ACCEPTANCE_SOURCE_DRIFT", result["blockers"])

    def test_recovery_overlay_binding_must_be_live_on_active_production_chain(self):
        payload = self.healthy_payload()
        payload["contract"]["demand_expansion_v6_3"]["recovery_overlay_binding"] = "CANDIDATE_ONLY"
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_RECOVERY_OVERLAY_NOT_BOUND", result["blockers"])

    def test_live_recovery_overlay_acceptance_is_required(self):
        payload = self.healthy_payload()
        payload["live_v63_recovery_overlay_acceptance_verified"] = False
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_LIVE_RECOVERY_OVERLAY_ACCEPTANCE_NOT_VERIFIED", result["blockers"])

    def test_live_recovery_overlay_acceptance_must_match_current_source_snapshot(self):
        payload = self.healthy_payload()
        payload["live_v63_recovery_overlay_acceptance_snapshot_sha256"] = "b" * 64
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_RECOVERY_OVERLAY_ACCEPTANCE_SOURCE_DRIFT", result["blockers"])

    def test_render_r2_pvc_acceptance_is_required(self):
        payload = self.healthy_payload()
        payload["render_r2_pvc_acceptance_verified"] = False
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_RENDER_R2_PVC_ACCEPTANCE_NOT_VERIFIED", result["blockers"])

    def test_unsafe_live_correlation_preconditions_block_release(self):
        payload = self.healthy_payload()
        payload["health"]["mutation_event_correlation"]["correlation_contains_raw_idempotency_key"] = True
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("LIVE_PHASE_B_PRECONDITIONS_FAILED", result["blockers"])
        self.assertIn("MUTATION_CORRELATION_POLICY_UNSAFE", result["live_phase_b_blockers"])

    def test_missing_peer_lifecycle_precedent_blocks_release_even_when_v63_inventory_is_complete(self):
        payload = self.healthy_payload()
        payload["health"]["peer_pivot_lifecycle_recovery"]["status"] = "DISABLED"
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("LIVE_PHASE_B_PRECONDITIONS_FAILED", result["blockers"])
        self.assertIn("PEER_LIFECYCLE_RECOVERY_PRECEDENT_UNSAFE", result["live_phase_b_blockers"])

    def test_only_fully_verified_payload_is_production_ready(self):
        result = evaluate_v63_production_gate(self.healthy_payload())
        self.assertTrue(result["production_ready"])
        self.assertEqual(result["blockers"], [])


if __name__ == "__main__":
    unittest.main()
