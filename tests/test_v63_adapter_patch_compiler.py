import ast
import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.adapter_source_probe_v63 import inspect_production_adapter_structure
from unified_runtime.mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES


BASE_SERVER = '''\
_MUTATING_TOOLS = {\n    "append_peer_discovery",\n    "promote_anchor",\n    "resolve_or_create_account",\n    "append_information_record",\n}\n\nTOOL_DEFINITIONS = [\n    {"name": "append_peer_discovery", "inputSchema": {"type": "object"}},\n    {"name": "promote_anchor", "inputSchema": {"type": "object"}},\n    {"name": "resolve_or_create_account", "inputSchema": {"type": "object"}},\n    {"name": "append_information_record", "inputSchema": {"type": "object"}},\n]\n\ndef _invoke_mutation(tool_name, handler, arguments):\n    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n    request_for_hash = dict(arguments)\n    return handler(arguments)\n\ndef _peer_handler(arguments):\n    return _invoke_mutation("append_peer_discovery", runtime.append_peer_discovery, arguments)\n\ndef _promote_handler(arguments):\n    return _invoke_mutation("promote_anchor", runtime.promote_anchor, arguments)\n\ndef _canonical_handler(arguments):\n    return _invoke_mutation("resolve_or_create_account", runtime.resolve_or_create_account, arguments)\n\ndef _info_handler(arguments):\n    return _invoke_mutation("append_information_record", runtime.append_information_record, arguments)\n\nHANDLERS = {\n    "append_peer_discovery": _peer_handler,\n    "promote_anchor": _promote_handler,\n    "resolve_or_create_account": _canonical_handler,\n    "append_information_record": _info_handler,\n}\n'''


class V63AdapterPatchCompilerTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        (repo / "unified_runtime").mkdir(parents=True)
        (repo / "mcp").mkdir(parents=True)
        (repo / "unified_runtime" / "research_orchestration_hardening.py").write_text(
            "class V61ResearchOrchestrationHardeningMixin: pass\n", encoding="utf-8"
        )
        (repo / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n",
            encoding="utf-8",
        )
        (repo / "mcp" / "server_v61.py").write_text(BASE_SERVER, encoding="utf-8")
        (repo / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from .server_v61 import *\n", encoding="utf-8"
        )
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"cbi": {"args": ["mcp/server_v61_backup_recovery.py", "--stdio"]}}}),
            encoding="utf-8",
        )
        return repo

    @staticmethod
    def _function_segment(source: str, name: str) -> str:
        tree = ast.parse(source)
        matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        if len(matches) != 1:
            raise AssertionError(f"expected one {name}")
        return ast.get_source_segment(source, matches[0]) or ""

    def test_compiler_generates_candidate_without_modifying_checkout(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate

        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            server = repo / "mcp" / "server_v61.py"
            before_server = server.read_bytes()
            before_mcp = (repo / ".mcp.json").read_bytes()
            result = compile_v63_adapter_patch_candidate(repo)

            self.assertEqual(result["status"], "PATCH_CANDIDATE_READY")
            self.assertFalse(result["modifies_checkout"])
            self.assertFalse(result["switches_production_entrypoint"])
            self.assertEqual(server.read_bytes(), before_server)
            self.assertEqual((repo / ".mcp.json").read_bytes(), before_mcp)
            self.assertIn("--- a/mcp/server_v61.py", result["unified_diff"])
            self.assertIn("+++ b/mcp/server_v61.py", result["unified_diff"])
            self.assertEqual(len(result["candidate_sha256"]), 64)
            self.assertFalse(result["candidate_executable"])
            self.assertTrue(result["runtime_durable_backend_binding_required"])
            self.assertFalse(result["runtime_durable_backend_binding_proven"])
            self.assertEqual(result["next_gate"], "RUN_EXACT_BACKEND_CORRELATION_AND_RECOVERY_ACCEPTANCE" if result.get("adapter_codegen_mode") == "DELEGATED_SERVER_OVERLAY" else "BIND_RUNTIME_DURABLE_BACKEND_ON_EXACT_CHECKOUT")

    def test_candidate_has_exact_v63_handlers_and_preserves_invoke_mutation(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate

        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            original = (repo / "mcp" / "server_v61.py").read_text(encoding="utf-8")
            result = compile_v63_adapter_patch_candidate(repo)
            candidate = result["candidate_source"]

            self.assertEqual(
                self._function_segment(candidate, "_invoke_mutation"),
                self._function_segment(original, "_invoke_mutation"),
            )
            candidate_path = repo / "mcp" / "server_v61.py"
            candidate_path.write_text(candidate, encoding="utf-8")
            inspected = inspect_production_adapter_structure(repo)
            self.assertTrue(inspected["v63_handler_binding_complete"])
            self.assertTrue(inspected["v63_tool_descriptor_complete"])
            self.assertTrue(inspected["v63_dispatch_binding_complete"])
            self.assertTrue(inspected["v63_read_only_handler_binding_complete"])
            self.assertTrue(inspected["v63_tool_surface_complete"])
            self.assertEqual(set(inspected["v63_handler_map"]), set(V63_MUTATION_TOOL_NAMES))

    def test_expected_source_pin_mismatch_fails_closed(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
        from unified_runtime.adapter_patch_recipe_v63 import build_v63_adapter_patch_recipe

        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            pins = dict(build_v63_adapter_patch_recipe(repo)["source_pins"])
            pins["mcp/server_v61.py"] = "0" * 64
            result = compile_v63_adapter_patch_candidate(repo, expected_source_pins=pins)
            self.assertEqual(result["status"], "BLOCKED_SOURCE_PIN_MISMATCH")
            self.assertFalse(result["codegen_performed"])
            self.assertNotIn("candidate_source", result)

    def test_candidate_is_base_adapter_only_and_does_not_claim_recovery_binding(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate

        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            result = compile_v63_adapter_patch_candidate(repo)
            self.assertEqual(result["scope"], "BASE_ADAPTER_ONLY")
            self.assertTrue(result["recovery_overlay_binding_required"])
            self.assertFalse(result["adapter_bound"])
            self.assertFalse(result["production_ready"])
            self.assertEqual(set(result["durable_mutations"]), set(V63_MUTATION_TOOL_NAMES))
            self.assertEqual(set(result["read_only_tools"]), set(V63_READ_ONLY_TOOL_NAMES))


    def test_full_production_snapshot_drift_blocks_codegen_even_when_base_server_is_unchanged(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
        from unified_runtime.production_source_snapshot_v63 import build_v63_production_source_snapshot

        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            snapshot = build_v63_production_source_snapshot(repo)
            overlay = repo / "mcp" / "server_v61_backup_recovery.py"
            overlay.write_text(overlay.read_text(encoding="utf-8") + "# concurrent drift\n", encoding="utf-8")
            result = compile_v63_adapter_patch_candidate(
                repo, expected_production_snapshot=snapshot
            )
            self.assertEqual(result["status"], "BLOCKED_SOURCE_DRIFT")
            self.assertFalse(result["codegen_performed"])
            self.assertIn("mcp/server_v61_backup_recovery.py", result["source_snapshot_validation"]["drifted_files"])

    def test_successful_codegen_records_validated_production_snapshot(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
        from unified_runtime.production_source_snapshot_v63 import build_v63_production_source_snapshot

        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            snapshot = build_v63_production_source_snapshot(repo)
            result = compile_v63_adapter_patch_candidate(
                repo, expected_production_snapshot=snapshot
            )
            self.assertEqual(result["status"], "PATCH_CANDIDATE_READY")
            self.assertEqual(result["validated_production_snapshot_sha256"], snapshot["snapshot_sha256"])
            self.assertTrue(result["source_snapshot_validation"]["valid"])



if __name__ == "__main__":
    unittest.main()

class V63DelegatedAdapterPatchCompilerTests(V63AdapterPatchCompilerTests):
    def _repo(self, root: Path) -> Path:
        from tests.test_v63_adapter_source_probe import DELEGATED_SERVER
        repo = super()._repo(root)
        source = DELEGATED_SERVER.replace(
            '# PREPARED COMMITTED MUTATION_RECONCILIATION_REQUIRED request_sha256',
            '# PREPARED COMMITTED MUTATION_RECONCILIATION_REQUIRED request_sha256 MUTCORR',
        )
        (repo / 'mcp' / 'server_v61.py').write_text(source, encoding='utf-8')
        return repo

    def test_delegated_codegen_binds_existing_store_backend_once(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            result = compile_v63_adapter_patch_candidate(repo)
            self.assertEqual(result['status'], 'PATCH_CANDIDATE_READY')
            self.assertEqual(result['adapter_codegen_mode'], 'DELEGATED_SERVER_OVERLAY')
            candidate = result['candidate_source']
            self.assertEqual(candidate.count('ExistingProductionStoreBackend()'), 1)
            self.assertIn('bind_v63_runtime_durable_backend(_server.RUNTIME, _V63_DURABLE_BACKEND)', candidate)
            self.assertIn('_server.tool_descriptors = _v63_tool_descriptors', candidate)
            self.assertIn("_server.TOOL_HANDLERS['append_candidate_discovery'] = _v63_append_candidate_discovery_handler", candidate)
            self.assertTrue(result['runtime_durable_backend_binding_candidate_proven'])
            self.assertFalse(result['runtime_durable_backend_binding_proven'])

    def test_delegated_candidate_is_recognized_as_complete_v63_surface(self):
        from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            result = compile_v63_adapter_patch_candidate(repo)
            (repo / 'mcp' / 'server_v61.py').write_text(result['candidate_source'], encoding='utf-8')
            inspected = inspect_production_adapter_structure(repo)
            self.assertTrue(inspected['v63_tool_surface_complete'])
            self.assertEqual(inspected['adapter_codegen_mode'], 'DELEGATED_SERVER_OVERLAY')
