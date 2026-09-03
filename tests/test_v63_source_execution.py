import unittest

from unified_runtime.source_execution import (
    evaluate_source_coverage,
    plan_public_source_tasks,
)


class V63SourceExecutionTests(unittest.TestCase):
    def _expansion_plan(self):
        return {
            "branches": {
                "TRADE_GRAPH": ["same_supplier_buyer"],
                "APPLICATION_GRAPH": ["downstream_manufacturer"],
                "CHANNEL_GRAPH": ["distributor"],
                "MARKET_GRAPH": ["regional_peer"],
                "COMPETITIVE_GRAPH": ["competing_supplier_buyer"],
                "CROSS_SELL_GRAPH": ["same_company_other_product"],
            },
            "product_profile_id": "PVC",
            "market_acceptance": "M1",
        }

    def _discovery_plan(self, truncated=False):
        return {
            "queries": [
                {"query": "PVC CELUKA cabinet manufacturer Vietnam-HCMC"},
                {"query": 'PVC "building material distributor" Vietnam-HCMC'},
            ],
            "truncated": truncated,
            "planning_is_execution_proof": False,
        }

    def test_planner_emits_branch_bound_source_tasks_not_execution_proof(self):
        result = plan_public_source_tasks(self._expansion_plan(), self._discovery_plan(), max_tasks=200)
        self.assertGreater(result["returned_count"], 6)
        self.assertFalse(result["planning_is_execution_proof"])
        self.assertTrue(result["host_execution_required"])
        for task in result["tasks"]:
            self.assertTrue(task["execution_required"])
            self.assertTrue(task["receipt_required"])
            self.assertFalse(task["search_execution_performed"])
            self.assertTrue(task["source_family"])
            self.assertTrue(task["branch_group"])
            self.assertTrue(task["call_id"].startswith("V63CALL-"))

    def test_no_receipts_means_source_coverage_incomplete(self):
        plan = plan_public_source_tasks(self._expansion_plan(), self._discovery_plan())
        coverage = evaluate_source_coverage(plan, [])
        self.assertFalse(coverage["source_coverage_complete"])
        self.assertEqual(coverage["status"], "INCOMPLETE")
        self.assertEqual(coverage["missing_call_count"], plan["returned_count"])

    def test_all_valid_terminal_receipts_can_prove_complete_for_untruncated_plan(self):
        plan = plan_public_source_tasks(self._expansion_plan(), self._discovery_plan())
        receipts = [{
            "call_id": task["call_id"],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": f"raw:{task['call_id']}",
        } for task in plan["tasks"]]
        coverage = evaluate_source_coverage(plan, receipts)
        self.assertTrue(coverage["source_coverage_complete"])
        self.assertEqual(coverage["status"], "PROVEN_COMPLETE")

    def test_blocked_receipt_never_closes_source_call(self):
        plan = plan_public_source_tasks(self._expansion_plan(), self._discovery_plan())
        receipts = [{
            "call_id": task["call_id"],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": f"raw:{task['call_id']}",
        } for task in plan["tasks"]]
        receipts[0] = {
            "call_id": plan["tasks"][0]["call_id"],
            "result": "BLOCKED",
            "completed_at": "2026-09-02T00:00:00Z",
            "blocked_reason": "LOGIN_REQUIRED",
        }
        coverage = evaluate_source_coverage(plan, receipts)
        self.assertFalse(coverage["source_coverage_complete"])
        self.assertIn(plan["tasks"][0]["call_id"], coverage["open_call_ids"])

    def test_positive_receipt_requires_evidence_binding(self):
        plan = plan_public_source_tasks(self._expansion_plan(), self._discovery_plan())
        receipts = [{
            "call_id": task["call_id"],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": f"raw:{task['call_id']}",
        } for task in plan["tasks"]]
        receipts[0] = {
            "call_id": plan["tasks"][0]["call_id"],
            "result": "POSITIVE",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": "raw:positive",
            "evidence_ids": [],
        }
        coverage = evaluate_source_coverage(plan, receipts)
        self.assertFalse(coverage["source_coverage_complete"])
        self.assertIn(plan["tasks"][0]["call_id"], coverage["open_call_ids"])

    def test_truncated_upstream_plan_can_never_prove_complete(self):
        plan = plan_public_source_tasks(self._expansion_plan(), self._discovery_plan(truncated=True))
        receipts = [{
            "call_id": task["call_id"],
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-02T00:00:00Z",
            "raw_result_locator": f"raw:{task['call_id']}",
        } for task in plan["tasks"]]
        coverage = evaluate_source_coverage(plan, receipts)
        self.assertFalse(coverage["source_coverage_complete"])
        self.assertEqual(coverage["status"], "INCOMPLETE_TRUNCATED_PLAN")


if __name__ == "__main__":
    unittest.main()
