"""Reject ambiguous CBI plug-in entrypoints and accidental legacy policy regressions."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SingleMcpEntrypointTests(unittest.TestCase):
    def test_only_cloud_mcp_is_discoverable_at_repository_root(self):
        self.assertTrue((ROOT / ".mcp.json").is_file())
        mcp = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(set(mcp["mcpServers"]), {"buyer-outreach-actions"})
        server = mcp["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual(server, {
            "type": "streamable-http",
            "url": "https://cbi-v61-preview.onrender.com/mcp",
        })
        for field in ("command", "args", "env", "cwd"):
            self.assertNotIn(field, server)

    def test_legacy_launcher_is_non_discoverable_fixture(self):
        path = ROOT / "tests/fixtures/mcp/legacy_windows_launcher.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.name, "mcp")
        payload = json.loads(path.read_text(encoding="utf-8"))
        launcher = payload["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual(launcher["command"].lower(), "powershell.exe")
        compatibility = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(set(compatibility), {"mcp_servers"})
        remote = compatibility["mcp_servers"]["buyer-outreach-actions"]
        self.assertEqual(remote, {"url": "https://cbi-v61-preview.onrender.com/mcp"})
        self.assertNotIn("command", remote)

    def test_plugin_manifest_points_to_single_cloud_endpoint(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertNotIn("mcpServers", json.loads((ROOT / "plugin.json").read_text(encoding="utf-8")))

    def test_synthetic_legacy_checkout_isolated_from_real_plugin_root(self):
        from unified_runtime.mcp_entrypoint_v63 import resolve_active_mcp_entrypoint
        with tempfile.TemporaryDirectory(prefix="cbi-mcp-isolation-") as td:
            root = Path(td)
            old = root / ".mcp.json"
            old.write_text(json.dumps({"mcpServers": {
                "test-only": {"args": ["mcp/server_v61_backup_recovery.py"]},
            }}), encoding="utf-8")
            # Old tests can parse this explicit synthetic checkout only.
            self.assertEqual(resolve_active_mcp_entrypoint(root), "mcp/server_v61_backup_recovery.py")
            # A real plugin cannot fall back to the root legacy dotfile.
            (root / "plugin.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(resolve_active_mcp_entrypoint(root))
            (root / "mcp.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(resolve_active_mcp_entrypoint(root))

    def test_active_skill_contract_has_no_answer_first_research_route(self):
        docs = (ROOT / "skills/investigate-customs-buyers/references/unified-runtime-contract.md").read_text(encoding="utf-8")
        self.assertIn("one** `FULL_AUDIT`", docs)
        self.assertIn("mode=EXHAUSTIVE", docs)
        self.assertNotIn("lookups stay in `ANSWER_FIRST`", docs)
        self.assertIn("INTERRUPTED", docs)
        self.assertIn("28 minutes of active useful work", docs)


if __name__ == "__main__":
    unittest.main()
