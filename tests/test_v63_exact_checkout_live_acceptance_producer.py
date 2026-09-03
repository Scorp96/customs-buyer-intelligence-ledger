from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"
HARNESS_MODULE = "unified_runtime.exact_checkout_mcp_harness_v63"
V63_MUTATION_TOOLS = {
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
}


class V63ExactCheckoutLiveAcceptanceProducerBoundaryTests(unittest.TestCase):
    def _module(self):
        spec = importlib.util.find_spec(MODULE)
        self.assertIsNotNone(
            spec,
            "exact-checkout live acceptance producer has not been implemented",
        )
        return importlib.import_module(MODULE)

    def test_public_api_accepts_execution_configuration_only(self):
        module = self._module()
        config_type = module.ExactCheckoutAcceptanceConfig
        self.assertTrue(dataclasses.is_dataclass(config_type))
        self.assertEqual(
            [field.name for field in dataclasses.fields(config_type)],
            ["repo_root", "expected_git_sha", "output_dir"],
        )
        signature = inspect.signature(module.run_v63_exact_checkout_live_acceptance)
        self.assertEqual(tuple(signature.parameters), ("config",))
        self.assertEqual(signature.parameters["config"].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)

    def test_public_api_exposes_no_caller_verdict_or_report_parameters(self):
        module = self._module()
        signature = inspect.signature(module.run_v63_exact_checkout_live_acceptance)
        forbidden = {
            "report",
            "backend_report",
            "receipt_envelope",
            "receipts",
            "passed",
            "exact_correlation_proven",
            "exact_request_hash_proven",
            "reexecute_side_effect",
        }
        self.assertTrue(forbidden.isdisjoint(signature.parameters))

    def test_config_paths_and_expected_git_sha_are_caller_inputs(self):
        module = self._module()
        config = module.ExactCheckoutAcceptanceConfig(
            repo_root=Path("/tmp/cbi-v63-checkout"),
            expected_git_sha="a" * 40,
            output_dir=Path("/tmp/cbi-v63-output"),
        )
        self.assertEqual(config.repo_root, Path("/tmp/cbi-v63-checkout"))
        self.assertEqual(config.expected_git_sha, "a" * 40)
        self.assertEqual(config.output_dir, Path("/tmp/cbi-v63-output"))

    def test_expected_git_sha_mismatch_blocks_before_mutation_process_start(self):
        module = self._module()
        config = module.ExactCheckoutAcceptanceConfig(
            repo_root=ROOT,
            expected_git_sha="0" * 40,
            output_dir=ROOT / ".tmp-v63-acceptance-should-not-exist",
        )
        with mock.patch(
            "unified_runtime.exact_checkout_mcp_harness_v63.ExactCheckoutMcpHarness.start"
        ) as start:
            with self.assertRaisesRegex(RuntimeError, "GIT_SHA_MISMATCH"):
                module.run_v63_exact_checkout_live_acceptance(config)
        start.assert_not_called()

    def test_source_snapshot_must_be_ready_before_mutation_process_start(self):
        module = self._module()
        config = module.ExactCheckoutAcceptanceConfig(
            repo_root=ROOT,
            expected_git_sha=module._checkout_git_sha(ROOT),
            output_dir=ROOT / ".tmp-v63-acceptance-should-not-exist",
        )
        blocked_snapshot = {
            "status": "BLOCKED",
            "source_pins_complete": False,
            "snapshot_sha256": "",
            "blockers": ["SOURCE_PIN_MISSING"],
        }
        with mock.patch(
            "unified_runtime.production_source_snapshot_v63.build_v63_production_source_snapshot",
            return_value=blocked_snapshot,
        ):
            with mock.patch(
                "unified_runtime.exact_checkout_mcp_harness_v63.ExactCheckoutMcpHarness.start"
            ) as start:
                with self.assertRaisesRegex(RuntimeError, "SOURCE_SNAPSHOT_NOT_READY"):
                    module.run_v63_exact_checkout_live_acceptance(config)
        start.assert_not_called()


class V63ExactCheckoutMcpHarnessContractTests(unittest.TestCase):
    def _module(self):
        spec = importlib.util.find_spec(HARNESS_MODULE)
        self.assertIsNotNone(
            spec,
            "exact-checkout active MCP harness has not been implemented",
        )
        return importlib.import_module(HARNESS_MODULE)

    def test_harness_public_contract_is_process_oriented(self):
        module = self._module()
        harness = module.ExactCheckoutMcpHarness
        expected = {
            "__init__": ("self", "repo_root", "persistence_root"),
            "active_entrypoint": ("self",),
            "start": ("self", "crash_after_handler"),
            "list_tool_names": ("self", "request_id"),
            "tool": ("self", "request_id", "name", "arguments"),
            "crash_tool": ("self", "request_id", "name", "arguments"),
            "stop": ("self",),
        }
        for name, parameters in expected.items():
            signature = inspect.signature(getattr(harness, name))
            self.assertEqual(tuple(signature.parameters), parameters, name)
        self.assertEqual(
            inspect.signature(harness.start).parameters["crash_after_handler"].default,
            "",
        )
        self.assertEqual(
            inspect.signature(harness.list_tool_names).parameters["request_id"].default,
            2,
        )

    def test_active_entrypoint_is_resolved_from_checkout_configuration(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "mcp").mkdir()
            (root / "mcp" / "server_v61_backup_recovery.py").write_text(
                "def main(): return 0\n",
                encoding="utf-8",
            )
            (root / ".mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "cbi": {
                                "command": "python",
                                "args": ["mcp/server_v61_backup_recovery.py", "--stdio"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            harness = module.ExactCheckoutMcpHarness(root, root / "persistence")
            self.assertEqual(
                harness.active_entrypoint(),
                "mcp/server_v61_backup_recovery.py",
            )

    def test_real_feature_checkout_launches_active_recovery_entrypoint_and_lists_v63_mutations(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            harness = module.ExactCheckoutMcpHarness(ROOT, Path(td))
            self.assertEqual(
                harness.active_entrypoint(),
                "mcp/server_v61_backup_recovery.py",
            )
            harness.start()
            try:
                names = harness.list_tool_names()
            finally:
                harness.stop()
            self.assertTrue(V63_MUTATION_TOOLS <= names)

    def test_tool_calls_real_active_mcp_and_returns_structured_content(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            harness = module.ExactCheckoutMcpHarness(ROOT, Path(td))
            harness.start()
            try:
                contract = harness.tool(3, "get_runtime_contract", {})
            finally:
                harness.stop()
            self.assertIsInstance(contract, dict)
            self.assertIn("production_adapter_mutation_wal", contract)

    def test_crash_tool_observes_cold_process_exit_after_handler_side_effect(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            persistence_root = Path(td)
            harness = module.ExactCheckoutMcpHarness(ROOT, persistence_root)
            args = {
                "candidate": {
                    "account_id": "C-V63-HARNESS-CRASH",
                    "country": "Synthetic",
                    "name": "Synthetic v6.3 Harness Crash Buyer",
                },
                "requested_account_id": "C-V63-HARNESS-CRASH",
                "create_if_missing": True,
                "idempotency_key": "v63-harness-crash-0001",
            }
            harness.start(crash_after_handler="resolve_or_create_account")
            try:
                harness.crash_tool(2, "resolve_or_create_account", args)
            finally:
                harness.stop()

            canonical_log = (
                persistence_root
                / "sessions"
                / ".runtime"
                / "canonical"
                / "accounts.jsonl"
            )
            self.assertTrue(canonical_log.is_file())
            self.assertEqual(
                len(canonical_log.read_text(encoding="utf-8").splitlines()),
                1,
            )


if __name__ == "__main__":
    unittest.main()
