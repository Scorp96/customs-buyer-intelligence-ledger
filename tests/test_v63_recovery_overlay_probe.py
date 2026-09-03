import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.recovery_overlay_probe_v63 import probe_v63_recovery_overlay


BASE = '''\
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


class V63RecoveryOverlayProbeTests(unittest.TestCase):
    def _repo(self, root: Path, overlay_source: str = BASE) -> Path:
        repo = root / "repo"
        (repo / "mcp").mkdir(parents=True)
        (repo / "unified_runtime").mkdir(parents=True)
        (repo / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(V61ResearchOrchestrationHardeningMixin): pass\n",
            encoding="utf-8",
        )
        (repo / "unified_runtime" / "research_orchestration_hardening.py").write_text(
            "class V61ResearchOrchestrationHardeningMixin: pass\n", encoding="utf-8"
        )
        (repo / "unified_runtime" / "v6.py").write_text("class V6RuntimeMixin: pass\n", encoding="utf-8")
        (repo / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS={'append_peer_discovery','promote_anchor','resolve_or_create_account','append_information_record'}\n"
            "def _invoke_mutation(tool, handler, arguments):\n"
            "    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n"
            "    return handler(arguments)\n",
            encoding="utf-8",
        )
        (repo / "mcp" / "server_v61_peer_pivot_recovery.py").write_text(
            "from . import server_v61 as _base\n" + overlay_source,
            encoding="utf-8",
        )
        (repo / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from . import server_v61_peer_pivot_recovery as _base\n",
            encoding="utf-8",
        )
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers":{"cbi":{"args":["mcp/server_v61_backup_recovery.py","--stdio"]}}}),
            encoding="utf-8",
        )
        return repo

    def test_unique_recovery_registry_and_peer_precedents_are_proven(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe_v63_recovery_overlay(self._repo(Path(td)))
            self.assertEqual(result["status"], "RECOVERY_OVERLAY_PRIMITIVE_PROVEN")
            self.assertEqual(result["recovery_registry_name"], "RECOVERY_HANDLERS")
            self.assertEqual(result["recovery_registry_file"], "mcp/server_v61_peer_pivot_recovery.py")
            self.assertEqual(result["peer_handler"], "_recover_peer")
            self.assertEqual(result["anchor_handler"], "_recover_anchor")
            self.assertEqual(result["peer_handler_signature"], ["intent", "durable_events"])
            self.assertEqual(result["anchor_handler_signature"], ["intent", "durable_events"])
            self.assertTrue(result["handler_signatures_compatible"])
            self.assertEqual(result["shared_intent_keys"], ["arguments", "correlation_id"])
            self.assertTrue(result["intent_contract_proven"])
            self.assertTrue(result["recovery_overlay_codegen_allowed"])

    def test_ambiguous_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE + '\nOTHER_RECOVERY_HANDLERS = {"append_peer_discovery": _recover_peer, "promote_anchor": _recover_anchor}\n'
            result = probe_v63_recovery_overlay(self._repo(Path(td), source))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("RECOVERY_REGISTRY_AMBIGUOUS", result["blockers"])
            self.assertFalse(result["recovery_overlay_codegen_allowed"])

    def test_missing_anchor_precedent_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE.replace('    "promote_anchor": _recover_anchor,\n', '')
            result = probe_v63_recovery_overlay(self._repo(Path(td), source))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("PEER_ANCHOR_RECOVERY_PRECEDENTS_INCOMPLETE", result["blockers"])

    def test_incompatible_handler_signatures_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE.replace('def _recover_anchor(intent, durable_events):', 'def _recover_anchor(intent, durable_events, extra):')
            result = probe_v63_recovery_overlay(self._repo(Path(td), source))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("RECOVERY_HANDLER_SIGNATURE_MISMATCH", result["blockers"])

    def test_registry_outside_active_overlay_chain_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td), 'x = 1\n')
            (repo / "mcp" / "server_v61_unused_recovery.py").write_text(BASE, encoding="utf-8")
            result = probe_v63_recovery_overlay(repo)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("RECOVERY_REGISTRY_NOT_PROVEN", result["blockers"])

    def test_missing_correlation_field_access_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE.replace('    correlation_id = intent["correlation_id"]\n', '', 2)
            result = probe_v63_recovery_overlay(self._repo(Path(td), source))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("RECOVERY_INTENT_CONTRACT_NOT_PROVEN", result["blockers"])
            self.assertFalse(result["intent_contract_proven"])



if __name__ == "__main__":
    unittest.main()

class V63SyncRecoveryOverlayProbeTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        (root/'mcp').mkdir(parents=True); (root/'unified_runtime').mkdir(parents=True)
        (root/'.mcp.json').write_text('{"mcpServers":{"cbi":{"args":["mcp/server_v61_backup_recovery.py","--stdio"]}}}')
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
''')
        (root/'mcp/server_v61_sync_recovery_base.py').write_text('from mcp import server_v61 as _base\n_v61=_base\n_RUNTIME=_base.RUNTIME\ndef _recover_target_result(*a): return None\n')
        (root/'mcp/server_v61.py').write_text('RUNTIME=object()\n')
        return root
    def test_sync_layer_is_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            r=probe_v63_recovery_overlay(self._repo(Path(td)))
            self.assertEqual(r['status'],'RECOVERY_OVERLAY_PRIMITIVE_PROVEN'); self.assertEqual(r['recovery_codegen_mode'],'SYNC_RECOVERY_EXTENSION'); self.assertEqual(r['recovery_registry_file'],'mcp/server_v61_sync_recovery.py')
