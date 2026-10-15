"""Isolated Host SessionStore + WAL receipt ownership proof tests.

The WAL checker is a synthetic fixture, NOT an implementation of the
production WAL reader or proof of a real customer source call.
"""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime.core import SessionStore
from unified_runtime.host_wal_receipt_verifier_v64 import make_host_wal_receipt_verifier
from unified_runtime.source_execution import evaluate_source_coverage
from unified_runtime.contact_source_execution import evaluate_contact_coverage

INV = "INV-20261015T060000Z-1a2b3c4d5e6f"
ACCOUNT = "SYN-ACCOUNT-01"
HASH = "a" * 64

class IsolatedHostWalReceiptProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-ledger-proof-")
        self.store = SessionStore(Path(self.temp.name) / "sessions")
        self.store.create({"investigation_id":INV,"account":{"account_id":ACCOUNT}})
        self.task={
            "call_id":"V63CALL-SYN-1","branch_group":"TRADE_GRAPH",
            "branch":"same_supplier_buyer","source_family":"trade_history",
            "query":"synthetic company trade",
        }
        self.attempt={
            **self.task,
            "investigation_id":INV,"owner_id":ACCOUNT,
            "attempt_id":"SYN-ATTEMPT-1","execution_id":"SYN-EXEC-1",
            "completed_at":"2026-10-15T06:00:00Z","result":"NEGATIVE_EXHAUSTED",
            "content_sha256":HASH,"raw_result_locator":"synthetic://local/raw",
            "evidence_ids":[],"blocked_reason":"",
            "wal_correlation_id":"SYN-WAL-1"
        }
        self.event=self.store.append(INV,"EXECUTION_RECEIPT_APPENDED",
            {"attempt":copy.deepcopy(self.attempt),"evidence":[]})
        self.wal_records={
            "SYN-WAL-1":{
                "state":"COMMITTED","investigation_id":INV,
                "request_sha256":"b"*64,"attempt_id":"SYN-ATTEMPT-1",
                "execution_id":"SYN-EXEC-1","event_hash":self.event["event_hash"],
                "event_seq":self.event["seq"],"result":"NEGATIVE_EXHAUSTED",
            }
        }
        self.receipt={
            **self.attempt,
            "account_id":ACCOUNT,
            "event_seq":self.event["seq"],"event_hash":self.event["event_hash"],
        }
        self.tail_seq=self.event["seq"]
        self.tail_hash=self.event["event_hash"]

    def tearDown(self):
        self.temp.cleanup()

    def trusted_wal(self, event, attempt, task):
        record=self.wal_records.get(attempt.get("wal_correlation_id"))
        return bool(
            record and record.get("state") == "COMMITTED"
            and record.get("investigation_id")==INV
            and record.get("attempt_id")==attempt.get("attempt_id")
            and record.get("execution_id")==attempt.get("execution_id")
            and record.get("event_hash")==event.get("event_hash")
            and record.get("event_seq")==event.get("seq")
            and record.get("result")==attempt.get("result")
            and record.get("request_sha256")=="b"*64
            and task.get("call_id")==attempt.get("call_id")
        )

    def verifier(self, **updates):
        kwargs={"session_store":self.store,"investigation_id":INV,
            "account_id":ACCOUNT,"expected_last_seq":self.tail_seq,
            "expected_last_event_hash":self.tail_hash,
            "wal_commit_verifier":self.trusted_wal}
        kwargs.update(updates)
        return make_host_wal_receipt_verifier(**kwargs)

    def coverage(self, *, receipt=None, verifier=None, task=None):
        p={"truncated":False,"tasks":[self.task if task is None else task]}
        return evaluate_source_coverage(
            p,[self.receipt if receipt is None else receipt],
            receipt_verifier=self.verifier() if verifier is None else verifier,
        )

    def test_synthetic_full_chain_and_committed_wal_allows_one_negative(self):
        r=self.coverage()
        self.assertTrue(r["source_coverage_complete"])

    def test_no_wal_checker_fails_closed(self):
        self.assertFalse(self.coverage(verifier=self.verifier(wal_commit_verifier=None))["source_coverage_complete"])

    def test_wal_prepared_not_committed(self):
        self.wal_records["SYN-WAL-1"]["state"]="PREPARED"
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_wal_committed_error_rejected(self):
        self.wal_records["SYN-WAL-1"]["state"]="COMMITTED_ERROR"
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_wal_missing_correlation_rejected(self):
        self.wal_records.clear()
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_wal_other_investigation_rejected(self):
        self.wal_records["SYN-WAL-1"]["investigation_id"]="INV-OTHER"
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_wal_wrong_event_hash_rejected(self):
        self.wal_records["SYN-WAL-1"]["event_hash"]="f"*64
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_session_wrong_tail_hash_rejected(self):
        v=self.verifier(expected_last_event_hash="f"*64)
        self.assertFalse(self.coverage(verifier=v)["source_coverage_complete"])

    def test_session_wrong_tail_seq_rejected(self):
        v=self.verifier(expected_last_seq=self.tail_seq+1)
        self.assertFalse(self.coverage(verifier=v)["source_coverage_complete"])

    def test_session_grows_after_pin_fails_closed(self):
        self.store.append(INV,"SYNTHETIC_OTHER_EVENT",{"test_only":True})
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_wrong_account_owner_rejected(self):
        v=self.verifier(account_id="FOREIGN-ACCOUNT")
        self.assertFalse(self.coverage(verifier=v)["source_coverage_complete"])

    def test_wrong_call_id_rejected(self):
        bad={**self.receipt,"call_id":"V63CALL-OTHER"}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_source_family_mismatch_rejected(self):
        bad={**self.receipt,"source_family":"maps_region"}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_wrong_branch_group_rejected(self):
        bad={**self.receipt,"branch_group":"CHANNEL_GRAPH"}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_changed_query_rejected(self):
        bad={**self.receipt,"query":"other query"}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_wrong_event_hash_from_client_rejected(self):
        bad={**self.receipt,"event_hash":"0"*64}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_bad_seq_boolean_not_accepted(self):
        bad={**self.receipt,"event_seq":True}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_forged_completed_at_rejected(self):
        bad={**self.receipt,"completed_at":"2026-10-16T00:00:00Z"}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_verified_true_without_wal_still_not_proof(self):
        self.wal_records.clear()
        bad={**self.receipt,"verified":True,"search_execution_performed":True}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

    def test_negative_with_blocked_reason_not_proven(self):
        # Even a synthetically valid WAL record cannot turn BLOCKED into NEGATIVE.
        self.attempt["blocked_reason"]="LOGIN_REQUIRED"
        v=self.verifier()
        event=self.store.read(INV)[1]
        # Immutable event remains unmodified. Forged receipt cannot change it.
        bad={**self.receipt,"blocked_reason":"LOGIN_REQUIRED"}
        self.assertFalse(
            # This particular receipt cannot force a blocked event since the
            # verifier compares actual WAL/event result rather than a flag.
            v(self.task, {**bad,"result":"BLOCKED"})
        )

    def test_contact_task_wrong_owner_does_not_reuse_source_receipt(self):
        p={
            "truncated":False,"company_route_required_for_completion":True,
            "named_route_required_for_completion":False,
            "tasks":[{
                "task_id":"SYN-CONTACT-1",
                "opportunity_id":"SYN-OPP","route_target":"COMPANY",
                "source_family":"official_contact","company_name":"Synthetic Co",
                "required_for_completion":True,
            }]
        }
        r=evaluate_contact_coverage(p,[self.receipt],receipt_verifier=self.verifier())
        self.assertFalse(r["contact_exhaustion_complete"])

    def test_corrupt_session_chain_fails_closed(self):
        path=self.store.path(INV)
        data=path.read_text(encoding="utf8")
        self.assertIn("NEGATIVE_EXHAUSTED",data)
        path.write_text(data.replace("NEGATIVE_EXHAUSTED","POSITIVE",1),encoding="utf8")
        self.assertFalse(self.coverage()["source_coverage_complete"])

    def test_wrong_event_type_fails_closed(self):
        bad={**self.receipt,"event_seq":1,
             "event_hash":self.store.read(INV)[0]["event_hash"]}
        self.assertFalse(self.coverage(receipt=bad)["source_coverage_complete"])

if __name__=="__main__":
    unittest.main()
