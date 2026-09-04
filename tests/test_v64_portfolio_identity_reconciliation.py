import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_overlay():
    for name in list(sys.modules):
        if name == "unified_runtime" or name.startswith("unified_runtime."):
            sys.modules.pop(name, None)
    root = Path(__file__).resolve().parents[1]
    package = types.ModuleType("unified_runtime")
    package.__path__ = [str(root / "unified_runtime")]
    sys.modules["unified_runtime"] = package
    errors = types.ModuleType("unified_runtime.errors")

    class ValidationError(ValueError):
        pass

    errors.ValidationError = ValidationError
    sys.modules["unified_runtime.errors"] = errors
    path = root / "unified_runtime" / "research_orchestration_hardening.py"
    spec = importlib.util.spec_from_file_location(
        "unified_runtime.research_orchestration_hardening", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.V61ResearchOrchestrationHardeningMixin


Mixin = _load_overlay()


class FakeBase:
    def __init__(self):
        self.portfolio_limits = []
        self.account_states = {
            "INV-1": {
                "account": {
                    "account_id": "ACCT-1",
                    "name": "Acme Trading and Production Company Limited",
                    "country": "Vietnam",
                    "tax_id": "SYNTH-TAX-ALPHA",
                }
            },
            "INV-2": {
                "account": {
                    "account_id": "ACCT-2",
                    "name": "Unrelated Company Limited",
                    "country": "Vietnam",
                    "tax_id": "SYNTH-TAX-OTHER",
                }
            },
            "INV-3": {
                "account": {
                    "account_id": "ACCT-3",
                    "name": "ACME TRADING & PRODUCTION CO LTD",
                    "country": "Vietnam",
                    "tax_ids": ["SYNTH-TAX-ALPHA"],
                }
            },
        }
        self.rows = [
            {"investigation_id": "INV-1", "account_id": "ACCT-1", "account_name": "Acme", "environment": "PRODUCTION", "lifecycle": "ACTIVE", "commercial_value_grade": "A", "research_confidence": "R3", "observation_count": 5, "peer_count": 0},
            {"investigation_id": "INV-2", "account_id": "ACCT-2", "account_name": "Other", "environment": "PRODUCTION", "lifecycle": "ACTIVE", "commercial_value_grade": "NQ", "research_confidence": "R0", "observation_count": 0, "peer_count": 0},
            {"investigation_id": "INV-3", "account_id": "ACCT-3", "account_name": "Acme Duplicate", "environment": "PRODUCTION", "lifecycle": "ACTIVE", "commercial_value_grade": "NQ", "research_confidence": "R0", "observation_count": 0, "peer_count": 0},
        ]

    def get_portfolio_queue(self, arguments):
        limit = int(arguments.get("limit", 100))
        self.portfolio_limits.append(limit)
        return {"schema": "cbi.portfolio-queue.v6.1", "count": len(self.rows), "queue": list(self.rows[:limit])}

    def get_account_state(self, arguments):
        state = self.account_states[arguments["investigation_id"]]
        if isinstance(state, Exception):
            raise state
        return state

    def get_runtime_contract(self, arguments):
        return {"schema": "cbi.runtime-contract.v6.1"}


class Runtime(Mixin, FakeBase):
    pass


class PortfolioIdentityReconciliationTests(unittest.TestCase):
    def test_runtime_contract_separates_lifecycle_from_operational_activity(self):
        runtime = Runtime()
        contract = runtime.get_runtime_contract({})
        policy = contract["portfolio_operational_activity_v6_4"]
        self.assertFalse(policy["active_lifecycle_implies_research_materialized"])
        self.assertEqual(
            policy["initialization_only_rule"],
            "ZERO_OBSERVATIONS_ZERO_PEERS_NQ_R0",
        )
        self.assertFalse(policy["lifecycle_rewritten"])
        self.assertFalse(policy["queue_reordered"])

    def test_runtime_contract_exposes_fail_closed_identity_reconciliation_policy(self):
        runtime = Runtime()
        contract = runtime.get_runtime_contract({})
        policy = contract["canonical_identity_reconciliation_v6_4"]
        self.assertEqual(policy["mode"], "READ_ONLY_DETECTION")
        self.assertFalse(policy["automatic_merge_allowed"])
        self.assertEqual(
            policy["deterministic_duplicate_requires"],
            "ALL_CLUSTER_MEMBERS_SHARE_STRUCTURED_TAX_ID",
        )
        self.assertEqual(
            policy["portfolio_scan_scope"],
            "FULL_VISIBLE_PORTFOLIO_BEFORE_LIMIT",
        )

    def test_identity_scan_errors_do_not_echo_exception_messages(self):
        runtime = Runtime()
        runtime.account_states["INV-2"] = ValueError("DETAIL_SHOULD_NOT_ECHO")
        result = runtime.get_portfolio_queue({"limit": 3})
        scan_errors = result["canonical_identity_reconciliation"]["scan_errors"]
        self.assertEqual(len(scan_errors), 1)
        self.assertEqual(scan_errors[0]["account_id"], "ACCT-2")
        self.assertEqual(scan_errors[0]["error_type"], "ValueError")
        self.assertEqual(scan_errors[0]["code"], "ACCOUNT_STATE_READ_FAILED")
        self.assertNotIn("error", scan_errors[0])
        self.assertNotIn("DETAIL_SHOULD_NOT_ECHO", str(scan_errors))

    def test_active_lifecycle_is_separated_from_operational_research_activity(self):
        runtime = Runtime()
        result = runtime.get_portfolio_queue({"limit": 3})
        by_id = {row["account_id"]: row for row in result["queue"]}
        self.assertEqual(by_id["ACCT-1"]["operational_activity_state"], "RESEARCH_MATERIALIZED")
        self.assertEqual(by_id["ACCT-2"]["operational_activity_state"], "INITIALIZATION_ONLY")
        self.assertEqual(by_id["ACCT-3"]["operational_activity_state"], "INITIALIZATION_ONLY")
        self.assertEqual(by_id["ACCT-2"]["lifecycle"], "ACTIVE")
        summary = result["operational_activity_summary"]
        self.assertEqual(summary["RESEARCH_MATERIALIZED"], 1)
        self.assertEqual(summary["INITIALIZATION_ONLY"], 2)
        self.assertFalse(summary["lifecycle_rewritten"])
        self.assertFalse(summary["queue_reordered"])

    def test_detector_scans_full_visible_portfolio_before_applying_user_limit(self):
        runtime = Runtime()
        result = runtime.get_portfolio_queue({"limit": 2})
        self.assertEqual(runtime.portfolio_limits, [1000])
        self.assertEqual(len(result["queue"]), 2)
        self.assertEqual(result["count"], 3)
        reconciliation = result["canonical_identity_reconciliation"]
        self.assertEqual(reconciliation["pair_count"], 1)
        self.assertEqual(reconciliation["items"][0]["account_ids"], ["ACCT-1", "ACCT-3"])
        self.assertEqual(
            reconciliation["items"][0]["status"],
            "DETERMINISTIC_DUPLICATE_CANDIDATE",
        )

    def test_portfolio_rows_are_flagged_but_never_collapsed_or_rewritten(self):
        runtime = Runtime()
        before = [dict(row) for row in runtime.rows]
        result = runtime.get_portfolio_queue({"limit": 3})
        self.assertEqual(len(result["queue"]), 3)
        self.assertEqual(runtime.rows, before)
        by_id = {row["account_id"]: row for row in result["queue"]}
        self.assertTrue(by_id["ACCT-1"]["canonical_identity_reconciliation_required"])
        self.assertTrue(by_id["ACCT-3"]["canonical_identity_reconciliation_required"])
        self.assertFalse(by_id["ACCT-2"]["canonical_identity_reconciliation_required"])
        self.assertEqual(
            by_id["ACCT-1"]["canonical_identity_reconciliation_statuses"],
            ["DETERMINISTIC_DUPLICATE_CANDIDATE"],
        )

    def test_many_same_identity_rows_remain_visible_but_share_one_reconciliation_cluster(self):
        runtime = Runtime()
        runtime.account_states["INV-4"] = {
            "account": {
                "account_id": "ACCT-4",
                "name": "Acme Trading and Production Company Limited",
                "country": "Vietnam",
            }
        }
        runtime.rows.append(
            {"investigation_id": "INV-4", "account_id": "ACCT-4", "account_name": "Acme Legacy"}
        )
        result = runtime.get_portfolio_queue({"limit": 4})
        reconciliation = result["canonical_identity_reconciliation"]
        self.assertEqual(reconciliation["cluster_count"], 1)
        self.assertEqual(len(reconciliation["items"]), 1)
        self.assertEqual(
            reconciliation["items"][0]["account_ids"],
            ["ACCT-1", "ACCT-3", "ACCT-4"],
        )
        self.assertEqual(reconciliation["items"][0]["status"], "REVIEW_REQUIRED")
        self.assertIn(
            "PARTIAL_SHARED_TAX_ID",
            reconciliation["items"][0]["evidence_basis"],
        )
        self.assertEqual(len(result["queue"]), 4)
        flagged = {
            row["account_id"]: row["canonical_identity_reconciliation_required"]
            for row in result["queue"]
        }
        self.assertTrue(flagged["ACCT-1"])
        self.assertTrue(flagged["ACCT-3"])
        self.assertTrue(flagged["ACCT-4"])
        self.assertFalse(flagged["ACCT-2"])

    def test_conflicting_tax_ids_on_same_legal_name_are_fail_closed(self):
        runtime = Runtime()
        runtime.account_states["INV-3"]["account"]["tax_ids"] = ["SYNTH-TAX-CONFLICT"]
        result = runtime.get_portfolio_queue({"limit": 3})
        item = result["canonical_identity_reconciliation"]["items"][0]
        self.assertEqual(item["status"], "IDENTITY_CONFLICT")
        self.assertFalse(item["auto_merge_allowed"])


if __name__ == "__main__":
    unittest.main()
