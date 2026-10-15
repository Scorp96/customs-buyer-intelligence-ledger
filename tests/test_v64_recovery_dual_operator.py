"""Offline dual-operator recovery intent/replay contract.

All operator approvals, protected stores and CAS decisions here are synthetic
and must never be treated as production MFA, signature validation or RBAC.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import threading
import unittest

from unified_runtime.core import digest
from unified_runtime.host_recovery_dual_operator_v64 import (
    make_dual_operator_recovery_authorization,
)

NOW=datetime(2026,10,15,9,0,0,tzinfo=timezone.utc)
PURPOSE="CBI_PARTIAL_HOST_WAL_ARCHIVE_RECOVERY_V1"
FIELDS=(
    "expected_snapshot_sha256","expected_pin_sha256","expected_request_sha256",
    "expected_event_hash","expected_task_digest","expected_account_id",
    "expected_investigation_id","expected_session_tail_hash","expected_last_seq",
)

class SyntheticDualOperatorGuardTests(unittest.TestCase):
    def setUp(self):
        self.task={"call_id":"V63CALL-FAKE-1","branch_group":"TRADE_GRAPH",
                   "source_family":"trade_history","query":"synthetic fixture"}
        self.event={"event_hash":"a"*64}
        self.args={"investigation_id":"INV-SYN-ONE",
                   "attempt":{"owner_id":"SYN-ACCOUNT-01"}}
        self.pin={
            "approved":True,"expected_snapshot_sha256":"b"*64,
            "expected_pin_sha256":"c"*64,"expected_request_sha256":"d"*64,
            "expected_event_hash":self.event["event_hash"],
            "expected_task_digest":digest(self.task),
            "expected_account_id":"SYN-ACCOUNT-01",
            "expected_investigation_id":"INV-SYN-ONE",
            "expected_session_tail_hash":"e"*64,"expected_last_seq":2,
        }
        scope={"purpose":PURPOSE}
        for field in FIELDS:scope[field]=self.pin[field]
        self.scope_hash=digest(scope)
        self.first=self.decision("RECOVERY_OPERATOR","SYN-OP-1","CRED-1","DEC-1")
        self.second=self.decision("INDEPENDENT_REVIEWER","SYN-OP-2","CRED-2","DEC-2")
        self.verified_registry={
            "DEC-1":copy.deepcopy(self.first),
            "DEC-2":copy.deepcopy(self.second)
        }
        self.redemptions={}
        self.lock=threading.Lock()

    def decision(self,role,who,cred,decision_id):
        return {
            "role":role,"subject_id":who,"credential_id":cred,
            "decision_id":decision_id,"decision":"APPROVED",
            "purpose":PURPOSE,"scope_digest":self.scope_hash,
            "issued_at":NOW.isoformat(),
            "expires_at":(NOW+timedelta(minutes=10)).isoformat(),
        }

    def check_signature(self,decision,role):
        return (decision.get("role")==role and
                self.verified_registry.get(decision.get("decision_id"))==decision)

    def durable_fixture_cas(self,lease,scope,max_attempts):
        with self.lock:
            count=self.redemptions.get(lease,0)
            if count>=max_attempts:
                return {"allowed":False,"lease_digest":lease,
                        "scope_digest":scope,"redemption_count":count}
            count+=1
            self.redemptions[lease]=count
            return {"allowed":True,"lease_digest":lease,
                    "scope_digest":scope,"redemption_count":count}

    def auth(self,**updates):
        callbacks={
            "trusted_pinned_recovery":lambda *_:copy.deepcopy(self.pin),
            "trusted_operator_one":lambda *_:copy.deepcopy(self.first),
            "trusted_operator_two":lambda *_:copy.deepcopy(self.second),
            "verify_authenticated_decision":self.check_signature,
            "redeem_durable_scoped_lease":self.durable_fixture_cas,
            "trusted_utc_now":lambda:NOW,
            "max_recovery_attempts":3,
        }
        callbacks.update(updates)
        return make_dual_operator_recovery_authorization(**callbacks)

    def invoke(self,**updates):
        return self.auth(**updates)(self.event,self.args,self.task)

    def test_two_independently_verified_decisions_approve(self):
        self.assertEqual(self.invoke(),self.pin)

    def test_second_operator_missing_denied(self):
        self.assertIsNone(self.invoke(trusted_operator_two=None))

    def test_same_identity_denied_even_with_two_credential_ids(self):
        self.second["subject_id"]="SYN-OP-1"
        self.verified_registry["DEC-2"]=copy.deepcopy(self.second)
        self.assertIsNone(self.invoke())

    def test_same_credential_denied_even_with_two_identities(self):
        self.second["credential_id"]="CRED-1"
        self.verified_registry["DEC-2"]=copy.deepcopy(self.second)
        self.assertIsNone(self.invoke())

    def test_same_decision_id_denied(self):
        self.second["decision_id"]="DEC-1"
        self.verified_registry["DEC-1"]=copy.deepcopy(self.second)
        self.assertIsNone(self.invoke())

    def test_unsigned_or_unrecognized_decision_denied(self):
        self.second["credential_id"]="ATTACKER-CRED"
        self.assertIsNone(self.invoke())

    def test_wrong_role_denied(self):
        self.second["role"]="RECOVERY_OPERATOR"
        self.assertIsNone(self.invoke())

    def test_unrelated_task_scope_denied(self):
        self.second["scope_digest"]="f"*64
        self.assertIsNone(self.invoke())

    def test_wrong_pin_hash_denied_before_lease(self):
        self.pin["expected_snapshot_sha256"]="0"*64
        self.assertIsNone(self.invoke())
        self.assertEqual(self.redemptions,{})

    def test_wrong_event_hash_denied(self):
        self.pin["expected_event_hash"]="0"*64
        self.assertIsNone(self.invoke())

    def test_wrong_account_id_denied(self):
        self.pin["expected_account_id"]="SYN-FOREIGN"
        self.assertIsNone(self.invoke())

    def test_wrong_task_digest_denied(self):
        self.pin["expected_task_digest"]="0"*64
        self.assertIsNone(self.invoke())

    def test_wrong_investigation_denied(self):
        self.pin["expected_investigation_id"]="OTHER-INV"
        self.assertIsNone(self.invoke())

    def test_expired_second_decision_denied(self):
        self.second["expires_at"]=(NOW-timedelta(seconds=1)).isoformat()
        self.assertIsNone(self.invoke())

    def test_future_issued_decision_denied(self):
        self.second["issued_at"]=(NOW+timedelta(seconds=1)).isoformat()
        self.assertIsNone(self.invoke())

    def test_excessively_long_approval_ttl_denied(self):
        self.second["expires_at"]=(NOW+timedelta(hours=2)).isoformat()
        self.assertIsNone(self.invoke())

    def test_naive_datetime_denied(self):
        self.second["issued_at"]="2026-10-15T09:00:00"
        self.assertIsNone(self.invoke())

    def test_false_string_not_an_approval(self):
        self.second["decision"]="false"
        self.assertIsNone(self.invoke())

    def test_approved_one_integer_not_accepted(self):
        self.pin["approved"]=1
        self.assertIsNone(self.invoke())

    def test_cas_callback_required(self):
        self.assertIsNone(self.invoke(redeem_durable_scoped_lease=None))

    def test_false_cas_flag_denied(self):
        self.assertIsNone(self.invoke(redeem_durable_scoped_lease=lambda *a:{
            "allowed":"true","scope_digest":a[1],"lease_digest":a[0],
            "redemption_count":1}))

    def test_wrong_cas_scope_denied(self):
        self.assertIsNone(self.invoke(redeem_durable_scoped_lease=lambda *a:{
            "allowed":True,"scope_digest":"0"*64,"lease_digest":a[0],
            "redemption_count":1}))

    def test_cas_exception_denied(self):
        def bad(*_):raise OSError("Synthetic protected CAS offline")
        self.assertIsNone(self.invoke(redeem_durable_scoped_lease=bad))

    def test_replays_bounded_at_three(self):
        permit=self.auth()
        self.assertIsNotNone(permit(self.event,self.args,self.task))
        self.assertIsNotNone(permit(self.event,self.args,self.task))
        self.assertIsNotNone(permit(self.event,self.args,self.task))
        self.assertIsNone(permit(self.event,self.args,self.task))
        self.assertEqual(list(self.redemptions.values()),[3])

    def test_false_boolean_replay_count_rejected(self):
        self.assertIsNone(self.invoke(redeem_durable_scoped_lease=lambda *a:{
            "allowed":True,"scope_digest":a[1],"lease_digest":a[0],
            "redemption_count":True}))

    def test_concurrent_replays_admit_at_most_three(self):
        f=self.auth()
        decisions=[]
        threads=[]
        def runner():
            decisions.append(f(self.event,self.args,self.task) is not None)
        for _ in range(24):
            th=threading.Thread(target=runner);threads.append(th);th.start()
        for th in threads:th.join()
        self.assertEqual(sum(decisions),3)
        self.assertEqual(len(decisions),24)

    def test_without_independent_clock_denied(self):
        self.assertIsNone(self.invoke(trusted_utc_now=None))

    def test_excessive_configured_retry_limit_denied(self):
        self.assertIsNone(self.invoke(max_recovery_attempts=100))

    def test_operator_verifier_exception_denied(self):
        def fail(*_):raise RuntimeError("synthetic signature service down")
        self.assertIsNone(self.invoke(verify_authenticated_decision=fail))

if __name__=="__main__":
    unittest.main()
