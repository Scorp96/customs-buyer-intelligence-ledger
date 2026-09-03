import tempfile
import unittest
from pathlib import Path

from unified_runtime.production_integration_runner import apply_v63_runtime_phase


V62_INIT = '''from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n\nclass UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n    object,\n):\n    pass\n'''

SERVER = '''\ndef _invoke_mutation(*args, **kwargs):\n    # PREPARED -> COMMITTED / MUTATION_RECONCILIATION_REQUIRED\n    correlation_id = "mutation_correlation"\n    return args, kwargs\n\nTOOLS = [\n    "append_peer_discovery",\n    "promote_anchor",\n    "resolve_or_create_account",\n    "append_information_record",\n]\n'''


class V63ProductionIntegrationRunnerTests(unittest.TestCase):
    def _repo(self, root: Path, *, with_v62: bool = True) -> Path:
        repo = root / "repo"
        (repo / "unified_runtime").mkdir(parents=True)
        (repo / "mcp").mkdir(parents=True)
        if with_v62:
            (repo / "unified_runtime" / "research_orchestration_hardening.py").write_text(
                "class V61ResearchOrchestrationHardeningMixin: pass\n", encoding="utf-8"
            )
            (repo / "unified_runtime" / "v6.py").write_text(
                "class V6RuntimeMixin: pass\n", encoding="utf-8"
            )
            (repo / "unified_runtime" / "__init__.py").write_text(V62_INIT, encoding="utf-8")
        else:
            (repo / "unified_runtime" / "__init__.py").write_text(
                "class UnifiedRuntime(object): pass\n", encoding="utf-8"
            )
        (repo / "mcp" / "server_v61.py").write_text(SERVER, encoding="utf-8")
        (repo / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from .server_v61 import *\n", encoding="utf-8"
        )
        (repo / ".mcp.json").write_text(
            '{"command":"python mcp/server_v61_backup_recovery.py --stdio"}\n', encoding="utf-8"
        )
        return repo

    def test_dry_run_does_not_modify_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            before = (repo / "unified_runtime" / "__init__.py").read_bytes()
            result = apply_v63_runtime_phase(repo, dry_run=True)
            self.assertEqual(result["status"], "READY_TO_APPLY_RUNTIME_PATCH")
            self.assertFalse(result["modified_checkout"])
            self.assertEqual((repo / "unified_runtime" / "__init__.py").read_bytes(), before)
            self.assertFalse((repo / "unified_runtime" / "demand_expansion.py").exists())

    def test_apply_copies_runtime_and_patches_mro_without_switching_mcp_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            mcp_before = (repo / ".mcp.json").read_bytes()
            result = apply_v63_runtime_phase(repo, dry_run=False)
            self.assertEqual(result["status"], "RUNTIME_PATCH_APPLIED_ADAPTER_PENDING")
            self.assertTrue(result["modified_checkout"])
            init_text = (repo / "unified_runtime" / "__init__.py").read_text(encoding="utf-8")
            self.assertIn("from .demand_expansion import V63DemandExpansionMixin", init_text)
            self.assertLess(
                init_text.index("    V63DemandExpansionMixin,"),
                init_text.index("    V61ResearchOrchestrationHardeningMixin,"),
            )
            self.assertTrue((repo / "unified_runtime" / "demand_expansion.py").is_file())
            self.assertEqual((repo / ".mcp.json").read_bytes(), mcp_before)
            self.assertFalse(result["adapter_bound"])
            snapshot = result["phase_b_source_snapshot"]
            self.assertEqual(snapshot["status"], "READY")
            self.assertEqual(len(snapshot["snapshot_sha256"]), 64)
            self.assertIn("mcp/server_v61_backup_recovery.py", snapshot["files"])
            self.assertIn("unified_runtime/__init__.py", snapshot["files"])

    def test_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            first = apply_v63_runtime_phase(repo, dry_run=False)
            second = apply_v63_runtime_phase(repo, dry_run=False)
            self.assertEqual(first["status"], "RUNTIME_PATCH_APPLIED_ADAPTER_PENDING")
            self.assertEqual(second["status"], "RUNTIME_PATCH_ALREADY_PRESENT_ADAPTER_PENDING")
            init_text = (repo / "unified_runtime" / "__init__.py").read_text(encoding="utf-8")
            self.assertEqual(init_text.count("V63DemandExpansionMixin,"), 1)
            self.assertEqual(init_text.count("from .demand_expansion import V63DemandExpansionMixin"), 1)

    def test_pre_v62_checkout_fails_closed_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td), with_v62=False)
            before = (repo / "unified_runtime" / "__init__.py").read_bytes()
            result = apply_v63_runtime_phase(repo, dry_run=False)
            self.assertEqual(result["status"], "BLOCKED_PREPATCH")
            self.assertFalse(result["modified_checkout"])
            self.assertIn("V62_ORCHESTRATION_NOT_PRESENT", result["blockers"])
            self.assertEqual((repo / "unified_runtime" / "__init__.py").read_bytes(), before)

    def test_existing_different_v63_runtime_file_blocks_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            target = repo / "unified_runtime" / "demand_expansion.py"
            target.write_text("# unrelated existing file\n", encoding="utf-8")
            before = target.read_bytes()
            result = apply_v63_runtime_phase(repo, dry_run=False)
            self.assertEqual(result["status"], "BLOCKED_PREPATCH")
            self.assertIn("V63_RUNTIME_FILE_CONFLICT:demand_expansion.py", result["blockers"])
            self.assertEqual(target.read_bytes(), before)
            init_text = (repo / "unified_runtime" / "__init__.py").read_text(encoding="utf-8")
            self.assertNotIn("V63DemandExpansionMixin", init_text)

    def test_runtime_phase_never_claims_production_ready(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            result = apply_v63_runtime_phase(repo, dry_run=False)
            self.assertFalse(result["production_ready"])
            self.assertFalse(result["adapter_bound"])
            self.assertEqual(result["next_gate"], "BIND_EXISTING_PRODUCTION_WAL_AND_MCP")


if __name__ == "__main__":
    unittest.main()
