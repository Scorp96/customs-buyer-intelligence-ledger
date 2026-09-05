import tempfile
import unittest
from pathlib import Path

from release_ops_v63.exact_checkout_candidate_builder import run_exact_checkout_validation_suite
from tests.test_v63_production_gate import V63ProductionGateTests
from unified_runtime.contract_v63 import build_v63_contract
from unified_runtime.production_binding_plan import _runtime_payload_files
from unified_runtime.production_gate_v63 import evaluate_v63_production_gate
from unified_runtime.production_integration_runner import V63_RUNTIME_PAYLOAD_NAMES, _payload_paths


class V64StreamBSemanticForwardPortTests(unittest.TestCase):
    SNAP = "SNAP-20260901T061755Z-0813157703d0"
    SHA = "a" * 64

    def test_backup_retention_builder_derives_verification(self):
        from unified_runtime.backup_retention_evidence_v64 import build_backup_retention_evidence

        def health(snapshot_id):
            return {
                "status": "READY",
                "backup_recovery": {
                    "schema": "cbi.backup-status.v6.1",
                    "source_session_root": "/var/lib/cbi/live/sessions",
                    "backup_root": "s3://cbi-prod/backups-v61",
                    "latest": {
                        "snapshot_id": snapshot_id,
                        "created_at": "2026-09-01T06:17:56.436542Z",
                        "reasons": ["DAILY"],
                        "path": f"s3://cbi-prod/backups-v61/{snapshot_id}",
                    },
                    "daily_snapshot_present": True,
                    "restore_overwrites_live_root": False,
                },
            }

        result = build_backup_retention_evidence(
            pre_deploy_health=health(self.SNAP),
            post_restart_health=health(self.SNAP),
            post_deploy_health=health(self.SNAP),
            production_source_snapshot_sha256=self.SHA,
            backup_root_persistence_mode="OBJECT_STORE_REPLICATED",
            external_replication_verified=True,
            external_snapshot_locator=f"s3://cbi-prod/backups-v61/{self.SNAP}",
            observed_at="2026-09-04T00:00:00Z",
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["blockers"], [])

    def test_production_gate_fails_closed_without_backup_retention(self):
        payload = V63ProductionGateTests().healthy_payload()
        payload["backup_retention_verified"] = False
        result = evaluate_v63_production_gate(payload)
        self.assertFalse(result["production_ready"])
        self.assertIn("BACKUP_RETENTION_NOT_VERIFIED", result["blockers"])
        self.assertFalse(result["checked_backup_retention"])

    def test_contract_declares_v64_backup_retention_gate(self):
        contract = build_v63_contract()
        gate = contract["deployment_backup_retention_v6_4"]
        self.assertTrue(gate["required_before_production"])
        self.assertEqual(gate["evidence_schema"], "cbi.v64-backup-retention-evidence.v1")
        self.assertFalse(gate["local_ephemeral_root_sufficient"])
        self.assertTrue(gate["restore_target_must_be_isolated"])

    def test_release_evidence_validates_backup_retention_report(self):
        from unified_runtime.release_evidence_v63 import _validate_backup_retention_report

        report = {
            "schema": "cbi.v64-backup-retention-evidence.v1",
            "verified": True,
            "production_source_snapshot_sha256": self.SHA,
            "preexisting_snapshot_observed": True,
            "snapshot_id_before_deploy": self.SNAP,
            "snapshot_id_after_restart": self.SNAP,
            "snapshot_ids_after_deploy": [self.SNAP],
            "backup_history_preserved_after_restart": True,
            "backup_history_preserved_after_deploy": True,
            "backup_root_persistence_mode": "OBJECT_STORE_REPLICATED",
            "external_replication_verified": True,
            "external_snapshot_locator": f"s3://cbi-prod/backups-v61/{self.SNAP}",
            "restore_target_isolated": True,
            "restore_overwrites_live_root": False,
            "observed_at": "2026-09-04T00:00:00Z",
            "source": "HOST_BACKUP_RETENTION_HEALTH_SEQUENCE",
        }
        result = _validate_backup_retention_report(
            report,
            expected_production_source_snapshot_sha256=self.SHA,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["blockers"], [])

    def test_binding_plan_uses_explicit_current_v63_payload_inventory(self):
        expected = [f"unified_runtime/{name}" for name in V63_RUNTIME_PAYLOAD_NAMES]
        files = _runtime_payload_files()
        self.assertEqual(files, expected)
        self.assertNotIn("unified_runtime/research_orchestration_hardening.py", files)
        self.assertNotIn("unified_runtime/canonical_identity_reconciliation_v64.py", files)
        self.assertNotIn("unified_runtime/backup_retention_evidence_v64.py", files)

    def test_integration_runner_payload_matches_owned_inventory(self):
        self.assertEqual([path.name for path in _payload_paths()], list(V63_RUNTIME_PAYLOAD_NAMES))
        self.assertNotIn("research_orchestration_hardening.py", V63_RUNTIME_PAYLOAD_NAMES)
        self.assertNotIn("canonical_identity_reconciliation_v64.py", V63_RUNTIME_PAYLOAD_NAMES)

    def test_staging_validation_runs_v64_gate_tests_too(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            export = root / "export"
            payload = root / "payload"
            (export / "tests").mkdir(parents=True)
            (payload / "tests").mkdir(parents=True)
            (export / "unified_runtime").mkdir(parents=True)
            (export / "tests" / "test_production_smoke.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (payload / "tests" / "test_v63_smoke.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (payload / "tests" / "test_v64_release_gate.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_must_run(self): self.fail('V64_GATE_EXECUTED')\n",
                encoding="utf-8",
            )

            result = run_exact_checkout_validation_suite(
                export,
                payload_root=payload,
                python_executable=__import__("sys").executable,
            )
            staging = result["checks"]["v63_staging_tests"]
            self.assertFalse(staging["passed"])
            self.assertIn("V64_GATE_EXECUTED", staging["output"])
            self.assertIn("test_*.py", staging["args"])


if __name__ == "__main__":
    unittest.main()
