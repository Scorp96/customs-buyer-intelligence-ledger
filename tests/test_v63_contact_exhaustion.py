import unittest

from unified_runtime.contact_exhaustion import (
    contact_exhaustion_complete,
    named_role_relevant,
    plan_contact_exhaustion,
)


class V63ContactExhaustionTests(unittest.TestCase):
    def test_a_plus_without_contact_stays_commercially_a_plus(self):
        opp = {
            "commercial_value_grade": "A+",
            "outreach_readiness": "IDENTITY_ONLY",
            "product_profile_id": "PVC",
            "buyer_archetypes": ["SIGN_MATERIAL_DISTRIBUTOR"],
        }
        plan = plan_contact_exhaustion(opp, {})
        self.assertEqual(opp["commercial_value_grade"], "A+")
        self.assertTrue(plan["company_route_required"])
        self.assertTrue(plan["named_route_exhaustive"])

    def test_bplus_requires_company_route_but_named_is_eiv_driven(self):
        opp = {
            "commercial_value_grade": "B+",
            "outreach_readiness": "IDENTITY_ONLY",
            "product_profile_id": "PVC",
            "buyer_archetypes": ["CABINET_MANUFACTURER"],
        }
        plan = plan_contact_exhaustion(opp, {})
        self.assertTrue(plan["company_route_required"])
        self.assertEqual(plan["named_route_policy"], "EIV_DRIVEN")

    def test_spc_manager_is_not_automatically_pvc_named_route(self):
        self.assertFalse(
            named_role_relevant(
                "PVC",
                ["SIGN_MATERIAL_DISTRIBUTOR"],
                "SPC Flooring Category Manager",
            )
        )

    def test_procurement_role_is_relevant_for_pvc_buyer(self):
        self.assertTrue(
            named_role_relevant(
                "PVC",
                ["CABINET_MANUFACTURER"],
                "Purchasing Manager",
            )
        )

    def test_company_route_ready_is_terminal_for_company_requirement(self):
        self.assertTrue(contact_exhaustion_complete({
            "company_route_status": "COMPANY_ROUTE_READY",
            "named_route_status": "IDENTITY_ONLY",
            "applicable_material_source_receipts": [],
        }))

    def test_blocked_receipts_do_not_complete_exhaustion(self):
        self.assertFalse(contact_exhaustion_complete({
            "company_route_status": "IDENTITY_ONLY",
            "named_route_status": "IDENTITY_ONLY",
            "applicable_material_source_receipts": [
                {"source_family": "official_contact", "result": "BLOCKED"},
                {"source_family": "linkedin_people", "result": "NEGATIVE_EXHAUSTED"},
            ],
        }))

    def test_all_material_sources_terminal_can_complete(self):
        self.assertTrue(contact_exhaustion_complete({
            "company_route_status": "IDENTITY_ONLY",
            "named_route_status": "IDENTITY_ONLY",
            "applicable_material_source_receipts": [
                {"source_family": "official_contact", "result": "NEGATIVE_EXHAUSTED"},
                {"source_family": "linkedin_people", "result": "NOT_APPLICABLE_JUSTIFIED"},
            ],
        }))


if __name__ == "__main__":
    unittest.main()

class V63RouteFreshnessReadinessTests(unittest.TestCase):
    def test_stale_named_route_downgrades_to_current_company_route(self):
        from unified_runtime.contact_exhaustion import recompute_outreach_readiness
        result = recompute_outreach_readiness({
            "company_routes": [{
                "verified": True,
                "route_eligible": True,
                "owner_scope": "ACCOUNT",
                "freshness": "CURRENT_CONFIRMED",
            }],
            "named_routes": [{
                "verified": True,
                "route_eligible": True,
                "current_company_association": True,
                "role_relevant": True,
                "freshness": "STALE",
            }],
        })
        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertTrue(result["readiness_can_regress_when_routes_stale"])

    def test_all_routes_stale_falls_back_to_identity_only(self):
        from unified_runtime.contact_exhaustion import recompute_outreach_readiness
        result = recompute_outreach_readiness({
            "company_routes": [{
                "verified": True,
                "route_eligible": True,
                "owner_scope": "ACCOUNT",
                "freshness": "STALE",
            }],
            "named_routes": [],
        })
        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")

    def test_current_named_route_requires_identity_bridge(self):
        from unified_runtime.contact_exhaustion import recompute_outreach_readiness
        result = recompute_outreach_readiness({
            "company_routes": [],
            "named_routes": [{
                "verified": True,
                "route_eligible": True,
                "current_company_association": False,
                "role_relevant": True,
                "freshness": "CURRENT",
            }],
        })
        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")

    def test_current_named_route_can_be_named_ready_when_bridge_complete(self):
        from unified_runtime.contact_exhaustion import recompute_outreach_readiness
        result = recompute_outreach_readiness({
            "company_routes": [],
            "named_routes": [{
                "verified": True,
                "route_eligible": True,
                "current_company_association": True,
                "role_relevant": True,
                "freshness": "RECENT",
            }],
        })
        self.assertEqual(result["outreach_readiness"], "NAMED_ROUTE_READY")
        self.assertFalse(result["commercial_grade_mutated"])
