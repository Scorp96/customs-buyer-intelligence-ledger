from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "investigate-customs-buyers" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "social_radar"
sys.path.insert(0, str(SCRIPTS))

from social_radar_handoff import build_social_radar_research_handoff  # noqa: E402


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SocialRadarResearchHandoffTests(unittest.TestCase):
    def test_mixed_bundle_preserves_evidence_inferences_and_routes(self) -> None:
        source = _fixture("mixed_candidate.json")
        result = build_social_radar_research_handoff(source)
        self.assertEqual(result["schema_version"], "cbi.social-radar-research-handoff.v1")
        self.assertEqual(len(result["direct_evidence"]), len(source["evidence"]))
        self.assertEqual(len(result["inferences"]), len(source["inferences"]))
        self.assertEqual(len(result["routes"]), len(source["routes"]))
        self.assertEqual(result["discovery"], source["discovery"])
        self.assertEqual(result["recommended_cbi_priority"], "URGENT_RESEARCH")

    def test_handoff_is_explicitly_non_mutating(self) -> None:
        result = build_social_radar_research_handoff(_fixture("instagram_candidate.json"))
        self.assertEqual(
            result["side_effects"],
            {
                "runtime_constructed": False,
                "mcp_mutation_called": False,
                "crm_write_performed": False,
                "outreach_sent": False,
            },
        )

    def test_final_cbi_authority_is_withheld(self) -> None:
        result = build_social_radar_research_handoff(_fixture("mixed_candidate.json"))
        self.assertEqual(result["cbi_authority"]["commercial_value"], "NOT_EVALUATED")
        self.assertEqual(result["cbi_authority"]["research_confidence"], "NOT_EVALUATED")
        self.assertEqual(result["cbi_authority"]["outreach_readiness"], "NOT_EVALUATED")
        self.assertEqual(result["cbi_authority"]["decision_saturation"], "NOT_EVALUATED")
        self.assertIsNone(result["cbi_authority"]["final_grade"])

    def test_candidate_fingerprint_is_carried_into_handoff(self) -> None:
        result = build_social_radar_research_handoff(_fixture("tiktok_candidate.json"))
        self.assertRegex(result["candidate_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["candidate_id"], "fixture-tiktok-cabinet")


if __name__ == "__main__":
    unittest.main()
