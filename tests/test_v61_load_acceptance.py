from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.run_v6_load_acceptance import TARGETS, UnifiedRuntime, run_full, run_smoke


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

    def test_reduced_full_profile_verifies_persisted_canonical_accounts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-load-full-count-") as temp:
            result = run_full(
                Path(temp) / "sessions",
                canonical_accounts=7,
                total_evidence=20,
                pivot_count=4,
                peer_count=3,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["profile"], "full-reduced-structural")
        self.assertEqual(result["counts"]["canonical_accounts_requested"], 7)
        self.assertEqual(result["counts"]["canonical_accounts_created_results"], 7)
        self.assertEqual(result["counts"]["canonical_accounts_persisted"], 7)
        self.assertEqual(result["counts"]["canonical_account_ids_unique"], 7)

    def test_full_profile_fails_if_resolver_reports_created_without_persistence(self) -> None:
        fake_created = {
            "status": "CREATED",
            "match": {
                "account_id": "C-FAKE",
                "score": 100,
                "reasons": ["SYNTHETIC_TEST_ONLY"],
                "origin": "CANONICAL_REGISTRY",
            },
            "candidates": [],
        }
        with tempfile.TemporaryDirectory(prefix="cbi-v61-load-full-failclosed-") as temp:
            with mock.patch.object(
                UnifiedRuntime,
                "resolve_or_create_account",
                return_value=fake_created,
            ):
                result = run_full(
                    Path(temp) / "sessions",
                    canonical_accounts=3,
                    total_evidence=8,
                    pivot_count=2,
                    peer_count=1,
                )

        self.assertFalse(result["passed"])
        self.assertEqual(result["counts"]["canonical_accounts_created_results"], 3)
        self.assertEqual(result["counts"]["canonical_accounts_persisted"], 0)
        self.assertEqual(result["counts"]["canonical_account_ids_unique"], 0)

    def test_spec_performance_targets_are_explicit_not_silently_relaxed(self) -> None:
        self.assertEqual(TARGETS["bundle_100_seconds"], 5.0)
        self.assertEqual(TARGETS["state_query_seconds"], 0.5)
        self.assertEqual(TARGETS["resume_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
