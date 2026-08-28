from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_v6_load_acceptance import (
    SCALE_TARGETS,
    TARGETS,
    run_scale,
    run_smoke,
)


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

    def test_spec_scalability_targets_are_explicit_not_silently_relaxed(self) -> None:
        self.assertEqual(
            SCALE_TARGETS,
            {
                "canonical_accounts": 5000,
                "simultaneous_investigations": 1000,
                "evidence_records": 100000,
                "source_attempts": 100000,
                "peers": 20000,
            },
        )

    def test_reduced_scale_profile_uses_cold_hash_chains_and_public_portfolio(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-scale-structural-") as temp:
            result = run_scale(
                Path(temp) / "sessions",
                canonical_accounts=5,
                simultaneous_investigations=2,
                evidence_records=6,
                source_attempts=6,
                peers=2,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["profile"], "scale-reduced-structural")
        self.assertEqual(
            result["counts"],
            {
                "canonical_accounts": 5,
                "simultaneous_investigations": 2,
                "evidence_records": 6,
                "source_attempts": 6,
                "peers": 2,
                "portfolio_active_investigations": 2,
                "portfolio_total_scanned": 2,
                "portfolio_superseded": 0,
                "portfolio_quarantined": 0,
            },
        )
        self.assertEqual(result["formal_api_samples"]["evidence_compiler_investigations"], 2)
        self.assertEqual(result["formal_api_samples"]["source_attempt_api_samples"], 2)
        self.assertEqual(result["formal_api_samples"]["peer_discovery_api_samples"], 2)
        boundary = result["acceptance_boundary"]
        self.assertTrue(boundary["proves_durable_state_scalability"])
        self.assertFalse(boundary["proves_single_record_mutation_throughput_slo"])
        self.assertTrue(boundary["all_evidence_compiled_by_formal_v6_compiler"])
        self.assertTrue(boundary["cold_reload_validates_hash_chains"])
        self.assertTrue(boundary["portfolio_active_count_uses_public_runtime_view"])


if __name__ == "__main__":
    unittest.main()
