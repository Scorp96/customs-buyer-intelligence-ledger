"""Synthetic, read-only domain tests for explicit route-account owner binding."""
import unittest
from unified_runtime.route_reuse import reuse_route_for_opportunity


TARGET = {"account_id": "C500", "product_profile_id": "PVC"}

def company_route(**overrides):
    route = {"route_id": "R-C500-1", "owner_scope": "ACCOUNT",
             "verified": True, "route_eligible": True,
             "guessed": False, "freshness": "CURRENT"}
    route.update(overrides)
    return route

class RouteAccountBindingRegressions(unittest.TestCase):
    def test_cross_account_verified_route_is_rejected(self):
        r = reuse_route_for_opportunity(company_route(account_id="C600"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_OWNER_MISMATCH", r["blockers"])

    def test_missing_route_account_identity_fails_closed(self):
        r = reuse_route_for_opportunity(company_route(), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_MISSING", r["blockers"])

    def test_person_route_without_current_account_identity_fails_closed(self):
        route = company_route(owner_scope="PERSON", current_company_association=True,
                              role_relevant=True, product_relevance=["GENERAL_PROCUREMENT"])
        r = reuse_route_for_opportunity(route, TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_MISSING", r["blockers"])

    def test_conflicting_claimed_account_fields_fail_closed(self):
        r = reuse_route_for_opportunity(company_route(account_id="C500", owner_account_id="C600"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_CONFLICT", r["blockers"])

    def test_missing_opportunity_account_fails_closed(self):
        r = reuse_route_for_opportunity(company_route(account_id="C500"), {"product_profile_id":"PVC"})
        self.assertFalse(r["route_reusable"])
        self.assertIn("OPPORTUNITY_ACCOUNT_ID_MISSING", r["blockers"])

    def test_route_id_looks_like_target_but_owner_is_foreign(self):
        r = reuse_route_for_opportunity(company_route(route_id="R-C500-1", account_id="C777"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_OWNER_MISMATCH", r["blockers"])

    def test_same_account_company_route_stays_eligible(self):
        r = reuse_route_for_opportunity(company_route(account_id="C500"), TARGET)
        self.assertTrue(r["route_reusable"])
        self.assertFalse(r["route_proves_procurement"])
        self.assertFalse(r["route_proves_product_interest"])

    def test_same_account_named_general_procurement_stays_eligible(self):
        route = company_route(account_id="C500", owner_scope="PERSON",
                              current_company_association=True, role_relevant=True,
                              product_relevance=["GENERAL_PROCUREMENT"])
        r = reuse_route_for_opportunity(route, TARGET)
        self.assertTrue(r["route_reusable"])
        self.assertEqual(r["reuse_scope"],"NAMED_ROUTE_GENERAL_PROCUREMENT")

    def test_same_account_named_irrelevant_product_rejected(self):
        route = company_route(account_id="C500", owner_scope="PERSON",
                              current_company_association=True, role_relevant=True,
                              product_relevance=["WPC"])
        r = reuse_route_for_opportunity(route, TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_UNPROVEN",r["blockers"])

    def test_stale_and_guessed_route_rejected_even_when_account_matches(self):
        route = company_route(account_id="C500",guessed=True,freshness="STALE")
        r = reuse_route_for_opportunity(route,TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("GUESSED_ROUTE_FORBIDDEN",r["blockers"])
        self.assertIn("ROUTE_NOT_CURRENT",r["blockers"])

    def test_explicit_owner_account_id_alone_can_bind(self):
        r = reuse_route_for_opportunity(company_route(owner_account_id="C500"), TARGET)
        self.assertTrue(r["route_reusable"])

if __name__ == '__main__':
    unittest.main()
