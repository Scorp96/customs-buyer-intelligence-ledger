from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cbi-v63-live-acceptance-ci.yml"
PRODUCTION_BASELINE = "ba3bffdae13cef186b20b50335c3207fb3390ec6"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


class V63ExactCheckoutReleaseCiContractTests(unittest.TestCase):
    def test_feature_only_release_gate_runs_full_regression_protocols_cli_and_uploads_only_four_receipts(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("cbi-v6-3-demand-expansion", text)
        self.assertIn("contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("id-token: write", text)

        self.assertIn("python-version: '3.10'", text)
        self.assertIn("python-version: '3.11'", text)
        self.assertIn("python -m unittest discover -s tests -p 'test_v63_*.py' -q", text)
        self.assertIn("python -m unittest discover -s tests -p 'test_*.py' -q", text)
        self.assertIn("python mcp/v6_protocol_test.py", text)
        self.assertIn("python mcp/v61_hardening_protocol_test.py", text)
        self.assertIn("git diff --check", text)

        self.assertIn("scripts/run_v63_exact_checkout_live_acceptance.py", text)
        self.assertIn("--expected-git-sha \"$GITHUB_SHA\"", text)
        self.assertIn("--output-dir \"$RUNNER_TEMP/v63-exact-checkout-artifacts\"", text)

        self.assertIn(
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}",
            text,
        )
        self.assertIn("V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json", text)
        self.assertIn("V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json", text)
        self.assertIn("V63_EXACT_CHECKOUT_RECOVERY_OVERLAY.json", text)
        self.assertIn("V63_EXACT_CHECKOUT_ACCEPTANCE.json", text)
        self.assertIn("recovery_overlay_validation", text)

        self.assertIn("cbi-v6-cloud-runtime-20260901", text)
        self.assertIn(PRODUCTION_BASELINE, text)
        self.assertIn("PRODUCTION_BRANCH_UNCHANGED", text)

        for forbidden in (
            "git push",
            "render deploy",
            "wrangler deploy",
            "aws s3",
            "rclone copy",
        ):
            self.assertNotIn(forbidden, text.lower())


if __name__ == "__main__":
    unittest.main()
