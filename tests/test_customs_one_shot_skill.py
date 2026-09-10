from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
SKILL = ROOT / "skills" / "customs-buyer-one-shot" / "SKILL.md"


class CustomsBuyerOneShotSkillTests(unittest.TestCase):
    def test_manifest_routes_customs_tasks_to_one_shot_skill(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        prompts = manifest["interface"]["defaultPrompt"]
        self.assertTrue(
            any("$customs-buyer-one-shot" in prompt for prompt in prompts),
            "customs default prompts must route to the one-shot skill",
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


if __name__ == "__main__":
    unittest.main()
