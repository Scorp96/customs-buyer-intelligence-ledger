import unittest

from unified_runtime.contract_v63 import build_v63_contract


class V63ContractTests(unittest.TestCase):
    def test_contract_exposes_primary_product_and_generic_profiles(self):
        contract = build_v63_contract()
        self.assertEqual(contract["primary_product_profile"], "PVC")
        self.assertTrue({"PVC", "WPC", "SPC", "ACRYLIC_PMMA"} <= set(contract["product_profiles"]))

    def test_contract_exposes_six_branch_groups_and_market_levels(self):
        contract = build_v63_contract()
        self.assertEqual(len(contract["branch_groups"]), 6)
        self.assertEqual(contract["market_acceptance_levels"], ["M0", "M1", "M2", "M3", "M4", "M5"])

    def test_contract_prevents_old_completion_shortcuts(self):
        contract = build_v63_contract()
        self.assertFalse(contract["fixed_depth_or_count_closes_expansion"])
        self.assertFalse(contract["budget_exhaustion_closes_research"])
        self.assertTrue(contract["decision_saturation_remains_closure_authority"])
        self.assertTrue(contract["source_coverage_separate_from_expansion_saturation"])

    def test_contract_keeps_commercial_value_independent_from_contact(self):
        contract = build_v63_contract()
        self.assertTrue(contract["commercial_value_independent_of_contact"])
        self.assertFalse(contract["contact_readiness_required_for_anchor_eligibility"])

    def test_contract_marks_planning_as_not_execution_proof(self):
        contract = build_v63_contract()
        boundary = contract["public_source_execution_boundary"]
        self.assertFalse(boundary["planning_is_execution_proof"])
        self.assertTrue(boundary["real_execution_receipt_required"])

    def test_contract_keeps_legacy_peer_projection_non_authoritative(self):
        contract = build_v63_contract()
        legacy = contract["legacy_peer_compatibility"]
        self.assertFalse(legacy["legacy_promote_grants_v63_anchor_authority"])
        self.assertEqual(legacy["maximum_projection"], "ANCHOR_ELIGIBLE_LEGACY_SIGNAL")

    def test_contract_lists_v63_mutations_for_future_wal_binding(self):
        contract = build_v63_contract()
        mutations = set(contract["mutation_event_types"])
        self.assertNotIn("V63_DEMAND_ANCHOR_CREATED", mutations)
        self.assertIn("V63_PRODUCT_OPPORTUNITY_CREATED", mutations)
        self.assertNotIn("V63_PRODUCT_OPPORTUNITY_EVALUATED", mutations)
        self.assertIn("V63_OPPORTUNITY_ANCHOR_PROMOTED", mutations)
        self.assertIn("DEMAND_ANCHOR", contract["derived_views"])
        self.assertIn("PRODUCT_OPPORTUNITY_EVALUATION", contract["derived_views"])
        self.assertTrue(contract["mutations_require_existing_wal_integration"])


    def test_contract_exposes_three_production_recovery_mappings(self):
        contract = build_v63_contract()
        mappings = contract["production_recovery_mapping_v6_3"]
        self.assertEqual(
            set(mappings),
            {"append_candidate_discovery", "create_product_opportunity", "promote_opportunity_anchor"},
        )
        self.assertEqual(mappings["append_candidate_discovery"]["recovery_family"], "PEER_PIVOT_LIFECYCLE")
        self.assertEqual(mappings["create_product_opportunity"]["recovery_family"], "CANONICAL_OPPORTUNITY_CREATE")


    def test_contract_exposes_exact_recovery_acceptance_gate(self):
        contract = build_v63_contract()
        gate = contract["exact_recovery_acceptance_v6_3"]
        self.assertTrue(gate["required_before_production"])
        self.assertEqual(gate["reference_runner"], "scripts/run_v63_recovery_acceptance.py")
        self.assertEqual(gate["live_runner"], "scripts/run_v63_live_exact_recovery_acceptance.py")
        self.assertEqual(gate["live_receipt_schema"], "cbi.v63-live-exact-recovery-receipts.v1")
        self.assertEqual(gate["result_schema"], "cbi.v63-recovery-acceptance.v1")
        self.assertEqual(gate["execution_origin_required"], "LIVE_PRODUCTION_CHECKOUT")
        self.assertEqual(gate["adapter_path_required"], "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH")
        self.assertTrue(gate["must_match_current_production_source_snapshot"])
        self.assertFalse(gate["reference_runner_sufficient"])
        self.assertFalse(gate["side_effect_reexecution_allowed"])



    def test_contract_exposes_live_backend_correlation_acceptance_gate(self):
        contract = build_v63_contract()
        gate = contract["live_backend_correlation_acceptance_v6_3"]
        self.assertTrue(gate["required_before_production"])
        self.assertEqual(gate["result_schema"], "cbi.v63-backend-correlation-acceptance.v1")
        self.assertEqual(gate["adapter_path_required"], "EXISTING_PRODUCTION_INVOKE_MUTATION")
        self.assertEqual(gate["runtime_store_required"], "EXISTING_PRODUCTION_APPEND_ONLY_STORE")
        self.assertFalse(gate["synthetic_or_reference_run_sufficient"])
        self.assertFalse(gate["side_effect_reexecution_allowed"])
        self.assertTrue(gate["must_match_current_production_source_snapshot"])


    def test_contract_declares_recovery_overlay_fail_closed_until_live_binding(self):
        contract = build_v63_contract()
        self.assertEqual(contract["recovery_overlay_binding"], "FAIL_CLOSED_PENDING_ACTIVE_OVERLAY_BINDING")
        self.assertFalse(contract["recovery_overlay_candidate_is_binding_proof"])

    def test_contract_exposes_live_recovery_overlay_acceptance_gate(self):
        contract = build_v63_contract()
        gate = contract["live_recovery_overlay_acceptance_v6_3"]
        self.assertTrue(gate["required_before_production"])
        self.assertEqual(gate["result_schema"], "cbi.v63-recovery-overlay-acceptance.v1")
        self.assertEqual(gate["active_overlay_path_required"], "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN")
        self.assertTrue(gate["must_match_current_production_source_snapshot"])
        self.assertFalse(gate["reference_runner_sufficient"])
        self.assertFalse(gate["side_effect_reexecution_allowed"])
        self.assertEqual(gate["receipt_schema"], "cbi.v63-live-recovery-overlay-receipts.v1")
        self.assertEqual(gate["runner"], "scripts/run_v63_live_recovery_overlay_acceptance.py")
        self.assertFalse(gate["report_builder_claims_verified"])
        self.assertTrue(gate["expected_snapshot_must_be_external_authority"])

    def test_contract_declares_internal_runtime_durable_backend_requirements(self):
        contract = build_v63_contract()
        backend = contract["runtime_durable_backend_contract_v6_3"]
        self.assertEqual(backend["schema"], "cbi.v63-production-durable-backend.v1")
        self.assertEqual(backend["binding_strategy"], "EXISTING_PRODUCTION_APPEND_ONLY_STORE")
        self.assertFalse(backend["parallel_state_store_allowed"])
        self.assertTrue(backend["requires_existing_mutation_correlation"])
        self.assertFalse(backend["raw_idempotency_key_persisted"])
        self.assertFalse(backend["side_effect_reexecution_allowed"])
        self.assertTrue(backend["request_arguments_cannot_authorize_binding"])

    def test_contract_exposes_exact_v63_wal_recovery_policy(self):
        contract = build_v63_contract()
        wal = contract["mutation_wal_v6_3"]
        self.assertEqual(wal["binding_strategy"], "EXTEND_EXISTING_PRODUCTION_WAL")
        self.assertFalse(wal["parallel_wal_allowed"])
        self.assertFalse(wal["prepared_auto_replay_without_proof"])
        self.assertIn("create_product_opportunity", wal["bindings"])
        self.assertTrue(wal["bindings"]["create_product_opportunity"]["requires_exact_result_snapshot"])


if __name__ == "__main__":
    unittest.main()

class V63ContractConsistencyTests(unittest.TestCase):
    def test_persistent_mutation_event_types_match_wal_bindings_exactly(self):
        from unified_runtime.contract_v63 import build_v63_contract
        from unified_runtime.wal_contract_v63 import V63_WAL_BINDINGS
        contract = build_v63_contract()
        expected = {binding["event_type"] for binding in V63_WAL_BINDINGS.values()}
        self.assertEqual(set(contract["mutation_event_types"]), expected)

    def test_relative_ranking_is_declared_as_derived_not_wal_mutation(self):
        from unified_runtime.contract_v63 import build_v63_contract
        contract = build_v63_contract()
        self.assertIn("RELATIVE_OPPORTUNITY", contract["derived_views"])
        self.assertNotIn("V63_RELATIVE_OPPORTUNITY_EVALUATED", contract["mutation_event_types"])

    def test_state_dimensions_remain_separate(self):
        from unified_runtime.contract_v63 import build_v63_contract
        contract = build_v63_contract()
        dimensions = set(contract["state_dimensions"])
        self.assertTrue({
            "research_state",
            "resource_state",
            "research_action",
            "source_coverage_state",
            "commercial_value",
            "research_confidence",
            "outreach_readiness",
            "expansion_state",
            "expansion_coverage",
            "market_acceptance",
            "crm_sync_state",
            "closure_state",
        } <= dimensions)

class V63LocalOutreachContractTests(unittest.TestCase):
    def test_contract_exposes_local_time_language_and_channel_policy(self):
        contract = build_v63_contract()
        policy = contract["local_outreach_policy"]
        self.assertTrue(policy["iana_timezone_required"])
        self.assertTrue(policy["dst_aware"])
        self.assertTrue(policy["holiday_calendar_must_be_current_for_execution_ready"])
        self.assertTrue(policy["research_language_separate_from_outreach_language"])
        self.assertEqual(policy["language_priority"][0], "RECIPIENT_PREFERENCE")
        self.assertIn("WHATSAPP", policy["channel_windows_local"])
        self.assertFalse(policy["sends_message"])

class V63LocalMarketAndSalesReadinessContractTests(unittest.TestCase):
    def test_contract_exposes_workweek_and_sales_readiness_separation(self):
        contract = build_v63_contract()
        local = contract["local_outreach_policy"]
        self.assertTrue(local["market_workweek_must_be_resolved_or_curated"])
        self.assertFalse(local["unknown_market_assumes_mon_fri_for_execution"])
        self.assertIn("SALES_READINESS", contract["derived_views"])
        sales = contract["sales_readiness_policy"]
        self.assertTrue(sales["commercial_outreach_separate_from_technical_offer"])
        self.assertTrue(sales["capability_needs_verification_blocks_technical_promise_only"])
        self.assertFalse(sales["sends_message"])

class V63HighRecallDiscoveryContractTests(unittest.TestCase):
    def test_contract_declares_wide_discovery_strict_promotion_policy(self):
        contract = build_v63_contract()
        policy = contract["candidate_research_policy"]
        self.assertEqual(policy["strategy"], "WIDE_DISCOVERY_STRICT_PROMOTION")
        self.assertFalse(policy["canonical_identity_required_for_discovery"])
        self.assertFalse(policy["canonical_identity_required_for_research"])
        self.assertTrue(policy["canonical_identity_required_before_opportunity_creation"])
        self.assertFalse(policy["contact_readiness_is_discovery_gate"])
        self.assertFalse(policy["procurement_proof_required_for_candidate_retention"])
        self.assertTrue(policy["d3_d4_can_remain_research_active"])
        self.assertEqual(
            set(policy["proven_rejection_authorities"]),
            {"PROVEN_NEGATIVE", "PROVEN_DUPLICATE", "PROVEN_MISMATCH"},
        )
