"""Synthetic compatibility tests. No production contacts or customer data."""
import unittest

from unified_runtime.route_reuse import reuse_route_for_opportunity


TARGET = {"account_id": "C500", "product_profile_id": "PVC"}


def normalized_canonical_route(**kwargs):
    route = {
        "route_id": "SYN-CANONICAL-ROUTE",
        "owner_scope": "ACCOUNT",
        "route_scope": "BUYER_DIRECT",
        "owner_entity_id": "C500",
        "owned_by_account": True,
        "verified": True,
        "route_eligible": True,
        "freshness": "CURRENT",
        "guessed": False,
    }
    route.update(kwargs)
    return route


class CanonicalRouteOwnerCompatibility(unittest.TestCase):
    def test_canonical_owner_entity_id_without_other_alias_is_accepted(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(), TARGET)
        self.assertTrue(r["route_reusable"])
        self.assertEqual(r["reuse_scope"], "ACCOUNT_LEVEL_COMPANY_ROUTE")
        self.assertFalse(r["route_proves_procurement"])

    def test_canonical_cross_owner_is_blocked(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(owner_entity_id="C600"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_OWNER_MISMATCH", r["blockers"])

    def test_canonical_owner_conflicts_with_account_id_alias(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(account_id="C600"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_CONFLICT", r["blockers"])

    def test_canonical_owner_conflicts_with_owner_account_id_alias(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(owner_account_id="C600"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_CONFLICT", r["blockers"])

    def test_canonical_owner_without_owned_by_account_is_untrusted(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(owned_by_account=None), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_MISSING", r["blockers"])

    def test_explicit_unowned_flag_blocks_even_if_account_id_matches(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(account_id="C500", owned_by_account=False), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_OWNERSHIP_UNVERIFIED", r["blockers"])

    def test_non_buyer_direct_route_scope_not_auth_for_account_owner(self):
        r = reuse_route_for_opportunity(normalized_canonical_route(route_scope="SUPPLIER_REFERRAL"), TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_MISSING", r["blockers"])

    def test_untransformed_live_canonical_route_does_not_bypass_legacy_gates(self):
        route = {"kind": "EMAIL", "owner_entity_id": "C500", "route_scope": "BUYER_DIRECT", "owned_by_account": True, "verified": True, "current": True}
        r = reuse_route_for_opportunity(route, TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_NOT_ELIGIBLE", r["blockers"])
        self.assertIn("ROUTE_NOT_CURRENT", r["blockers"])
        self.assertIn("ROUTE_OWNER_SCOPE_NOT_REUSABLE", r["blockers"])

    def test_person_owner_entity_id_is_not_confused_with_account_identity(self):
        route = normalized_canonical_route(owner_scope="PERSON", owner_entity_id="P999", product_relevance=["PVC"], current_company_association=True, role_relevant=True)
        r = reuse_route_for_opportunity(route, TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_BINDING_MISSING", r["blockers"])

    def test_person_with_explicit_account_binding_still_requires_role(self):
        route = normalized_canonical_route(owner_scope="PERSON", owner_entity_id="P999", account_id="C500", role_relevant=False, current_company_association=True, product_relevance=["PVC"])
        r = reuse_route_for_opportunity(route, TARGET)
        self.assertFalse(r["route_reusable"])
        self.assertIn("NAMED_ROUTE_ROLE_RELEVANCE_UNPROVEN", r["blockers"])

if __name__ == "__main__":
    unittest.main()
