"""Regression: public HS/tariff information searches are not contact exhaustion.

This fixture uses no network, production sessions, credentials, or writes.
"""
from __future__ import annotations

import asyncio
import unittest

from unified_runtime.crawler_execution_bridge import (
    CrawlExecutionBridge,
    CrawlPage,
    _task_is_contact_research,
)


class _FakeBackend:
    name = "fixture"

    async def fetch(self, url: str) -> CrawlPage:
        return CrawlPage(
            url=url,
            text="2022 HS nomenclature: heading 8422 and heading 8479",
            links=(),
        )


class CrawlResearchIntentTests(unittest.TestCase):
    def test_hs_public_information_task_id_positive_without_contacts(self) -> None:
        receipt = asyncio.run(
            CrawlExecutionBridge(_FakeBackend(), max_pages=1).execute(
                {
                    "task_id": "HS-20261012-CANARY",
                    "research_type": "HS_CLASSIFICATION",
                    "research_intent": "Read official HS nomenclature for machinery",
                },
                seed_url="https://example.com/",
            )
        )
        self.assertEqual(receipt["result"], "POSITIVE")
        self.assertEqual(receipt["pages_crawled"], 1)
        self.assertFalse(receipt["negative_contact_conclusion_allowed"])
        self.assertEqual(receipt["route_candidates"], [])
        self.assertIn("nomenclature", receipt["goal_terms"])

    def test_general_research_intent_without_type_is_not_contact_negative(self) -> None:
        receipt = asyncio.run(
            CrawlExecutionBridge(_FakeBackend(), max_pages=1).execute(
                {
                    "task_id": "HS-20261012-FREE-TEXT",
                    "research_intent": "Review official public WCO HS 2022 Chapter 84 classification",
                },
                seed_url="https://example.com/",
            )
        )
        self.assertEqual(receipt["result"], "POSITIVE")
        self.assertFalse(receipt["negative_contact_conclusion_allowed"])

    def test_explicit_contact_source_remains_contact(self) -> None:
        self.assertTrue(_task_is_contact_research(
            {"task_id": "CONTACT-ONE", "source_family": "official_contact"}, "task_id",
        ))
        self.assertTrue(_task_is_contact_research(
            {"task_id": "CONTACT-TWO", "research_type": "CONTACT"}, "task_id",
        ))

    def test_legacy_contact_task_id_remains_compatible(self) -> None:
        receipt = asyncio.run(
            CrawlExecutionBridge(_FakeBackend(), max_pages=1).execute(
                {"task_id": "LEGACY-CONTACT"},
                seed_url="https://example.com/",
            )
        )
        self.assertEqual(receipt["result"], "NEGATIVE_EXHAUSTED")
        self.assertTrue(receipt["negative_contact_conclusion_allowed"])

    def test_explicit_route_target_overrides_free_text_intent(self) -> None:
        self.assertTrue(_task_is_contact_research(
            {
                "task_id": "CONTACT-GOAL",
                "route_target": "NAMED",
                "research_intent": "Identify verified procurement person",
            },
            "task_id",
        ))

    def test_explicit_product_family_overrides_legacy_task_id(self) -> None:
        self.assertFalse(_task_is_contact_research(
            {"task_id": "PUBLIC-PRODUCT", "source_family": "official_products"}, "task_id",
        ))


if __name__ == "__main__":
    unittest.main()
