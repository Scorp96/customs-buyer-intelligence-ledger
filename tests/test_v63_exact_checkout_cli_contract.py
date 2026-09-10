from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_v63_exact_checkout_live_acceptance.py"


class V63ExactCheckoutCliContractTests(unittest.TestCase):
    def test_cli_exposes_only_expected_git_sha_and_output_dir_inputs(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        help_text = completed.stdout
        self.assertIn("--expected-git-sha", help_text)
        self.assertIn("--output-dir", help_text)
        self.assertNotIn("--receipts", help_text)
        self.assertNotIn("--report", help_text)
        self.assertNotIn("--passed", help_text)
        self.assertNotIn("--repo-root", help_text)
        self.assertNotIn("--source-snapshot", help_text)

    def test_cli_returns_nonzero_before_artifact_issuance_for_invalid_git_sha(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "artifacts"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--expected-git-sha",
                    "not-a-git-sha",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
