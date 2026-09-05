from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V64PromotionIntegrationContractTests(unittest.TestCase):
    def test_production_ci_portability_is_preserved(self) -> None:
        text = (ROOT / ".github" / "workflows" / "cbi-v6-ci.yml").read_text(encoding="utf-8")
        self.assertIn("PyYAML==6.0.2 tzdata==2026.3", text)

    def test_render_r2_blocked_external_env_is_semantically_reconciled(self) -> None:
        text = (ROOT / "tests" / "test_v63_render_r2_workflow_contract.py").read_text(encoding="utf-8")
        self.assertIn('"CBI_V63_R2_REGION",', text)
        self.assertIn('environment["PYTHONHASHSEED"] = "0"', text)

    def test_candidate_windows_semantics_remain_authoritative(self) -> None:
        text = (ROOT / "tests" / "test_v6_windows_portability.py").read_text(encoding="utf-8")
        self.assertIn("environment = dict(os.environ)", text)
        self.assertIn("_declared_production_tool_names()", text)
        self.assertIn("_declared_core_tool_names()", text)


if __name__ == "__main__":
    unittest.main()
