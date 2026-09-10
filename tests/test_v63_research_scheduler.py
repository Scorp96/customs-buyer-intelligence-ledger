import unittest

from unified_runtime.research_scheduler import rank_research_opportunities


class V63ResearchSchedulerTests(unittest.TestCase):
    def _base(self, **overrides):
        row = {
            "opportunity_id": "OPP-1",
            "product_profile_id": "PVC",
            "commercial_value_grade": "A",
            "commercial_score": 90,
            "relative_class": "SAME_TIER",
            "market_acceptance": "M2",
            "eiv": 0.8,
            "outreach_readiness": "IDENTITY_ONLY",
            "source_coverage_complete": False,
        }
        row.update(overrides)
        return row

    def test_same_quality_pvc_ranks_above_acrylic_due_business_priority(self):
        pvc = self._base(opportunity_id="PVC", product_profile_id="PVC")
        acrylic = self._base(opportunity_id="ACR", product_profile_id="ACRYLIC_PMMA")
        ranked = rank_research_opportunities([acrylic, pvc])
        self.assertEqual(ranked[0]["opportunity_id"], "PVC")
        self.assertEqual(ranked[0]["commercial_value_grade"], "A")

    def test_stronger_acrylic_a_plus_can_outrank_pvc_bplus(self):
        acrylic = self._base(
            opportunity_id="ACR",
            product_profile_id="ACRYLIC_PMMA",
            commercial_value_grade="A+",
            commercial_score=97,
        )
        pvc = self._base(
            opportunity_id="PVC",
            product_profile_id="PVC",
            commercial_value_grade="B+",
            commercial_score=84,
        )
        ranked = rank_research_opportunities([pvc, acrylic])
        self.assertEqual(ranked[0]["opportunity_id"], "ACR")

    def test_high_value_contact_gap_increases_research_priority_without_changing_grade(self):
        missing = self._base(opportunity_id="MISSING", outreach_readiness="IDENTITY_ONLY")
        named = self._base(opportunity_id="READY", outreach_readiness="NAMED_ROUTE_READY")
        ranked = rank_research_opportunities([named, missing])
        self.assertEqual(ranked[0]["opportunity_id"], "MISSING")
        self.assertEqual(ranked[0]["commercial_value_grade"], "A")
        self.assertFalse(ranked[0]["commercial_grade_mutated"])

    def test_reject_relative_class_has_zero_research_priority(self):
        ranked = rank_research_opportunities([
            self._base(relative_class="REJECT")
        ])
        self.assertEqual(ranked[0]["research_priority"], 0.0)

    def test_unknown_commercial_grade_fails_closed(self):
        with self.assertRaises(ValueError):
            rank_research_opportunities([self._base(commercial_value_grade="GOLD")])


if __name__ == "__main__":
    unittest.main()

class V63SoftBudgetSchedulerTests(unittest.TestCase):
    def test_budget_exhaustion_does_not_hide_material_deferred_work(self):
        from unified_runtime.research_scheduler import schedule_research_work
        rows = [
            {
                "opportunity_id": "HIGH",
                "product_profile_id": "PVC",
                "commercial_value_grade": "A",
                "commercial_score": 92,
                "relative_class": "UPGRADE_TARGET",
                "market_acceptance": "M2",
                "eiv": 0.9,
                "outreach_readiness": "IDENTITY_ONLY",
                "source_coverage_complete": False,
                "estimated_cost_units": 2,
                "material": True,
            },
            {
                "opportunity_id": "NEXT",
                "product_profile_id": "PVC",
                "commercial_value_grade": "B+",
                "commercial_score": 85,
                "relative_class": "SAME_TIER_HIGH",
                "market_acceptance": "M2",
                "eiv": 0.8,
                "outreach_readiness": "IDENTITY_ONLY",
                "source_coverage_complete": False,
                "estimated_cost_units": 2,
                "material": True,
            },
        ]
        result = schedule_research_work(rows, budget_units=2)
        self.assertEqual(len(result["scheduled"]), 1)
        self.assertEqual(len(result["deferred_material"]), 1)
        self.assertEqual(result["resource_state"], "EXHAUSTED")
        self.assertEqual(result["research_action"], "CONTINUE_WHEN_RESOURCE_AVAILABLE")
        self.assertFalse(result["budget_exhaustion_closes_research"])
        self.assertFalse(result["research_complete"])

    def test_zero_budget_still_returns_ranked_material_work(self):
        from unified_runtime.research_scheduler import schedule_research_work
        row = {
            "opportunity_id": "HIGH",
            "product_profile_id": "PVC",
            "commercial_value_grade": "A+",
            "commercial_score": 97,
            "relative_class": "UPGRADE_TARGET",
            "market_acceptance": "M3",
            "eiv": 0.95,
            "outreach_readiness": "IDENTITY_ONLY",
            "source_coverage_complete": False,
            "estimated_cost_units": 1,
            "material": True,
        }
        result = schedule_research_work([row], budget_units=0)
        self.assertEqual(result["scheduled"], [])
        self.assertEqual(result["deferred_material"][0]["opportunity_id"], "HIGH")
        self.assertFalse(result["research_complete"])

    def test_nonmaterial_low_priority_work_can_be_deferred_without_forcing_continue_action(self):
        from unified_runtime.research_scheduler import schedule_research_work
        row = {
            "opportunity_id": "LOW",
            "product_profile_id": "PVC",
            "commercial_value_grade": "C",
            "commercial_score": 55,
            "relative_class": "SECONDARY",
            "market_acceptance": "M0",
            "eiv": 0.1,
            "outreach_readiness": "IDENTITY_ONLY",
            "source_coverage_complete": False,
            "estimated_cost_units": 2,
            "material": False,
        }
        result = schedule_research_work([row], budget_units=0)
        self.assertEqual(result["deferred_material"], [])
        self.assertEqual(result["research_action"], "NO_MATERIAL_DEFERRED_WORK")
