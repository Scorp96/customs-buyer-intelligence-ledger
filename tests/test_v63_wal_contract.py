import unittest

from unified_runtime.wal_contract_v63 import (
    V63_WAL_BINDINGS,
    build_v63_wal_contract,
    validate_v63_durable_event_proof,
)


class V63WALContractTests(unittest.TestCase):
    def test_only_three_durable_mutations_have_exact_binding_contracts(self):
        expected = {
            "append_candidate_discovery",
            "create_product_opportunity",
            "promote_opportunity_anchor",
        }
        self.assertEqual(set(V63_WAL_BINDINGS), expected)

    def test_each_binding_requires_exact_correlation_but_snapshot_policy_is_family_specific(self):
        for tool, binding in V63_WAL_BINDINGS.items():
            with self.subTest(tool=tool):
                self.assertTrue(binding["requires_exact_event_correlation"])
                self.assertFalse(binding["prepared_auto_reexecutes_without_proof"])
                self.assertEqual(binding["unproven_prepared_result"], "MUTATION_RECONCILIATION_REQUIRED")
                self.assertFalse(binding["correlation_contains_raw_idempotency_key"])
        self.assertFalse(V63_WAL_BINDINGS["append_candidate_discovery"]["requires_exact_result_snapshot"])
        self.assertTrue(V63_WAL_BINDINGS["create_product_opportunity"]["requires_exact_result_snapshot"])
        self.assertFalse(V63_WAL_BINDINGS["promote_opportunity_anchor"]["requires_exact_result_snapshot"])

    def test_contract_preserves_existing_wal_as_only_authority(self):
        contract = build_v63_wal_contract()
        self.assertEqual(contract["binding_strategy"], "EXTEND_EXISTING_PRODUCTION_WAL")
        self.assertFalse(contract["parallel_wal_allowed"])
        self.assertTrue(contract["existing_wal_is_authority"])
        self.assertTrue(contract["r2_durable_state_preserved"])

    def test_exact_durable_event_proof_validates(self):
        binding = V63_WAL_BINDINGS["create_product_opportunity"]
        proof = validate_v63_durable_event_proof(binding, {
            "event_type": binding["event_type"],
            "correlation_id": "corr-123",
            "request_sha256": "a" * 64,
            "result_snapshot_sha256": "b" * 64,
            "result_snapshot": {"status": "CREATED", "opportunity_id": "OPP-C1-PVC-PRIMARY"},
            "raw_idempotency_key_persisted": False,
        })
        self.assertTrue(proof["valid"])
        self.assertEqual(proof["recovery_action"], "RETURN_EXACT_STORED_RESULT")


    def test_candidate_discovery_recovers_from_exact_correlated_event_without_result_snapshot(self):
        binding = V63_WAL_BINDINGS["append_candidate_discovery"]
        proof = validate_v63_durable_event_proof(binding, {
            "event_type": binding["event_type"],
            "correlation_id": "corr-candidate",
            "request_sha256": "a" * 64,
            "candidate_id": "CAND-1",
            "discovered_from_anchor_id": "ANCHOR-1",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_supplier_buyer",
            "company_name": "Example Candidate",
            "product_profile_id": "PVC",
            "stage": "DISCOVERED",
            "inherited_anchor_facts": False,
            "raw_idempotency_key_persisted": False,
        })
        self.assertTrue(proof["valid"])
        self.assertEqual(proof["recovery_action"], "RECONSTRUCT_FROM_CORRELATED_EVENT")

    def test_candidate_discovery_missing_reconstruction_material_fails_closed(self):
        binding = V63_WAL_BINDINGS["append_candidate_discovery"]
        proof = validate_v63_durable_event_proof(binding, {
            "event_type": binding["event_type"],
            "correlation_id": "corr-candidate",
            "request_sha256": "a" * 64,
            "raw_idempotency_key_persisted": False,
        })
        self.assertFalse(proof["valid"])
        self.assertIn("MISSING_EVENT_FIELD:candidate_id", proof["blockers"])

    def test_anchor_promotion_requires_eligibility_and_cycle_snapshots(self):
        binding = V63_WAL_BINDINGS["promote_opportunity_anchor"]
        proof = validate_v63_durable_event_proof(binding, {
            "event_type": binding["event_type"],
            "correlation_id": "corr-anchor",
            "request_sha256": "a" * 64,
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "anchor_id": "ANCHOR-2",
            "promotion_reason": "NEW_MARKET_CELL",
            "stage": "PROMOTED_ANCHOR",
            "anchor_eligibility_snapshot": {"anchor_eligible": True},
            "cycle_dedup_snapshot": {"cycle_dedup_complete": True},
            "raw_idempotency_key_persisted": False,
        })
        self.assertTrue(proof["valid"])
        self.assertEqual(proof["recovery_action"], "RECONSTRUCT_FROM_CORRELATED_EVENT")

    def test_anchor_promotion_false_cycle_snapshot_fails_closed(self):
        binding = V63_WAL_BINDINGS["promote_opportunity_anchor"]
        proof = validate_v63_durable_event_proof(binding, {
            "event_type": binding["event_type"],
            "correlation_id": "corr-anchor",
            "request_sha256": "a" * 64,
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "anchor_id": "ANCHOR-2",
            "promotion_reason": "NEW_MARKET_CELL",
            "stage": "PROMOTED_ANCHOR",
            "anchor_eligibility_snapshot": {"anchor_eligible": True},
            "cycle_dedup_snapshot": {"cycle_dedup_complete": False},
            "raw_idempotency_key_persisted": False,
        })
        self.assertFalse(proof["valid"])
        self.assertIn("EVENT_CONSTRAINT_FAILED:cycle_dedup_snapshot.cycle_dedup_complete", proof["blockers"])

    def test_missing_snapshot_fails_closed(self):
        binding = V63_WAL_BINDINGS["create_product_opportunity"]
        proof = validate_v63_durable_event_proof(binding, {
            "event_type": binding["event_type"],
            "correlation_id": "corr-123",
            "request_sha256": "a" * 64,
            "raw_idempotency_key_persisted": False,
        })
        self.assertFalse(proof["valid"])
        self.assertEqual(proof["recovery_action"], "MUTATION_RECONCILIATION_REQUIRED")

    def test_wrong_event_type_or_raw_key_persistence_fails_closed(self):
        binding = V63_WAL_BINDINGS["promote_opportunity_anchor"]
        for payload in (
            {
                "event_type": "WRONG_EVENT",
                "correlation_id": "corr-x",
                "request_sha256": "a" * 64,
                "result_snapshot_sha256": "b" * 64,
                "result_snapshot": {},
                "raw_idempotency_key_persisted": False,
            },
            {
                "event_type": binding["event_type"],
                "correlation_id": "corr-x",
                "request_sha256": "a" * 64,
                "result_snapshot_sha256": "b" * 64,
                "result_snapshot": {},
                "raw_idempotency_key_persisted": True,
            },
        ):
            with self.subTest(payload=payload):
                result = validate_v63_durable_event_proof(binding, payload)
                self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
