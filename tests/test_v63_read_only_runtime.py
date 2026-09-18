import copy
import unittest

from unified_runtime.demand_expansion import V63DemandExpansionMixin


class FakeBase:
    def __init__(self):
        self.state = {"sentinel": [1, 2, 3]}

    def get_runtime_contract(self, arguments=None):
        return {"runtime_version": "6.2-test", "existing": {"preserved": True}}


class Runtime(V63DemandExpansionMixin, FakeBase):
    pass


class V63ReadOnlyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_contract_overlay_preserves_existing_contract(self):
        contract = self.runtime.get_runtime_contract({})
        self.assertEqual(contract["runtime_version"], "6.2-test")
        self.assertTrue(contract["existing"]["preserved"])
        self.assertEqual(contract["demand_expansion_v6_3"]["primary_product_profile"], "PVC")

    def test_product_profile_read_is_non_mutating(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.get_product_profiles({})
        self.assertEqual(result["status"], "READY")
        self.assertGreaterEqual(len(result["profiles"]), 4)
        self.assertEqual(self.runtime.state, before)

    def test_candidate_expansion_planning_is_non_mutating_and_requires_host_execution(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.plan_candidate_expansion({
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "market_acceptance": "M1",
            "anchor_grade": "B+",
            "anchor_score": 84.0,
            "applications": ["CABINETRY"],
            "buyer_archetypes": ["CABINET_MANUFACTURER"],
            "geography": "Vietnam-HCMC",
            "local_language_terms": ["tủ bếp"],
            "query_limit": 20,
            "source_task_limit": 200,
        })
        self.assertFalse(result["planning_is_execution_proof"])
        self.assertTrue(result["host_execution_required"])
        self.assertGreater(result["source_plan"]["returned_count"], 0)
        self.assertEqual(self.runtime.state, before)

    def test_relative_opportunity_runtime_wrapper_is_read_only(self):
        result = self.runtime.evaluate_relative_opportunity({
            "anchor_score": 84,
            "candidate_score": 92,
            "anchor_grade": "B+",
            "candidate_grade": "A",
        })
        self.assertEqual(result["relative_class"], "UPGRADE_TARGET")

    def test_contact_planner_runtime_wrapper_is_read_only(self):
        result = self.runtime.plan_contact_exhaustion({
            "opportunity": {
                "product_profile_id": "PVC",
                "commercial_value_grade": "A+",
                "outreach_readiness": "IDENTITY_ONLY",
            },
            "current_routes": {},
        })
        self.assertTrue(result["company_route_required"])
        self.assertTrue(result["named_route_exhaustive"])



    def test_unbound_capability_profile_returns_unconfigured_instead_of_inventing_specs(self):
        result = self.runtime.get_capability_profile({"product_profile_id": "PVC"})
        self.assertEqual(result["status"], "UNCONFIGURED")
        self.assertEqual(result["product_profile_id"], "PVC")
        self.assertEqual(result["capability_profile"], None)
        self.assertFalse(result["persistent_mutation_performed"])

    def test_bound_capability_profile_can_be_evaluated_read_only(self):
        self.runtime._v63_capability_profiles = {
            "PVC": {
                "capability_profile_id": "CAP-PVC-1",
                "version": "1",
                "product_profile_id": "PVC",
                "supported_variants": ["CELUKA"],
                "supported_thickness_mm": [3.0, 30.0],
                "supported_sizes_mm": [[1220.0, 2440.0]],
                "verified_claims": [],
                "unverified_claims": [],
                "known_limitations": [],
                "validation_status": "VERIFIED",
                "sha256": "a" * 64,
            }
        }
        result = self.runtime.evaluate_capability_fit({
            "product_profile_id": "PVC",
            "demand": {
                "product_profile_id": "PVC",
                "product_variant": "CELUKA",
                "thickness_mm": 18,
                "size_mm": [1220, 2440],
            },
        })
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["capability_fit"]["capability_fit"], "SUPPORTED")
        self.assertFalse(result["persistent_mutation_performed"])

    def test_legacy_peer_projection_runtime_wrapper_is_read_only(self):
        result = self.runtime.project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "P100",
            "promotion_decision": "PROMOTE",
            "canonical_status": "NEW",
        })
        self.assertEqual(result["maximum_stage"], "ANCHOR_ELIGIBLE_LEGACY_SIGNAL")
        self.assertFalse(result["grants_v63_anchor_authority"])
        self.assertFalse(result["persistent_mutation_performed"])

    def test_recursive_anchor_preview_runtime_wrapper_is_read_only(self):
        result = self.runtime.preview_recursive_anchor_expansion({
            "promoted_anchor": {
                "opportunity_id": "OPP-C501-PVC-PRIMARY",
                "account_id": "C501",
                "product_profile_id": "PVC",
                "commercial_value_grade": "A",
                "commercial_value_score": 92.0,
                "stage": "PROMOTED_ANCHOR",
            },
            "market_cell": {
                "market_cell_id": "MC-US-MA-PVC-CABINETRY",
                "geography": "US-MA",
                "product_profile_id": "PVC",
                "application_ids": ["CABINETRY"],
                "buyer_archetype_ids": ["CABINET_MANUFACTURER"],
                "market_acceptance": "M2",
            },
        })
        self.assertEqual(result["status"], "PLANNED")
        self.assertTrue(result["preview_only"])
        self.assertFalse(result["persistent_mutation_performed"])


    def test_demand_anchor_is_derived_read_only_view(self):
        result = self.runtime.derive_demand_anchor({
            "account_id": "C1",
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "source_type": "CUSTOMS",
            "source_evidence_ids": ["E1"],
            "product_profile_id": "PVC",
            "geography": "US-MA",
            "shipment_date": "2026-08-02",
        })
        self.assertEqual(result["account_id"], "C1")
        self.assertTrue(result["derived_view"])
        self.assertFalse(result["persistent_mutation_performed"])

    def test_product_opportunity_evaluation_is_derived_read_only_view(self):
        result = self.runtime.evaluate_product_opportunity({
            "investigation_id": "INV-1",
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "assessment": {
                "commercial_value_grade": "A",
                "commercial_value_score": 92,
                "commercial_evidence_ids": ["E-COM-1"],
                "research_confidence": 80,
            },
        })
        self.assertEqual(result["commercial_value_grade"], "A")
        self.assertTrue(result["derived_view"])
        self.assertFalse(result["persistent_mutation_performed"])

    def test_persistent_v63_mutations_fail_closed_until_real_wal_binding_exists(self):
        mutation_methods = [
            "append_candidate_discovery",
            "create_product_opportunity",
            "promote_opportunity_anchor",
        ]
        for name in mutation_methods:
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, "V63_MUTATION_REQUIRES_PRODUCTION_WAL_BINDING"):
                    getattr(self.runtime, name)({"idempotency_key": "test-key-123"})


if __name__ == "__main__":
    unittest.main()

class V63RouteReuseAndMetricsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_runtime_can_project_account_route_reuse_read_only(self):
        result = self.runtime.evaluate_route_reuse({
            "route": {
                "route_id": "R1",
                "owner_scope": "ACCOUNT",
                "verified": True,
                "route_eligible": True,
                "freshness": "CURRENT",
            },
            "opportunity": {"account_id": "C1", "product_profile_id": "PVC"},
        })
        self.assertTrue(result["route_reusable"])
        self.assertFalse(result["route_proves_product_interest"])
        self.assertFalse(result["persistent_mutation_performed"])

    def test_runtime_can_compute_portfolio_metrics_read_only(self):
        result = self.runtime.get_portfolio_metrics({
            "opportunities": [
                {"account_id": "C1", "opportunity_id": "O1", "commercial_value_grade": "A", "outreach_readiness": "COMPANY_ROUTE_READY"},
                {"account_id": "C1", "opportunity_id": "O2", "commercial_value_grade": "B+", "outreach_readiness": "IDENTITY_ONLY"},
            ]
        })
        self.assertEqual(result["unique_account_count"], 1)
        self.assertEqual(result["product_opportunity_count"], 2)
        self.assertFalse(result["persistent_mutation_performed"])

class V63ResearchSchedulerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_runtime_soft_budget_keeps_material_deferred_work_visible(self):
        result = self.runtime.schedule_expansion_research({
            "budget_units": 0,
            "opportunities": [{
                "opportunity_id": "O1",
                "product_profile_id": "PVC",
                "commercial_value_grade": "A",
                "commercial_score": 92,
                "relative_class": "UPGRADE_TARGET",
                "market_acceptance": "M2",
                "eiv": 0.9,
                "outreach_readiness": "IDENTITY_ONLY",
                "source_coverage_complete": False,
                "material": True,
            }],
        })
        self.assertEqual(result["resource_state"], "EXHAUSTED")
        self.assertEqual(result["deferred_material"][0]["opportunity_id"], "O1")
        self.assertFalse(result["budget_exhaustion_closes_research"])
        self.assertFalse(result["persistent_mutation_performed"])

class V63LocalOutreachRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_runtime_plans_local_outreach_without_mutation(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
        })
        self.assertTrue(result["contact_window_open"])
        self.assertEqual(result["outreach_language"], "vi")
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertEqual(self.runtime.state, before)

class V63LocalContextResolutionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_runtime_plans_missing_timezone_and_holiday_resolution(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.plan_local_context_resolution({
            "account_id": "C500",
            "country_code": "US",
            "city": "Boston",
            "market_locale": "en-US",
            "holiday_calendar_status": "UNKNOWN",
        })
        kinds = {task["task_type"] for task in result["tasks"]}
        self.assertIn("RESOLVE_IANA_TIMEZONE", kinds)
        self.assertIn("VERIFY_LOCAL_BUSINESS_HOLIDAY", kinds)
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertEqual(self.runtime.state, before)

class V63SalesReadinessRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        from unified_runtime.capability_profile import build_capability_profile
        self.runtime._v63_capability_profiles = {
            "PVC": build_capability_profile({
                "capability_profile_id": "CAP-PVC-1",
                "version": "1",
                "product_profile_id": "PVC",
                "supported_variants": ["CELUKA"],
                "variant_capabilities": {
                    "CELUKA": {
                        "inherit_family_specs": False,
                        "supported_thickness_values_mm": [18],
                        "supported_sizes_mm": [[1220, 2440]],
                        "density_g_cm3": [0.40, 0.65],
                    }
                },
            })
        }

    def test_runtime_evaluates_sales_readiness_without_persistence(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.evaluate_sales_readiness({
            "opportunity": {
                "opportunity_id": "OPP-C500-PVC-PRIMARY",
                "account_id": "C500",
                "product_profile_id": "PVC",
                "product_variant": "CELUKA",
                "commercial_value_grade": "A",
                "lifecycle_stage": "QUALIFIED_TARGET",
            },
            "selected_route": {
                "route_id": "R1", "channel": "EMAIL", "owner_scope": "COMPANY",
                "verified": True, "route_eligible": True, "freshness": "CURRENT",
            },
            "local_context": {
                "now_utc": "2026-09-03T03:00:00+00:00",
                "timezone_name": "Asia/Ho_Chi_Minh",
                "timezone_confidence": "VERIFIED",
                "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
                "holiday_calendar_status": "VERIFIED",
                "market_locale": "vi-VN",
                "official_site_languages": ["vi"],
            },
            "product_demand": {
                "product_profile_id": "PVC", "product_variant": "CELUKA",
                "thickness_mm": 18, "size_mm": [1220, 2440], "density_g_cm3": 0.55,
            },
        })
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["sales_readiness"]["sales_readiness_state"], "OUTREACH_EXECUTION_READY")
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertEqual(self.runtime.state, before)

class V63CandidateResearchGateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_runtime_keeps_high_eiv_unresolved_candidate_in_research_pool(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.assess_candidate_researchability({
            "candidate_id": "CAN-D4-RUNTIME",
            "company_name": "Example Cabinet Works",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.75,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": True,
            "contact_readiness": "BLOCKED",
        })
        self.assertEqual(result["research_state"], "RESEARCH_ACTIVE")
        self.assertTrue(result["retain_in_candidate_pool"])
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertEqual(self.runtime.state, before)

class V63CandidateResearchQueueRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_runtime_ranks_high_eiv_d4_without_commercial_grade(self):
        before = copy.deepcopy(self.runtime.state)
        result = self.runtime.rank_candidate_research_queue({
            "candidates": [{
                "candidate_id": "CAN-D4-QUEUE",
                "company_name": "Example PVC Distributor",
                "product_profile_id": "PVC",
                "signal_tier": "D4",
                "eiv": 0.8,
                "canonical_status": "UNRESOLVED",
                "product_or_application_signal": True,
            }]
        })
        self.assertEqual(result["status"], "READY")
        self.assertGreater(result["candidates"][0]["research_priority"], 0)
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertEqual(self.runtime.state, before)
