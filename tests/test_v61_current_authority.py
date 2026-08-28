from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


class V61CurrentAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-authority-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-AUTH-SYNTH",
                "country": "Synthetic",
                "name": "Synthetic Authority Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = started["investigation_id"]

    def decision_observation(
        self,
        suffix: str,
        value: dict,
        *,
        domain: str = "authority-one.invalid",
        freshness: str = "CURRENT_CONFIRMED",
    ) -> dict:
        return {
            "claim_key": "buying_group.decision_chain",
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": "C-AUTH-SYNTH",
            "value": value,
            "source": {
                "source_family": "synthetic_official",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": f"https://{domain}/authority/{suffix}",
                "locator": f"https://{domain}/authority/{suffix}#record",
                "raw_excerpt": f"Synthetic current-authority fixture {suffix}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": freshness,
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": (
                "Synthetic authority fixture only; support is limited to the "
                "explicit person, association, role and relevance fields."
            ),
        }

    def compile(self, rows: list[dict], bundle_id: str) -> None:
        result = self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": bundle_id, "observations": rows},
        })
        self.assertIn(result["status"], {"ACCEPTED", "PARTIAL_SUCCESS"})

    def claim(self) -> dict:
        return self.runtime.get_claims({
            "investigation_id": self.investigation_id,
        })["claims"]["buying_group.decision_chain"]

    def test_contract_declares_four_current_authority_prerequisites(self) -> None:
        contract = self.runtime.get_runtime_contract({})
        authority = contract["current_authority_v6_1"]
        self.assertEqual(
            authority["decision_chain_requires"],
            [
                "NAMED_PERSON",
                "CURRENT_COMPANY_ASSOCIATION",
                "CURRENT_OR_SUFFICIENTLY_RECENT_ROLE",
                "ROLE_RELEVANCE",
            ],
        )
        self.assertFalse(authority["mere_company_association_is_decision_chain_authority"])
        self.assertTrue(
            contract["production_contract_hardening"][
                "decision_chain_current_authority_fail_closed"
            ]
        )

    def test_current_source_and_relevant_title_without_explicit_association_does_not_pass(self) -> None:
        self.compile(
            [
                self.decision_observation(
                    "missing-association",
                    {
                        "person_name": "Synthetic President",
                        "role": "President",
                        "role_freshness": "CURRENT_CONFIRMED",
                    },
                )
            ],
            "BUNDLE-AUTH-MISSING-ASSOCIATION",
        )
        claim = self.claim()
        self.assertEqual(claim["state"], "SEARCHING")
        assessment = claim["current_authority_assessments"][0]
        self.assertIn(
            "CURRENT_COMPANY_ASSOCIATION_REQUIRED",
            assessment["missing_prerequisites"],
        )
        self.assertEqual(
            claim["blocked_from_support_reason"],
            "CURRENT_DECISION_AUTHORITY_PREREQUISITES_NOT_PROVEN",
        )

    def test_company_association_only_does_not_become_decision_chain(self) -> None:
        self.compile(
            [
                self.decision_observation(
                    "association-only",
                    {
                        "person_name": "Synthetic Electronic Contact",
                        "company_association_current": True,
                        "role": "Electronic Business Contact",
                        "role_freshness": "CURRENT_CONFIRMED",
                    },
                )
            ],
            "BUNDLE-AUTH-ASSOCIATION-ONLY",
        )
        claim = self.claim()
        self.assertEqual(claim["state"], "SEARCHING")
        assessment = claim["current_authority_assessments"][0]
        self.assertTrue(assessment["company_association_current"])
        self.assertFalse(assessment["role_relevant"])
        self.assertIn("ROLE_RELEVANCE_REQUIRED", assessment["missing_prerequisites"])

    def test_owner_with_current_association_and_current_role_passes(self) -> None:
        self.compile(
            [
                self.decision_observation(
                    "owner-current",
                    {
                        "person_name": "Synthetic Owner",
                        "company_association_status": "CURRENT_CONFIRMED",
                        "role": "Owner",
                        "role_freshness": "CURRENT_CONFIRMED",
                    },
                )
            ],
            "BUNDLE-AUTH-OWNER-CURRENT",
        )
        claim = self.claim()
        self.assertEqual(claim["state"], "SUPPORTED")
        self.assertEqual(len(claim["qualifying_current_authority_observation_ids"]), 1)
        self.assertEqual(
            claim["current_authority_assessments"][0]["missing_prerequisites"],
            [],
        )

    def test_two_independent_qualifying_sources_can_strongly_support(self) -> None:
        rows = [
            self.decision_observation(
                "owner-source-one",
                {
                    "person_name": "Synthetic Owner",
                    "company_association_current": True,
                    "role": "Owner",
                    "role_freshness": "CURRENT_CONFIRMED",
                },
                domain="authority-one.invalid",
            ),
            self.decision_observation(
                "owner-source-two",
                {
                    "person_name": "Synthetic Owner",
                    "company_association_current": True,
                    "role": "Owner",
                    "role_freshness": "RECENT",
                },
                domain="registry-two.invalid",
                freshness="RECENT",
            ),
        ]
        self.compile(rows, "BUNDLE-AUTH-TWO-SOURCES")
        claim = self.claim()
        self.assertEqual(claim["state"], "STRONGLY_SUPPORTED")
        self.assertEqual(claim["independent_source_count"], 2)
        self.assertEqual(len(claim["qualifying_current_authority_observation_ids"]), 2)

    def test_explicit_procurement_relevance_can_qualify_non_whitelisted_role(self) -> None:
        self.compile(
            [
                self.decision_observation(
                    "operations-relevant",
                    {
                        "person_name": "Synthetic Operations Lead",
                        "company_association_current": True,
                        "role": "Operations Lead",
                        "role_freshness": "CURRENT_LIKELY",
                        "procurement_relevance": "DIRECT",
                    },
                    freshness="CURRENT_LIKELY",
                )
            ],
            "BUNDLE-AUTH-OPERATIONS-DIRECT",
        )
        claim = self.claim()
        self.assertEqual(claim["state"], "SUPPORTED")
        self.assertTrue(claim["current_authority_assessments"][0]["role_relevant"])


if __name__ == "__main__":
    unittest.main()
