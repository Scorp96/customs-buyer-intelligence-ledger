"""Prevent obvious website template contact values from becoming verified routes."""
import unittest

from unified_runtime.research_orchestration_hardening import (
    V61ResearchOrchestrationHardeningMixin,
    _is_obvious_placeholder_route,
)


class TemplateRouteSafetyTests(unittest.TestCase):
    def test_known_published_template_contact_values_are_rejected(self):
        examples = (
            ("EMAIL", "X.XXXXX@COM"),
            ("PHONE", "020-000000"),
            ("PHONE", "000-000000"),
            ("PHONE", "020-000000 000-000000"),
        )
        for channel, value in examples:
            with self.subTest(value=value):
                self.assertTrue(_is_obvious_placeholder_route(channel, value))
                route = V61ResearchOrchestrationHardeningMixin._route_payload(
                    {"channel": channel, "value": value, "verified": True},
                    account_id="SYNTH-ACCOUNT", source_kind="COMPILED_OBSERVATION",
                    evidence_ids=["EVD-1"],
                )
                self.assertIsNone(route)

    def test_genuine_looking_official_contact_not_blanket_blocked(self):
        for channel, value in (
            ("EMAIL", "sales@example.com"),
            ("EMAIL", "contact@example.com"),
            ("PHONE", "0086-13710005492"),
            ("PHONE", "+15550101001"),
        ):
            with self.subTest(value=value):
                self.assertFalse(_is_obvious_placeholder_route(channel, value))

    def test_compiled_observation_rejection_is_diagnostic(self):
        observation = {
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": "SYNTH-ACCOUNT",
            "evidence_id": "EVD-1",
            "source": {"freshness": "CURRENT_CONFIRMED"},
            "value": {"channel": "EMAIL", "value": "X.XXXXX@COM",
                      "verified": True, "guessed": False, "masked": False},
        }
        reject = V61ResearchOrchestrationHardeningMixin._compiled_route_rejection_reasons(
            observation, account_id="SYNTH-ACCOUNT",
        )
        self.assertIn("OBVIOUS_TEMPLATE_CONTACT_VALUE", reject)


if __name__ == "__main__":
    unittest.main()
