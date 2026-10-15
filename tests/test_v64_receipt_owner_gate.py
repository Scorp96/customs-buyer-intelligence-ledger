"""Stage-5 receipt provenance/scope fail-closed tests.

The synthetic callback simulates an independently authenticated ledger-origin
verifier. No fixture is real trade evidence and no production state is written.
"""
from __future__ import annotations
import copy
import unittest

from unified_runtime.source_execution import evaluate_source_coverage
from unified_runtime.contact_source_execution import evaluate_contact_coverage

def synthetic_host_ledger_verifier(task, receipt):
    # CI-only imitation of a trusted host evidence lookup.
    return (
        receipt.get("fixture_event_id") == "CI-EVENT:" + str(
            task.get("call_id") or task.get("task_id"))
        and receipt.get("fixture_ledger_owner") == "SYNTHETIC-ACCOUNT-01"
    )

def rejecting_verifier(task, receipt):
    return False

def raising_verifier(task, receipt):
    raise ValueError("simulated host ledger unavailable")

class SourceFamilyReceiptSecurity(unittest.TestCase):
    def plan(self):
        return {
            "truncated": False,
            "tasks": [{
                "call_id": "V63CALL-LOCAL-1", "branch_group": "TRADE_GRAPH",
                "branch": "same_supplier_buyer", "source_family": "trade_history",
                "query": "synthetic trade history only",
            }]
        }
    def receipt(self, **overrides):
        d = {
            **self.plan()["tasks"][0],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-10-15T00:00:00Z",
            "raw_result_locator": "synthetic://raw/C1",
            "fixture_event_id": "CI-EVENT:V63CALL-LOCAL-1",
            "fixture_ledger_owner": "SYNTHETIC-ACCOUNT-01",
        }
        d.update(overrides)
        return d
    def eval(self, receipt, verifier=synthetic_host_ledger_verifier, plan=None):
        return evaluate_source_coverage(
            self.plan() if plan is None else plan,
            [receipt], receipt_verifier=verifier)

    def test_untrusted_negative_never_closes(self):
        r=self.eval(self.receipt(), verifier=None)
        self.assertFalse(r["source_coverage_complete"])
        self.assertEqual(r["status"],"AUTHORITATIVE_RECEIPT_VERIFIER_REQUIRED")

    def test_caller_verified_flag_without_verifier_not_proof(self):
        self.assertFalse(self.eval(self.receipt(verified=True), verifier=None)["source_coverage_complete"])

    def test_synthetic_verified_negative_can_close(self):
        r=self.eval(self.receipt())
        self.assertTrue(r["source_coverage_complete"])
        self.assertTrue(r["authoritative_receipt_verifier_supplied"])

    def test_positive_receipt_needs_real_evidence_ids_even_with_verifier(self):
        self.assertFalse(self.eval(self.receipt(result="POSITIVE", evidence_ids=[]))["source_coverage_complete"])
        self.assertTrue(self.eval(self.receipt(result="POSITIVE", evidence_ids=["E-CI-1"]))["source_coverage_complete"])

    def test_not_applicable_requires_verified_reason(self):
        self.assertFalse(self.eval(self.receipt(result="NOT_APPLICABLE_JUSTIFIED",raw_result_locator="",
                                                 not_applicable_reason=""))["source_coverage_complete"])
        self.assertTrue(self.eval(self.receipt(result="NOT_APPLICABLE_JUSTIFIED",raw_result_locator="",
                                                not_applicable_reason="Synthetic jurisdiction not applicable"))["source_coverage_complete"])

    def test_wrong_family_rejected_even_if_stub_approves(self):
        self.assertFalse(self.eval(self.receipt(source_family="maps_region"))["source_coverage_complete"])

    def test_wrong_branch_rejected_even_if_stub_approves(self):
        self.assertFalse(self.eval(self.receipt(branch="competitor_customer"))["source_coverage_complete"])

    def test_wrong_branch_group_rejected(self):
        self.assertFalse(self.eval(self.receipt(branch_group="CROSS_SELL_GRAPH"))["source_coverage_complete"])

    def test_wrong_query_rejected(self):
        self.assertFalse(self.eval(self.receipt(query="unrelated synthetic query"))["source_coverage_complete"])

    def test_incomplete_negative_has_no_raw_proof(self):
        self.assertFalse(self.eval(self.receipt(raw_result_locator=""))["source_coverage_complete"])

    def test_receipt_for_other_task_does_not_close(self):
        self.assertFalse(self.eval(self.receipt(call_id="V63CALL-OTHER"))["source_coverage_complete"])

    def test_blocked_receipt_cannot_be_relabelled_na(self):
        receipts=[self.receipt(result="BLOCKED",blocked_reason="LOGIN_REQUIRED"),
                  self.receipt(result="NOT_APPLICABLE_JUSTIFIED",not_applicable_reason="arbitrary")]
        r=evaluate_source_coverage(self.plan(),receipts,receipt_verifier=synthetic_host_ledger_verifier)
        self.assertFalse(r["source_coverage_complete"])

    def test_both_negative_and_blocked_same_call_keep_open(self):
        receipts=[self.receipt(),self.receipt(result="BLOCKED",blocked_reason="AUTHORIZATION_REQUIRED")]
        r=evaluate_source_coverage(self.plan(),receipts,receipt_verifier=synthetic_host_ledger_verifier)
        self.assertFalse(r["source_coverage_complete"])

    def test_untrusted_callback_false_keeps_incomplete(self):
        self.assertFalse(self.eval(self.receipt(),verifier=rejecting_verifier)["source_coverage_complete"])

    def test_verifier_exception_fails_closed(self):
        self.assertFalse(self.eval(self.receipt(),verifier=raising_verifier)["source_coverage_complete"])

    def test_duplicate_task_ids_do_not_prove_completion(self):
        p=self.plan()
        p["tasks"].append(copy.deepcopy(p["tasks"][0]))
        r=self.eval(self.receipt(),plan=p)
        self.assertFalse(r["source_coverage_complete"])
        self.assertEqual(r["status"],"INVALID_OR_DUPLICATE_SOURCE_TASK_IDENTITIES")

    def test_false_string_truncated_plan_stays_incomplete(self):
        p=self.plan()
        p["truncated"]="false"
        self.assertFalse(self.eval(self.receipt(),plan=p)["source_coverage_complete"])

class ContactReceiptSecurity(unittest.TestCase):
    def plan(self):
        return {
            "truncated":False,
            "company_route_required_for_completion":True,
            "named_route_required_for_completion":False,
            "initial_company_route_ready":False,
            "initial_named_route_ready":False,
            "tasks":[{
                "task_id":"CI-CONTACT-T1","opportunity_id":"SYNTHETIC-OPP-1",
                "route_target":"COMPANY","source_family":"official_contact",
                "company_name":"Synthetic Company", "required_for_completion":True,
            }]
        }
    def receipt(self, **updates):
        d={
            **self.plan()["tasks"][0],
            "result":"NEGATIVE_EXHAUSTED",
            "completed_at":"2026-10-15T00:00:00Z",
            "raw_result_locator":"synthetic://raw/C2",
            "fixture_event_id":"CI-EVENT:CI-CONTACT-T1",
            "fixture_ledger_owner":"SYNTHETIC-ACCOUNT-01",
        }
        d.update(updates)
        return d
    def eval(self, receipts, verifier=synthetic_host_ledger_verifier, plan=None):
        return evaluate_contact_coverage(
            self.plan() if plan is None else plan, receipts,
            receipt_verifier=verifier)

    def test_no_backend_verifier_never_closes_negative(self):
        r=self.eval([self.receipt()],verifier=None)
        self.assertFalse(r["contact_exhaustion_complete"])
        self.assertEqual(r["completion_reason"],"AUTHORITATIVE_RECEIPT_VERIFIER_REQUIRED")

    def test_host_verified_negative_can_close(self):
        r=self.eval([self.receipt()])
        self.assertTrue(r["contact_exhaustion_complete"])
        self.assertEqual(r["completion_reason"],"REQUIRED_CONTACT_SOURCES_EXHAUSTED")

    def test_host_verified_na_can_close_if_not_blocked(self):
        r=self.eval([self.receipt(result="NOT_APPLICABLE_JUSTIFIED",raw_result_locator="",
                                   not_applicable_reason="Synthetic regional jurisdiction proof")])
        self.assertTrue(r["contact_exhaustion_complete"])

    def test_na_cannot_override_blocked_source(self):
        rs=[self.receipt(result="BLOCKED",blocked_reason="LOGIN_REQUIRED"),
            self.receipt(result="NOT_APPLICABLE_JUSTIFIED",not_applicable_reason="guess")]
        self.assertFalse(self.eval(rs)["contact_exhaustion_complete"])

    def test_negative_cannot_override_blocked_source(self):
        rs=[self.receipt(result="BLOCKED"),self.receipt()]
        self.assertFalse(self.eval(rs)["contact_exhaustion_complete"])

    def test_wrong_source_family_does_not_close(self):
        self.assertFalse(self.eval([self.receipt(source_family="official_team")])["contact_exhaustion_complete"])

    def test_wrong_opportunity_id_does_not_close(self):
        self.assertFalse(self.eval([self.receipt(opportunity_id="SYNTHETIC-OTHER")])["contact_exhaustion_complete"])

    def test_wrong_company_does_not_close(self):
        self.assertFalse(self.eval([self.receipt(company_name="Different Fixture")])["contact_exhaustion_complete"])

    def test_wrong_route_target_does_not_close(self):
        self.assertFalse(self.eval([self.receipt(route_target="NAMED")])["contact_exhaustion_complete"])

    def test_malformed_source_receipt_cannot_close(self):
        self.assertFalse(self.eval([self.receipt(raw_result_locator="")])["contact_exhaustion_complete"])

    def test_verified_positive_route_needs_bound_host_receipt(self):
        r=self.receipt(result="POSITIVE",verified=True,guessed=False,
                       route_evidence_ids=["SYN-E1"],owner_scope="ACCOUNT")
        self.assertTrue(self.eval([r])["company_route_proven"])
        self.assertFalse(self.eval([r],verifier=None)["company_route_proven"])

    def test_verifier_false_does_not_close(self):
        self.assertFalse(self.eval([self.receipt()],verifier=rejecting_verifier)["contact_exhaustion_complete"])

    def test_verifier_raises_without_leaking(self):
        self.assertFalse(self.eval([self.receipt()],verifier=raising_verifier)["contact_exhaustion_complete"])

    def test_duplicate_task_id_is_not_accepted_as_two_exhausted_sources(self):
        p=self.plan()
        p["tasks"].append(copy.deepcopy(p["tasks"][0]))
        r=self.eval([self.receipt()],plan=p)
        self.assertFalse(r["contact_exhaustion_complete"])
        self.assertEqual(r["completion_reason"],"INVALID_OR_DUPLICATE_CONTACT_TASK_IDENTITIES")

    def test_named_required_does_not_complete_on_company_negative_alone(self):
        p=self.plan()
        p["named_route_required_for_completion"]=True
        self.assertFalse(self.eval([self.receipt()],plan=p)["contact_exhaustion_complete"])

    def test_caller_declared_initial_ready_without_verifier_does_not_close(self):
        p=self.plan()
        p["initial_company_route_ready"]=True
        self.assertFalse(self.eval([],plan=p,verifier=None)["contact_exhaustion_complete"])

if __name__ == "__main__":
    unittest.main()
