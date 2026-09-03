from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import inspect
import unittest
from pathlib import Path


MODULE = "unified_runtime.exact_checkout_live_acceptance_producer_v63"


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


if __name__ == "__main__":
    unittest.main()
