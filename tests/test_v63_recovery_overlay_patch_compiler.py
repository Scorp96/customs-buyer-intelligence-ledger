import ast
import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.production_source_snapshot_v63 import build_v63_production_source_snapshot
from unified_runtime.recovery_overlay_patch_compiler_v63 import compile_v63_recovery_overlay_patch_candidate


OVERLAY = '''\
from . import server_v61 as _base

def _recover_peer(intent, durable_events):
    arguments = intent["arguments"]
    correlation_id = intent["correlation_id"]
    if not durable_events:
        return {"status": "MUTATION_RECONCILIATION_REQUIRED", "correlation_id": correlation_id}
    return {"status": "RECOVERED", "event": durable_events[0], "arguments": arguments}

def _recover_anchor(intent, durable_events):
    arguments = intent["arguments"]
    correlation_id = intent["correlation_id"]
    if not durable_events:
        return {"status": "MUTATION_RECONCILIATION_REQUIRED", "correlation_id": correlation_id}
    return {"status": "RECOVERED", "event": durable_events[0], "arguments": arguments}

RECOVERY_HANDLERS = {
    "append_peer_discovery": _recover_peer,
    "promote_anchor": _recover_anchor,
}
'''


class V63RecoveryOverlayPatchCompilerTests(unittest.TestCase):
    def _repo(self, root: Path, overlay_source: str = OVERLAY) -> Path:
        repo = root / "repo"
        (repo / "mcp").mkdir(parents=True)
        (repo / "unified_runtime").mkdir(parents=True)
        (repo / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(V61ResearchOrchestrationHardeningMixin): pass\n", encoding="utf-8"
        )
        (repo / "unified_runtime" / "research_orchestration_hardening.py").write_text(
            "class V61ResearchOrchestrationHardeningMixin: pass\n", encoding="utf-8"
        )
        (repo / "unified_runtime" / "v6.py").write_text("class V6RuntimeMixin: pass\n", encoding="utf-8")
        (repo / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS={'append_peer_discovery','promote_anchor','resolve_or_create_account','append_information_record'}\n"
            "def _invoke_mutation(tool, handler, arguments):\n"
            "    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n"
            "    return handler(arguments)\n", encoding="utf-8"
        )
        (repo / "mcp" / "server_v61_peer_pivot_recovery.py").write_text(overlay_source, encoding="utf-8")
        (repo / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from . import server_v61_peer_pivot_recovery as _base\n", encoding="utf-8"
        )
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers":{"cbi":{"args":["mcp/server_v61_backup_recovery.py","--stdio"]}}}), encoding="utf-8"
        )
        return repo

    @staticmethod
    def _function_segment(source: str, name: str) -> str:
        tree = ast.parse(source)
        matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(matches) != 1:
            raise AssertionError(name)
        return ast.get_source_segment(source, matches[0]) or ""

    def test_compiles_overlay_candidate_without_modifying_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            snapshot = build_v63_production_source_snapshot(repo)
            overlay = repo / "mcp" / "server_v61_peer_pivot_recovery.py"
            before_overlay = overlay.read_bytes()
            before_mcp = (repo / ".mcp.json").read_bytes()
            result = compile_v63_recovery_overlay_patch_candidate(repo, expected_production_snapshot=snapshot)
            self.assertEqual(result["status"], "RECOVERY_OVERLAY_PATCH_CANDIDATE_READY")
            self.assertFalse(result["modifies_checkout"])
            self.assertEqual(overlay.read_bytes(), before_overlay)
            self.assertEqual((repo / ".mcp.json").read_bytes(), before_mcp)
            self.assertEqual(result["target_file"], "mcp/server_v61_peer_pivot_recovery.py")
            self.assertIn("--- a/mcp/server_v61_peer_pivot_recovery.py", result["unified_diff"])
            self.assertFalse(result["recovery_overlay_binding_complete"])
            self.assertEqual(result["next_gate"], "APPLY_ON_EXACT_CHECKOUT_AND_RUN_RECOVERY_ACCEPTANCE")

    def test_candidate_preserves_precedent_handlers_and_adds_three_v63_recovery_handlers(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            original = (repo / "mcp" / "server_v61_peer_pivot_recovery.py").read_text(encoding="utf-8")
            snapshot = build_v63_production_source_snapshot(repo)
            result = compile_v63_recovery_overlay_patch_candidate(repo, expected_production_snapshot=snapshot)
            candidate = result["candidate_source"]
            self.assertEqual(self._function_segment(candidate, "_recover_peer"), self._function_segment(original, "_recover_peer"))
            self.assertEqual(self._function_segment(candidate, "_recover_anchor"), self._function_segment(original, "_recover_anchor"))
            tree = ast.parse(candidate)
            functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
            self.assertTrue({
                "_v63_recover_append_candidate_discovery",
                "_v63_recover_create_product_opportunity",
                "_v63_recover_promote_opportunity_anchor",
            } <= functions)
            compile(candidate, "<candidate>", "exec")
            for tool in ("append_candidate_discovery", "create_product_opportunity", "promote_opportunity_anchor"):
                self.assertIn(repr(tool), candidate)
            self.assertIn("recover_prepared_v63_mutation", candidate)
            self.assertIn('intent["arguments"]', candidate)
            self.assertIn('intent["correlation_id"]', candidate)

    def test_source_drift_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            snapshot = build_v63_production_source_snapshot(repo)
            overlay = repo / "mcp" / "server_v61_peer_pivot_recovery.py"
            overlay.write_text(overlay.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
            result = compile_v63_recovery_overlay_patch_candidate(repo, expected_production_snapshot=snapshot)
            self.assertEqual(result["status"], "BLOCKED_SOURCE_DRIFT")
            self.assertFalse(result["codegen_performed"])
            self.assertIn("mcp/server_v61_peer_pivot_recovery.py", result["source_snapshot_validation"]["drifted_files"])

    def test_unproven_intent_contract_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            bad = OVERLAY.replace('    correlation_id = intent["correlation_id"]\n', '', 2)
            repo = self._repo(Path(td), bad)
            snapshot = build_v63_production_source_snapshot(repo)
            result = compile_v63_recovery_overlay_patch_candidate(repo, expected_production_snapshot=snapshot)
            self.assertEqual(result["status"], "BLOCKED_RECOVERY_OVERLAY_STRUCTURE")
            self.assertIn("RECOVERY_INTENT_CONTRACT_NOT_PROVEN", result["blockers"])

    def test_base_server_and_active_entrypoint_are_never_changed_by_compiler(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            snapshot = build_v63_production_source_snapshot(repo)
            base_before = (repo / "mcp" / "server_v61.py").read_bytes()
            entry_before = (repo / "mcp" / "server_v61_backup_recovery.py").read_bytes()
            result = compile_v63_recovery_overlay_patch_candidate(repo, expected_production_snapshot=snapshot)
            self.assertEqual(result["status"], "RECOVERY_OVERLAY_PATCH_CANDIDATE_READY")
            self.assertEqual((repo / "mcp" / "server_v61.py").read_bytes(), base_before)
            self.assertEqual((repo / "mcp" / "server_v61_backup_recovery.py").read_bytes(), entry_before)
            self.assertFalse(result["switches_production_entrypoint"])


if __name__ == "__main__":
    unittest.main()

class V63SyncRecoveryOverlayPatchCompilerTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        (root/'mcp').mkdir(parents=True); (root/'unified_runtime').mkdir(parents=True)
        (root/'.mcp.json').write_text(json.dumps({'mcpServers':{'cbi':{'args':['mcp/server_v61_backup_recovery.py','--stdio']}}}))
        for n in ('__init__.py','research_orchestration_hardening.py','v6.py'):(root/'unified_runtime'/n).write_text('# authority\n')
        (root/'mcp/server_v61_backup_recovery.py').write_text('from mcp import server_v61_sync_recovery as _base\n')
        (root/'mcp/server_v61_sync_recovery.py').write_text('''\
from mcp import server_v61_sync_recovery_base as _base
_v61 = _base._v61
_RUNTIME = _base._RUNTIME
_BASE_RECOVER_TARGET_RESULT = _base._recover_target_result

def _reconciliation_inventory():
    guarded = sorted(set(_v61._MUTATING_TOOLS))
    automatic = sorted(set(_v61._AUTOMATIC_RECONCILIATION_TOOLS))
    return guarded, automatic, sorted(set(guarded)-set(automatic))

def main(): return _base.main()
''')
        (root/'mcp/server_v61_sync_recovery_base.py').write_text('from mcp import server_v61 as _base\n_v61=_base\n_RUNTIME=_base.RUNTIME\ndef _recover_target_result(*a): return None\ndef main(): return 0\n')
        (root/'mcp/server_v61.py').write_text('RUNTIME=object()\n')
        return root
    def test_compiler_targets_sync_layer(self):
        with tempfile.TemporaryDirectory() as td:
            repo=self._repo(Path(td)); snapshot=build_v63_production_source_snapshot(repo); before=(repo/'mcp/server_v61_sync_recovery.py').read_bytes(); result=compile_v63_recovery_overlay_patch_candidate(repo,expected_production_snapshot=snapshot)
            self.assertEqual(result['status'],'RECOVERY_OVERLAY_PATCH_CANDIDATE_READY'); self.assertEqual(result['target_file'],'mcp/server_v61_sync_recovery.py'); self.assertEqual(result['probe']['recovery_codegen_mode'],'SYNC_RECOVERY_EXTENSION'); self.assertEqual((repo/'mcp/server_v61_sync_recovery.py').read_bytes(),before)
            c=result['candidate_source']; compile(c,'<candidate>','exec'); self.assertIn('_BASE_V63_RECONCILE_PREPARED = _v61._reconcile_prepared',c); self.assertIn('_production._finish_reconciliation(',c); self.assertIn('_v61._AUTOMATIC_RECONCILIATION_TOOLS.update(',c)
