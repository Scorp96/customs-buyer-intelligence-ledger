import unittest

from unified_runtime.recursive_expansion import prepare_recursive_expansion


class V63RecursiveExpansionTests(unittest.TestCase):
    def _payload(self):
        return {
            "promoted_anchor": {
                "opportunity_id": "OPP-C501-PVC-PRIMARY",
                "account_id": "C501",
                "product_profile_id": "PVC",
                "commercial_value_grade": "A",
                "commercial_value_score": 92.0,
                "stage": "PROMOTED_ANCHOR",
            },
            "market_cell": {
                "market_cell_id": "MC-US-MA-PVC-CABINETRY",
                "geography": "US-MA",
                "product_profile_id": "PVC",
                "application_ids": ["CABINETRY"],
                "buyer_archetype_ids": ["CABINET_MANUFACTURER"],
                "market_acceptance": "M2",
            },
            "visited_anchor_ids": [],
            "visited_expansion_keys": [],
        }

    def test_promoted_anchor_generates_fresh_recursive_plan(self):
        result = prepare_recursive_expansion(self._payload())
        self.assertEqual(result["status"], "PLANNED")
        self.assertEqual(result["anchor_opportunity_id"], "OPP-C501-PVC-PRIMARY")
        self.assertEqual(len(result["expansion_plan"]["branch_groups"]), 6)
        self.assertGreater(result["discovery_plan"]["returned_count"], 0)
        self.assertFalse(result["planning_is_execution_proof"])
        self.assertFalse(result["persistent_mutation_performed"])

    def test_same_anchor_cannot_reexpand_in_same_cycle(self):
        payload = self._payload()
        payload["visited_anchor_ids"] = ["OPP-C501-PVC-PRIMARY"]
        result = prepare_recursive_expansion(payload)
        self.assertEqual(result["status"], "SKIPPED_CYCLE_DUPLICATE")
        self.assertEqual(result["reason"], "ANCHOR_ALREADY_EXPANDED_IN_CYCLE")
        self.assertEqual(result["discovery_plan"], None)

    def test_same_account_product_market_cell_key_is_deduped(self):
        payload = self._payload()
        payload["visited_expansion_keys"] = ["C501|PVC|MC-US-MA-PVC-CABINETRY"]
        result = prepare_recursive_expansion(payload)
        self.assertEqual(result["status"], "SKIPPED_CYCLE_DUPLICATE")
        self.assertEqual(result["reason"], "EXPANSION_KEY_ALREADY_VISITED")

    def test_non_promoted_anchor_fails_closed(self):
        payload = self._payload()
        payload["promoted_anchor"]["stage"] = "ANCHOR_ELIGIBLE"
        with self.assertRaises(ValueError):
            prepare_recursive_expansion(payload)

    def test_recursive_plan_does_not_inherit_procurement_evidence(self):
        payload = self._payload()
        payload["promoted_anchor"]["procurement_evidence_ids"] = ["E-ANCHOR-1"]
        result = prepare_recursive_expansion(payload)
        self.assertEqual(result["candidate_inheritance_policy"]["procurement_evidence"], "FORBIDDEN")
        self.assertEqual(result["candidate_inheritance_policy"]["product_evidence"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
