from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_v6_load_acceptance import TARGETS, run_smoke


ROOT = Path(__file__).resolve().parents[1]


class V61LoadAcceptanceTests(unittest.TestCase):
    def test_smoke_profile_builds_100_evidence_and_reports_spec_metrics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-load-test-") as temp:
            result = run_smoke(Path(temp) / "sessions", enforce_targets=False)

        self.assertTrue(result["passed"])
        self.assertEqual(result["profile"], "smoke")
        self.assertEqual(result["evidence_count"], 100)
        self.assertFalse(result["enforce_targets"])
        self.assertEqual(result["targets"], TARGETS)
        self.assertEqual(set(result["metrics"]), set(TARGETS))
        self.assertEqual(set(result["target_results"]), set(TARGETS))
        for value in result["metrics"].values():
            self.assertGreaterEqual(value, 0.0)

    def test_direct_cli_smoke_runs_from_repository_root(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_v6_load_acceptance.py"),
                "--profile",
                "smoke",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence_count"], 100)

    def test_spec_performance_targets_are_explicit_not_silently_relaxed(self) -> None:
        self.assertEqual(TARGETS["bundle_100_seconds"], 5.0)
        self.assertEqual(TARGETS["state_query_seconds"], 0.5)
        self.assertEqual(TARGETS["resume_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
