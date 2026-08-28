from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_private_golden_acceptance import (
    READ_ONLY_TOOLS,
    run_manifest,
    validate_manifest,
)
from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]


def portfolio_row(
    investigation_id: str,
    account_id: str,
    account_name: str,
    scope: str = "DEFAULT",
) -> dict:
    return {
        "investigation_id": investigation_id,
        "account_id": account_id,
        "account_name": account_name,
        "investigation_scope": scope,
        "environment": "PRODUCTION",
        "lifecycle": "ACTIVE",
    }


class DummyRuntime:
    def __init__(self, rows: list[dict] | None = None, active_count: int | None = None):
        self.rows = list(rows or [])
        self.active_count = len(self.rows) if active_count is None else active_count
        self.portfolio_calls = 0
        self.account_state_calls: list[str] = []

    def get_portfolio_queue(self, arguments: dict) -> dict:
        self.portfolio_calls += 1
        limit = int(arguments.get("limit", 100))
        return {
            "queue": self.rows[:limit],
            "count": min(len(self.rows), limit),
            "active_count": self.active_count,
        }

    def get_account_state(self, arguments: dict) -> dict:
        investigation_id = arguments["investigation_id"]
        self.account_state_calls.append(investigation_id)
        return {
            "account": {"account_id": investigation_id},
            "commercial_value": {
                "commercial_value_grade": "A",
                "score": 88.5,
            },
            "crm_sync": "NOT_REQUESTED",
            "routes": [],
        }

    def get_information_history(self, arguments: dict) -> dict:
        return {
            "investigation_id": arguments["investigation_id"],
            "records": [
                {"role": "CUSTOMS_BROKER"},
                {"role": "TRADING_INTERMEDIARY"},
            ],
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
                        {
                            "path": "crm_sync",
                            "op": "eq",
                            "value": "NOT_REQUESTED",
                        },
                    ],
                },
                {
                    "case_id": "role-classification",
                    "tool": "get_information_history",
                    "arguments": {"investigation_id": "INV-SYNTH-001"},
                    "assertions": [
                        {"path": "records", "op": "length_at_least", "value": 2},
                        {
                            "path": "records.0.role",
                            "op": "eq",
                            "value": "CUSTOMS_BROKER",
                        },
                        {
                            "path": "records.1.role",
                            "op": "not_in",
                            "value": ["BUYER_DECISION_MAKER"],
                        },
                    ],
                },
            ]
        }
        result = run_manifest(DummyRuntime(), manifest)
        self.assertTrue(result["read_only"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["passed_count"], 2)
        self.assertEqual(result["failed_count"], 0)

    def test_selector_resolves_unique_active_production_investigation_once(self) -> None:
        runtime = DummyRuntime(
            [
                portfolio_row(
                    "INV-GOLD-001",
                    "C001",
                    "Western Woods, LLC",
                ),
                portfolio_row(
                    "INV-GOLD-002",
                    "C002",
                    "Arecibo Home Center",
                ),
            ]
        )
        manifest = {
            "cases": [
                {
                    "case_id": "western-commercial",
                    "tool": "get_account_state",
                    "selector": {"account_name": "  WESTERN WOODS, LLC  "},
                    "assertions": [
                        {
                            "path": "commercial_value.commercial_value_grade",
                            "op": "grade_at_least",
                            "value": "A",
                        }
                    ],
                },
                {
                    "case_id": "western-role-history",
                    "tool": "get_information_history",
                    "selector": {
                        "account_id": "c001",
                        "investigation_scope": "default",
                    },
                    "assertions": [
                        {
                            "path": "investigation_id",
                            "op": "eq",
                            "value": "INV-GOLD-001",
                        }
                    ],
                },
            ]
        }

        result = run_manifest(runtime, manifest)

        self.assertTrue(result["passed"])
        self.assertEqual(runtime.portfolio_calls, 1)
        self.assertEqual(runtime.account_state_calls, ["INV-GOLD-001"])
        for row in result["results"]:
            self.assertEqual(row["selection"]["investigation_id"], "INV-GOLD-001")
            self.assertEqual(row["selection"]["environment"], "PRODUCTION")
            self.assertEqual(row["selection"]["lifecycle"], "ACTIVE")

    def test_selector_ambiguity_and_missing_match_fail_closed(self) -> None:
        runtime = DummyRuntime(
            [
                portfolio_row("INV-A", "C-A", "Shared Golden Name"),
                portfolio_row("INV-B", "C-B", "Shared Golden Name"),
            ]
        )
        ambiguous = run_manifest(
            runtime,
            {
                "cases": [
                    {
                        "case_id": "ambiguous",
                        "tool": "get_account_state",
                        "selector": {"account_name": "Shared Golden Name"},
                        "assertions": [{"path": "account.account_id", "op": "truthy"}],
                    }
                ]
            },
        )
        self.assertFalse(ambiguous["passed"])
        self.assertIn("multiple PRODUCTION/ACTIVE", ambiguous["results"][0]["error"])
        self.assertEqual(runtime.account_state_calls, [])

        missing = run_manifest(
            runtime,
            {
                "cases": [
                    {
                        "case_id": "missing",
                        "tool": "get_account_state",
                        "selector": {"account_name": "No Such Golden"},
                        "assertions": [{"path": "account.account_id", "op": "truthy"}],
                    }
                ]
            },
        )
        self.assertFalse(missing["passed"])
        self.assertIn("matched no unique", missing["results"][0]["error"])
        self.assertEqual(runtime.account_state_calls, [])

    def test_selector_rejects_truncated_active_portfolio(self) -> None:
        runtime = DummyRuntime(
            [portfolio_row("INV-FIRST", "C001", "Western Woods, LLC")],
            active_count=1001,
        )
        result = run_manifest(
            runtime,
            {
                "cases": [
                    {
                        "case_id": "truncated",
                        "tool": "get_account_state",
                        "selector": {"account_id": "C001"},
                        "assertions": [{"path": "account.account_id", "op": "truthy"}],
                    }
                ]
            },
        )
        self.assertFalse(result["passed"])
        self.assertIn("exceeds 1000-row public API limit", result["results"][0]["error"])
        self.assertEqual(runtime.account_state_calls, [])

    def test_selector_manifest_contract_is_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            validate_manifest(
                {
                    "cases": [
                        {
                            "case_id": "global-selector",
                            "tool": "get_runtime_contract",
                            "selector": {"account_id": "C001"},
                            "assertions": [{"path": "runtime_version", "op": "truthy"}],
                        }
                    ]
                }
            )
        with self.assertRaises(ValueError):
            validate_manifest(
                {
                    "cases": [
                        {
                            "case_id": "two-authorities",
                            "tool": "get_account_state",
                            "selector": {"account_id": "C001"},
                            "arguments": {"investigation_id": "INV-EXPLICIT"},
                            "assertions": [{"path": "account", "op": "truthy"}],
                        }
                    ]
                }
            )
        with self.assertRaises(ValueError):
            validate_manifest(
                {
                    "cases": [
                        {
                            "case_id": "empty-selector",
                            "tool": "get_account_state",
                            "selector": {"investigation_scope": "DEFAULT"},
                            "assertions": [{"path": "account", "op": "truthy"}],
                        }
                    ]
                }
            )

    def test_selector_is_byte_for_byte_read_only_on_real_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-private-golden-readonly-") as temp:
            runtime = UnifiedRuntime(Path(temp) / "sessions")
            investigation_id = runtime.start_investigation(
                {
                    "account": {
                        "account_id": "C-GOLDEN-READONLY",
                        "name": "Private Golden Read Only Buyer",
                        "country": "Puerto Rico",
                    },
                    "mode": "EXHAUSTIVE",
                    "history": {"events": []},
                }
            )["investigation_id"]
            session_path = runtime.store.path(investigation_id)
            before = session_path.read_bytes()

            result = run_manifest(
                runtime,
                {
                    "cases": [
                        {
                            "case_id": "read-only-selection",
                            "tool": "get_account_state",
                            "selector": {"account_id": "C-GOLDEN-READONLY"},
                            "assertions": [
                                {
                                    "path": "account.account_id",
                                    "op": "eq",
                                    "value": "C-GOLDEN-READONLY",
                                }
                            ],
                        }
                    ]
                },
            )

            self.assertTrue(result["passed"])
            self.assertEqual(
                result["results"][0]["selection"]["investigation_id"],
                investigation_id,
            )
            self.assertEqual(session_path.read_bytes(), before)

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
            validate_manifest(
                {
                    "cases": [
                        {
                            "case_id": "forbidden-mutation",
                            "tool": "start_investigation",
                            "arguments": {},
                            "assertions": [{"path": "status", "op": "truthy"}],
                        }
                    ]
                }
            )

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

    def test_direct_cli_help_runs_from_repository_root(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_private_golden_acceptance.py"),
                "--help",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Run read-only v6 Golden acceptance", completed.stdout)


if __name__ == "__main__":
    unittest.main()
