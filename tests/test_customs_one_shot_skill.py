from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SingleCBIAuditSurfaceTests(unittest.TestCase):
    def test_only_one_investigation_skill_exposed(self):
        self.assertTrue((ROOT/"skills/investigate-customs-buyers/SKILL.md").exists())
        self.assertFalse((ROOT/"skills/customs-buyer-one-shot/SKILL.md").exists())
        manifest=json.loads((ROOT/".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(all("$customs-buyer-one-shot" not in p for p in manifest["interface"]["defaultPrompt"]))
        self.assertTrue(all("$investigate-customs-buyers" in p for p in manifest["interface"]["defaultPrompt"][:3]))

    def test_customs_and_decision_grade_survive_as_references(self):
        root=ROOT/"skills/investigate-customs-buyers"
        skill=(root/"SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/customs-investigation-checklist.md",skill)
        self.assertIn("references/decision-grade-full-audit.md",skill)
        customs=(root/"references/customs-investigation-checklist.md").read_text(encoding="utf-8")
        research=(root/"references/decision-grade-full-audit.md").read_text(encoding="utf-8")
        for token in ["regional_peer","industry_peer","scale_peer","same_supplier_buyer",
                       "same_product_hs_application_buyer","competing_supplier_alternative"]:
            self.assertIn(token,customs)
        for token in ["28 minutes","Google Maps","Facebook","中断交接报告","evidence cluster"]:
            self.assertIn(token,research)

if __name__=="__main__":
    unittest.main()
