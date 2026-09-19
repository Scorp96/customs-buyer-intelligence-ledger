from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
SKILL = ROOT / "skills" / "customs-buyer-one-shot" / "SKILL.md"
MCP_CONFIG = ROOT / ".mcp.json"
LOCAL_MCP_CONFIG = ROOT / "deploy" / "local" / "mcp.windows.json"


class CustomsBuyerOneShotSkillTests(unittest.TestCase):
    def test_manifest_routes_customs_tasks_to_one_shot_skill(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        prompts = manifest["interface"]["defaultPrompt"]
        self.assertEqual(manifest["version"], "6.4.0+codex.20260918")
        self.assertIn("$investigate-customs-buyers", prompts[0])
        self.assertIn("批量写回", prompts[1])
        self.assertTrue(
            any("$customs-buyer-one-shot" in prompt for prompt in prompts[2:]),
            "customs default prompts must route to the one-shot skill without displacing legacy prompt indexes",
        )

    def test_one_shot_skill_contains_required_cloud_contract(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        required = [
            "ONE-SHOT CUSTOMS",
            "one consolidated final answer",
            "do **not** ask the user to open a computer",
            "Runtime unavailability is **not** permission to fall back to the user's PC",
            "regional_peer",
            "industry_peer",
            "scale_peer",
            "same_supplier_buyer",
            "same_product_hs_application_buyer",
            "competing_supplier_alternative",
            "Cloud customs delta monitoring",
            "notify only for a genuinely new shipment",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_answer_first_skill_explicitly_hands_deep_customs_to_one_shot(self) -> None:
        answer_first = (ROOT / "skills" / "investigate-customs-buyers" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("$customs-buyer-one-shot", answer_first)
        self.assertIn("takes precedence over `ANSWER_FIRST`", answer_first)

    def test_one_shot_skill_does_not_require_runtime_for_public_research(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "If they are not exposed, continue the complete one-shot investigation",
            text,
        )
        self.assertIn(
            "Runtime unavailability is **not** permission to fall back to the user's PC",
            text,
        )


    def test_plugin_mcp_is_cloud_first_and_local_windows_is_engineering_only(self) -> None:
        config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
        server = config["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual("http", server["type"])
        self.assertEqual("https://cbi-v61-preview.onrender.com/mcp", server["url"])
        self.assertEqual("oauth", server["auth"])
        self.assertEqual("CBI_REMOTE_BEARER_TOKEN", server["bearer_token_env_var"])
        self.assertNotIn("command", server)
        self.assertNotIn("args", server)
        self.assertTrue(LOCAL_MCP_CONFIG.is_file())
        local = json.loads(LOCAL_MCP_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual("powershell.exe", local["mcpServers"]["buyer-outreach-actions"]["command"])

    def test_one_shot_documents_remote_mcp_as_canonical_plugin_path(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("The plugin `.mcp.json` is the cloud production MCP route", text)
        self.assertIn("deploy/local/mcp.windows.json", text)


if __name__ == "__main__":
    unittest.main()
