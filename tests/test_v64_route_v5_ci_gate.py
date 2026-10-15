"""Isolated V5 route-owner and input-type release gate. No production data."""
import unittest

from unified_runtime.route_reuse import reuse_route_for_opportunity

A = "SYNTHETIC-A"
B = "SYNTHETIC-B"
OPPORTUNITY = {"account_id": A, "product_profile_id": "PVC"}


def company(**updates):
    route = {
        "route_id": "SYNTHETIC-COMPANY-ROUTE",
        "owner_scope": "ACCOUNT",
        "account_id": A,
        "verified": True,
        "route_eligible": True,
        "guessed": False,
        "freshness": "CURRENT",
    }
    route.update(updates)
    return route


def person(**updates):
    route = company(
        owner_scope="PERSON",
        current_company_association=True,
        role_relevant=True,
        product_relevance=["GENERAL_PROCUREMENT"],
    )
    route.update(updates)
    return route


class RouteV5IsolatedCIGate(unittest.TestCase):
    def result(self, route):
        return reuse_route_for_opportunity(route, OPPORTUNITY)

    def test_valid_company_route(self):
        self.assertTrue(self.result(company())["route_reusable"])

    def test_cross_owner_rejected(self):
        r = self.result(company(account_id=B))
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_OWNER_MISMATCH", r["blockers"])

    def test_missing_account_binding_rejected(self):
        r = company()
        r.pop("account_id")
        self.assertIn("ROUTE_ACCOUNT_BINDING_MISSING", self.result(r)["blockers"])

    def test_conflicting_account_bindings_rejected(self):
        r = self.result(company(owner_account_id=B))
        self.assertIn("ROUTE_ACCOUNT_BINDING_CONFLICT", r["blockers"])

    def test_verified_string_false_rejected(self):
        self.assertIn("ROUTE_NOT_VERIFIED", self.result(company(verified="false"))["blockers"])

    def test_route_eligible_int_rejected(self):
        self.assertIn("ROUTE_NOT_ELIGIBLE", self.result(company(route_eligible=1))["blockers"])

    def test_valid_person_route(self):
        r = self.result(person())
        self.assertTrue(r["route_reusable"])
        self.assertFalse(r["route_proves_procurement"])

    def test_person_association_string_false_rejected(self):
        r = self.result(person(current_company_association="false"))
        self.assertIn("NAMED_ROUTE_COMPANY_ASSOCIATION_UNPROVEN", r["blockers"])

    def test_person_role_int_rejected(self):
        r = self.result(person(role_relevant=1))
        self.assertIn("NAMED_ROUTE_ROLE_RELEVANCE_UNPROVEN", r["blockers"])

    def test_person_relevance_null_rejected_without_crash(self):
        r = self.result(person(product_relevance=None))
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED", r["blockers"])

    def test_person_relevance_dict_rejected(self):
        r = self.result(person(product_relevance={"GENERAL_PROCUREMENT": True}))
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED", r["blockers"])

    def test_person_relevance_numeric_rejected(self):
        r = self.result(person(product_relevance=1))
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED", r["blockers"])

    def test_person_relevance_mixed_array_rejected(self):
        r = self.result(person(product_relevance=["GENERAL_PROCUREMENT", None]))
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED", r["blockers"])

    def test_canonical_company_owner_allowed(self):
        r = company(route_scope="BUYER_DIRECT", owned_by_account=True, owner_entity_id=A)
        self.assertTrue(self.result(r)["route_reusable"])

    def test_canonical_cross_account_owner_rejected(self):
        r = company(route_scope="BUYER_DIRECT", owned_by_account=True, owner_entity_id=B)
        self.assertIn("ROUTE_ACCOUNT_BINDING_CONFLICT", self.result(r)["blockers"])

    def test_fake_canonical_flag_rejected(self):
        r = company(route_scope="BUYER_DIRECT", owned_by_account="true", owner_entity_id=A)
        self.assertIn("ROUTE_ACCOUNT_OWNERSHIP_UNVERIFIED", self.result(r)["blockers"])


if __name__ == "__main__":
    unittest.main()
