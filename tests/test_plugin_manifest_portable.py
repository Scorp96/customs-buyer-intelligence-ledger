from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


class PortablePluginManifestTests(unittest.TestCase):
    def test_portable_plugin_manifest_exists_and_is_agent_plugins_v1(self) -> None:
        path = ROOT / "plugin.json"
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload.get("$schema"),
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        self.assertEqual(payload.get("name"), "customs-buyer-intelligence")

    def test_portable_mcp_uses_remote_streamable_http_endpoint(self) -> None:
        path = ROOT / "mcp.json"
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload.get("$schema"),
            "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        )
        servers = payload.get("mcpServers") or {}
        remote = servers.get("buyer-outreach-actions") or {}
        self.assertEqual(remote.get("type"), "streamable-http")
        url = str(remote.get("url") or "")
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(parsed.netloc)
        self.assertEqual(parsed.path, "/mcp")
        self.assertFalse(parsed.query)
        self.assertFalse(parsed.fragment)

    def test_legacy_codex_compatibility_manifest_remains_available(self) -> None:
        self.assertTrue((ROOT / ".codex-plugin" / "plugin.json").is_file())
        self.assertTrue((ROOT / ".mcp.json").is_file(), "Codex compatibility must point to remote-only .mcp.json")
        self.assertTrue((ROOT / "tests/fixtures/mcp/legacy_windows_launcher.json").is_file())

    def test_codex_plugin_uses_only_portable_cloud_mcp(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        portable = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        exposed = portable["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual(exposed["type"], "streamable-http")
        self.assertEqual(exposed["url"], "https://cbi-v61-preview.onrender.com/mcp")
        self.assertNotIn("command", exposed)
        self.assertNotIn("args", exposed)

    def test_portable_and_codex_package_versions_match_for_cache_refresh(self):
        portable = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(portable["name"], codex["name"])
        self.assertEqual(portable["version"], codex["version"])
        self.assertTrue(portable["version"].startswith("6.4.1"), portable["version"])

    def test_legacy_engineering_launcher_not_referenced_by_active_manifest(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        compatibility = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        portable = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        # OpenAI Codex compatibility uses camelCase mcpServers, not config.toml
        # snake_case mcp_servers. Keep a single hosted MCP and zero stdio fallbacks.
        self.assertEqual(set(compatibility), {"mcpServers"})
        self.assertNotIn("mcp_servers", compatibility)
        self.assertEqual(set(compatibility["mcpServers"]), {"buyer-outreach-actions"})
        remote = compatibility["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual(remote, {
            "type": "http",
            "url": portable["mcpServers"]["buyer-outreach-actions"]["url"],
        })
        for prohibited in ("command", "args", "cwd", "env"):
            self.assertNotIn(prohibited, remote)
        legacy = json.loads((ROOT / "tests/fixtures/mcp/legacy_windows_launcher.json").read_text(encoding="utf-8"))
        self.assertIn("command", legacy["mcpServers"]["buyer-outreach-actions"])

if __name__ == "__main__":
    unittest.main()
