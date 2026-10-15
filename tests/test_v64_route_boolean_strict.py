import unittest
from unified_runtime.route_reuse import reuse_route_for_opportunity

OPP = {"account_id": "C500", "product_profile_id": "PVC"}
COMPANY = {"route_id": "SYNTHETIC-BOOL-01", "owner_scope": "ACCOUNT", "account_id": "C500",
           "verified": True, "route_eligible": True, "guessed": False, "freshness": "CURRENT"}
NAMED = {**COMPANY, "owner_scope": "PERSON", "current_company_association": True,
         "role_relevant": True, "product_relevance": ["GENERAL_PROCUREMENT"]}

class StrictRouteBooleanTypes(unittest.TestCase):
    def test_control_same_account_company_still_accepted(self):
        self.assertTrue(reuse_route_for_opportunity(COMPANY, OPP)["route_reusable"])
    def test_control_same_account_named_still_accepted(self):
        self.assertTrue(reuse_route_for_opportunity(NAMED, OPP)["route_reusable"])
    def test_string_false_verified_rejected(self):
        x=reuse_route_for_opportunity({**COMPANY,"verified":"false"},OPP)
        self.assertFalse(x["route_reusable"])
        self.assertIn("ROUTE_NOT_VERIFIED", x["blockers"])
    def test_string_zero_verified_rejected(self):
        self.assertFalse(reuse_route_for_opportunity({**COMPANY,"verified":"0"},OPP)["route_reusable"])
    def test_integer_one_verified_rejected(self):
        self.assertFalse(reuse_route_for_opportunity({**COMPANY,"verified":1},OPP)["route_reusable"])
    def test_string_false_route_eligible_rejected(self):
        x=reuse_route_for_opportunity({**COMPANY,"route_eligible":"false"},OPP)
        self.assertFalse(x["route_reusable"])
        self.assertIn("ROUTE_NOT_ELIGIBLE",x["blockers"])
    def test_integer_one_route_eligible_rejected(self):
        self.assertFalse(reuse_route_for_opportunity({**COMPANY,"route_eligible":1},OPP)["route_reusable"])
    def test_string_false_current_company_association_rejected(self):
        x=reuse_route_for_opportunity({**NAMED,"current_company_association":"false"},OPP)
        self.assertFalse(x["route_reusable"])
        self.assertIn("NAMED_ROUTE_COMPANY_ASSOCIATION_UNPROVEN",x["blockers"])
    def test_string_false_role_relevant_rejected(self):
        x=reuse_route_for_opportunity({**NAMED,"role_relevant":"false"},OPP)
        self.assertFalse(x["route_reusable"])
        self.assertIn("NAMED_ROUTE_ROLE_RELEVANCE_UNPROVEN",x["blockers"])
    def test_nonboolean_owned_by_account_rejected_with_explicit_id(self):
        x=reuse_route_for_opportunity({**COMPANY,"owned_by_account":"false"},OPP)
        self.assertFalse(x["route_reusable"])
        self.assertIn("ROUTE_ACCOUNT_OWNERSHIP_UNVERIFIED",x["blockers"])
    def test_canonical_owner_true_boolean_accepted(self):
        x=reuse_route_for_opportunity({**COMPANY,"account_id":"","owner_entity_id":"C500", "owned_by_account":True, "route_scope":"BUYER_DIRECT"},OPP)
        self.assertTrue(x["route_reusable"])
    def test_negative_guessed_preserves_rejection(self):
        x=reuse_route_for_opportunity({**COMPANY,"guessed":"false"},OPP)
        self.assertFalse(x["route_reusable"])
        self.assertIn("GUESSED_ROUTE_FORBIDDEN",x["blockers"])
    def test_boolean_negative_verified_rejected(self):
        self.assertFalse(reuse_route_for_opportunity({**COMPANY,"verified":False},OPP)["route_reusable"])

if __name__ == "__main__": unittest.main()
