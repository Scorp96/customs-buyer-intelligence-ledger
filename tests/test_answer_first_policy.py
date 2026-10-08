from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnifiedFullAuditPolicyTests(unittest.TestCase):
    def test_single_investigation_route_and_identity_order_in_skill(self):
        skill = (ROOT / "skills/investigate-customs-buyers/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Only investigation route: CBI FULL_AUDIT + Decision-Grade Evidence Saturation", skill)
        self.assertNotIn("## Default mode: `ANSWER_FIRST`", skill)
        seq = ["**Company and industry**", "**Google Maps / Business**",
               "**Official website**", "**Company decision-makers and official social media**",
               "**Every relevant decision-maker's social media and route**"]
        indices = [skill.index(s) for s in seq]
        self.assertEqual(indices, sorted(indices))
        for s in ["28 minutes", "中断交接报告", "six", "Facebook",
                  "no automatic CRM", "EXHAUSTIVE"]:
            # Source policy uses different precise words for side effects.
            if s == "no automatic CRM":
                self.assertIn("CRM/workbook mutation", skill)
            else:
                self.assertIn(s, skill)

    def test_cloud_runtime_contract_is_full_audit_default(self):
        core = (ROOT / "unified_runtime/core.py").read_text(encoding="utf-8")
        self.assertIn('"default_mode": "FULL_AUDIT"', core)
        self.assertIn('"single_investigation_mode": "EXHAUSTIVE"', core)
        self.assertIn('"min_active_research_minutes": 28', core)
        self.assertIn('"EACH_DECISION_MAKER_PERSONAL_SOCIAL_AND_CONTACT_ROUTE"', core)
        self.assertIn('"crm_write_requires_separate_authorization": True', core)
        self.assertIn('"continuation_resumes_existing_full_audit": True', core)

    def test_mcp_discovery_cannot_route_to_answer_first(self):
        server = (ROOT / "mcp/server.py").read_text(encoding="utf-8")
        self.assertIn("Use ONLY unified CBI FULL_AUDIT", server)
        self.assertNotIn("Default to ANSWER_FIRST", server)
        self.assertNotIn("Not for ANSWER_FIRST ordinary buyer/contact lookups", server)
        self.assertNotIn("recover_pending_once", server)
        self.assertIn("MCP initialize never mutates state", server)

    def test_manifest_and_agent_enforce_one_route(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertIn("FULL_AUDIT", manifest["interface"]["longDescription"])
        self.assertIn("Google Maps/Business", manifest["interface"]["longDescription"])
        self.assertIn("Facebook", manifest["interface"]["longDescription"])
        self.assertIn("Decision-Grade", manifest["interface"]["longDescription"])
        self.assertIn("$investigate-customs-buyers", manifest["interface"]["defaultPrompt"][0])
        self.assertIn("FULL_AUDIT", manifest["interface"]["defaultPrompt"][0])
        agent = (ROOT / "skills/investigate-customs-buyers/agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("ONE CBI FULL_AUDIT", agent)
        self.assertIn("do not", agent.lower())

if __name__ == "__main__":
    unittest.main()
