import json
from pathlib import Path
import unittest


class ContactFirstPluginPolicyTest(unittest.TestCase):
    def test_contact_first_policy_is_exposed(self):
        p = Path(".codex-plugin/plugin.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        text = data.get("longDescription") or data.get("presentation", {}).get("longDescription", "") or data.get("interface", {}).get("longDescription", "")
        required = [
            "Google Maps/Business",
            "Facebook",
            "决策人",
            "公开 LinkedIn",
            "反查",
            "CONTACT_PENDING",
            "SOURCE_UNAVAILABLE",
            "不得猜姓名",
            "公司 route 与 named-person route 必须分开验证",
            "COMPANY_ROUTE_READY",
            "不得因此停止 named-person research",
            "终止性 receipt",
        ]
        for token in required:
            self.assertIn(token, text)

    def test_policy_preserves_customs_and_safety_boundaries(self):
        p = Path(".codex-plugin/plugin.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        text = data.get("interface", {}).get("longDescription", "")
        for token in [
            "one-shot customs route",
            "six",
            "WAL durability",
            "draft-only outreach",
            "不得把公司总机、通用邮箱或公司级 route 冒充具体决策人的个人直线",
        ]:
            if token == "six":
                self.assertIn("六分支", text)
            else:
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
