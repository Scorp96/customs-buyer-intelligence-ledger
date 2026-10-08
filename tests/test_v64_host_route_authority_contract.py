"""No state writes to a CBI namesake Runtime without canonical route preflight.

This is a host/skill policy regression, not a server-enforced runtime ACL.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/investigate-customs-buyers/SKILL.md"
CANONICAL = "https://cbi-v61-preview.onrender.com/mcp"


class CanonicalRoutePreflightContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        cls.portable = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        cls.compatibility = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

    def test_preflight_must_precede_state_write_in_active_skill(self):
        rule = self.skill.index("Mandatory host-side MCP authority preflight")
        first_write = self.skill.index("resolve_or_create_account")
        self.assertLess(rule, first_write)
        for required in (
            "get_runtime_contract",
            "get_runtime_health",
            "cloud_mcp_canonical_endpoint",
            "FULL_AUDIT",
            "EXHAUSTIVE",
            "backup_recovery.external_replication_configured",
            "backup_recovery.external_replication_verified",
            "mutation_wal.prepared_count",
            "mutation_wal.invalid_count",
            "ROUTE_IDENTITY_CONFLICT",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.skill)

    def test_no_fallback_or_cross_runtime_migration(self):
        for required in (
            "never", "No", "Never",
        ):
            self.assertIn(required, self.skill)
        self.assertIn("server-side tenant/storage authority check", self.skill)
        self.assertIn("host execution policy", self.skill)
        self.assertIn("**Never** try an alternate MCP", self.skill)
        self.assertIn("merge Canonical IDs", self.skill)
        self.assertIn("CRM writes", self.skill)

    def test_manifest_and_runtime_endpoint_pin_match(self):
        url1 = self.portable["mcpServers"]["buyer-outreach-actions"]["url"]
        url2 = self.compatibility["mcpServers"]["buyer-outreach-actions"]["url"]
        self.assertEqual(url1, url2)
        self.assertEqual(url1, CANONICAL)
        self.assertIn(CANONICAL, self.skill)
        self.assertEqual(self.compatibility["mcpServers"]["buyer-outreach-actions"]["type"], "http")
        self.assertEqual(self.codex["mcpServers"], "./.mcp.json")

    def test_active_plugin_prompts_invoke_preflight(self):
        prompts = self.codex["interface"]["defaultPrompt"]
        for prompt in prompts[:3]:
            self.assertIn("写入前先执行规范Render连接身份检查", prompt)
        self.assertIn("Runtime契约", self.codex["interface"]["longDescription"])
        self.assertEqual(self.codex["version"], "6.4.2+codex.20261009.r1")


if __name__ == "__main__":
    unittest.main()
