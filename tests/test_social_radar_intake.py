from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "investigate-customs-buyers" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "social_radar"
sys.path.insert(0, str(SCRIPTS))

from social_radar_intake import (  # noqa: E402
    SocialRadarIntakeError,
    candidate_fingerprint,
    validate_and_normalize_social_radar_candidate,
)


def _base_bundle(stage: str = "SOCIAL", platform: str = "INSTAGRAM") -> dict:
    return {
        "schema_version": "cbi.social-radar-candidate.v1",
        "candidate_id": "cand-acme-001",
        "observed_at": "2026-09-11T06:30:00Z",
        "source_stage": stage,
        "canonical_identity": {
            "display_name": "Acme Sign Supply",
            "normalized_name": "acme sign supply",
            "entity_type": "COMPANY",
            "confidence": 0.82,
        },
        "profiles": [
            {
                "platform": platform,
                "profile_id": "acme-sign-supply",
                "url": "https://example.invalid/acme-sign-supply",
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "evidence_type": "BIO_TEXT",
                "value": "Advertising materials distributor and large-format print supplier",
                "source_url": "https://example.invalid/acme-sign-supply",
                "source_platform": platform,
                "observed_at": "2026-09-11T06:30:00Z",
                "confidence": 1.0,
            }
        ],
        "inferences": [
            {
                "inference_id": "inf-1",
                "claim": "Likely recurring consumer of printable PVC sheet",
                "confidence": 0.74,
                "basis_evidence_ids": ["ev-1"],
                "reason_code": "SIGN_SUPPLY_USE_CASE",
            }
        ],
        "routes": [
            {
                "route_type": "WEBSITE",
                "route_value": "https://example.invalid",
                "source": "https://example.invalid/acme-sign-supply",
                "confidence": 1.0,
                "purpose": "GENERAL_BUSINESS",
                "validation_status": "PUBLIC_OBSERVED",
            }
        ],
        "discovery": {
            "market": "Brazil",
            "language": "pt-BR",
            "keyword": "comunicacao visual pvc",
            "semantic_cluster": "SIGN_DISPLAY",
            "source_platform": platform,
            "graph_depth": 1,
        },
        "source_score": {
            "grade": "B+",
            "score": 78.0,
            "components": {"buyer_fit": 23.0, "product_relevance": 18.0},
        },
        "recommended_cbi_priority": "HIGH",
    }


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SocialRadarIntakeTests(unittest.TestCase):
    def test_instagram_only_bundle_normalizes(self) -> None:
        result = validate_and_normalize_social_radar_candidate(_base_bundle())
        self.assertEqual(result["source_stage"], "SOCIAL")
        self.assertEqual(result["profiles"][0]["platform"], "INSTAGRAM")
        self.assertRegex(result["candidate_fingerprint"], r"^[0-9a-f]{64}$")

    def test_radar_only_bundle_normalizes(self) -> None:
        bundle = _base_bundle(stage="GLOBAL_RADAR", platform="SEARCH_TREND")
        bundle["profiles"] = []
        bundle["discovery"].update({"trend_window": "30d", "graph_depth": None})
        result = validate_and_normalize_social_radar_candidate(bundle)
        self.assertEqual(result["source_stage"], "GLOBAL_RADAR")
        self.assertEqual(result["discovery"]["trend_window"], "30d")

    def test_inference_only_bundle_is_rejected(self) -> None:
        bundle = _base_bundle()
        bundle["evidence"] = []
        with self.assertRaisesRegex(SocialRadarIntakeError, "direct evidence"):
            validate_and_normalize_social_radar_candidate(bundle)

    def test_source_cannot_assert_final_cbi_grade(self) -> None:
        bundle = _base_bundle()
        bundle["source_score"]["final_grade"] = "A+"
        with self.assertRaisesRegex(SocialRadarIntakeError, "final CBI grade"):
            validate_and_normalize_social_radar_candidate(bundle)

    def test_inference_must_reference_known_evidence(self) -> None:
        bundle = _base_bundle()
        bundle["inferences"][0]["basis_evidence_ids"] = ["ev-missing"]
        with self.assertRaisesRegex(SocialRadarIntakeError, "unknown evidence"):
            validate_and_normalize_social_radar_candidate(bundle)

    def test_fingerprint_is_stable_across_mapping_order(self) -> None:
        first = _base_bundle()
        second = json.loads(json.dumps(first, sort_keys=True))
        second = dict(reversed(list(second.items())))
        self.assertEqual(candidate_fingerprint(first), candidate_fingerprint(second))

    def test_validation_does_not_mutate_input(self) -> None:
        bundle = _base_bundle()
        before = copy.deepcopy(bundle)
        validate_and_normalize_social_radar_candidate(bundle)
        self.assertEqual(bundle, before)

    def test_all_cross_project_fixtures_normalize(self) -> None:
        expected = {
            "instagram_candidate.json": "SOCIAL",
            "tiktok_candidate.json": "SOCIAL",
            "radar_candidate.json": "GLOBAL_RADAR",
            "mixed_candidate.json": "SOCIAL_AND_RADAR",
        }
        for name, stage in expected.items():
            with self.subTest(name=name):
                result = validate_and_normalize_social_radar_candidate(_fixture(name))
                self.assertEqual(result["source_stage"], stage)
                self.assertGreaterEqual(len(result["evidence"]), 1)
                self.assertRegex(result["candidate_fingerprint"], r"^[0-9a-f]{64}$")

    def test_tiktok_use_case_inference_is_not_promoted_to_direct_evidence(self) -> None:
        result = validate_and_normalize_social_radar_candidate(_fixture("tiktok_candidate.json"))
        inferred_claims = {row["claim"] for row in result["inferences"]}
        direct_values = {str(row["value"]) for row in result["evidence"]}
        self.assertTrue(any("purchase history is not verified" in claim for claim in inferred_claims))
        self.assertFalse(any("purchase history" in value.lower() for value in direct_values))


if __name__ == "__main__":
    unittest.main()
