"""Exercise two-operator authorization against the real isolated recovery API.

This is integration over existing synthetic Host archive fixtures. It does
NOT attest live operator RBAC, independently signed decisions, cross-volume
power loss, or a production persistent replay ledger.
"""
import copy
from datetime import datetime, timedelta, timezone
import unittest

from unified_runtime.core import digest
from unified_runtime.host_recovery_dual_operator_v64 import (
    make_dual_operator_recovery_authorization,
)


class RecoveryDualOperatorExistingApiIntegration(unittest.TestCase):
    def setUp(self):
        # Local import avoids rediscovering/duplicating fixture test classes.
        from tests.test_v64_host_postcommit_archive import HostPostcommitArchiveTests
        self.fixture = HostPostcommitArchiveTests(
            methodName="test_recovery_snapshot_only_after_request_interrupt"
        )
        self.fixture.setUp()
        self.fixture._interrupt_publish(".pin.json")
        self.pin = copy.deepcopy(self.fixture._external_recovery_record())
        self.now = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
        scope = {"purpose": "CBI_PARTIAL_HOST_WAL_ARCHIVE_RECOVERY_V1"}
        for k in (
            "expected_snapshot_sha256", "expected_pin_sha256",
            "expected_request_sha256", "expected_event_hash",
            "expected_task_digest", "expected_account_id",
            "expected_investigation_id", "expected_session_tail_hash",
            "expected_last_seq",
        ):
            scope[k] = self.pin[k]
        self.scope_sha = digest(scope)
        self.operators = [
            self.decision("RECOVERY_OPERATOR", "SYN-OP-01", "SYN-CRED-01", "SYN-AUTH-A"),
            self.decision("INDEPENDENT_REVIEWER", "SYN-OP-02", "SYN-CRED-02", "SYN-AUTH-B"),
        ]
        self.registry = {d["decision_id"]: copy.deepcopy(d) for d in self.operators}
        self.counter = {}

    def tearDown(self):
        self.fixture.tearDown()

    def decision(self, role, principal, credential, decision_id):
        return {
            "role": role, "subject_id": principal,
            "credential_id": credential, "decision_id": decision_id,
            "decision": "APPROVED",
            "purpose": "CBI_PARTIAL_HOST_WAL_ARCHIVE_RECOVERY_V1",
            "scope_digest": self.scope_sha,
            "issued_at": self.now.isoformat(),
            "expires_at": (self.now+timedelta(minutes=8)).isoformat(),
        }

    def authorizer(self):
        def consume(lease, scope, max_attempts):
            used = self.counter.get(lease, 0)
            if used >= max_attempts:
                return {"allowed": False, "lease_digest": lease,
                        "scope_digest": scope, "redemption_count": used}
            self.counter[lease] = used + 1
            return {"allowed": True, "lease_digest": lease,
                    "scope_digest": scope, "redemption_count": used + 1}
        return make_dual_operator_recovery_authorization(
            trusted_pinned_recovery=lambda *_: copy.deepcopy(self.pin),
            trusted_operator_one=lambda *_: copy.deepcopy(self.operators[0]),
            trusted_operator_two=lambda *_: copy.deepcopy(self.operators[1]),
            verify_authenticated_decision=lambda d, role:
                d.get("role") == role and self.registry.get(d.get("decision_id")) == d,
            redeem_durable_scoped_lease=consume,  # synthetic memory CAS
            trusted_utc_now=lambda: self.now,
            max_recovery_attempts=2,
        )

    def test_dual_approved_partial_recovery_then_bounded_verified_replay(self):
        auth = self.authorizer()
        result = self.fixture._resume_partial(authorizer=auth)
        self.assertEqual(result["status"], "ISOLATED_PARTIAL_RECOVERY_PUBLISHED")
        self.assertEqual(result["independent_operator_authority_proven"], False)
        self.fixture.fixture_independently_pin()
        self.assertTrue(self.fixture.covered())
        replay = self.fixture._resume_partial(authorizer=auth)
        self.assertEqual(replay["status"], "ALREADY_PUBLISHED_VERIFIED")
        self.assertEqual(replay["new_files_created"], 0)
        with self.assertRaises(PermissionError):
            self.fixture._resume_partial(authorizer=auth)
        self.assertTrue(self.fixture.covered())

    def test_shared_operator_identity_rejects_before_archive_mutation(self):
        self.operators[1]["subject_id"] = self.operators[0]["subject_id"]
        self.registry[self.operators[1]["decision_id"]] = copy.deepcopy(self.operators[1])
        before = self.fixture._archive_bytes_by_slot()
        with self.assertRaises(PermissionError):
            self.fixture._resume_partial(authorizer=self.authorizer())
        self.assertEqual(before, self.fixture._archive_bytes_by_slot())
        self.assertFalse(self.fixture.covered())

    def test_expired_operator_rejects_before_archive_mutation(self):
        self.operators[1]["expires_at"] = (self.now-timedelta(seconds=1)).isoformat()
        before = self.fixture._archive_bytes_by_slot()
        with self.assertRaises(PermissionError):
            self.fixture._resume_partial(authorizer=self.authorizer())
        self.assertEqual(before, self.fixture._archive_bytes_by_slot())
        self.assertFalse(self.fixture.covered())


if __name__ == "__main__":
    unittest.main()
