import unittest
from unified_runtime.route_reuse import reuse_route_for_opportunity


class NamedRouteRelevanceInputContract(unittest.TestCase):
    def route(self, **kwargs):
        route = {
            "route_id": "SYNTHETIC-PERSON-A",
            "owner_scope": "PERSON",
            "account_id": "SYNTHETIC-ACCOUNT-A",
            "verified": True,
            "route_eligible": True,
            "guessed": False,
            "freshness": "CURRENT",
            "current_company_association": True,
            "role_relevant": True,
            "product_relevance": ["GENERAL_PROCUREMENT"],
        }
        route.update(kwargs)
        return route

    def check(self, route):
        return reuse_route_for_opportunity(route, {"account_id": "SYNTHETIC-ACCOUNT-A", "product_profile_id": "PVC"})

    def assert_malformed(self, value):
        result = self.check(self.route(product_relevance=value))
        self.assertFalse(result["route_reusable"])
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED", result["blockers"])
        self.assertFalse(result["route_proves_procurement"])
        self.assertFalse(result["commercial_grade_mutated"])

    def test_null_is_rejected_without_exception(self):
        self.assert_malformed(None)

    def test_integer_is_rejected_without_exception(self):
        self.assert_malformed(1)

    def test_dictionary_keys_are_not_treated_as_evidence(self):
        self.assert_malformed({"GENERAL_PROCUREMENT": True})

    def test_string_is_not_valid_json_array(self):
        self.assert_malformed("GENERAL_PROCUREMENT")

    def test_tuple_is_not_valid_json_array(self):
        self.assert_malformed(("GENERAL_PROCUREMENT",))

    def test_array_with_null_fails_closed(self):
        self.assert_malformed([None, "GENERAL_PROCUREMENT"])

    def test_array_with_boolean_fails_closed(self):
        self.assert_malformed([True, "GENERAL_PROCUREMENT"])

    def test_array_with_integer_fails_closed(self):
        self.assert_malformed([123, "GENERAL_PROCUREMENT"])

    def test_array_with_dict_fails_closed(self):
        self.assert_malformed([{"GENERAL_PROCUREMENT": True}, "GENERAL_PROCUREMENT"])

    def test_empty_list_is_unproven_not_malformed(self):
        result = self.check(self.route(product_relevance=[]))
        self.assertFalse(result["route_reusable"])
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_UNPROVEN", result["blockers"])
        self.assertNotIn("NAMED_ROUTE_PRODUCT_RELEVANCE_MALFORMED", result["blockers"])

    def test_missing_list_is_unproven(self):
        route = self.route()
        route.pop("product_relevance")
        result = self.check(route)
        self.assertFalse(result["route_reusable"])
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_UNPROVEN", result["blockers"])

    def test_valid_general_procurement_array_preserves_route(self):
        result = self.check(self.route(product_relevance=["GENERAL_PROCUREMENT"]))
        self.assertTrue(result["route_reusable"])
        self.assertFalse(result["route_proves_procurement"])
        self.assertFalse(result["route_proves_product_interest"])

    def test_valid_exact_product_array_preserves_route(self):
        result = self.check(self.route(product_relevance=["PVC"]))
        self.assertTrue(result["route_reusable"])
        self.assertEqual(result["reuse_scope"], "NAMED_ROUTE_PRODUCT_SPECIFIC")

    def test_other_product_remains_unproven(self):
        result = self.check(self.route(product_relevance=["SPC"]))
        self.assertFalse(result["route_reusable"])
        self.assertIn("NAMED_ROUTE_PRODUCT_RELEVANCE_UNPROVEN", result["blockers"])

if __name__ == "__main__":
    unittest.main()
