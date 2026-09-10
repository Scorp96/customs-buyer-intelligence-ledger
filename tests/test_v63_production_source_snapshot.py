import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.production_source_snapshot_v63 import (
    build_v63_production_source_snapshot,
    validate_v63_production_source_snapshot,
)


class V63ProductionSourceSnapshotTests(unittest.TestCase):
    def _checkout(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "mcp").mkdir()
        (root / "unified_runtime").mkdir()
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(V61ResearchOrchestrationHardeningMixin): pass\n",
            encoding="utf-8",
        )
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text(
            "class V61ResearchOrchestrationHardeningMixin: pass\n",
            encoding="utf-8",
        )
        (root / "unified_runtime" / "v6.py").write_text(
            "class V6RuntimeMixin: pass\n", encoding="utf-8"
        )
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS={'append_peer_discovery','promote_anchor','resolve_or_create_account','append_information_record'}\n"
            "def _invoke_mutation(tool, handler, arguments):\n"
            "    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n"
            "    return handler(arguments)\n",
            encoding="utf-8",
        )
        (root / "mcp" / "server_v61_peer_pivot_recovery.py").write_text(
            "from . import server_v61 as _base\n"
            "RECOVERY_TOOLS=('append_peer_discovery','promote_anchor')\n",
            encoding="utf-8",
        )
        (root / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from . import server_v61_peer_pivot_recovery as _base\n",
            encoding="utf-8",
        )
        (root / ".mcp.json").write_text(
            json.dumps({"mcpServers":{"cbi":{"args":["mcp/server_v61_backup_recovery.py","--stdio"]}}}),
            encoding="utf-8",
        )
        return td, root

    def test_snapshot_pins_active_overlay_chain_and_runtime_sources(self):
        td, root = self._checkout()
        self.addCleanup(td.cleanup)
        snapshot = build_v63_production_source_snapshot(root)
        self.assertEqual(snapshot["status"], "READY")
        self.assertEqual(snapshot["active_mcp_entrypoint"], "mcp/server_v61_backup_recovery.py")
        paths = set(snapshot["files"])
        self.assertTrue({
            ".mcp.json",
            "unified_runtime/__init__.py",
            "unified_runtime/research_orchestration_hardening.py",
            "unified_runtime/v6.py",
            "mcp/server_v61.py",
            "mcp/server_v61_peer_pivot_recovery.py",
            "mcp/server_v61_backup_recovery.py",
        } <= paths)
        self.assertEqual(len(snapshot["snapshot_sha256"]), 64)
        for meta in snapshot["files"].values():
            self.assertEqual(len(meta["sha256"]), 64)
            self.assertGreater(meta["size_bytes"], 0)

    def test_snapshot_validation_passes_on_unchanged_checkout(self):
        td, root = self._checkout()
        self.addCleanup(td.cleanup)
        snapshot = build_v63_production_source_snapshot(root)
        result = validate_v63_production_source_snapshot(root, snapshot)
        self.assertTrue(result["valid"])
        self.assertEqual(result["drifted_files"], [])
        self.assertEqual(result["missing_files"], [])

    def test_any_pinned_overlay_drift_blocks_phase_b(self):
        td, root = self._checkout()
        self.addCleanup(td.cleanup)
        snapshot = build_v63_production_source_snapshot(root)
        path = root / "mcp" / "server_v61_peer_pivot_recovery.py"
        path.write_text(path.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        result = validate_v63_production_source_snapshot(root, snapshot)
        self.assertFalse(result["valid"])
        self.assertIn("mcp/server_v61_peer_pivot_recovery.py", result["drifted_files"])
        self.assertIn("SOURCE_DRIFT_DETECTED", result["blockers"])

    def test_missing_imported_overlay_is_fail_closed(self):
        td, root = self._checkout()
        self.addCleanup(td.cleanup)
        (root / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from . import server_v61_missing_recovery as _base\n",
            encoding="utf-8",
        )
        snapshot = build_v63_production_source_snapshot(root)
        self.assertEqual(snapshot["status"], "BLOCKED")
        self.assertIn("ACTIVE_OVERLAY_IMPORT_MISSING", snapshot["blockers"])


if __name__ == "__main__":
    unittest.main()
