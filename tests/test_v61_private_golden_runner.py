from __future__ import annotations

import unittest

from scripts.run_private_golden_acceptance import (
    READ_ONLY_TOOLS,
    run_manifest,
    validate_manifest,
)


class DummyRuntime:
    def get_account_state(self, arguments: dict) -> dict:
        return {
            "account": {"account_id": arguments["investigation_id"]},
            "commercial_value": {
                "commercial_value_grade": "A",
                "score": 88.5,
            },
            "crm_sync": "NOT_REQUESTED",
            "routes": [],
        }

    def get_information_history(self, arguments: dict) -> dict:
        return {
            "records": [
                {"role": "CUSTOMS_BROKER"},
                {"role": "TRADING_INTERMEDIARY"},
            ]
        }


class V61PrivateGoldenRunnerTests(unittest.TestCase):
    def test_manifest_runs_generic_read_only_assertions(self) -> None:
        manifest = {
            "cases": [
                {
                    "case_id": "commercial-minimum",
                    "tool": "get_account_state",
                    "arguments": {"investigation_id": "INV-SYNTH-001"},
                    "assertions": [
                        {
                            "path": "commercial_value.commercial_value_grade",
                            "op": "grade_at_least",
                            "value": "A",
                        },
                        {
                            "path": "commercial_value.score",
                            "op": "number_at_least",
                            "value": 84,
                        },
                        {"path": "crm_sync", "op": "eq", "value": "NOT_REQUESTED"},
                    ],
                },
                {
                    "case_id": "role-classification",
                    "tool": "get_information_history",
                    "arguments": {"investigation_id": "INV-SYNTH-001"},
                    "assertions": [
                        {"path": "records", "op": "length_at_least", "value": 2},
                        {"path": "records.0.role", "op": "eq", "value": "CUSTOMS_BROKER"},
                        {"path": "records.1.role", "op": "not_in", "value": ["BUYER_DECISION_MAKER"]},
                    ],
                },
            ]
        }
        result = run_manifest(DummyRuntime(), manifest)
        self.assertTrue(result["read_only"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["passed_count"], 2)
        self.assertEqual(result["failed_count"], 0)

    def test_mutation_and_resume_tools_are_not_allowed(self) -> None:
        forbidden = {
            "start_investigation",
            "resolve_or_create_account",
            "compile_and_append_research_bundle",
            "append_information_record",
            "append_execution_receipt",
            "append_provider_receipt",
            "append_peer_receipt",
            "promote_anchor",
            "prepare_crm_writeback",
            "append_crm_writeback_receipt",
            "prepare_outreach",
            "migrate_v5_4_1_to_v6",
            "resume_investigation",
        }
        self.assertFalse(READ_ONLY_TOOLS & forbidden)
        with self.assertRaises(ValueError):
            validate_manifest({
                "cases": [
                    {
                        "case_id": "forbidden-mutation",
                        "tool": "start_investigation",
                        "arguments": {},
                        "assertions": [{"path": "status", "op": "truthy"}],
                    }
                ]
            })

    def test_failed_assertion_is_reported_without_mutation(self) -> None:
        result = run_manifest(
            DummyRuntime(),
            {
                "cases": [
                    {
                        "case_id": "expected-failure",
                        "tool": "get_account_state",
                        "arguments": {"investigation_id": "INV-SYNTH-002"},
                        "assertions": [
                            {
                                "path": "commercial_value.commercial_value_grade",
                                "op": "eq",
                                "value": "A+",
                            }
                        ],
                    }
                ]
            },
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_count"], 1)
        self.assertFalse(result["results"][0]["assertions"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
