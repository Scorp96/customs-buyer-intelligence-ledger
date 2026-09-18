import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class V63ExactCheckoutCandidateBuilderTests(unittest.TestCase):
    def test_builder_source_avoids_python311_forbidden_backslash_in_fstring_expression(self):
        import re

        source_path = Path(__file__).resolve().parents[1] / "release_ops_v63" / "exact_checkout_candidate_builder.py"
        source = source_path.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if re.search(r"f[\"\'][^\n]*\{[^}\n]*\\\\[^}\n]*\}[^\n]*", line)
        ]
        self.assertEqual(
            offenders,
            [],
            "Python 3.11 rejects backslashes inside f-string expressions; "
            f"offending lines: {offenders}",
        )

    def _repo(self, root: Path) -> tuple[Path, str]:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "CBI Test"], check=True)
        (repo / "tracked.txt").write_text("exact-source\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run([
            "git", "-C", str(repo), "remote", "add", "origin",
            "https://github.com/Scorp96/customs-buyer-intelligence-ledger.git",
        ], check=True)
        return repo, head

    def test_verifies_exact_commit_object_without_branch_or_network_dependency(self):
        from release_ops_v63.exact_checkout_candidate_builder import verify_exact_source_commit

        with tempfile.TemporaryDirectory() as td:
            repo, head = self._repo(Path(td))
            result = verify_exact_source_commit(repo, expected_commit=head)
            self.assertEqual(result["status"], "EXACT_COMMIT_READY")
            self.assertEqual(result["commit_sha"], head)
            self.assertFalse(result["network_required"])
            self.assertFalse(result["modifies_git_refs"])

    def test_wrong_or_missing_commit_fails_closed(self):
        from release_ops_v63.exact_checkout_candidate_builder import verify_exact_source_commit

        with tempfile.TemporaryDirectory() as td:
            repo, _ = self._repo(Path(td))
            result = verify_exact_source_commit(repo, expected_commit="0" * 40)
            self.assertEqual(result["status"], "BLOCKED_EXACT_COMMIT_MISSING")
            self.assertFalse(result["ready"])

    def test_exports_exact_commit_with_git_archive_without_mutating_repo(self):
        from release_ops_v63.exact_checkout_candidate_builder import export_exact_commit

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo, head = self._repo(root)
            status_before = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
            destination = root / "export"
            result = export_exact_commit(repo, head, destination)
            status_after = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
            self.assertEqual(result["status"], "EXPORTED_EXACT_COMMIT")
            self.assertEqual((destination / "tracked.txt").read_text(encoding="utf-8"), "exact-source\n")
            self.assertEqual(status_after, status_before)
            self.assertFalse((destination / ".git").exists())
            self.assertFalse(result["modifies_source_repo"])

    def test_artifact_writer_rejects_secret_material(self):
        from release_ops_v63.exact_checkout_candidate_builder import write_candidate_artifact

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result.zip"
            with self.assertRaisesRegex(RuntimeError, "SECRET_MATERIAL_DETECTED"):
                write_candidate_artifact(
                    out,
                    report={"status": "X", "token": "github_" + "pat_" + "A" * 32},
                    text_files={"adapter.diff": "safe"},
                )
            self.assertFalse(out.exists())

    def test_artifact_paths_are_ascii_and_manifest_bound(self):
        from release_ops_v63.exact_checkout_candidate_builder import write_candidate_artifact
        import zipfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result.zip"
            result = write_candidate_artifact(
                out,
                report={"status": "READY", "production_ready": False},
                text_files={"adapter.diff": "--- a\n+++ b\n", "recovery.diff": "safe\n"},
            )
            self.assertEqual(result["status"], "ARTIFACT_READY")
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertTrue(all(name.isascii() for name in names))
                self.assertIn("MANIFEST.json", names)
                manifest = json.loads(zf.read("MANIFEST.json"))
                self.assertEqual(set(manifest["files"]), set(names) - {"MANIFEST.json"})


if __name__ == "__main__":
    unittest.main()

class V63ExactCheckoutStaticPipelineTests(unittest.TestCase):
    def _production_export(self, root: Path) -> Path:
        repo = root / "export"
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
        (repo / "unified_runtime" / "v6.py").write_text(
            "class V6RuntimeMixin:\n"
            "    def append_peer_discovery(self, arguments):\n"
            "        return self._append_event('V6_PEER_DISCOVERED', arguments)\n"
            "    def promote_anchor(self, arguments):\n"
            "        return self._append_event('V6_ANCHOR_PROMOTED', arguments)\n"
            "    def append_information_record(self, arguments):\n"
            "        return self._append_event('INFORMATION_RECORD_APPENDED', arguments)\n",
            encoding="utf-8",
        )
        base_server = '''\
_MUTATING_TOOLS = {\n    "append_peer_discovery",\n    "promote_anchor",\n    "resolve_or_create_account",\n    "append_information_record",\n}\n\nTOOL_DEFINITIONS = [\n    {"name": "append_peer_discovery", "inputSchema": {"type": "object"}},\n    {"name": "promote_anchor", "inputSchema": {"type": "object"}},\n    {"name": "resolve_or_create_account", "inputSchema": {"type": "object"}},\n    {"name": "append_information_record", "inputSchema": {"type": "object"}},\n]\n\ndef _invoke_mutation(tool_name, handler, arguments):\n    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED correlation_id\n    request_for_hash = dict(arguments)\n    return handler(arguments)\n\ndef _peer_handler(arguments):\n    return _invoke_mutation("append_peer_discovery", runtime.append_peer_discovery, arguments)\n\ndef _promote_handler(arguments):\n    return _invoke_mutation("promote_anchor", runtime.promote_anchor, arguments)\n\ndef _canonical_handler(arguments):\n    return _invoke_mutation("resolve_or_create_account", runtime.resolve_or_create_account, arguments)\n\ndef _info_handler(arguments):\n    return _invoke_mutation("append_information_record", runtime.append_information_record, arguments)\n\nHANDLERS = {\n    "append_peer_discovery": _peer_handler,\n    "promote_anchor": _promote_handler,\n    "resolve_or_create_account": _canonical_handler,\n    "append_information_record": _info_handler,\n}\n'''
        (repo / "mcp" / "server_v61.py").write_text(base_server, encoding="utf-8")
        overlay = '''\
from . import server_v61 as _base\n\ndef _recover_peer(intent, durable_events):\n    arguments = intent["arguments"]\n    correlation_id = intent["correlation_id"]\n    if not durable_events:\n        return {"status": "MUTATION_RECONCILIATION_REQUIRED", "correlation_id": correlation_id}\n    return {"status": "RECOVERED", "event": durable_events[0], "arguments": arguments}\n\ndef _recover_anchor(intent, durable_events):\n    arguments = intent["arguments"]\n    correlation_id = intent["correlation_id"]\n    if not durable_events:\n        return {"status": "MUTATION_RECONCILIATION_REQUIRED", "correlation_id": correlation_id}\n    return {"status": "RECOVERED", "event": durable_events[0], "arguments": arguments}\n\nRECOVERY_HANDLERS = {\n    "append_peer_discovery": _recover_peer,\n    "promote_anchor": _recover_anchor,\n}\n'''
        (repo / "mcp" / "server_v61_peer_pivot_recovery.py").write_text(overlay, encoding="utf-8")
        (repo / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from . import server_v61_peer_pivot_recovery as _base\n", encoding="utf-8"
        )
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"cbi": {"args": ["mcp/server_v61_backup_recovery.py", "--stdio"]}}}),
            encoding="utf-8",
        )
        return repo

    def test_static_pipeline_applies_only_to_disposable_export_and_stops_before_live_binding(self):
        from release_ops_v63.exact_checkout_candidate_builder import build_static_candidate_on_export

        with tempfile.TemporaryDirectory() as td:
            repo = self._production_export(Path(td))
            result = build_static_candidate_on_export(repo)
            self.assertEqual(result["status"], "STATIC_CANDIDATE_READY_LIVE_ACCEPTANCE_PENDING")
            self.assertTrue(result["phase_a"]["modified_checkout"])
            self.assertEqual(result["adapter"]["status"], "PATCH_CANDIDATE_READY")
            self.assertEqual(result["recovery"]["status"], "RECOVERY_OVERLAY_PATCH_CANDIDATE_READY")
            self.assertTrue(result["adapter_candidate_applied_to_export"])
            self.assertTrue(result["recovery_candidate_applied_to_export"])
            self.assertFalse(result["production_ready"])
            self.assertIn("V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND", result["remaining_gates"])
            self.assertIn("V63_RECOVERY_OVERLAY_LIVE_ACCEPTANCE_REQUIRED", result["remaining_gates"])
            self.assertIn("V63DemandExpansionMixin", (repo / "unified_runtime" / "__init__.py").read_text(encoding="utf-8"))
            self.assertIn("append_candidate_discovery", (repo / "mcp" / "server_v61.py").read_text(encoding="utf-8"))
            self.assertIn("_v63_recover_create_product_opportunity", (repo / "mcp" / "server_v61_peer_pivot_recovery.py").read_text(encoding="utf-8"))

class V63ExactCheckoutEndToEndTests(V63ExactCheckoutStaticPipelineTests):
    def test_end_to_end_offline_git_archive_to_candidate_artifact(self):
        from release_ops_v63.exact_checkout_candidate_builder import build_exact_checkout_candidate_artifact
        import zipfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._production_export(root)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "CBI Test"], check=True)
            subprocess.run([
                "git", "-C", str(source), "remote", "add", "origin",
                "https://github.com/Scorp96/customs-buyer-intelligence-ledger.git",
            ], check=True)
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-qm", "synthetic production"], check=True)
            head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            output = root / "candidate.zip"
            result = build_exact_checkout_candidate_artifact(
                source,
                output,
                payload_root=Path(__file__).resolve().parents[1],
                python_executable=sys.executable,
                expected_commit=head,
                run_validation=False,
            )
            self.assertTrue(result["artifact_written"])
            self.assertFalse(result["production_ready"])
            self.assertEqual(result["pipeline"]["status"], "STATIC_CANDIDATE_READY_LIVE_ACCEPTANCE_PENDING")
            with zipfile.ZipFile(output) as zf:
                names = set(zf.namelist())
                self.assertIn("report.json", names)
                self.assertIn("adapter.diff", names)
                self.assertIn("recovery.diff", names)
                self.assertIn("candidate/mcp/server_v61.py", names)
                self.assertIn("source_authority/mcp/server_v61.py", names)

class V63DelegatedSyncStaticPipelineTests(V63ExactCheckoutStaticPipelineTests):
    def _delegated_sync_export(self, root: Path) -> Path:
        from tests.test_v63_adapter_source_probe import DELEGATED_SERVER
        from tests.test_v63_production_correlation_source_probe import CORRELATED
        repo=self._production_export(root)
        delegated=DELEGATED_SERVER.replace('# PREPARED COMMITTED MUTATION_RECONCILIATION_REQUIRED request_sha256','# PREPARED COMMITTED MUTATION_RECONCILIATION_REQUIRED request_sha256 MUTCORR correlation_id')
        (repo/'mcp/server_v61.py').write_text(delegated,encoding='utf-8')
        (repo/'mcp/server_v61_backup_recovery.py').write_text('from mcp import server_v61_sync_recovery as _base\n',encoding='utf-8')
        (repo/'mcp/server_v61_sync_recovery.py').write_text('''\
from mcp import server_v61_sync_recovery_base as _base
_v61 = _base._v61
_RUNTIME = _base._RUNTIME
_BASE_RECOVER_TARGET_RESULT = _base._recover_target_result

def _reconciliation_inventory():
    guarded=sorted(set(_v61._MUTATING_TOOLS)); automatic=sorted(set(_v61._AUTOMATIC_RECONCILIATION_TOOLS)); return guarded,automatic,sorted(set(guarded)-set(automatic))

def main(): return _base.main()
''',encoding='utf-8')
        (repo/'mcp/server_v61_sync_recovery_base.py').write_text('from mcp import server_v61_correlated as _base\n_v61=_base._v61\n_RUNTIME=_v61._server.RUNTIME\ndef _recover_target_result(*a): return None\ndef main(): return 0\n',encoding='utf-8')
        (repo/'mcp/server_v61_correlated.py').write_text(CORRELATED,encoding='utf-8')
        (repo/'mcp/server_v61_recovery.py').write_text('from mcp import server_v61 as _v61\n',encoding='utf-8')
        (repo/'mcp/server_v61_production.py').write_text('from mcp import server_v61 as _v61\ndef _finish_reconciliation(tool_name,stored,request_hash,path,raw_result,event_seq,proof): return raw_result\n',encoding='utf-8')
        (repo/'unified_runtime/core.py').write_text('# SessionStore authority\n',encoding='utf-8')
        (repo/'unified_runtime/resilience.py').write_text('# HashChain authority\n',encoding='utf-8')
        return repo
    def test_delegated_sync_pipeline_closes_static_backend_and_recovery_codegen(self):
        from release_ops_v63.exact_checkout_candidate_builder import build_static_candidate_on_export
        with tempfile.TemporaryDirectory() as td:
            repo=self._delegated_sync_export(Path(td)); result=build_static_candidate_on_export(repo)
            self.assertEqual(result['status'],'STATIC_CANDIDATE_READY_LIVE_ACCEPTANCE_PENDING')
            self.assertEqual(result['adapter']['adapter_codegen_mode'],'DELEGATED_SERVER_OVERLAY')
            self.assertTrue(result['adapter']['runtime_durable_backend_binding_candidate_proven'])
            self.assertEqual(result['recovery']['probe']['recovery_codegen_mode'],'SYNC_RECOVERY_EXTENSION')
            self.assertTrue(result['correlation_source_probe']['static_correlation_bridge_proven'])
            self.assertEqual(result['reference_backend_correlation']['execution_origin'],'REFERENCE_EXECUTABLE')
            self.assertTrue(all(row['status']=='PASS' for row in result['reference_backend_correlation']['scenarios']))
            self.assertNotIn('V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND',result['remaining_gates'])
            self.assertIn('V63_RUNTIME_DURABLE_BACKEND_LIVE_ACCEPTANCE_REQUIRED',result['remaining_gates'])
