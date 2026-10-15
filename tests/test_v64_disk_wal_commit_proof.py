"""Offline tests using the actual on-disk CBI v6.1 WAL record schema.

No live WAL, production account, paid API or external website is used. The
trusted original-arguments provider is an explicitly isolated fixture.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from unified_runtime.core import SessionStore, digest, canonical_json
from unified_runtime.host_wal_receipt_verifier_v64 import make_host_wal_receipt_verifier
from unified_runtime.v61_disk_wal_commit_proof_v64 import make_v61_disk_wal_commit_verifier
from unified_runtime.source_execution import evaluate_source_coverage
from unified_runtime.wal_immutable_snapshot_v64 import (
    create_immutable_terminal_wal_snapshot,
)

INV="INV-20261015T120000Z-abcdef123456"
ACCOUNT="SYN-ONLY-ACCOUNT"
KEY="synthetic-host-authorized-key-001"
TOOL="append_execution_receipt"
SHA="f"*64

class DiskV61WalIsolatedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="cbi-v61-wal-disk-")
        self.root=Path(self.temp.name)
        self.store=SessionStore(self.root/"sessions")
        self.store.create({"investigation_id":INV,"account":{"account_id":ACCOUNT}})
        self.walroot=self.root/"mcp-idempotency-v61"
        self.walroot.mkdir()
        self.task={"call_id":"V63CALL-SYN-1","branch_group":"TRADE_GRAPH",
                   "branch":"same_supplier_buyer","source_family":"trade_history",
                   "query":"synthetic never external"}
        self.attempt={**self.task,"investigation_id":INV,"owner_id":ACCOUNT,
            "module_or_branch":"trade_supplier_continuity",
            "attempt_id":"SYN-ATT-1","execution_id":"SYN-EX-1",
            "completed_at":"2026-10-15T12:00:00Z",
            "result":"NEGATIVE_EXHAUSTED","content_sha256":SHA,
            "raw_result_locator":"synthetic://offline-only",
            "evidence_ids":[],"blocked_reason":""}
        self.args={"idempotency_key":KEY,"investigation_id":INV,
                   "attempt":copy.deepcopy(self.attempt),"evidence":[],"pivots":[],
                   "pivots_consumed":[],"manual_visual_items_resolved":[]}
        self.corr="MUTCORR-"+hashlib.sha256(f"{TOOL}:{KEY}".encode()).hexdigest()[:24]
        self.correlation={"schema":"cbi.mutation-correlation.v6.1",
                          "correlation_id":self.corr,"tool":TOOL}
        pre=self.store.read(INV)[-1]
        evt={"seq":2,"prev_hash":pre["event_hash"],
             "event_type":"EXECUTION_RECEIPT_APPENDED",
             "recorded_at":"2026-10-15T12:00:00Z",
             "payload":{"attempt":copy.deepcopy(self.attempt),"evidence":[],
                        "pivots_generated":[],"pivots_consumed":[]},
             "mutation_correlation":copy.deepcopy(self.correlation)}
        evt["event_hash"]=digest(evt)
        with self.store.path(INV).open("a",encoding="utf8") as f:
            f.write(canonical_json(evt)+"\n")
        self.event=evt
        req=dict(self.args);req.pop("idempotency_key")
        self.request_hash=digest({"tool":TOOL,"arguments":req})
        self.result={
          "accepted":True,"attempt_id":self.attempt["attempt_id"],
          "evidence_count":0,
          "mutation_meta":{
             "schema":"cbi.mutation-meta.v6.1","tool":TOOL,"idempotency_key":KEY,
             "request_sha256":self.request_hash,"state_version_before":1,
             "state_version_after":2,"replayed":False,"write_ahead_intent":True,
           }}
        self.wal={"schema":"cbi.mutation-wal.v6.1","status":"COMMITTED",
            "tool":TOOL,"idempotency_key":KEY,"request_sha256":self.request_hash,
            "state_version_before":1,"state_version_after":2,
            "mutation_correlation_id":self.corr,
            "prepared_at":"2026-10-15T11:59:59Z",
            "completed_at":"2026-10-15T12:00:01Z",
            "result":self.result,"result_sha256":digest(self.result)}
        self.walpath=self.walroot/f"{TOOL}-{hashlib.sha256(KEY.encode()).hexdigest()}.json"
        self.persist()
        self.snapshot_root=self.root/"host-postcommit-immutable"
        self.snapshot_root.mkdir()
        self.snapshot_pin=create_immutable_terminal_wal_snapshot(
            terminal_wal_path=self.walpath,
            snapshot_root=self.snapshot_root,
            expected_request_sha256=self.request_hash,
        )
        self.receipt={**self.attempt,"account_id":ACCOUNT,
                      "event_seq":2,"event_hash":evt["event_hash"]}
        self.proof=self.build_proof()
        self.snapshot_proof=self.build_snapshot_proof()
    def tearDown(self):
        self.temp.cleanup()
    def persist(self):
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
    def trusted_original(self,event,attempt,task):
        return copy.deepcopy(self.args)
    def build_proof(self,provider=None):
        cb=make_v61_disk_wal_commit_verifier(
            wal_root=self.walroot,
            trusted_original_arguments=self.trusted_original if provider is None else provider)
        return make_host_wal_receipt_verifier(
            session_store=self.store, investigation_id=INV,account_id=ACCOUNT,
            expected_last_seq=2,expected_last_event_hash=self.event["event_hash"],
            wal_commit_verifier=cb)
    def build_snapshot_proof(self,pin_provider=None):
        cb=make_v61_disk_wal_commit_verifier(
            wal_root=self.walroot,
            trusted_original_arguments=self.trusted_original,
            immutable_snapshot_root=self.snapshot_root,
            trusted_snapshot_sha256=(
                pin_provider if pin_provider is not None
                else lambda event,attempt,task: self.snapshot_pin
            ),
        )
        return make_host_wal_receipt_verifier(
            session_store=self.store, investigation_id=INV,account_id=ACCOUNT,
            expected_last_seq=2,expected_last_event_hash=self.event["event_hash"],
            wal_commit_verifier=cb,
        )

    def valid(self,proof=None):
        r=evaluate_source_coverage({"tasks":[self.task],"truncated":False},
            [self.receipt],receipt_verifier=self.proof if proof is None else proof)
        return r["source_coverage_complete"]

    def test_exact_on_disk_v61_wal_and_valid_session_pass(self):
        self.assertTrue(self.valid())

    def test_prepared_never_suffices(self):
        self.wal["status"]="PREPARED";self.persist();self.assertFalse(self.valid())

    def test_committed_error_never_suffices(self):
        self.wal["status"]="COMMITTED_ERROR";self.persist();self.assertFalse(self.valid())

    def test_missing_wal_record_fails_closed(self):
        self.walpath.unlink();self.assertFalse(self.valid())

    def test_unreadable_or_torn_json_fails_closed(self):
        self.walpath.write_text('{"status":"COMMITTED"',encoding="utf8")
        self.assertFalse(self.valid())

    def test_wrong_tool_fails_closed(self):
        self.wal["tool"]="create_product_opportunity";self.persist();self.assertFalse(self.valid())

    def test_corrupted_request_digest_fails_closed(self):
        self.wal["request_sha256"]="0"*64;self.persist();self.assertFalse(self.valid())

    def test_wal_result_tampering_detected(self):
        self.wal["result"]["accepted"]=False;self.persist();self.assertFalse(self.valid())

    def test_forged_result_digest_detected(self):
        self.wal["result_sha256"]="0"*64;self.persist();self.assertFalse(self.valid())

    def test_wrong_correlation_fails_closed(self):
        self.wal["mutation_correlation_id"]="MUTCORR-FAKE";self.persist()
        self.assertFalse(self.valid())

    def test_wrong_state_version_before_fails_closed(self):
        self.wal["state_version_before"]=0;self.persist()
        self.assertFalse(self.valid())

    def test_wrong_state_version_after_fails_closed(self):
        self.wal["state_version_after"]=3;self.persist()
        self.assertFalse(self.valid())

    def test_result_meta_wrong_request_fails_closed(self):
        self.wal["result"]["mutation_meta"]["request_sha256"]="a"*64
        self.wal["result_sha256"]=digest(self.wal["result"]);self.persist()
        self.assertFalse(self.valid())

    def test_result_meta_replayed_boolean_rejected(self):
        self.wal["result"]["mutation_meta"]["replayed"]=True
        self.wal["result_sha256"]=digest(self.wal["result"]);self.persist()
        self.assertFalse(self.valid())

    def test_integer_as_boolean_accepted_flag_rejected(self):
        self.wal["result"]["accepted"]=1
        self.wal["result_sha256"]=digest(self.wal["result"]);self.persist()
        self.assertFalse(self.valid())

    def test_mismatched_evidence_count_rejected(self):
        self.wal["result"]["evidence_count"]=1
        self.wal["result_sha256"]=digest(self.wal["result"]);self.persist()
        self.assertFalse(self.valid())

    def test_foreign_source_family_fails_even_with_committed_wal(self):
        self.receipt["source_family"]="official_contact"
        self.assertFalse(self.valid())

    def test_stale_session_pin_fails_even_with_committed_wal(self):
        self.store.append(INV,"SYN_AFTER",{"only":"fixture"})
        self.assertFalse(self.valid())

    def test_corrupt_session_chain_fails_even_with_committed_wal(self):
        p=self.store.path(INV);p.write_text(p.read_text().replace("NEGATIVE_EXHAUSTED","POSITIVE",1))
        self.assertFalse(self.valid())

    def test_untrusted_request_provider_absent_fails_closed(self):
        proof=self.build_proof(provider=lambda e,a,t:None)
        self.assertFalse(self.valid(proof))

    def test_original_request_changed_fails_closed(self):
        self.args["attempt"]["query"]="different query"
        self.assertFalse(self.valid())

    def test_request_argument_tamper_rehashed_not_accepted(self):
        self.args["pivots"]=[{"pivot_id":"SYN-INJECT"}]
        self.assertFalse(self.valid())

    def test_wrong_wal_key_directory_entry_not_accepted(self):
        self.wal["idempotency_key"]="different-idempotency-key"
        self.persist();self.assertFalse(self.valid())

    def test_symlink_wal_record_rejected(self):
        outside=self.root/"outside.json"
        outside.write_text(canonical_json(self.wal))
        self.walpath.unlink()
        try:
            self.walpath.symlink_to(outside)
        except OSError:
            self.skipTest("Windows symlinks unavailable")
        self.assertFalse(self.valid())

    def test_no_unbounded_record_read(self):
        self.walpath.write_bytes(b" "+b"x"*2_000_010)
        self.assertFalse(self.valid())

    def test_atomic_rename_race_never_causes_exception(self):
        """Simulate native atomic WAL PREPARED/COMMITTED replacement."""
        good=canonical_json(self.wal)+"\n"
        bad=canonical_json({**self.wal,"status":"PREPARED"})+"\n"
        stop=threading.Event()
        failures=[]
        outcomes={"replaced":0, "sharing_denied":0}
        def mutate():
            try:
                for k in range(150):
                    temp=self.walroot/(f"synthetic-{k}.tmp")
                    temp.write_text(good if k%2 else bad,encoding="utf8")
                    try:
                        os.replace(temp,self.walpath)
                    except PermissionError as exc:
                        # Windows can deny replace while a different thread
                        # has the WAL file open for reading (WinError 5).
                        # This is a real production-safety caveat, not a
                        # reason to loosen WAL verification.
                        if os.name != "nt":
                            failures.append(type(exc).__name__)
                        outcomes["sharing_denied"] += 1
                        temp.unlink(missing_ok=True)
                    else:
                        outcomes["replaced"] += 1
            except Exception as exc:
                failures.append(type(exc).__name__)
            finally:
                stop.set()
        th=threading.Thread(target=mutate)
        th.start()
        try:
            for _ in range(150):
                # A contested/partial WAL read must never become proof by
                # exception or coercion; only exact, verified rows pass.
                self.assertTrue(self.valid(proof=self.snapshot_proof))
        finally:
            th.join(timeout=8)
        self.assertTrue(stop.is_set(), "bounded writer did not finish")
        self.assertEqual(failures, [], failures)
        self.assertEqual(outcomes["replaced"] + outcomes["sharing_denied"], 150)
        self.assertEqual(
            outcomes["sharing_denied"], 0,
            "Read-only WAL verifier caused atomic writer replacement denial",
        )
        self.assertEqual(outcomes["replaced"], 150)
        # Production usage still requires a trusted Host authority, exact
        # request ownership and independent on-host adversarial acceptance.
        self.wal["status"]="PREPARED";self.persist()
        self.assertFalse(self.valid())

    def test_snapshot_reads_stay_valid_during_live_wal_replacement(self):
        """Reader may accept a complete COMMITTED snapshot, never PREPARED."""
        good=canonical_json(self.wal)+"\n"
        bad=canonical_json({**self.wal,"status":"PREPARED"})+"\n"
        counts={"accepted":0,"rejected":0}
        failures=[]
        stop=threading.Event()
        def mutate():
            try:
                for k in range(90):
                    p=self.walroot/(f"write-race-{k}.tmp")
                    p.write_text(bad if k%2==0 else good,encoding="utf8")
                    os.replace(p,self.walpath)
            except Exception as exc:
                failures.append(type(exc).__name__)
            finally:
                stop.set()
        th=threading.Thread(target=mutate)
        th.start()
        try:
            for _ in range(400):
                outcome=self.valid(proof=self.snapshot_proof)
                self.assertIs(type(outcome),bool)
                self.assertTrue(outcome)
                counts["accepted" if outcome else "rejected"]+=1
                if stop.is_set():
                    break
        finally:
            th.join(timeout=8)
        self.assertFalse(th.is_alive())
        self.assertEqual(failures,[])
        self.assertGreater(counts["accepted"]+counts["rejected"],0)

    def test_symlink_root_is_forbidden(self):
        alt=self.root/"wal-root-symlink"
        try:
            alt.symlink_to(self.walroot, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        from unified_runtime.v61_disk_wal_commit_proof_v64 import make_v61_disk_wal_commit_verifier
        from unified_runtime.host_wal_receipt_verifier_v64 import make_host_wal_receipt_verifier
        cb=make_v61_disk_wal_commit_verifier(
            wal_root=alt,trusted_original_arguments=self.trusted_original
        )
        proof=make_host_wal_receipt_verifier(
            session_store=self.store, investigation_id=INV,account_id=ACCOUNT,
            expected_last_seq=2,expected_last_event_hash=self.event["event_hash"],
            wal_commit_verifier=cb
        )
        self.assertFalse(self.valid(proof))

    def test_snapshot_pin_required_and_wrong_pin_rejected(self):
        p=self.build_snapshot_proof(
            pin_provider=lambda event,attempt,task:"a"*64
        )
        self.assertFalse(self.valid(proof=p))

    def test_snapshot_missing_fails_closed(self):
        (self.snapshot_root/self.walpath.name).unlink()
        self.assertFalse(self.valid(proof=self.snapshot_proof))

    def test_snapshot_tamper_fails_closed(self):
        p=self.snapshot_root/self.walpath.name
        p.write_bytes(p.read_bytes().replace(b"COMMITTED",b"PREPARED ",1))
        self.assertFalse(self.valid(proof=self.snapshot_proof))

    def test_snapshot_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            create_immutable_terminal_wal_snapshot(
                terminal_wal_path=self.walpath,
                snapshot_root=self.snapshot_root,
                expected_request_sha256=self.request_hash,
            )

    def test_prepared_wal_not_snapshotted(self):
        self.wal["status"]="PREPARED";self.persist()
        dest=self.root/"new-immutable";dest.mkdir()
        with self.assertRaises(ValueError):
            create_immutable_terminal_wal_snapshot(
                terminal_wal_path=self.walpath,
                snapshot_root=dest,
                expected_request_sha256=self.request_hash,
            )

    def test_snapshot_wrong_request_digest_rejected(self):
        dest=self.root/"new-immutable";dest.mkdir()
        with self.assertRaises(ValueError):
            create_immutable_terminal_wal_snapshot(
                terminal_wal_path=self.walpath,
                snapshot_root=dest,
                expected_request_sha256="a"*64,
            )

    def test_snapshot_stays_verified_if_live_wal_deleted(self):
        self.walpath.unlink()
        self.assertTrue(self.valid(proof=self.snapshot_proof))
        self.assertFalse(self.valid())

    def test_post_read_atomic_commit_is_visible_and_verified(self):
        """After the read closes, replacement of PREPARED by COMMITTED works."""
        self.wal["status"]="PREPARED";self.persist()
        self.assertFalse(self.valid())
        self.wal["status"]="COMMITTED"
        tmp=self.walroot/"synthetic-terminal.tmp"
        tmp.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        os.replace(tmp,self.walpath)
        self.assertTrue(self.valid())

if __name__=="__main__":
    unittest.main()
