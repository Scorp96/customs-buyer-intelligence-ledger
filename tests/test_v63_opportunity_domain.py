import unittest

from unified_runtime.opportunity_domain import (
    build_opportunity_id,
    relative_opportunity,
    validate_product_opportunity,
)


class V63OpportunityDomainTests(unittest.TestCase):
    def test_same_account_can_hold_independent_product_opportunities(self):
        pvc = build_opportunity_id("C500", "PVC")
        acrylic = build_opportunity_id("C500", "ACRYLIC_PMMA")
        self.assertNotEqual(pvc, acrylic)

    def test_cross_product_grade_is_not_inherited(self):
        pvc = validate_product_opportunity({
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "commercial_value_grade": "A+",
        })
        acrylic = validate_product_opportunity({
            "opportunity_id": "OPP-C500-ACRYLIC_PMMA-PRIMARY",
            "account_id": "C500",
            "product_profile_id": "ACRYLIC_PMMA",
            "commercial_value_grade": "B",
        })
        self.assertEqual(pvc["commercial_value_grade"], "A+")
        self.assertEqual(acrylic["commercial_value_grade"], "B")

    def test_relative_upgrade_target(self):
        result = relative_opportunity(84.0, 92.0, "B+", "A")
        self.assertEqual(result["relative_class"], "UPGRADE_TARGET")
        self.assertEqual(result["relative_score_delta"], 8.0)

    def test_strategic_one_tier_lower_is_not_rejected(self):
        result = relative_opportunity(91.0, 84.0, "A", "B+", strategic=True)
        self.assertEqual(result["relative_class"], "STRATEGIC_LOWER")

    def test_invalid_product_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_product_opportunity({
                "opportunity_id": "OPP-C500-UNKNOWN-PRIMARY",
                "account_id": "C500",
                "product_profile_id": "UNKNOWN",
                "commercial_value_grade": "A",
            })

    def test_opportunity_id_rejects_empty_identity(self):
        with self.assertRaises(ValueError):
            build_opportunity_id("", "PVC")


if __name__ == "__main__":
    unittest.main()

class V63OpportunityProfilePinningTests(unittest.TestCase):
    def test_validation_pins_exact_product_profile_version_and_sha(self):
        from unified_runtime.product_profiles import get_product_profile
        profile = get_product_profile("PVC")
        result = validate_product_opportunity({
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "commercial_value_grade": "A",
        })
        self.assertEqual(result["product_profile_version"], profile["profile_version"])
        self.assertEqual(result["product_profile_sha256"], profile["profile_sha256"])

    def test_mismatched_supplied_profile_pin_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_product_opportunity({
                "opportunity_id": "OPP-C500-PVC-PRIMARY",
                "account_id": "C500",
                "product_profile_id": "PVC",
                "product_profile_version": "999",
            })

    def test_lifecycle_transition_is_monotonic(self):
        from unified_runtime.opportunity_domain import validate_lifecycle_transition
        result = validate_lifecycle_transition("QUALIFIED_TARGET", "CONTACT_EXHAUSTION")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["direction"], "FORWARD")

    def test_lifecycle_backward_transition_fails_closed(self):
        from unified_runtime.opportunity_domain import validate_lifecycle_transition
        with self.assertRaises(ValueError):
            validate_lifecycle_transition("SALES_READY", "QUALIFIED_TARGET")

    def test_lifecycle_same_stage_is_idempotent(self):
        from unified_runtime.opportunity_domain import validate_lifecycle_transition
        result = validate_lifecycle_transition("ANCHOR_ELIGIBLE", "ANCHOR_ELIGIBLE")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["direction"], "IDEMPOTENT")
