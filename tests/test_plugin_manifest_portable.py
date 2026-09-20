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
        self.assertTrue((ROOT / ".mcp.json").is_file())


if __name__ == "__main__":
    unittest.main()
