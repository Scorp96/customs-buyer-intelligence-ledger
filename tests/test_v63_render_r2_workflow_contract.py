from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cbi-v63-render-r2-pvc-acceptance.yml"
SCRIPT = ROOT / "scripts" / "run_v63_render_r2_pvc_acceptance.py"
STATUS_ARTIFACT = "V63_RENDER_R2_PVC_ACCEPTANCE_STATUS.json"
ZERO_SHA = "0" * 40
_EXTERNAL_ENV = (
    "CBI_V63_RENDER_DEPLOY_HOOK_URL",
    "CBI_V63_RENDER_RESTART_HOOK_URL",
    "CBI_V63_ACCEPTANCE_BASE_URL",
    "CBI_V63_ACCEPTANCE_BEARER_TOKEN",
    "CBI_V63_R2_ENDPOINT",
    "CBI_V63_R2_BUCKET",
    "CBI_V63_R2_ACCESS_KEY_ID",
    "CBI_V63_R2_SECRET_ACCESS_KEY",
    "CBI_V63_R2_PREFIX",
    "CBI_V63_R2_REGION",
)


class V63RenderR2WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_explicit_dispatch_only_and_preserves_production_boundary(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), "Task 9 workflow is missing")
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("\n  push:", text)
        self.assertNotIn("\n  pull_request:", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("cbi-v6-3-demand-expansion", text)
        self.assertIn("Assert exact feature SHA", text)
        self.assertIn("Run deterministic regressions", text)
        self.assertIn("Run Render R2 PVC acceptance", text)
        self.assertIn("Upload sanitized Render R2 PVC acceptance receipts", text)
        self.assertIn("Verify production branch baseline is unchanged", text)
        self.assertIn("ba3bffdae13cef186b20b50335c3207fb3390ec6", text)
        self.assertIn("BLOCKED_EXTERNAL", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("gh pr merge", text)

    def test_workflow_requires_isolated_external_coordinates_without_committed_credentials(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), "Task 9 workflow is missing")
        text = WORKFLOW.read_text(encoding="utf-8")
        for name in (
            "CBI_V63_RENDER_DEPLOY_HOOK_URL",
            "CBI_V63_RENDER_RESTART_HOOK_URL",
            "CBI_V63_ACCEPTANCE_BASE_URL",
            "CBI_V63_ACCEPTANCE_BEARER_TOKEN",
            "CBI_V63_R2_ENDPOINT",
            "CBI_V63_R2_BUCKET",
            "CBI_V63_R2_ACCESS_KEY_ID",
            "CBI_V63_R2_SECRET_ACCESS_KEY",
            "CBI_V63_R2_PREFIX",
        ):
            self.assertIn(name, text)
        self.assertIn("secrets.", text)
        self.assertNotIn("cbi-v6-cloud-runtime-20260901.onrender.com", text)

    def test_cli_missing_external_configuration_is_blocked_external_not_pass(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "Task 9 CLI is missing")
        with tempfile.TemporaryDirectory(prefix="cbi-v63-render-r2-blocked-") as tmp_name:
            environment = dict(os.environ)
            for name in _EXTERNAL_ENV:
                environment.pop(name, None)
            environment["PATH"] = str(Path(sys.executable).parent)
            environment["PYTHONHASHSEED"] = "0"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--expected-git-sha",
                    ZERO_SHA,
                    "--output-dir",
                    tmp_name,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=environment,
                timeout=20,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            status_path = Path(tmp_name) / STATUS_ARTIFACT
            self.assertTrue(status_path.is_file(), completed.stderr)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status.get("status"), "BLOCKED_EXTERNAL")
            self.assertIs(status.get("verified"), False)
            self.assertIs(status.get("production_ready"), False)
            self.assertTrue(status.get("missing_external_configuration"))
            serialized = json.dumps(status, sort_keys=True).casefold()
            self.assertNotIn("bearer_token", serialized)
            self.assertNotIn("secret_access_key", serialized)
            self.assertNotIn("idempotency_key", serialized)

    def test_cli_exposes_configuration_only_not_caller_verdict_switches(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "Task 9 CLI is missing")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        help_text = completed.stdout
        self.assertIn("--expected-git-sha", help_text)
        self.assertIn("--output-dir", help_text)
        self.assertNotIn("--verified", help_text)
        self.assertNotIn("--pass", help_text)
        self.assertNotIn("--production-ready", help_text)
        self.assertNotIn("--report", help_text)


if __name__ == "__main__":
    unittest.main()
