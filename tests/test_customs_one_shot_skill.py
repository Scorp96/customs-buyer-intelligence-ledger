from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class UnifiedOneShotAliasTests(unittest.TestCase):
    def test_manifest_alias_is_not_second_investigation(self):
        m=json.loads((ROOT/".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        prompts=m["interface"]["defaultPrompt"]
        self.assertTrue(str(m["version"]).startswith("6.4.0+codex."))
        self.assertIn("$investigate-customs-buyers",prompts[0])
        self.assertIn("批量写回",prompts[1])
        self.assertTrue(any("$customs-buyer-one-shot" in v for v in prompts[2:]))
        self.assertIn("不是第二调查模式",prompts[2])

    def test_one_shot_alias_preserves_complete_cloud_research_and_safety(self):
        t=(ROOT/"skills/customs-buyer-one-shot/SKILL.md").read_text(encoding="utf-8")
        for s in ["ONE-SHOT CUSTOMS", "one consolidated final answer",
                  "do **not** ask the user to open a computer",
                  "Runtime unavailability is **not** permission to fall back to the user's PC",
                  "regional_peer","industry_peer","scale_peer",
                  "same_supplier_buyer","same_product_hs_application_buyer",
                  "competing_supplier_alternative", "Cloud customs delta monitoring",
                  "notify only for a genuinely new shipment",
                  "same unified `FULL_AUDIT`", "INTERRUPTED"]:
            self.assertIn(s,t)
        self.assertNotIn("takes precedence over the generic `ANSWER_FIRST`",t)
        self.assertNotIn("continue the complete one-shot investigation with the Host's",t)

if __name__=="__main__":
    unittest.main()
