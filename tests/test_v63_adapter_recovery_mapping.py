import unittest

from unified_runtime.adapter_recovery_mapping_v63 import (
    V63_PRODUCTION_RECOVERY_MAPPINGS,
    validate_recovery_precedents,
)


class V63AdapterRecoveryMappingTests(unittest.TestCase):
    def test_exactly_three_durable_mutations_are_mapped(self):
        self.assertEqual(
            set(V63_PRODUCTION_RECOVERY_MAPPINGS),
            {
                "append_candidate_discovery",
                "create_product_opportunity",
                "promote_opportunity_anchor",
            },
        )

    def test_candidate_and_anchor_reuse_peer_lifecycle_precedents(self):
        candidate = V63_PRODUCTION_RECOVERY_MAPPINGS["append_candidate_discovery"]
        promote = V63_PRODUCTION_RECOVERY_MAPPINGS["promote_opportunity_anchor"]
        self.assertEqual(candidate["recovery_family"], "PEER_PIVOT_LIFECYCLE")
        self.assertIn("append_peer_discovery", candidate["production_precedent_tools"])
        self.assertEqual(promote["recovery_family"], "PEER_PIVOT_LIFECYCLE")
        self.assertIn("promote_anchor", promote["production_precedent_tools"])

    def test_opportunity_creation_requires_canonical_and_append_only_precedents(self):
        mapping = V63_PRODUCTION_RECOVERY_MAPPINGS["create_product_opportunity"]
        self.assertEqual(mapping["recovery_family"], "CANONICAL_OPPORTUNITY_CREATE")
        self.assertIn("resolve_or_create_account", mapping["production_precedent_tools"])
        self.assertIn("append_information_record", mapping["production_precedent_tools"])
        self.assertTrue(mapping["canonical_resolution_proof_required"])

    def test_all_mappings_fail_closed_without_exact_durable_proof(self):
        for name, mapping in V63_PRODUCTION_RECOVERY_MAPPINGS.items():
            with self.subTest(name=name):
                self.assertTrue(mapping["requires_event_correlation"])
                self.assertFalse(mapping["automatic_reexecution_without_proof"])
                self.assertEqual(mapping["unproven_prepared_result"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertFalse(V63_PRODUCTION_RECOVERY_MAPPINGS["append_candidate_discovery"]["requires_exact_result_snapshot"])
        self.assertTrue(V63_PRODUCTION_RECOVERY_MAPPINGS["create_product_opportunity"]["requires_exact_result_snapshot"])
        self.assertFalse(V63_PRODUCTION_RECOVERY_MAPPINGS["promote_opportunity_anchor"]["requires_exact_result_snapshot"])

    def test_precedent_validator_blocks_missing_production_family(self):
        result = validate_recovery_precedents({
            "guarded_mutation_tools": ["append_peer_discovery", "promote_anchor"],
            "automatic_reconciliation_tools": ["append_peer_discovery", "promote_anchor"],
        })
        self.assertFalse(result["ready"])
        self.assertIn("resolve_or_create_account", result["missing_precedent_tools"])

    def test_precedent_validator_accepts_complete_production_family_inventory(self):
        tools = [
            "append_peer_discovery",
            "promote_anchor",
            "resolve_or_create_account",
            "append_information_record",
        ]
        result = validate_recovery_precedents({
            "guarded_mutation_tools": tools,
            "automatic_reconciliation_tools": tools,
        })
        self.assertTrue(result["ready"])
        self.assertEqual(result["missing_precedent_tools"], [])


if __name__ == "__main__":
    unittest.main()
