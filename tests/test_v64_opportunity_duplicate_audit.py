"""No-network no-production-write regression tests for P0 duplicate-create audit."""
from __future__ import annotations

import copy
import unittest

from unified_runtime.opportunity_duplicate_audit_v64 import diagnose_opportunity_create_events
from unified_runtime.product_profiles import get_product_profile
from unified_runtime.recovery_semantics_v63 import snapshot_sha256


def create_event(
    *,
    opportunity_id="OPP-C123-PVC-PRIMARY",
    account="C123",
    profile="PVC",
    inv="INV-ISOLATED-001",
    corr="MUTCORR-111",
    request="a" * 64,
    seq=1,
    application_ids=None,
):
    p = get_product_profile(profile)
    snapshot = {
        "status": "CREATED",
        "stage": "OPPORTUNITY_CREATED",
        "opportunity_id": opportunity_id,
        "account_id": account,
        "product_profile_id": profile,
        "product_profile_version": p["profile_version"],
        "product_profile_sha256": p["profile_sha256"],
    }
    if application_ids is not None:
        snapshot["application_ids"] = application_ids
    return {
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "investigation_id": inv,
        "seq": seq,
        "correlation_id": corr,
        "request_sha256": request,
        "result_snapshot": snapshot,
        "result_snapshot_sha256": snapshot_sha256(snapshot),
        "raw_idempotency_key_persisted": False,
    }


class OpportunityCreateAuditTests(unittest.TestCase):
    def test_normal_single_create_does_not_rewrite_or_raise(self):
        a = create_event()
        src = [a, {"event_type": "UNRELATED"}]
        original = copy.deepcopy(src)
        report = diagnose_opportunity_create_events(src)
        self.assertEqual(src, original)
        self.assertEqual(report["status"], "NO_DUPLICATE_CREATE_EVENTS")
        self.assertEqual(report["create_event_count"], 1)
        self.assertEqual(report["duplicate_opportunity_groups"], 0)
        self.assertFalse(report["production_write_performed"])

    def test_identical_correlation_replay_requires_independent_wal(self):
        src = [create_event(seq=1), create_event(seq=2)]
        report = diagnose_opportunity_create_events(src)
        self.assertEqual(report["status"], "REPLAY_CANDIDATES_NEED_INDEPENDENT_WAL_PROOF")
        self.assertEqual(report["counts"]["exact_replay_candidates"], 1)
        self.assertFalse(report["safe_to_autorepair"])
        self.assertFalse(report["input_event_chain_verified"])
        self.assertFalse(report["mutation_wal_correlated_independently"])
        self.assertNotIn("private_event_metadata", report["collisions"][0])

    def test_identical_business_request_different_correlation_is_conflict(self):
        src = [create_event(seq=1), create_event(seq=2, corr="MUTCORR-222")]
        report = diagnose_opportunity_create_events(src)
        self.assertEqual(report["status"], "CONFLICT")
        self.assertEqual(report["counts"]["distinct_correlation_conflicts"], 1)

    def test_same_opportunity_conflicting_snapshot_is_blocked(self):
        src = [create_event(seq=1), create_event(seq=2, application_ids=["CABINETRY"])]
        report = diagnose_opportunity_create_events(src)
        self.assertEqual(report["status"], "CONFLICT")
        self.assertEqual(report["counts"]["conflicting_create_groups"], 1)

    def test_cross_investigation_duplicate_identity_never_coalesces(self):
        src = [create_event(seq=1), create_event(seq=1, inv="INV-ISOLATED-002")]
        report = diagnose_opportunity_create_events(src)
        self.assertEqual(report["status"], "CONFLICT")
        self.assertFalse(report["collisions"][0]["investigation_equal"])

    def test_owner_or_product_profile_conflict_blocks(self):
        src = [create_event(seq=1), create_event(seq=2, account="C999")]
        report = diagnose_opportunity_create_events(src)
        self.assertEqual(report["status"], "CONFLICT")
        self.assertFalse(report["collisions"][0]["account_equal"])

    def test_missing_correlation_invalidates_event_before_duplicate_comparison(self):
        src = create_event()
        src["correlation_id"] = ""
        report = diagnose_opportunity_create_events([src])
        self.assertEqual(report["status"], "INVALID_EVENT_PROOF")
        self.assertEqual(report["invalid_event_count"], 1)

    def test_tampered_snapshot_hash_rejected(self):
        src = create_event()
        src["result_snapshot"]["stage"] = "PROMOTED_ANCHOR"
        report = diagnose_opportunity_create_events([src])
        self.assertEqual(report["status"], "INVALID_EVENT_PROOF")

    def test_private_details_explicitly_opt_in(self):
        report = diagnose_opportunity_create_events(
            [create_event(), create_event(seq=2)],
            include_private_event_metadata=True,
        )
        self.assertEqual(report["collisions"][0]["private_event_metadata"][0]["seq"], 1)
        self.assertTrue(report["collisions"][0]["private_event_metadata"][0]["request_sha256"])

    def test_input_type_fail_closed(self):
        with self.assertRaises(TypeError):
            diagnose_opportunity_create_events({})


if __name__ == "__main__":
    unittest.main()
