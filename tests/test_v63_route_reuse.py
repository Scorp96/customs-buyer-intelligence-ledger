import unittest


class V63RouteReuseTests(unittest.TestCase):
    def test_verified_account_company_route_can_be_reused_without_proving_product_interest(self):
        from unified_runtime.route_reuse import reuse_route_for_opportunity
        result = reuse_route_for_opportunity({
            "route_id": "R-C500-1",
            "owner_scope": "ACCOUNT",
            "verified": True,
            "route_eligible": True,
            "freshness": "CURRENT_CONFIRMED",
            "kind": "EMAIL",
        }, {
            "account_id": "C500",
            "product_profile_id": "WPC",
        })
        self.assertTrue(result["route_reusable"])
        self.assertEqual(result["reuse_scope"], "ACCOUNT_LEVEL_COMPANY_ROUTE")
        self.assertFalse(result["route_proves_product_interest"])

    def test_stale_company_route_is_not_reusable(self):
        from unified_runtime.route_reuse import reuse_route_for_opportunity
        result = reuse_route_for_opportunity({
            "route_id": "R-C500-1",
            "owner_scope": "ACCOUNT",
            "verified": True,
            "route_eligible": True,
            "freshness": "STALE",
        }, {"account_id": "C500", "product_profile_id": "PVC"})
        self.assertFalse(result["route_reusable"])
        self.assertIn("ROUTE_NOT_CURRENT", result["blockers"])

    def test_named_route_requires_product_or_general_procurement_relevance(self):
        from unified_runtime.route_reuse import reuse_route_for_opportunity
        result = reuse_route_for_opportunity({
            "route_id": "R-PERSON-1",
            "owner_scope": "PERSON",
            "verified": True,
            "route_eligible": True,
            "freshness": "CURRENT",
            "current_company_association": True,
            "role_relevant": True,
            "product_relevance": ["SPC"],
        }, {"account_id": "C500", "product_profile_id": "PVC"})
        self.assertFalse(result["route_reusable"])
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_UNPROVEN", result["blockers"])

    def test_general_procurement_named_route_can_be_reused_but_still_does_not_prove_interest(self):
        from unified_runtime.route_reuse import reuse_route_for_opportunity
        result = reuse_route_for_opportunity({
            "route_id": "R-PERSON-1",
            "owner_scope": "PERSON",
            "verified": True,
            "route_eligible": True,
            "freshness": "RECENT",
            "current_company_association": True,
            "role_relevant": True,
            "product_relevance": ["GENERAL_PROCUREMENT"],
        }, {"account_id": "C500", "product_profile_id": "PVC"})
        self.assertTrue(result["route_reusable"])
        self.assertEqual(result["reuse_scope"], "NAMED_ROUTE_GENERAL_PROCUREMENT")
        self.assertFalse(result["route_proves_product_interest"])
