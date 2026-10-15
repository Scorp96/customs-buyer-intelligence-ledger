import unittest

from unified_runtime.contact_exhaustion import plan_contact_exhaustion
from unified_runtime.contact_source_execution import (
    evaluate_contact_coverage,
    plan_contact_source_tasks,
)


class V63ContactSourceExecutionTests(unittest.TestCase):
    @staticmethod
    def _fixture_authoritative_verifier(task, receipt):
        """Synthetic host ledger fixture; not proof of real-world execution."""
        return (
            receipt.get("task_id") == task.get("task_id")
            and str(receipt.get("raw_result_locator") or "").startswith("raw:")
        )

    def test_a_plus_plans_company_and_named_route_tasks(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "A+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks(
            "OPP-C500-PVC-PRIMARY",
            "Example Materials LLC",
            contact,
        )
        targets = {task["route_target"] for task in plan["tasks"]}
        self.assertEqual(targets, {"COMPANY", "NAMED"})
        self.assertTrue(plan["named_route_required_for_completion"])
        self.assertTrue(all(not task["search_execution_performed"] for task in plan["tasks"]))

    def test_bplus_named_route_is_optional_by_default_but_company_route_is_material(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "B+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks(
            "OPP-C500-PVC-PRIMARY",
            "Example Materials LLC",
            contact,
        )
        self.assertFalse(plan["named_route_required_for_completion"])
        company_tasks = [task for task in plan["tasks"] if task["route_target"] == "COMPANY"]
        self.assertTrue(company_tasks)
        self.assertTrue(all(task["material"] for task in company_tasks))

    def test_verified_company_positive_can_close_bplus_contact_coverage(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "B+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks("OPP-C500-PVC-PRIMARY", "Example Materials LLC", contact)
        company_task = next(task for task in plan["tasks"] if task["route_target"] == "COMPANY")
        coverage = evaluate_contact_coverage(plan, [{
            "task_id": company_task["task_id"],
            "opportunity_id": company_task["opportunity_id"],
            "route_target": company_task["route_target"],
            "source_family": company_task["source_family"],
            "company_name": company_task["company_name"],
            "result": "POSITIVE",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": "raw:company",
            "route_evidence_ids": ["E-ROUTE-1"],
            "verified": True,
            "guessed": False,
            "owner_scope": "ACCOUNT",
        }], receipt_verifier=self._fixture_authoritative_verifier)
        self.assertTrue(coverage["contact_exhaustion_complete"])
        self.assertTrue(coverage["company_route_proven"])
        self.assertFalse(coverage["named_route_proven"])

    def test_a_plus_company_route_does_not_skip_named_exhaustion(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "A+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks("OPP-C500-PVC-PRIMARY", "Example Materials LLC", contact)
        company_task = next(task for task in plan["tasks"] if task["route_target"] == "COMPANY")
        coverage = evaluate_contact_coverage(plan, [{
            "task_id": company_task["task_id"],
            "opportunity_id": company_task["opportunity_id"],
            "route_target": company_task["route_target"],
            "source_family": company_task["source_family"],
            "company_name": company_task["company_name"],
            "result": "POSITIVE",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": "raw:company",
            "route_evidence_ids": ["E-ROUTE-1"],
            "verified": True,
            "guessed": False,
            "owner_scope": "ACCOUNT",
        }], receipt_verifier=self._fixture_authoritative_verifier)
        self.assertFalse(coverage["contact_exhaustion_complete"])
        self.assertTrue(coverage["company_route_proven"])
        self.assertGreater(coverage["open_required_task_count"], 0)

    def test_guessed_positive_route_does_not_count_as_proven(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "B+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks("OPP-C500-PVC-PRIMARY", "Example Materials LLC", contact)
        company_task = next(task for task in plan["tasks"] if task["route_target"] == "COMPANY")
        coverage = evaluate_contact_coverage(plan, [{
            "task_id": company_task["task_id"],
            "opportunity_id": company_task["opportunity_id"],
            "route_target": company_task["route_target"],
            "source_family": company_task["source_family"],
            "company_name": company_task["company_name"],
            "result": "POSITIVE",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": "raw:company",
            "route_evidence_ids": ["E-ROUTE-1"],
            "verified": True,
            "guessed": True,
            "owner_scope": "ACCOUNT",
        }], receipt_verifier=self._fixture_authoritative_verifier)
        self.assertFalse(coverage["company_route_proven"])
        self.assertFalse(coverage["contact_exhaustion_complete"])

    def test_all_required_negative_exhausted_receipts_can_close_without_route(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "B+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks("OPP-C500-PVC-PRIMARY", "Example Materials LLC", contact)
        receipts = [{
            "task_id": task["task_id"],
            "opportunity_id": task["opportunity_id"],
            "route_target": task["route_target"],
            "source_family": task["source_family"],
            "company_name": task["company_name"],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": f"raw:{task['task_id']}",
        } for task in plan["tasks"] if task["required_for_completion"]]
        coverage = evaluate_contact_coverage(plan, receipts, receipt_verifier=self._fixture_authoritative_verifier)
        self.assertTrue(coverage["contact_exhaustion_complete"])
        self.assertEqual(coverage["completion_reason"], "REQUIRED_CONTACT_SOURCES_EXHAUSTED")

    def test_blocked_required_source_remains_open(self):
        contact = plan_contact_exhaustion({
            "product_profile_id": "PVC",
            "commercial_value_grade": "B+",
            "outreach_readiness": "IDENTITY_ONLY",
        }, {})
        plan = plan_contact_source_tasks("OPP-C500-PVC-PRIMARY", "Example Materials LLC", contact)
        receipts = [{
            "task_id": task["task_id"],
            "opportunity_id": task["opportunity_id"],
            "route_target": task["route_target"],
            "source_family": task["source_family"],
            "company_name": task["company_name"],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": f"raw:{task['task_id']}",
        } for task in plan["tasks"] if task["required_for_completion"]]
        receipts[0] = {
            "task_id": receipts[0]["task_id"],
            "result": "BLOCKED",
            "completed_at": "2026-09-02T00:00:00Z",
            "blocked_reason": "LOGIN_REQUIRED",
        }
        coverage = evaluate_contact_coverage(plan, receipts, receipt_verifier=self._fixture_authoritative_verifier)
        self.assertFalse(coverage["contact_exhaustion_complete"])
        self.assertGreater(coverage["open_required_task_count"], 0)


if __name__ == "__main__":
    unittest.main()
