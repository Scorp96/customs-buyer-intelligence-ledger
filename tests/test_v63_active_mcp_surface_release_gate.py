import unittest

from unified_runtime.mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES
from unified_runtime.production_gate_v63 import evaluate_v63_production_gate
from unified_runtime.release_evidence_v63 import _validate_mcp_surface_evidence


ALL_V63_MCP_TOOLS = [*V63_READ_ONLY_TOOL_NAMES, *V63_MUTATION_TOOL_NAMES]
V63_MUTATIONS = list(V63_MUTATION_TOOL_NAMES)


class V63ActiveMcpSurfaceReleaseGateTests(unittest.TestCase):
    def healthy_gate_payload(self):
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
            "active_mcp_tool_names": list(ALL_V63_MCP_TOOLS),
        }

    def test_complete_active_mcp_surface_preserves_green_gate(self):
        result = evaluate_v63_production_gate(self.healthy_gate_payload())
        self.assertTrue(result["production_ready"], result)
        self.assertEqual(result["missing_active_mcp_tools"], [])

    def test_missing_v63_mutation_blocks_production_gate(self):
        payload = self.healthy_gate_payload()
        payload["active_mcp_tool_names"].remove("create_product_opportunity")
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_ACTIVE_MCP_SURFACE_INCOMPLETE", result["blockers"])
        self.assertIn("create_product_opportunity", result["missing_active_mcp_tools"])

    def test_contract_and_wal_cannot_substitute_for_missing_active_surface(self):
        payload = self.healthy_gate_payload()
        payload.pop("active_mcp_tool_names")
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_ACTIVE_MCP_SURFACE_INCOMPLETE", result["blockers"])

    def test_source_bound_mcp_surface_evidence_accepts_complete_tool_list(self):
        result = _validate_mcp_surface_evidence(
            {
                "schema": "cbi.v63-mcp-surface-evidence.v1",
                "verified": True,
                "production_source_snapshot_sha256": "a" * 64,
                "active_entrypoint_observed": True,
                "tools_list_observed": True,
                "tool_names": list(ALL_V63_MCP_TOOLS),
            },
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["missing_tools"], [])

    def test_source_bound_mcp_surface_evidence_rejects_missing_tool(self):
        tools = list(ALL_V63_MCP_TOOLS)
        tools.remove("promote_opportunity_anchor")
        result = _validate_mcp_surface_evidence(
            {
                "schema": "cbi.v63-mcp-surface-evidence.v1",
                "verified": True,
                "production_source_snapshot_sha256": "a" * 64,
                "active_entrypoint_observed": True,
                "tools_list_observed": True,
                "tool_names": tools,
            },
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertFalse(result["verified"])
        self.assertIn("ACTIVE_MCP_TOOL_SET_INCOMPLETE", result["blockers"])
        self.assertIn("promote_opportunity_anchor", result["missing_tools"])

    def test_source_bound_mcp_surface_evidence_rejects_stale_snapshot(self):
        result = _validate_mcp_surface_evidence(
            {
                "schema": "cbi.v63-mcp-surface-evidence.v1",
                "verified": True,
                "production_source_snapshot_sha256": "b" * 64,
                "active_entrypoint_observed": True,
                "tools_list_observed": True,
                "tool_names": list(ALL_V63_MCP_TOOLS),
            },
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertFalse(result["verified"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH", result["blockers"])


if __name__ == "__main__":
    unittest.main()
