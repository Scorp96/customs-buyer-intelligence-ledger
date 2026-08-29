from __future__ import annotations

import json
import unittest
from pathlib import Path

from unified_runtime.core import CBI_MCP_TOOL_NAMES


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class AnswerFirstPolicyTests(unittest.TestCase):
    def test_skill_declares_no_write_default_and_explicit_commit_boundary(self) -> None:
        skill = (
            PLUGIN_ROOT
            / "skills"
            / "investigate-customs-buyers"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("## Default mode: `ANSWER_FIRST`", skill)
        self.assertIn("Do **not** locate, open, compare, render, edit or export", skill)
        self.assertIn(
            "仅回答｜草稿已生成｜未写回CRM｜未生成审计/Closure｜未生成一键发送｜未发送",
            skill,
        )
        self.assertIn("enter `BATCH_COMMIT`", skill)
        self.assertIn("a target count such as ten Buyers", skill)
        self.assertIn("does **not** run in `ANSWER_FIRST`", skill)
        self.assertIn("**邮件草稿**", skill)
        self.assertIn("**即时聊天草稿**", skill)
        self.assertIn("must not produce `mailto:`", skill)
        self.assertIn("Do **not** call any Customs Buyer Intelligence MCP tool", skill)
        for tool_name in CBI_MCP_TOOL_NAMES:
            self.assertIn(f"`{tool_name}`", skill)

    def test_runtime_and_server_make_answer_first_machine_discoverable(self) -> None:
        server = (PLUGIN_ROOT / "mcp" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("recover_pending_once", server)
        initialize_body = server.split('if method == "initialize":', 1)[1].split('if method == "ping"', 1)[0]
        self.assertNotIn("sync_pending_receipts({", initialize_body)
        self.assertIn("Default to ANSWER_FIRST", server)
        self.assertIn("Do not call any Customs Buyer Intelligence ", server)
        self.assertIn("MCP tool, access CRM/workbooks", server)
        self.assertIn("Not for ANSWER_FIRST ordinary buyer/contact lookups", server)

    def test_default_prompts_are_answer_first(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        prompts = manifest["interface"]["defaultPrompt"]

        self.assertIn("默认只查公开来源并立即回答", prompts[0])
        self.assertIn("不修改 CRM/Excel", prompts[0])
        self.assertIn("深度定制开发邮件", prompts[0])
        self.assertIn("即时聊天草稿", prompts[0])
        self.assertIn("批量写回", prompts[1])

        agent = (
            PLUGIN_ROOT
            / "skills"
            / "investigate-customs-buyers"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("ANSWER_FIRST mode by default", agent)
        self.assertIn("one development email and one instant-chat message", agent)
        self.assertIn("ten Buyers never authorizes automatic persistence", agent)


if __name__ == "__main__":
    unittest.main()
