import unittest

from unified_runtime.candidate_anchor import (
    build_candidate_discovery,
    build_cross_sell_hypotheses,
    evaluate_anchor_eligibility,
    project_anchor_promotion,
)


class V63CandidateAnchorTests(unittest.TestCase):
    def test_candidate_never_inherits_anchor_procurement_facts(self):
        candidate = build_candidate_discovery({
            "candidate_id": "CAN-1",
            "discovered_from_anchor_id": "DA-1",
            "branch_group": "APPLICATION_GRAPH",
            "branch": "downstream_manufacturer",
            "company_name": "Example Cabinet Co",
            "product_profile_id": "PVC",
        })
        self.assertFalse(candidate["inherited_anchor_facts"])
        self.assertEqual(candidate["product_evidence_ids"], [])
        self.assertEqual(candidate["procurement_evidence_ids"], [])
        self.assertEqual(candidate["stage"], "DISCOVERED")

    def test_cross_sell_creates_hypothesis_without_evidence_inheritance(self):
        hypotheses = build_cross_sell_hypotheses({
            "account_id": "C500",
            "source_opportunity_id": "OPP-C500-PVC-PRIMARY",
            "source_product_profile_id": "PVC",
            "source_product_evidence_ids": ["E-PVC-1"],
        })
        by_profile = {row["product_profile_id"]: row for row in hypotheses}
        self.assertIn("ACRYLIC_PMMA", by_profile)
        self.assertEqual(by_profile["ACRYLIC_PMMA"]["state"], "CROSS_SELL_HYPOTHESIS")
        self.assertEqual(by_profile["ACRYLIC_PMMA"]["product_evidence_ids"], [])
        self.assertFalse(by_profile["ACRYLIC_PMMA"]["inherits_source_product_evidence"])

    def test_a_opportunity_with_novelty_is_anchor_eligible_without_contact(self):
        result = evaluate_anchor_eligibility({
            "commercial_value_grade": "A",
            "canonical_status": "CONFIRMED",
            "commercial_evidence_bound": True,
            "novelty_signals": ["NEW_MARKET_CELL"],
            "outreach_readiness": "IDENTITY_ONLY",
        })
        self.assertTrue(result["anchor_eligible"])
        self.assertFalse(result["contact_readiness_is_gate"])

    def test_bplus_without_material_novelty_is_not_anchor_eligible(self):
        result = evaluate_anchor_eligibility({
            "commercial_value_grade": "B+",
            "canonical_status": "CONFIRMED",
            "commercial_evidence_bound": True,
            "novelty_signals": [],
        })
        self.assertFalse(result["anchor_eligible"])
        self.assertIn("BPLUS_REQUIRES_MATERIAL_NOVELTY", result["blockers"])

    def test_bplus_with_supplier_network_novelty_can_be_anchor_eligible(self):
        result = evaluate_anchor_eligibility({
            "commercial_value_grade": "B+",
            "canonical_status": "CONFIRMED",
            "commercial_evidence_bound": True,
            "novelty_signals": ["NEW_SUPPLIER_NETWORK"],
        })
        self.assertTrue(result["anchor_eligible"])

    def test_ambiguous_canonical_identity_blocks_anchor(self):
        result = evaluate_anchor_eligibility({
            "commercial_value_grade": "A+",
            "canonical_status": "AMBIGUOUS",
            "commercial_evidence_bound": True,
            "novelty_signals": ["NEW_MARKET_CELL"],
        })
        self.assertFalse(result["anchor_eligible"])
        self.assertIn("CANONICAL_ACCOUNT_NOT_CONFIRMED", result["blockers"])

    def test_promotion_requires_cycle_dedup(self):
        with self.assertRaises(ValueError):
            project_anchor_promotion({
                "opportunity_id": "OPP-C500-PVC-PRIMARY",
                "anchor_eligibility": {"anchor_eligible": True},
                "cycle_dedup_complete": False,
            })


if __name__ == "__main__":
    unittest.main()

class V63NewCanonicalAccountAnchorEligibilityTests(unittest.TestCase):
    def test_production_created_canonical_account_can_be_anchor_eligible(self):
        from unified_runtime.candidate_anchor import evaluate_anchor_eligibility
        result = evaluate_anchor_eligibility({
            "commercial_value_grade": "A",
            "canonical_status": "CREATED",
            "commercial_evidence_bound": True,
            "novelty_signals": ["NEW_MARKET_CELL"],
        })
        self.assertTrue(result["anchor_eligible"])
        self.assertNotIn("CANONICAL_ACCOUNT_NOT_CONFIRMED", result["blockers"])
