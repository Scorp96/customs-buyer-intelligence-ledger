from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path


MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"
HARNESS_MODULE = "unified_runtime.exact_checkout_mcp_harness_v63"


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


if __name__ == "__main__":
    unittest.main()
