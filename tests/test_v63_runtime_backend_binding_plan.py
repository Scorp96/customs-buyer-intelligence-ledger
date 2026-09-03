import tempfile
import unittest
from pathlib import Path

from unified_runtime.runtime_backend_binding_plan_v63 import build_v63_runtime_backend_binding_plan


class V63RuntimeBackendBindingPlanTests(unittest.TestCase):
    def _repo(self, with_runtime=True):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "unified_runtime").mkdir()
        if with_runtime:
            (root / "unified_runtime" / "v6.py").write_text('''\
class V6RuntimeMixin:
    def append_peer_discovery(self, arguments):
        return self.store.append(arguments["investigation_id"], "V6_PEER_DISCOVERED", arguments)
    def promote_anchor(self, arguments):
        return self.store.append(arguments["investigation_id"], "V6_ANCHOR_PROMOTED", arguments)
    def append_information_record(self, arguments):
        return self.store.append(arguments["investigation_id"], "INFORMATION_RECORD_APPENDED", arguments)
''', encoding="utf-8")
        return td, root

    def test_shared_primitive_alone_is_not_enough_to_generate_backend(self):
        td, root = self._repo()
        self.addCleanup(td.cleanup)
        result = build_v63_runtime_backend_binding_plan(root)
        self.assertEqual(result["status"], "BACKEND_BINDING_BLOCKED")
        self.assertEqual(result["event_primitive_probe"]["shared_primitive"], "self.store.append")
        self.assertFalse(result["runtime_durable_backend_binding_proven"])
        self.assertFalse(result["backend_codegen_allowed"])
        self.assertIn("CORRELATION_PROPAGATION_NOT_YET_PROVEN", result["blockers"])
        self.assertIn("V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND", result["blockers"])
        self.assertFalse(result["modifies_checkout"])


    def _passing_acceptance_report(self, snapshot_sha="a" * 64):
        from unified_runtime.backend_correlation_acceptance_v63 import REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
        return {
            "schema": "cbi.v63-backend-correlation-acceptance.v1",
            "adapter_path_exercised": "EXISTING_PRODUCTION_INVOKE_MUTATION",
            "runtime_store_exercised": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
            "production_source_snapshot_sha256": snapshot_sha,
            "scenarios": [
                {
                    "scenario": name,
                    "status": "PASS",
                    "reexecute_side_effect": False,
                    "exact_correlation_proven": True,
                    "exact_request_hash_proven": True,
                    "cross_key_result_claimed": False,
                }
                for name in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
            ],
        }

    def test_source_bound_live_acceptance_can_prove_runtime_backend_binding(self):
        td, root = self._repo()
        self.addCleanup(td.cleanup)
        result = build_v63_runtime_backend_binding_plan(
            root,
            backend_correlation_acceptance_report=self._passing_acceptance_report(),
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertEqual(result["status"], "BACKEND_BINDING_PROVEN")
        self.assertTrue(result["correlation_propagation_proven"])
        self.assertTrue(result["runtime_durable_backend_binding_proven"])
        self.assertTrue(result["backend_codegen_allowed"])
        self.assertEqual(result["blockers"], [])

    def test_stale_live_acceptance_does_not_prove_runtime_backend_binding(self):
        td, root = self._repo()
        self.addCleanup(td.cleanup)
        result = build_v63_runtime_backend_binding_plan(
            root,
            backend_correlation_acceptance_report=self._passing_acceptance_report("a" * 64),
            expected_production_source_snapshot_sha256="b" * 64,
        )
        self.assertEqual(result["status"], "BACKEND_BINDING_BLOCKED")
        self.assertFalse(result["runtime_durable_backend_binding_proven"])
        self.assertIn("PRODUCTION_SOURCE_SNAPSHOT_MISMATCH", result["blockers"])

    def test_missing_runtime_source_is_explicit_blocker(self):
        td, root = self._repo(with_runtime=False)
        self.addCleanup(td.cleanup)
        result = build_v63_runtime_backend_binding_plan(root)
        self.assertEqual(result["status"], "BACKEND_BINDING_BLOCKED")
        self.assertIn("RUNTIME_SOURCE_NOT_FOUND", result["blockers"])
        self.assertIn("V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND", result["blockers"])


if __name__ == "__main__":
    unittest.main()
