"""Stage-5 fail-closed positive-proof, expansion and Source Family regression tests.

All fixtures synthetic. No customer, network, CRM, event or production write.
"""
import unittest

from unified_runtime.candidate_research_gate import assess_candidate_researchability
from unified_runtime.expansion_planner import evaluate_expansion_saturation
from unified_runtime.contact_exhaustion import recompute_outreach_readiness
from unified_runtime.contact_source_execution import (
    _positive_route, evaluate_contact_coverage, plan_contact_source_tasks,
)


class Stage5StrictEvidenceTypes(unittest.TestCase):
    @staticmethod
    def candidate(**updates):
        v = {
            "candidate_id": "SYN-AUDIT-ONLY", "company_name": "Synthetic Test Only",
            "product_profile_id": "PVC", "canonical_status": "CONFIRMED",
            "signal_tier": "D1", "eiv": 1, "procurement_proven": False,
            "product_or_application_signal": True,
        }
        v.update(updates)
        return assess_candidate_researchability(v)

    def test_real_boolean_false_procurement_keeps_research_active(self):
        r = self.candidate(procurement_proven=False)
        self.assertFalse(r["opportunity_creation_ready"])
        self.assertIn("PROCUREMENT_NOT_YET_PROVEN", r["qualification_gaps"])

    def test_string_false_procurement_cannot_create_qualified_opportunity(self):
        r = self.candidate(procurement_proven="false")
        self.assertFalse(r["opportunity_creation_ready"])
        self.assertIn("PROCUREMENT_NOT_YET_PROVEN", r["qualification_gaps"])

    def test_integer_one_procurement_cannot_claim_verified_purchase(self):
        r = self.candidate(procurement_proven=1)
        self.assertFalse(r["opportunity_creation_ready"])

    def test_valid_boolean_proof_still_qualifies_d1(self):
        r = self.candidate(procurement_proven=True)
        self.assertTrue(r["opportunity_creation_ready"])
        self.assertEqual(r["research_state"], "READY_FOR_QUALIFICATION")

    def test_false_string_product_signal_does_not_imply_active_signal(self):
        r = self.candidate(eiv=0, product_or_application_signal="false")
        self.assertEqual(r["research_state"], "DEFERRED_LOW_EIV")

    def test_false_string_proven_negative_does_not_reject(self):
        r = self.candidate(proven_negative="false")
        self.assertFalse(r["rejected"])
        self.assertTrue(r["retain_in_candidate_pool"])

    def test_false_string_duplicate_does_not_reject(self):
        r = self.candidate(duplicate_proven="false")
        self.assertFalse(r["rejected"])
        self.assertEqual(r["rejection_reasons"], [])

    def test_false_string_mismatch_does_not_reject(self):
        r = self.candidate(mismatch_proven="false")
        self.assertFalse(r["rejected"])

    def test_actual_boolean_proven_duplicate_still_rejects(self):
        r = self.candidate(duplicate_proven=True)
        self.assertTrue(r["rejected"])
        self.assertIn("PROVEN_DUPLICATE", r["rejection_reasons"])

    def test_d4_still_retained_without_procurement(self):
        r = self.candidate(signal_tier="D4", canonical_status="UNRESOLVED",
                           eiv=0, procurement_proven=False,
                           product_or_application_signal=False)
        self.assertFalse(r["rejected"])
        self.assertTrue(r["retain_in_candidate_pool"])

    @staticmethod
    def expansion(**updates):
        p = {
            "remaining_material_work": [],
            "undispositioned_high_value_candidates": [],
            "unresolved_research_candidates": [],
            "unexpanded_promoted_anchors": [],
            "open_high_yield_pivots": [],
            "cycle_dedup_complete": True,
        }
        p.update(updates)
        return evaluate_expansion_saturation(p)

    def test_false_string_cycle_dedup_cannot_saturate(self):
        r = self.expansion(cycle_dedup_complete="false")
        self.assertFalse(r["expansion_saturated"])
        self.assertIn("CYCLE_DEDUP_INCOMPLETE", r["blockers"])

    def test_integer_one_cycle_dedup_cannot_saturate(self):
        r = self.expansion(cycle_dedup_complete=1)
        self.assertFalse(r["expansion_saturated"])

    def test_boolean_false_cycle_dedup_blocks(self):
        self.assertFalse(self.expansion(cycle_dedup_complete=False)["expansion_saturated"])

    def test_boolean_true_cycle_dedup_empty_work_saturates(self):
        self.assertTrue(self.expansion()["expansion_saturated"])

    def test_material_pivot_always_blocks_saturation(self):
        r = self.expansion(open_high_yield_pivots=[{"pivot_id": "SYN-P1"}])
        self.assertIn("OPEN_HIGH_YIELD_PIVOTS", r["blockers"])

    @staticmethod
    def company_route(**updates):
        r = {"verified": True, "route_eligible": True, "guessed": False,
             "freshness": "CURRENT", "owner_scope": "ACCOUNT"}
        r.update(updates)
        return r

    @staticmethod
    def named_route(**updates):
        r = {"verified": True, "route_eligible": True, "guessed": False,
             "freshness": "CURRENT", "owner_scope": "PERSON",
             "current_company_association": True, "role_relevant": True}
        r.update(updates)
        return r

    def test_company_verified_false_string_cannot_be_route_ready(self):
        r = recompute_outreach_readiness({"company_routes":
                   [self.company_route(verified="false")], "named_routes":[]})
        self.assertEqual(r["outreach_readiness"], "IDENTITY_ONLY")

    def test_company_eligible_false_string_cannot_be_route_ready(self):
        r = recompute_outreach_readiness({"company_routes":
                   [self.company_route(route_eligible="false")], "named_routes":[]})
        self.assertFalse(r["company_route_ready"])

    def test_named_association_false_string_cannot_be_named_ready(self):
        r = recompute_outreach_readiness({"company_routes":[], "named_routes":
                   [self.named_route(current_company_association="false")]})
        self.assertFalse(r["named_route_ready"])

    def test_named_role_false_string_cannot_be_named_ready(self):
        r = recompute_outreach_readiness({"company_routes":[], "named_routes":
                   [self.named_route(role_relevant="false")]})
        self.assertEqual(r["outreach_readiness"], "IDENTITY_ONLY")

    def test_real_positive_company_and_named_routes_still_ready(self):
        r = recompute_outreach_readiness({"company_routes":[self.company_route()],
                                           "named_routes":[self.named_route()]})
        self.assertTrue(r["company_route_ready"])
        self.assertTrue(r["named_route_ready"])
        self.assertFalse(r["commercial_grade_mutated"])

    @staticmethod
    def receipt(**updates):
        r = {"task_id":"SYN-T1", "result":"POSITIVE",
             "opportunity_id":"SYN-OPP", "company_name":"Synthetic Company",
             "route_target":"COMPANY", "source_family":"official_contact",
             "completed_at":"2026-10-15T00:00:00Z",
             "raw_result_locator":"synthetic://read-only",
             "route_evidence_ids":["SYN-E1"], "verified":True,
             "guessed":False, "owner_scope":"ACCOUNT"}
        r.update(updates)
        return r

    @staticmethod
    def contact_plan(**updates):
        p = {"tasks":[{"task_id":"SYN-T1","route_target":"COMPANY",
                        "opportunity_id":"SYN-OPP","company_name":"Synthetic Company",
                        "source_family":"official_contact",
                        "required_for_completion":True}],
             "initial_company_route_ready":False,
             "initial_named_route_ready":False,
             "company_route_required_for_completion":True,
             "named_route_required_for_completion":False,
             "truncated":False}
        p.update(updates)
        return p

    @staticmethod
    def _fixture_authoritative_verifier(task, receipt):
        return (
            task.get("task_id") == receipt.get("task_id")
            and receipt.get("raw_result_locator") == "synthetic://read-only"
        )

    def test_positive_receipt_verified_false_string_never_proves_route(self):
        r = evaluate_contact_coverage(self.contact_plan(),
                    [self.receipt(verified="false")],
                    receipt_verifier=self._fixture_authoritative_verifier)
        self.assertFalse(r["company_route_proven"])
        self.assertFalse(r["contact_exhaustion_complete"])

    def test_positive_receipt_true_boolean_proves_route(self):
        r = evaluate_contact_coverage(self.contact_plan(), [self.receipt()],
                    receipt_verifier=self._fixture_authoritative_verifier)
        self.assertTrue(r["company_route_proven"])
        self.assertTrue(r["contact_exhaustion_complete"])

    def test_initial_ready_string_false_does_not_prove_completion(self):
        r = evaluate_contact_coverage(
             self.contact_plan(initial_company_route_ready="false"), [])
        self.assertFalse(r["company_route_proven"])
        self.assertFalse(r["contact_exhaustion_complete"])

    def test_malformed_required_flag_fails_closed(self):
        p = self.contact_plan()
        p["tasks"][0]["required_for_completion"] = "false"
        r = evaluate_contact_coverage(p, [])
        self.assertFalse(r["contact_exhaustion_complete"])
        self.assertEqual(r["open_required_task_count"], 1)

    def test_malformed_named_required_flag_fails_closed(self):
        p = self.contact_plan(named_route_required_for_completion="false",
                              initial_company_route_ready=True)
        r = evaluate_contact_coverage(p, [])
        self.assertFalse(r["contact_exhaustion_complete"])

    def test_named_positive_requires_real_association_boolean(self):
        x = self.receipt(owner_scope="PERSON", current_company_association="false")
        self.assertFalse(_positive_route(x, "NAMED"))
        x["current_company_association"] = True
        self.assertTrue(_positive_route(x, "NAMED"))

    def test_source_planner_does_not_suppress_families_on_false_string(self):
        p = {"company_route_ready":"false","named_route_ready":"false",
             "company_route_required":True,"named_route_policy":"EXHAUSTIVE",
             "company_route_source_families":["official_contact"],
             "named_route_source_families":["official_team"],
             "commercial_value_grade":"A+"}
        r = plan_contact_source_tasks("SYN-OPP","Synthetic Company",p)
        self.assertEqual(r["task_candidate_count"],2)
        self.assertEqual(set(t["route_target"] for t in r["tasks"]),{"COMPANY","NAMED"})
        self.assertTrue(all(t["execution_required"] for t in r["tasks"]))
        self.assertFalse(r["planning_is_execution_proof"])


if __name__ == "__main__":
    unittest.main()
