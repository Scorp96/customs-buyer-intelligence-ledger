"""Isolated Host postcommit request/pin archive contract.

All original requests and credentials are synthetic. The barrier callback is a
fixture, not production authorization. Tests do not modify real WAL or CRM.
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
from unified_runtime.host_postcommit_archive_v64 import IsolatedHostReceiptAuthority
from unified_runtime.host_archive_recovery_v64 import resume_authorized_partial_archive
from unified_runtime.host_wal_receipt_verifier_v64 import make_host_wal_receipt_verifier
from unified_runtime.v61_disk_wal_commit_proof_v64 import make_v61_disk_wal_commit_verifier
from unified_runtime.source_execution import evaluate_source_coverage

INV="INV-20261015T140000Z-abcdef123456"
OWNER="SYN-OWNER-ONLY"
TOOL="append_execution_receipt"
KEY="SYN-POSTCOMMIT-KEY-001"


class HostPostcommitArchiveTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix="cbi-host-pin-fixture-")
        self.root=Path(self.t.name)
        self.s=SessionStore(self.root/"sessions")
        self.s.create({"investigation_id":INV,"account":{"account_id":OWNER}})
        self.walroot=self.root/"live-wal"
        self.request_root=self.root/"original-requests"
        self.snapshot_root=self.root/"wal-snapshots"
        self.pin_root=self.root/"external-pin-fixture"
        for p in (self.walroot,self.request_root,self.snapshot_root,self.pin_root):
            p.mkdir()
        self.task={
            "call_id":"V63CALL-SYN-PIN-1",
            "branch_group":"TRADE_GRAPH","branch":"same_supplier_buyer",
            "source_family":"trade_history","query":"synthetic no external buyer",
        }
        self.attempt={**self.task,"investigation_id":INV,"owner_id":OWNER,
            "module_or_branch":"trade_supplier_continuity",
            "attempt_id":"SYN-PIN-A1","execution_id":"SYN-PIN-E1",
            "completed_at":"2026-10-15T14:00:00Z","result":"NEGATIVE_EXHAUSTED",
            "content_sha256":"f"*64,"raw_result_locator":"synthetic://raw-safe",
            "evidence_ids":[],"blocked_reason":""}
        self.args={"idempotency_key":KEY,"investigation_id":INV,
            "attempt":copy.deepcopy(self.attempt),"evidence":[],
            "pivots":[],"pivots_consumed":[],
            "manual_visual_items_resolved":[],
            "private_synthetic_secret":"NOT_FOR_PUBLIC_RECEIPT"}
        self.correlation="MUTCORR-"+hashlib.sha256(f"{TOOL}:{KEY}".encode()).hexdigest()[:24]
        prior=self.s.read(INV)[-1]
        event={"seq":2,"prev_hash":prior["event_hash"],
            "event_type":"EXECUTION_RECEIPT_APPENDED",
            "recorded_at":"2026-10-15T14:00:00Z",
            "payload":{"attempt":copy.deepcopy(self.attempt),"evidence":[],
                       "pivots_generated":[],"pivots_consumed":[]},
            "mutation_correlation":{"schema":"cbi.mutation-correlation.v6.1",
                "correlation_id":self.correlation,"tool":TOOL}}
        event["event_hash"]=digest(event)
        with self.s.path(INV).open("a",encoding="utf8") as handle:
            handle.write(canonical_json(event)+"\n")
        self.event=event
        material={k:v for k,v in self.args.items() if k!="idempotency_key"}
        self.req_hash=digest({"tool":TOOL,"arguments":material})
        self.result={"accepted":True,"attempt_id":self.attempt["attempt_id"],
            "evidence_count":0,"mutation_meta":{
            "schema":"cbi.mutation-meta.v6.1","tool":TOOL,
            "idempotency_key":KEY,"request_sha256":self.req_hash,
            "state_version_before":1,"state_version_after":2,
            "write_ahead_intent":True,"replayed":False}}
        self.wal={"schema":"cbi.mutation-wal.v6.1","status":"COMMITTED","tool":TOOL,
            "idempotency_key":KEY,"request_sha256":self.req_hash,
            "state_version_before":1,"state_version_after":2,
            "mutation_correlation_id":self.correlation,
            "result":self.result,"result_sha256":digest(self.result)}
        self.wal_name=f"{TOOL}-{hashlib.sha256(KEY.encode()).hexdigest()}.json"
        self.walpath=self.walroot/self.wal_name
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self.operator_anchor_hash=None
        self.anchor_enabled=True
        self.anchor_raises=False
        self.authority=IsolatedHostReceiptAuthority(
            session_store=self.s,request_root=self.request_root,
            snapshot_root=self.snapshot_root,pin_root=self.pin_root,
            independent_operator_anchor=self.trusted_operator_fixture,
        )
        self.release_granted=True

    def tearDown(self):
        self.t.cleanup()

    def trusted_operator_fixture(self, canonical_pin_hash, event, task):
        # Synthetic *external* operator register held in fixture memory.
        # This is not a real signature, RBAC or independently controlled host.
        if self.anchor_raises:
            raise OSError("synthetic external authority unavailable")
        return (
            self.anchor_enabled
            and self.operator_anchor_hash == canonical_pin_hash
            and event.get("event_hash") == self.event["event_hash"]
            and task == self.task
        )

    def fixture_independently_pin(self):
        # Separate fixture act after publish, before any trusted read.
        # Never give this authority to the receipt claimant in production.
        from unified_runtime.core import canonical_json
        data=json.loads(next(self.pin_root.glob("*.pin.json")).read_text(encoding="utf8"))
        self.operator_anchor_hash=hashlib.sha256(canonical_json(data).encode("utf8")).hexdigest()

    def barrier(self,event,args,task):
        # Synthetic Host writes COMMITTED before unlocking. This is NOT proof
        # of real production locks or independently anchored operator action.
        return bool(self.release_granted and
            event.get("event_hash")==self.event["event_hash"]
            and args.get("idempotency_key")==KEY
            and task==self.task
            and json.loads(self.walpath.read_text())["status"]=="COMMITTED")

    def publish(self,*,fixture_operator_pin=True,**kw):
        params={"wal_root":self.walroot,"original_arguments":self.args,
            "task":self.task,"event":self.event,"account_id":OWNER,
            "expected_last_seq":2,"expected_last_hash":self.event["event_hash"],
            "trusted_postcommit_barrier":self.barrier}
        params.update(kw)
        result=self.authority.publish_from_host_wal(**params)
        if fixture_operator_pin:
            self.fixture_independently_pin()
        return result

    def read(self,event=None,task=None):
        return self.authority.read_host_binding(
            event=self.event if event is None else event,
            task=self.task if task is None else task,
            idempotency_key=KEY)

    def proof(self):
        def args_provider(ev,attempt,task):
            return self.read(ev,task)[0]
        def pin_provider(ev,attempt,task):
            return self.read(ev,task)[1]
        walcb=make_v61_disk_wal_commit_verifier(
            wal_root=self.walroot,trusted_original_arguments=args_provider,
            immutable_snapshot_root=self.snapshot_root,
            trusted_snapshot_sha256=pin_provider)
        return make_host_wal_receipt_verifier(
            session_store=self.s,investigation_id=INV,account_id=OWNER,
            expected_last_seq=2,expected_last_event_hash=self.event["event_hash"],
            wal_commit_verifier=walcb)

    def covered(self):
        receipt={**self.attempt,"account_id":OWNER,
            "event_seq":2,"event_hash":self.event["event_hash"]}
        return evaluate_source_coverage(
            {"tasks":[self.task],"truncated":False},
            [receipt],receipt_verifier=self.proof())["source_coverage_complete"]

    # Isolated partial-archive recovery: the fixture "operator" is not a
    # real authority; all source/ledger/WAL records are synthetic.
    def _external_recovery_record(self):
        from unified_runtime.host_postcommit_archive_v64 import _file_ids
        wal_name, request_name, pin_name, commit_name = _file_ids(KEY)
        shadow = self.snapshot_root / wal_name
        snap_sha = hashlib.sha256(shadow.read_bytes()).hexdigest()
        pin = {
            "schema": "cbi.host-wal-postcommit-pin.isolated.v1",
            "wal_filename": wal_name,
            "original_arguments_sha256": digest(self.args),
            "request_sha256": self.req_hash,
            "snapshot_sha256": snap_sha,
            "investigation_id": INV,
            "account_id": OWNER,
            "event_seq": 2,
            "event_hash": self.event["event_hash"],
            "task_digest": digest(self.task),
            "status": "PINNED_FOR_ISOLATED_VALIDATION",
        }
        return {
            "approved": True,
            "expected_snapshot_sha256": snap_sha,
            "expected_pin_sha256": hashlib.sha256(canonical_json(pin).encode()).hexdigest(),
            "expected_request_sha256": self.req_hash,
            "expected_event_hash": self.event["event_hash"],
            "expected_task_digest": digest(self.task),
            "expected_account_id": OWNER,
            "expected_investigation_id": INV,
            "expected_session_tail_hash": self.event["event_hash"],
            "expected_last_seq": 2,
        }

    def _interrupt_publish(self, stage):
        from unittest.mock import patch
        from unified_runtime import host_postcommit_archive_v64 as module
        real = module._create_once
        def fail_at(root, filename, value):
            if filename.endswith(stage):
                raise OSError("SYNTHETIC_INTERRUPT_BEFORE_" + stage)
            return real(root, filename, value)
        with patch.object(module, "_create_once", side_effect=fail_at):
            with self.assertRaisesRegex(OSError, "SYNTHETIC_INTERRUPT_BEFORE"):
                self.publish(fixture_operator_pin=False)

    def _resume_partial(self, authorizer=None, **updates):
        params = {
            "authority": self.authority,
            "original_arguments": self.args,
            "task": self.task,
            "event": self.event,
            "account_id": OWNER,
            "expected_last_seq": 2,
            "expected_last_hash": self.event["event_hash"],
            "trusted_postcommit_barrier": self.barrier,
            "trusted_recovery_authorization": (
                authorizer if authorizer is not None
                else lambda ev, args, task: self._external_recovery_record()
            ),
        }
        params.update(updates)
        return resume_authorized_partial_archive(**params)

    def test_recovery_snapshot_only_after_request_interrupt(self):
        self._interrupt_publish(".request.json")
        r = self._resume_partial()
        self.assertEqual(r["status"], "ISOLATED_PARTIAL_RECOVERY_PUBLISHED")
        self.assertEqual(r["new_files_created"], 3)
        self.assertFalse(r["independent_operator_authority_proven"])
        self.assertFalse(self.covered())
        self.fixture_independently_pin()
        self.assertTrue(self.covered())

    def test_recovery_snapshot_request_after_pin_interrupt(self):
        self._interrupt_publish(".pin.json")
        r = self._resume_partial()
        self.assertEqual(r["new_files_created"], 2)
        self.fixture_independently_pin()
        self.assertTrue(self.covered())

    def test_recovery_snapshot_request_pin_after_commit_interrupt(self):
        self._interrupt_publish(".commit.json")
        r = self._resume_partial()
        self.assertEqual(r["new_files_created"], 1)
        self.fixture_independently_pin()
        self.assertTrue(self.covered())

    def test_recovery_complete_archive_requires_operator_anchor(self):
        self.publish(fixture_operator_pin=False)
        with self.assertRaises(PermissionError):
            self._resume_partial()
        self.fixture_independently_pin()
        x = self._resume_partial()
        self.assertEqual(x["status"], "ALREADY_PUBLISHED_VERIFIED")
        self.assertEqual(x["new_files_created"], 0)
        self.assertTrue(self.covered())

    def test_recovery_multiple_retries_do_not_create_more_files(self):
        self._interrupt_publish(".commit.json")
        self._resume_partial()
        self.fixture_independently_pin()
        originals = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in (self.request_root,self.snapshot_root,self.pin_root)
            for p in root.iterdir()
        }
        for _ in range(3):
            self.assertEqual(self._resume_partial()["new_files_created"], 0)
        self.assertEqual(originals, {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in (self.request_root,self.snapshot_root,self.pin_root)
            for p in root.iterdir()
        })

    def test_recovery_authorization_absent_stays_partial(self):
        self._interrupt_publish(".commit.json")
        with self.assertRaises(PermissionError):
            self._resume_partial(trusted_recovery_authorization=None)
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_authorization_denied_stays_partial(self):
        self._interrupt_publish(".commit.json")
        with self.assertRaises(PermissionError):
            self._resume_partial(authorizer=lambda *args: {"approved":False})
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_authorization_exception_stays_partial(self):
        self._interrupt_publish(".commit.json")
        def unavailable(*args):
            raise OSError("SYNTHETIC_OPERATOR_DISCONNECTED")
        with self.assertRaises(PermissionError):
            self._resume_partial(authorizer=unavailable)
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_wrong_external_snapshot_pin_fails(self):
        self._interrupt_publish(".pin.json")
        def tamper(ev, args, task):
            x=self._external_recovery_record()
            x["expected_snapshot_sha256"]="0"*64
            return x
        with self.assertRaises((ValueError,PermissionError)):
            self._resume_partial(authorizer=tamper)
        self.assertEqual(list(self.pin_root.glob("*.pin.json")),[])

    def test_recovery_wrong_external_manifest_pin_fails(self):
        self._interrupt_publish(".pin.json")
        def tamper(ev, args, task):
            x=self._external_recovery_record()
            x["expected_pin_sha256"]="0"*64
            return x
        with self.assertRaises(PermissionError):
            self._resume_partial(authorizer=tamper)
        self.assertEqual(list(self.pin_root.glob("*.pin.json")),[])

    def test_recovery_wrong_expected_task_fails(self):
        self._interrupt_publish(".commit.json")
        with self.assertRaises(PermissionError):
            self._resume_partial(task={**self.task, "source_family":"competitor"})
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_corrupt_existing_request_stops_without_overwrite(self):
        self._interrupt_publish(".commit.json")
        p=next(self.request_root.iterdir())
        raw=json.loads(p.read_text())
        raw["private_synthetic_secret"]="CHANGED"
        p.write_text(canonical_json(raw)+"\n")
        altered=hashlib.sha256(p.read_bytes()).hexdigest()
        with self.assertRaises(PermissionError):
            self._resume_partial()
        self.assertEqual(altered, hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_corrupt_existing_pin_stops_without_overwrite(self):
        self._interrupt_publish(".commit.json")
        p=next(self.pin_root.glob("*.pin.json"))
        raw=json.loads(p.read_text()); raw["status"]="REISSUED"
        p.write_text(canonical_json(raw)+"\n")
        with self.assertRaises(PermissionError):
            self._resume_partial()
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_snapshot_tamper_rejected_before_new_files(self):
        self._interrupt_publish(".request.json")
        # The operator pin MUST be fixed *before* the hostile mutation.
        # Recomputing it from the tampered snapshot would manufacture proof.
        pre_pinned = copy.deepcopy(self._external_recovery_record())
        p=next(self.snapshot_root.iterdir())
        p.write_bytes(p.read_bytes()+b"\n")
        with self.assertRaises((PermissionError,ValueError,OSError)):
            self._resume_partial(
                authorizer=lambda event,args,task: copy.deepcopy(pre_pinned)
            )
        self.assertEqual(list(self.request_root.iterdir()),[])

    def test_recovery_cannot_recompute_operator_pin_after_request_tamper(self):
        self._interrupt_publish(".commit.json")
        operator_pin = copy.deepcopy(self._external_recovery_record())
        p=next(self.request_root.iterdir())
        value=json.loads(p.read_text(encoding="utf8"))
        value["private_synthetic_secret"]="TAMPERED"
        p.write_text(canonical_json(value)+"\n",encoding="utf8")
        with self.assertRaises(PermissionError):
            self._resume_partial(
                authorizer=lambda event,args,task: copy.deepcopy(operator_pin)
            )
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_missing_snapshot_stops_for_custody_review(self):
        self._interrupt_publish(".commit.json")
        next(self.snapshot_root.iterdir()).unlink()
        with self.assertRaises(PermissionError):
            self._resume_partial()
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_without_partial_does_not_implicitly_publish(self):
        with self.assertRaises(FileNotFoundError):
            self._resume_partial()
        self.assertEqual(list(self.snapshot_root.iterdir()),[])

    def test_recovery_out_of_order_archive_stops(self):
        self._interrupt_publish(".commit.json")
        next(self.request_root.iterdir()).unlink()
        with self.assertRaises(PermissionError):
            self._resume_partial()
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_stale_independent_session_tail_fails(self):
        self._interrupt_publish(".commit.json")
        with self.assertRaises(PermissionError):
            self._resume_partial(expected_last_hash="0"*64)
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_barrier_denial_does_not_publish(self):
        self._interrupt_publish(".commit.json")
        self.release_granted=False
        with self.assertRaises(PermissionError):
            self._resume_partial()
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])

    def test_recovery_mid_retry_interrupt_and_resume_again(self):
        self._interrupt_publish(".request.json")
        from unittest.mock import patch
        from unified_runtime import host_archive_recovery_v64 as module
        real=module._create_once
        def fail_mid(root,filename,value):
            if filename.endswith(".pin.json"):
                raise OSError("INJECTED_SECOND_INTERRUPT")
            return real(root,filename,value)
        with patch.object(module,"_create_once",side_effect=fail_mid):
            with self.assertRaisesRegex(OSError,"INJECTED_SECOND_INTERRUPT"):
                self._resume_partial()
        self.assertEqual(len(list(self.request_root.iterdir())),1)
        self.assertEqual(len(list(self.pin_root.iterdir())),0)
        r=self._resume_partial()
        self.assertEqual(r["new_files_created"],2)
        self.fixture_independently_pin()
        self.assertTrue(self.covered())

    def test_publication_commit_marker_required(self):
        self.publish()
        marker=next(self.pin_root.glob("*.commit.json"))
        marker.unlink()
        self.assertFalse(self.covered())

    def test_publication_commit_marker_identity_is_immutable(self):
        self.publish()
        marker=next(self.pin_root.glob("*.commit.json"))
        raw=json.loads(marker.read_text(encoding="utf8"))
        raw["task_digest"]="0"*64
        marker.write_text(canonical_json(raw)+"\n",encoding="utf8")
        self.assertFalse(self.covered())

    def test_publication_marker_wrong_status_cannot_close(self):
        self.publish()
        marker=next(self.pin_root.glob("*.commit.json"))
        raw=json.loads(marker.read_text(encoding="utf8"))
        raw["status"]="PREPARED"
        marker.write_text(canonical_json(raw)+"\n",encoding="utf8")
        self.assertFalse(self.covered())

    def test_interruption_before_commit_marker_is_a_non_authoritative_partial_archive(self):
        from unittest.mock import patch
        from unified_runtime import host_postcommit_archive_v64 as module
        original_create=module._create_once
        def injected(root, filename, value):
            if filename.endswith(".commit.json"):
                raise OSError("CI_INJECTED_POWER_FAILURE_BEFORE_COMMIT")
            return original_create(root, filename, value)
        with patch.object(module,"_create_once",side_effect=injected):
            with self.assertRaisesRegex(OSError,"CI_INJECTED_POWER_FAILURE_BEFORE_COMMIT"):
                self.publish()
        self.assertEqual(len(list(self.snapshot_root.iterdir())),1)
        self.assertEqual(len(list(self.request_root.iterdir())),1)
        self.assertEqual(len(list(self.pin_root.glob("*.pin.json"))),1)
        self.assertEqual(len(list(self.pin_root.glob("*.commit.json"))),0)
        self.fixture_independently_pin()
        self.assertFalse(self.covered())
        with self.assertRaises(FileExistsError):
            self.publish()

    def test_committed_marker_exists_only_after_full_publish(self):
        self.assertEqual(list(self.pin_root.glob("*.commit.json")),[])
        self.publish()
        marker=next(self.pin_root.glob("*.commit.json"))
        data=json.loads(marker.read_text(encoding="utf8"))
        self.assertEqual(data["status"],"PUBLISHED")
        self.assertEqual(data["event_hash"],self.event["event_hash"])
        self.assertTrue(self.covered())

    def test_default_missing_external_operator_anchor_is_not_proof(self):
        alternate=IsolatedHostReceiptAuthority(
            session_store=self.s,request_root=self.request_root,
            snapshot_root=self.snapshot_root,pin_root=self.pin_root,
        )
        self.publish()
        with self.assertRaises(PermissionError):
            alternate.read_host_binding(
                event=self.event,task=self.task,idempotency_key=KEY)

    def test_new_archive_without_external_pin_does_not_close(self):
        self.publish(fixture_operator_pin=False)
        self.assertFalse(self.covered())
        self.fixture_independently_pin()
        self.assertTrue(self.covered())

    def test_external_operator_anchor_denial_fails_closed(self):
        self.publish()
        self.anchor_enabled=False
        self.assertFalse(self.covered())

    def test_external_operator_anchor_exception_fails_closed(self):
        self.publish()
        self.anchor_raises=True
        self.assertFalse(self.covered())

    def test_wrong_external_anchor_hash_fails_closed(self):
        self.publish()
        self.operator_anchor_hash="0"*64
        self.assertFalse(self.covered())

    def test_claimant_verified_flag_cannot_replace_operator_anchor(self):
        self.publish(fixture_operator_pin=False)
        pin=next(self.pin_root.glob("*.pin.json"))
        value=json.loads(pin.read_text(encoding="utf8"))
        value["operator_verified"]=True
        pin.write_text(canonical_json(value)+"\n",encoding="utf8")
        self.assertFalse(self.covered())

    def test_archive_pin_after_anchor_cannot_be_reissued_without_new_auth(self):
        self.publish()
        pin=next(self.pin_root.glob("*.pin.json"))
        value=json.loads(pin.read_text(encoding="utf8"))
        value["operator_verified"]=True
        pin.write_text(canonical_json(value)+"\n",encoding="utf8")
        self.assertFalse(self.covered())

    def test_host_postcommit_archive_full_chain(self):
        result=self.publish()
        self.assertEqual(result["status"],"ISOLATED_PIN_CREATED")
        self.assertTrue(self.covered())
        self.assertFalse(result["independent_operator_authority_proven"])

    def test_barrier_denial_creates_nothing(self):
        self.release_granted=False
        with self.assertRaises(PermissionError):self.publish()
        self.assertEqual(list(self.snapshot_root.iterdir()),[])
        self.assertEqual(list(self.pin_root.iterdir()),[])

    def test_barrier_missing_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.publish(trusted_postcommit_barrier=None)

    def test_pending_wal_cannot_be_archived(self):
        self.wal["status"]="PREPARED"
        self.walpath.write_text(canonical_json(self.wal)+"\n")
        with self.assertRaises((PermissionError,ValueError)):self.publish()

    def test_wal_committed_error_cannot_be_archived(self):
        self.wal["status"]="COMMITTED_ERROR"
        self.walpath.write_text(canonical_json(self.wal)+"\n")
        with self.assertRaises((PermissionError,ValueError)):self.publish()

    def test_original_attempt_owner_mismatch(self):
        tamper=copy.deepcopy(self.args)
        tamper["attempt"]["owner_id"]="DIFFERENT"
        with self.assertRaises(PermissionError):
            self.publish(original_arguments=tamper)

    def test_original_attempt_task_mismatch(self):
        tamper=copy.deepcopy(self.args)
        tamper["attempt"]["source_family"]="maps"
        with self.assertRaises(PermissionError):
            self.publish(original_arguments=tamper)

    def test_wrong_external_tail_pin_blocks_archive(self):
        with self.assertRaises(PermissionError):
            self.publish(expected_last_hash="1"*64)

    def test_wrong_account_blocks_archive(self):
        with self.assertRaises(PermissionError):
            self.publish(account_id="OTHER_OWNER")

    def test_duplicate_publish_never_overwrites(self):
        self.publish()
        with self.assertRaises(FileExistsError):self.publish()
        self.assertTrue(self.covered())

    def test_archive_request_tamper_detected(self):
        self.publish()
        path=next(self.request_root.iterdir())
        contents=json.loads(path.read_text())
        contents["private_synthetic_secret"]="MODIFIED"
        path.write_text(canonical_json(contents)+"\n")
        self.assertFalse(self.covered())

    def test_pin_digest_tamper_detected(self):
        self.publish()
        path=next(self.pin_root.glob("*.pin.json"))
        contents=json.loads(path.read_text())
        contents["snapshot_sha256"]="0"*64
        path.write_text(canonical_json(contents)+"\n")
        self.assertFalse(self.covered())

    def test_snapshot_tamper_detected(self):
        self.publish()
        path=next(self.snapshot_root.iterdir())
        path.write_bytes(path.read_bytes()+b" ")
        self.assertFalse(self.covered())

    def test_removed_pin_fails_closed(self):
        self.publish()
        next(self.pin_root.glob("*.pin.json")).unlink()
        self.assertFalse(self.covered())

    def test_removed_original_request_fails_closed(self):
        self.publish()
        next(self.request_root.iterdir()).unlink()
        self.assertFalse(self.covered())

    def test_wrong_call_id_cannot_reuse_pin(self):
        self.publish()
        with self.assertRaises(PermissionError):
            self.read(task={**self.task,"call_id":"V63CALL-OTHER"})

    def test_no_private_request_leaked_in_public_receipt(self):
        response=self.publish()
        self.assertNotIn("private_synthetic_secret",json.dumps(response))
        self.assertNotIn("NOT_FOR_PUBLIC_RECEIPT",json.dumps(response))
        self.assertTrue(any(b"NOT_FOR_PUBLIC_RECEIPT" in p.read_bytes() for p in self.request_root.iterdir()))

    def test_same_live_wal_replaced_after_snapshot_still_proves_pin(self):
        self.publish()
        self.wal["status"]="PREPARED"
        self.walpath.write_text(canonical_json(self.wal)+"\n")
        self.assertTrue(self.covered())

    def test_snapshot_read_under_concurrent_live_wal_churn(self):
        self.publish()
        records=[canonical_json(self.wal)+"\n",
                 canonical_json({**self.wal,"status":"PREPARED"})+"\n"]
        errors=[]
        def writer():
            try:
                for i in range(100):
                    temp=self.walroot/f"postcommit-writer-{i}.tmp"
                    temp.write_text(records[i%2],encoding="utf8")
                    os.replace(temp,self.walpath)
            except Exception as exc:
                errors.append(type(exc).__name__)
        th=threading.Thread(target=writer)
        th.start()
        try:
            for _ in range(100):
                self.assertTrue(self.covered())
        finally:
            th.join(timeout=8)
        self.assertFalse(th.is_alive())
        self.assertEqual(errors,[])

    def test_symlink_request_root_is_rejected(self):
        alt=self.root/"fake-requests"
        try:alt.symlink_to(self.request_root,target_is_directory=True)
        except OSError:self.skipTest("Windows symlink creation blocked")
        with self.assertRaises(OSError):
            IsolatedHostReceiptAuthority(
                session_store=self.s,request_root=alt,
                snapshot_root=self.snapshot_root,pin_root=self.pin_root)

    def test_all_authority_directories_must_be_distinct(self):
        with self.assertRaises(ValueError):
            IsolatedHostReceiptAuthority(
                session_store=self.s,request_root=self.pin_root,
                snapshot_root=self.snapshot_root,pin_root=self.pin_root)

    def test_unauthorized_wal_location_cannot_be_supplied_in_request(self):
        tamper=copy.deepcopy(self.args)
        tamper["_internal_wal_path"]=str(self.root/"other")
        with self.assertRaises((PermissionError,ValueError)):
            self.publish(original_arguments=tamper)


    def _assert_bad_terminal_wal_never_occupies_archive(self):
        with self.assertRaises(PermissionError):
            self.publish()
        self.assertEqual(list(self.request_root.iterdir()), [])
        self.assertEqual(list(self.snapshot_root.iterdir()), [])
        self.assertEqual(list(self.pin_root.iterdir()), [])

    def test_corrupted_terminal_result_digest_does_not_poison_archive(self):
        self.wal["result_sha256"]="0"*64
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self._assert_bad_terminal_wal_never_occupies_archive()

    def test_accepted_false_terminal_result_does_not_poison_archive(self):
        self.wal["result"]["accepted"]=False
        self.wal["result_sha256"]=digest(self.wal["result"])
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self._assert_bad_terminal_wal_never_occupies_archive()

    def test_wrong_state_version_terminal_does_not_poison_archive(self):
        self.wal["state_version_after"]=3
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self._assert_bad_terminal_wal_never_occupies_archive()

    def test_wrong_mutation_correlation_terminal_does_not_poison_archive(self):
        self.wal["mutation_correlation_id"]="MUTCORR-FOREIGN"
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self._assert_bad_terminal_wal_never_occupies_archive()

    def test_false_write_ahead_intent_terminal_does_not_poison_archive(self):
        self.wal["result"]["mutation_meta"]["write_ahead_intent"]=False
        self.wal["result_sha256"]=digest(self.wal["result"])
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self._assert_bad_terminal_wal_never_occupies_archive()

    def test_wrong_attempt_id_terminal_does_not_poison_archive(self):
        self.wal["result"]["attempt_id"]="SYN-OTHER-ATTEMPT"
        self.wal["result_sha256"]=digest(self.wal["result"])
        self.walpath.write_text(canonical_json(self.wal)+"\n",encoding="utf8")
        self._assert_bad_terminal_wal_never_occupies_archive()


if __name__=="__main__":
    unittest.main()
