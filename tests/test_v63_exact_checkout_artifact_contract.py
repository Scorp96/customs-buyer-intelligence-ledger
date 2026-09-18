from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_runtime.backend_correlation_acceptance_v63 import (
    REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS,
)
from unified_runtime.exact_recovery_acceptance_v63 import (
    REQUIRED_V63_EXACT_RECOVERY_CASES,
)
from unified_runtime.recovery_overlay_acceptance_v63 import (
    REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS,
)
from unified_runtime.exact_checkout_live_acceptance_producer_v63 import (
    ExactCheckoutAcceptanceConfig,
    run_v63_exact_checkout_live_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FILES = {
    "V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json",
    "V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json",
    "V63_EXACT_CHECKOUT_RECOVERY_OVERLAY.json",
    "V63_EXACT_CHECKOUT_ACCEPTANCE.json",
}


def _assert_no_raw_idempotency_key_fields(testcase: unittest.TestCase, value) -> None:
    if isinstance(value, dict):
        testcase.assertNotIn("idempotency_key", value)
        for child in value.values():
            _assert_no_raw_idempotency_key_fields(testcase, child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_raw_idempotency_key_fields(testcase, child)


class V63ExactCheckoutArtifactContractTests(unittest.TestCase):
    def test_public_run_executes_live_checkout_and_writes_four_verified_nonproduction_artifacts(self):
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "artifacts"
            result = run_v63_exact_checkout_live_acceptance(
                ExactCheckoutAcceptanceConfig(
                    repo_root=ROOT,
                    expected_git_sha=git_sha,
                    output_dir=output_dir,
                )
            )

            self.assertEqual({path.name for path in output_dir.iterdir()}, EXPECTED_FILES)
            backend = json.loads(
                (output_dir / "V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json").read_text(
                    encoding="utf-8"
                )
            )
            receipts = json.loads(
                (output_dir / "V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json").read_text(
                    encoding="utf-8"
                )
            )
            overlay = json.loads(
                (output_dir / "V63_EXACT_CHECKOUT_RECOVERY_OVERLAY.json").read_text(
                    encoding="utf-8"
                )
            )
            acceptance = json.loads(
                (output_dir / "V63_EXACT_CHECKOUT_ACCEPTANCE.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(
            [row["scenario"] for row in backend["scenarios"]],
            list(REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS),
        )
        self.assertEqual(
            [row["case"] for row in receipts["receipts"]],
            list(REQUIRED_V63_EXACT_RECOVERY_CASES),
        )
        self.assertEqual(
            [row["scenario"] for row in overlay["scenarios"]],
            list(REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS),
        )
        self.assertEqual(backend["adapter_path_exercised"], "EXISTING_PRODUCTION_INVOKE_MUTATION")
        self.assertEqual(backend["runtime_store_exercised"], "EXISTING_PRODUCTION_APPEND_ONLY_STORE")
        for receipt in receipts["receipts"]:
            self.assertEqual(receipt["execution_origin"], "LIVE_PRODUCTION_CHECKOUT")
            self.assertEqual(
                receipt["adapter_path_exercised"],
                "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH",
            )
            self.assertTrue(receipt["passed"])
            self.assertFalse(receipt["reexecute_side_effect"])

        self.assertEqual(
            overlay["active_overlay_path_exercised"],
            "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
        )
        self.assertFalse(overlay["reference_runner_only"])
        for row in overlay["scenarios"]:
            self.assertEqual(row["status"], "PASS")
            self.assertTrue(row["active_overlay_handler_exercised"])
            self.assertFalse(row["reexecute_side_effect"])
            self.assertTrue(row["exact_correlation_proven"])
            self.assertTrue(row["exact_request_hash_proven"])
        opportunity = next(
            row
            for row in overlay["scenarios"]
            if row["scenario"] == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS"
        )
        self.assertTrue(opportunity["exact_result_snapshot_proven"])

        self.assertTrue(acceptance["backend_validation"]["verified"])
        self.assertTrue(acceptance["recovery_validation"]["verified"])
        self.assertTrue(acceptance["recovery_overlay_validation"]["verified"])
        self.assertEqual(acceptance["execution_environment"], "EXACT_CHECKOUT_ISOLATED")
        self.assertEqual(acceptance["deployment_environment"], "NOT_RENDER_PRODUCTION")
        self.assertEqual(acceptance["git_sha"], git_sha)
        self.assertTrue(acceptance["render_r2_acceptance_required"])
        self.assertFalse(acceptance["production_ready"])
        self.assertEqual(result, acceptance)

        _assert_no_raw_idempotency_key_fields(self, backend)
        _assert_no_raw_idempotency_key_fields(self, receipts)
        _assert_no_raw_idempotency_key_fields(self, overlay)
        _assert_no_raw_idempotency_key_fields(self, acceptance)


if __name__ == "__main__":
    unittest.main()
