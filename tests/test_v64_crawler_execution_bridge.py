from __future__ import annotations

import asyncio
import unittest

from unified_runtime.crawler_execution_bridge import (
    CrawlExecutionBridge,
    CrawlPage,
)


class FakeBackend:
    name = "fake-crawler"

    def __init__(self, pages: dict[str, CrawlPage]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> CrawlPage:
        self.calls.append(url)
        return self.pages.get(
            url,
            CrawlPage(url=url, text="", links=(), success=False, error="missing fixture"),
        )


def run(coro):
    return asyncio.run(coro)


class CrawlExecutionBridgeTests(unittest.TestCase):
    def test_prioritizes_same_site_contact_team_and_products(self) -> None:
        pages = {
            "https://example.com/": CrawlPage(
                url="https://example.com/",
                text="Example Company",
                links=(
                    "https://example.com/news",
                    "https://example.com/contact",
                    "https://example.com/team",
                    "https://example.com/products",
                    "https://external.example.org/contact",
                ),
            ),
            "https://example.com/contact": CrawlPage(
                url="https://example.com/contact",
                text="Sales: +51 983 752 162\nEmail: sales@example.com",
                links=(),
            ),
            "https://example.com/team": CrawlPage(
                url="https://example.com/team",
                text="Procurement team",
                links=(),
            ),
            "https://example.com/products": CrawlPage(
                url="https://example.com/products",
                text="PVC and WPC products",
                links=(),
            ),
            "https://example.com/news": CrawlPage(
                url="https://example.com/news",
                text="News",
                links=(),
            ),
        }
        backend = FakeBackend(pages)
        bridge = CrawlExecutionBridge(backend, max_pages=4)
        receipt = run(
            bridge.execute(
                {
                    "task_id": "V63CONTACT-1",
                    "source_family": "official_contact",
                },
                seed_url="https://example.com",
                official_domain_verified=True,
            )
        )

        self.assertEqual(receipt["result"], "POSITIVE")
        self.assertEqual(receipt["pages_crawled"], 4)
        self.assertNotIn("https://external.example.org/contact", backend.calls)
        self.assertEqual(backend.calls[0], "https://example.com/")
        self.assertIn("https://example.com/contact", backend.calls[:2])
        kinds = {(row["kind"], row["value"]) for row in receipt["route_candidates"]}
        self.assertIn(("EMAIL", "sales@example.com"), kinds)
        self.assertIn(("PHONE", "+51983752162"), kinds)
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["owner_scope"], "ACCOUNT")

    def test_extracts_whatsapp_link_as_channel_proof_candidate(self) -> None:
        pages = {
            "https://example.com/": CrawlPage(
                url="https://example.com/",
                text="Contact us",
                links=("https://wa.me/51983752162",),
            ),
        }
        backend = FakeBackend(pages)
        bridge = CrawlExecutionBridge(backend)
        receipt = run(
            bridge.execute(
                {"task_id": "V63CONTACT-WA", "source_family": "official_contact"},
                seed_url="https://example.com/",
                official_domain_verified=True,
            )
        )

        self.assertEqual(receipt["result"], "POSITIVE")
        rows = [row for row in receipt["route_candidates"] if row["kind"] == "WHATSAPP"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], "+51983752162")
        self.assertEqual(rows[0]["channel_url"], "https://wa.me/51983752162")
        self.assertTrue(receipt["route_evidence_ids"])

    def test_unverified_seed_never_promotes_route_owner(self) -> None:
        pages = {
            "https://directory.test/": CrawlPage(
                url="https://directory.test/",
                text="Example Company +1 212 555 0199 info@example.com",
                links=(),
            )
        }
        backend = FakeBackend(pages)
        bridge = CrawlExecutionBridge(backend)
        receipt = run(
            bridge.execute(
                {"task_id": "V63CONTACT-DIR", "source_family": "local_directory"},
                seed_url="https://directory.test/",
                official_domain_verified=False,
            )
        )

        self.assertEqual(receipt["result"], "POSITIVE")
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["owner_scope"], "UNVERIFIED")
        self.assertTrue(receipt["route_candidates"])

    def test_public_source_task_returns_page_evidence_without_contact(self) -> None:
        pages = {
            "https://example.com/": CrawlPage(
                url="https://example.com/",
                text="Manufacturer of PVC foam board.",
                links=("https://example.com/products",),
            ),
            "https://example.com/products": CrawlPage(
                url="https://example.com/products",
                text="PVC foam board 1220 x 2440 mm",
                links=(),
            ),
        }
        backend = FakeBackend(pages)
        bridge = CrawlExecutionBridge(backend)
        receipt = run(
            bridge.execute(
                {
                    "call_id": "V63CALL-PUBLIC",
                    "source_family": "official_products",
                },
                seed_url="https://example.com/",
            )
        )

        self.assertEqual(receipt["call_id"], "V63CALL-PUBLIC")
        self.assertEqual(receipt["result"], "POSITIVE")
        self.assertEqual(receipt["pages_crawled"], 2)
        self.assertTrue(receipt["evidence_ids"])
        self.assertEqual(receipt["route_evidence_ids"], [])

    def test_failed_seed_is_blocked_not_negative(self) -> None:
        backend = FakeBackend({})
        bridge = CrawlExecutionBridge(backend)
        receipt = run(
            bridge.execute(
                {"task_id": "V63CONTACT-FAIL", "source_family": "official_contact"},
                seed_url="https://example.com/",
                official_domain_verified=True,
            )
        )

        self.assertEqual(receipt["result"], "BLOCKED")
        self.assertEqual(receipt["pages_crawled"], 0)
        self.assertEqual(len(receipt["failed_urls"]), 1)

    def test_rejects_non_http_seed(self) -> None:
        backend = FakeBackend({})
        bridge = CrawlExecutionBridge(backend)
        with self.assertRaises(ValueError):
            run(
                bridge.execute(
                    {"call_id": "V63CALL-1"},
                    seed_url="file:///tmp/test.html",
                )
            )


if __name__ == "__main__":
    unittest.main()
