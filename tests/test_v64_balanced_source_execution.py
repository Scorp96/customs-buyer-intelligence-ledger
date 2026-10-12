"""Regression: all six discovery branches receive early research budget.

Fixtures are synthetic. Planner performs no network calls or mutations.
"""
from __future__ import annotations

import base64
import json
import unittest
from collections import Counter

from unified_runtime.source_execution import (
    SOURCE_FAMILIES_BY_BRANCH_GROUP,
    plan_public_source_tasks,
    evaluate_source_coverage,
)


def fixtures():
    plan = {
        "product_profile_id": "SOAP_MACHINERY",
        "market_acceptance": "M1",
        "branches": {
            "TRADE_GRAPH": ["same_supplier_buyer", "same_product_buyer"],
            "APPLICATION_GRAPH": ["direct_application_user", "OEM_ODM_user"],
            "CHANNEL_GRAPH": ["machinery_importer", "equipment_integrator"],
            "MARKET_GRAPH": ["regional_peer", "industry_peer"],
            "COMPETITIVE_GRAPH": ["competing_supplier_buyer", "second_source_candidate"],
            "CROSS_SELL_GRAPH": ["same_company_other_product", "application_overlap"],
        },
    }
    discover = {
        "queries": [
            {"query": "vacuum emulsifier import Indonesia"},
            {"query": "liquid perfume bottling line Indonesia"},
            {"query": "cosmetic factory mixing machine Indonesia"},
        ],
    }
    return plan, discover


class BalancedSourceTaskPlannerTests(unittest.TestCase):
    def test_first_six_tasks_cover_six_branch_groups(self):
        p, d = fixtures()
        out = plan_public_source_tasks(p, d, max_tasks=6)
        self.assertEqual(out["returned_count"], 6)
        self.assertEqual(
            {t["branch_group"] for t in out["tasks"]},
            set(SOURCE_FAMILIES_BY_BRANCH_GROUP),
        )
        self.assertTrue(out["has_more"])
        self.assertFalse(out["planning_is_execution_proof"])

    def test_first_fifty_are_not_all_same_trade_branch(self):
        p, d = fixtures()
        out = plan_public_source_tasks(p, d, max_tasks=50)
        count = Counter(t["branch_group"] for t in out["tasks"])
        self.assertEqual(len(count), 6)
        self.assertLessEqual(max(count.values()) - min(count.values()), 1)
        self.assertIn("equipment_integrator", {t["branch"] for t in out["tasks"]})
        self.assertIn("same_product_buyer", {t["branch"] for t in out["tasks"]})
        self.assertFalse(any(t["search_execution_performed"] for t in out["tasks"]))

    def test_trade_data_source_families_are_not_monopolized(self):
        p, d = fixtures()
        out = plan_public_source_tasks(p, d, max_tasks=30)
        trade = [t for t in out["tasks"] if t["branch_group"] == "TRADE_GRAPH"]
        self.assertGreaterEqual(len({t["source_family"] for t in trade}), 2)

    def test_exact_cursor_pagination_matches_unbounded_task_set(self):
        p, d = fixtures()
        full = plan_public_source_tasks(p, d, max_tasks=1000)
        tasks, token, pages = [], None, 0
        while True:
            page = plan_public_source_tasks(p, d, max_tasks=7, continuation_token=token)
            tasks.extend(page["tasks"])
            pages += 1
            if not page["has_more"]:
                self.assertIsNone(page["continuation_token"])
                break
            token = page["continuation_token"]
            self.assertLess(pages, 150)
        self.assertEqual(tasks, full["tasks"])
        self.assertEqual(len({t["call_id"] for t in tasks}), len(tasks))
        self.assertEqual(len(tasks), full["task_candidate_count"])

    def test_fingerprint_rejects_old_ordering_cursor(self):
        p, d = fixtures()
        legacy = {
            "schema": "cbi.v63-source-task-cursor.v1",
            "plan_fingerprint": "0" * 64,
            "offset": 6,
        }
        token = base64.urlsafe_b64encode(
            json.dumps(legacy).encode("utf-8")
        ).decode("ascii").rstrip("=")
        with self.assertRaisesRegex(ValueError, "SOURCE_TASK_CONTINUATION_PLAN_MISMATCH"):
            plan_public_source_tasks(p, d, max_tasks=6, continuation_token=token)

    def test_expansion_dict_order_not_pagination_authority(self):
        p, d = fixtures()
        reverse = dict(p)
        reverse["branches"] = dict(reversed(list(p["branches"].items())))
        x = plan_public_source_tasks(p, d, max_tasks=35)
        y = plan_public_source_tasks(reverse, d, max_tasks=35)
        self.assertEqual(x["plan_fingerprint"], y["plan_fingerprint"])
        self.assertEqual(x["tasks"], y["tasks"])

    def test_no_candidate_dropped_if_group_has_no_branches(self):
        p, d = fixtures()
        p["branches"]["COMPETITIVE_GRAPH"] = []
        out = plan_public_source_tasks(p, d, max_tasks=1000)
        self.assertEqual(len({x["branch_group"] for x in out["tasks"]}), 5)
        self.assertEqual(len(out["tasks"]), out["task_candidate_count"])

    def test_empty_queries_never_become_complete_without_receipts(self):
        p, d = fixtures()
        d["queries"] = []
        out = plan_public_source_tasks(p, d)
        self.assertEqual(out["tasks"], [])
        self.assertFalse(evaluate_source_coverage(out, [])["source_coverage_complete"])

    def test_truncated_page_cannot_be_marked_exhausted(self):
        p, d = fixtures()
        out = plan_public_source_tasks(p, d, max_tasks=12)
        self.assertEqual(evaluate_source_coverage(out, [])["status"], "INCOMPLETE_TRUNCATED_PLAN")

    def test_cursor_is_bound_to_queries(self):
        p, d = fixtures()
        first = plan_public_source_tasks(p, d, max_tasks=10)
        changed = dict(d)
        changed["queries"] = d["queries"] + [{"query": "industrial cosmetics mixer Malaysia"}]
        with self.assertRaisesRegex(ValueError, "SOURCE_TASK_CONTINUATION_PLAN_MISMATCH"):
            plan_public_source_tasks(p, changed, max_tasks=10, continuation_token=first["continuation_token"])


if __name__ == "__main__":
    unittest.main()
