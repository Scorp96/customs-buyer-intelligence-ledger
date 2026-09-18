import unittest

from unified_runtime.expansion_planner import (
    compute_expansion_priority,
    evaluate_expansion_saturation,
    plan_expansion,
)


def valid_context():
    return {
        "product_profile_id": "PVC",
        "market_acceptance": "M3",
        "anchor_grade": "B+",
        "anchor_score": 84.0,
        "applications": ["SIGNAGE"],
        "buyer_archetypes": ["SIGN_MAKER", "SIGN_MATERIAL_DISTRIBUTOR"],
        "geography": "US-MA",
    }


class V63ExpansionPlannerTests(unittest.TestCase):
    def test_all_six_branch_groups_are_planned(self):
        result = plan_expansion(valid_context())
        self.assertEqual(
            set(result["branch_groups"]),
            {
                "TRADE_GRAPH",
                "APPLICATION_GRAPH",
                "CHANNEL_GRAPH",
                "MARKET_GRAPH",
                "COMPETITIVE_GRAPH",
                "CROSS_SELL_GRAPH",
            },
        )

    def test_bplus_candidate_can_remain_material_relative_to_anchor(self):
        result = compute_expansion_priority({
            "commercial_grade": "B+",
            "commercial_score": 86.0,
            "relative_class": "SAME_TIER_HIGH",
            "eiv": 0.8,
            "product_profile_id": "PVC",
        })
        self.assertGreater(result["priority"], 0)
        self.assertEqual(result["commercial_grade"], "B+")

    def test_fixed_a_threshold_does_not_reject_v63_candidate(self):
        plan = plan_expansion(valid_context())
        self.assertNotEqual(plan["policy"].get("minimum_target_fit"), "A")
        self.assertEqual(plan["policy"]["qualification_strategy"], "RELATIVE_TO_ANCHOR")

    def test_pvc_priority_changes_queue_order_not_commercial_score(self):
        pvc = compute_expansion_priority({
            "commercial_grade": "A",
            "commercial_score": 90.0,
            "relative_class": "SAME_TIER",
            "eiv": 0.7,
            "product_profile_id": "PVC",
        })
        acrylic = compute_expansion_priority({
            "commercial_grade": "A",
            "commercial_score": 90.0,
            "relative_class": "SAME_TIER",
            "eiv": 0.7,
            "product_profile_id": "ACRYLIC_PMMA",
        })
        self.assertGreater(pvc["priority"], acrylic["priority"])
        self.assertEqual(pvc["commercial_score"], 90.0)
        self.assertEqual(acrylic["commercial_score"], 90.0)

    def test_open_high_eiv_branch_blocks_expansion_saturation(self):
        result = evaluate_expansion_saturation({
            "remaining_material_work": [{"branch_group": "APPLICATION_GRAPH", "eiv": 0.7}],
            "undispositioned_high_value_candidates": [],
            "unexpanded_promoted_anchors": [],
            "open_high_yield_pivots": [],
            "cycle_dedup_complete": True,
        })
        self.assertFalse(result["expansion_saturated"])

    def test_all_material_work_closed_can_saturate(self):
        result = evaluate_expansion_saturation({
            "remaining_material_work": [],
            "undispositioned_high_value_candidates": [],
            "unexpanded_promoted_anchors": [],
            "open_high_yield_pivots": [],
            "cycle_dedup_complete": True,
        })
        self.assertTrue(result["expansion_saturated"])

    def test_m1_does_not_start_dense_market_expansion(self):
        ctx = valid_context()
        ctx["market_acceptance"] = "M1"
        result = plan_expansion(ctx)
        self.assertNotIn("industrial_cluster", result["branches"]["MARKET_GRAPH"])
        self.assertIn("regional_peer", result["branches"]["MARKET_GRAPH"])


if __name__ == "__main__":
    unittest.main()

class V63DiscoveryQueryTests(unittest.TestCase):
    def test_query_generation_combines_product_application_archetype_and_geography(self):
        from unified_runtime.expansion_planner import generate_discovery_queries
        result = generate_discovery_queries({
            "product_profile_id": "PVC",
            "product_variant": "FREE_FOAM",
            "applications": ["SIGNAGE"],
            "buyer_archetypes": ["SIGN_MAKER"],
            "geography": "Mexico",
            "local_language_terms": ["fabricante de letreros", "materiales para anuncios"],
            "limit": 20,
        })
        joined = "\n".join(row["query"] for row in result["queries"])
        self.assertIn("Mexico", joined)
        self.assertIn("PVC", joined)
        self.assertTrue("SIGN_MAKER" in joined or "sign" in joined.lower())
        self.assertIn("fabricante de letreros", joined)

    def test_query_plan_never_counts_as_execution_or_source_completion(self):
        from unified_runtime.expansion_planner import generate_discovery_queries
        result = generate_discovery_queries({
            "product_profile_id": "PVC",
            "applications": ["CABINETRY"],
            "buyer_archetypes": ["CABINET_MANUFACTURER"],
            "geography": "Vietnam",
            "limit": 5,
        })
        self.assertFalse(result["planning_is_execution_proof"])
        self.assertFalse(result["source_coverage_complete"])
        self.assertTrue(all(not q["search_execution_performed"] for q in result["queries"]))

    def test_truncated_query_plan_is_explicit(self):
        from unified_runtime.expansion_planner import generate_discovery_queries
        result = generate_discovery_queries({
            "product_profile_id": "PVC",
            "applications": ["SIGNAGE", "CABINETRY", "PARTITION_WET_AREA"],
            "buyer_archetypes": ["SIGN_MAKER", "CABINET_MANUFACTURER", "PARTITION_MANUFACTURER"],
            "geography": "United States",
            "local_language_terms": ["PVC sheet distributor", "building materials"],
            "limit": 2,
        })
        self.assertTrue(result["truncated"])
        self.assertEqual(result["returned_count"], 2)

class V63ArchetypePriorityQueryTests(unittest.TestCase):
    def test_query_generation_applies_buyer_archetype_discovery_priority(self):
        from unified_runtime.expansion_planner import generate_discovery_queries
        result = generate_discovery_queries({
            "product_profile_id": "PVC",
            "product_variant": "FREE_FOAM",
            "applications": ["SIGNAGE"],
            "buyer_archetypes": ["SIGN_MAKER", "SIGN_MATERIAL_DISTRIBUTOR"],
            "geography": "Mexico",
            "limit": 20,
        })
        self.assertTrue(result["archetype_priority_applied"])
        self.assertEqual(result["ordered_buyer_archetypes"][0], "SIGN_MATERIAL_DISTRIBUTOR")
        self.assertIn("SIGN MATERIAL DISTRIBUTOR", result["queries"][0]["query"].upper())

class V63HighRecallSaturationTests(unittest.TestCase):
    def test_unresolved_high_eiv_discovery_candidate_blocks_saturation(self):
        result = evaluate_expansion_saturation({
            "remaining_material_work": [],
            "undispositioned_high_value_candidates": [],
            "unresolved_research_candidates": [
                {"candidate_id": "CAN-D4-1", "signal_tier": "D4", "eiv": 0.68, "research_state": "RESEARCH_ACTIVE"}
            ],
            "unexpanded_promoted_anchors": [],
            "open_high_yield_pivots": [],
            "cycle_dedup_complete": True,
        })
        self.assertFalse(result["expansion_saturated"])
        self.assertIn("UNRESOLVED_RESEARCH_CANDIDATES", result["blockers"])
        self.assertEqual(result["unresolved_research_candidate_count"], 1)

    def test_zero_eiv_deferred_candidate_does_not_block_saturation(self):
        result = evaluate_expansion_saturation({
            "remaining_material_work": [],
            "undispositioned_high_value_candidates": [],
            "unresolved_research_candidates": [
                {"candidate_id": "CAN-DEFER", "signal_tier": "D4", "eiv": 0.0, "research_state": "DEFERRED_LOW_EIV"}
            ],
            "unexpanded_promoted_anchors": [],
            "open_high_yield_pivots": [],
            "cycle_dedup_complete": True,
        })
        self.assertTrue(result["expansion_saturated"])
        self.assertEqual(result["unresolved_research_candidate_count"], 0)

    def test_proven_rejected_candidate_does_not_block_saturation(self):
        result = evaluate_expansion_saturation({
            "remaining_material_work": [],
            "undispositioned_high_value_candidates": [],
            "unresolved_research_candidates": [
                {"candidate_id": "CAN-REJECT", "signal_tier": "D4", "eiv": 0.9, "research_state": "REJECTED_PROVEN"}
            ],
            "unexpanded_promoted_anchors": [],
            "open_high_yield_pivots": [],
            "cycle_dedup_complete": True,
        })
        self.assertTrue(result["expansion_saturated"])
