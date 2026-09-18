import copy
import unittest

from unified_runtime.recovery_semantics_v63 import (
    canonical_v63_request_sha256,
    canonical_v63_wal_request_sha256,
    recover_prepared_v63_mutation,
    snapshot_sha256,
)


class V63RecoverySemanticsHarnessTests(unittest.TestCase):
    def _candidate_args(self, key="candidate-key-0001"):
        return {
            "investigation_id": "INV-TEST",
            "candidate_id": "CAND-001",
            "discovered_from_anchor_id": "ANCHOR-001",
            "branch_group": "APPLICATION_GRAPH",
            "branch": "downstream_manufacturer",
            "company_name": "Example Cabinet Co",
            "product_profile_id": "PVC",
            "idempotency_key": key,
            "expected_state_version": 7,
        }

    def _candidate_event(self, args=None, correlation="MUTCORR-001"):
        args = args or self._candidate_args()
        return {
            "event_type": "V63_CANDIDATE_DISCOVERED",
            "correlation_id": correlation,
            "request_sha256": canonical_v63_wal_request_sha256("append_candidate_discovery", args),
            "candidate_id": args["candidate_id"],
            "discovered_from_anchor_id": args["discovered_from_anchor_id"],
            "branch_group": args["branch_group"],
            "branch": args["branch"],
            "company_name": args["company_name"],
            "product_profile_id": args["product_profile_id"],
            "stage": "DISCOVERED",
            "inherited_anchor_facts": False,
            "raw_idempotency_key_persisted": False,
        }

    def test_request_hash_excludes_adapter_control_fields(self):
        a = self._candidate_args("candidate-key-0001")
        b = self._candidate_args("different-key-0002")
        b["expected_state_version"] = 99
        self.assertEqual(canonical_v63_request_sha256(a), canonical_v63_request_sha256(b))

    def test_candidate_recovers_only_from_exact_correlated_event(self):
        args = self._candidate_args()
        event = self._candidate_event(args, "MUTCORR-001")
        result = recover_prepared_v63_mutation(
            "append_candidate_discovery",
            args,
            expected_correlation_id="MUTCORR-001",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "RECOVERED")
        self.assertEqual(result["recovery_action"], "RECONSTRUCT_FROM_CORRELATED_EVENT")
        self.assertEqual(result["result"]["candidate_id"], "CAND-001")
        self.assertFalse(result["reexecute_side_effect"])

    def test_candidate_wrong_correlation_fails_closed_even_when_business_payload_matches(self):
        args = self._candidate_args()
        event = self._candidate_event(args, "OTHER-CORR")
        result = recover_prepared_v63_mutation(
            "append_candidate_discovery",
            args,
            expected_correlation_id="MUTCORR-001",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertIn("NO_EXACT_DURABLE_PROOF", result["blockers"])

    def test_same_content_different_key_cannot_claim_other_key_event(self):
        first = self._candidate_args("candidate-key-0001")
        second = self._candidate_args("candidate-key-0002")
        self.assertEqual(canonical_v63_request_sha256(first), canonical_v63_request_sha256(second))
        event = self._candidate_event(first, "CORR-FOR-KEY-1")
        result = recover_prepared_v63_mutation(
            "append_candidate_discovery",
            second,
            expected_correlation_id="CORR-FOR-KEY-2",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertIn("NO_EXACT_DURABLE_PROOF", result["blockers"])

    def test_wrong_request_hash_fails_closed(self):
        args = self._candidate_args()
        event = self._candidate_event(args)
        event["request_sha256"] = "0" * 64
        result = recover_prepared_v63_mutation(
            "append_candidate_discovery",
            args,
            expected_correlation_id="MUTCORR-001",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertIn("NO_EXACT_DURABLE_PROOF", result["blockers"])

    def test_duplicate_exact_events_are_ambiguous_and_fail_closed(self):
        args = self._candidate_args()
        event = self._candidate_event(args)
        result = recover_prepared_v63_mutation(
            "append_candidate_discovery",
            args,
            expected_correlation_id="MUTCORR-001",
            durable_events=[event, copy.deepcopy(event)],
        )
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertIn("AMBIGUOUS_EXACT_DURABLE_PROOF", result["blockers"])

    def test_opportunity_creation_returns_exact_snapshot(self):
        args = {
            "investigation_id": "INV-TEST",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "product_profile_version": "1",
            "product_profile_sha256": "a" * 64,
            "canonical_resolution_proof": {"status": "CONFIRMED", "account_id": "C500"},
            "idempotency_key": "opp-key-00000001",
        }
        snapshot = {
            "status": "CREATED",
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "stage": "OPPORTUNITY_CREATED",
        }
        event = {
            "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
            "correlation_id": "MUTCORR-OPP-1",
            "request_sha256": canonical_v63_wal_request_sha256("create_product_opportunity", args),
            "result_snapshot": snapshot,
            "result_snapshot_sha256": snapshot_sha256(snapshot),
            "raw_idempotency_key_persisted": False,
        }
        result = recover_prepared_v63_mutation(
            "create_product_opportunity",
            args,
            expected_correlation_id="MUTCORR-OPP-1",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "RECOVERED")
        self.assertEqual(result["recovery_action"], "RETURN_EXACT_STORED_RESULT")
        self.assertEqual(result["result"], snapshot)
        self.assertIsNot(result["result"], snapshot)

    def test_opportunity_snapshot_hash_mismatch_fails_closed(self):
        args = {
            "investigation_id": "INV-TEST",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "product_profile_version": "1",
            "product_profile_sha256": "a" * 64,
            "canonical_resolution_proof": {"status": "CONFIRMED", "account_id": "C500"},
            "idempotency_key": "opp-key-00000001",
        }
        event = {
            "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
            "correlation_id": "MUTCORR-OPP-1",
            "request_sha256": canonical_v63_wal_request_sha256("create_product_opportunity", args),
            "result_snapshot": {"status": "CREATED", "opportunity_id": "OPP-C500-PVC-PRIMARY"},
            "result_snapshot_sha256": "f" * 64,
            "raw_idempotency_key_persisted": False,
        }
        result = recover_prepared_v63_mutation(
            "create_product_opportunity",
            args,
            expected_correlation_id="MUTCORR-OPP-1",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertIn("RESULT_SNAPSHOT_HASH_MISMATCH", result["blockers"])

    def test_anchor_promotion_reconstructs_only_when_snapshots_prove_gate(self):
        args = {
            "investigation_id": "INV-TEST",
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "promotion_reason": "UPGRADE_TARGET",
            "idempotency_key": "anchor-key-000001",
        }
        event = {
            "event_type": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
            "correlation_id": "MUTCORR-ANCHOR-1",
            "request_sha256": canonical_v63_wal_request_sha256("promote_opportunity_anchor", args),
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "anchor_id": "ANCHOR-OPP-C500-PVC-PRIMARY",
            "promotion_reason": "UPGRADE_TARGET",
            "stage": "PROMOTED_ANCHOR",
            "anchor_eligibility_snapshot": {"anchor_eligible": True},
            "cycle_dedup_snapshot": {"cycle_dedup_complete": True},
            "raw_idempotency_key_persisted": False,
        }
        result = recover_prepared_v63_mutation(
            "promote_opportunity_anchor",
            args,
            expected_correlation_id="MUTCORR-ANCHOR-1",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "RECOVERED")
        self.assertEqual(result["result"]["stage"], "PROMOTED_ANCHOR")
        self.assertTrue(result["result"]["anchor_eligibility_snapshot"]["anchor_eligible"])

    def test_raw_idempotency_key_in_event_is_rejected(self):
        args = self._candidate_args()
        event = self._candidate_event(args)
        event["raw_idempotency_key_persisted"] = True
        result = recover_prepared_v63_mutation(
            "append_candidate_discovery",
            args,
            expected_correlation_id="MUTCORR-001",
            durable_events=[event],
        )
        self.assertEqual(result["status"], "MUTATION_RECONCILIATION_REQUIRED")
        self.assertIn("RAW_IDEMPOTENCY_KEY_PERSISTED", result["blockers"])


if __name__ == "__main__":
    unittest.main()
