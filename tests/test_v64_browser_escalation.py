from __future__ import annotations

import asyncio
import unittest

from unified_runtime.browser_escalation import (
    EscalatingCrawlerBackend,
    ResilientCrawlerBackend,
    _safe_click_label,
)
from unified_runtime.crawler_execution_bridge import CrawlPage


def run(coro):
    return asyncio.run(coro)


class SequenceBackend:
    def __init__(self, name: str, pages: list[CrawlPage]) -> None:
        self.name = name
        self.pages = list(pages)
        self.calls: list[str] = []

    async def fetch(self, url: str) -> CrawlPage:
        self.calls.append(url)
        if self.pages:
            return self.pages.pop(0)
        return CrawlPage(url=url, text="", success=False, error="fixture_exhausted")


class SlowBackend:
    name = "slow"

    async def fetch(self, url: str) -> CrawlPage:
        await asyncio.sleep(0.05)
        return CrawlPage(url=url, text="late", success=True)


class BrowserEscalationTests(unittest.TestCase):
    def test_healthy_primary_does_not_escalate(self) -> None:
        primary = SequenceBackend(
            "primary",
            [CrawlPage(
                url="https://example.com/",
                text="A" * 700,
                links=("https://example.com/contact",),
            )],
        )
        browser = SequenceBackend(
            "browser",
            [CrawlPage(url="https://example.com/", text="browser", success=True)],
        )
        backend = EscalatingCrawlerBackend(primary, browser, sparse_text_chars=200)

        page = run(backend.fetch("https://example.com/"))

        self.assertEqual(page.text, "A" * 700)
        self.assertEqual(len(browser.calls), 0)
        diag = backend.diagnostics()
        self.assertEqual(diag["browser_escalation_count"], 0)
        self.assertFalse(diag["events"][0]["escalated"])

    def test_sparse_primary_escalates_and_selects_browser(self) -> None:
        primary = SequenceBackend(
            "primary",
            [CrawlPage(url="https://example.com/", text="Loading...", links=(), success=True)],
        )
        browser = SequenceBackend(
            "browser",
            [CrawlPage(
                url="https://example.com/",
                text="Contact sales@example.com " + ("B" * 500),
                links=("https://example.com/contact",),
                link_hints=(("https://example.com/contact", "Contact"),),
                success=True,
            )],
        )
        backend = EscalatingCrawlerBackend(primary, browser, sparse_text_chars=200)

        page = run(backend.fetch("https://example.com/"))

        self.assertIn("sales@example.com", page.text)
        self.assertEqual(len(browser.calls), 1)
        diag = backend.diagnostics()
        self.assertEqual(diag["browser_escalation_count"], 1)
        self.assertEqual(diag["events"][0]["selected_backend"], "browser")
        self.assertEqual(diag["events"][0]["reason"], "PRIMARY_CONTENT_SPARSE")

    def test_browser_failure_keeps_better_primary_page(self) -> None:
        primary_page = CrawlPage(
            url="https://example.com/",
            text="Short but useful company text",
            links=(),
            success=True,
        )
        primary = SequenceBackend("primary", [primary_page])
        browser = SequenceBackend(
            "browser",
            [CrawlPage(url="https://example.com/", text="", success=False, error="blocked")],
        )
        backend = EscalatingCrawlerBackend(primary, browser, sparse_text_chars=200)

        page = run(backend.fetch("https://example.com/"))

        self.assertEqual(page, primary_page)
        self.assertEqual(backend.diagnostics()["events"][0]["selected_backend"], "primary")

    def test_resilient_backend_retries_transient_failure(self) -> None:
        inner = SequenceBackend(
            "flaky",
            [
                CrawlPage(url="https://example.com/", text="", success=False, error="temporary"),
                CrawlPage(url="https://example.com/", text="ok", success=True),
            ],
        )
        backend = ResilientCrawlerBackend(
            inner,
            timeout_seconds=1,
            max_retries=1,
            retry_delay_seconds=0,
        )

        page = run(backend.fetch("https://example.com/"))

        self.assertTrue(page.success)
        self.assertEqual(page.text, "ok")
        diag = backend.diagnostics()
        self.assertEqual(len(diag["retry_attempts"]), 2)
        self.assertFalse(diag["retry_attempts"][0]["success"])
        self.assertTrue(diag["retry_attempts"][1]["success"])

    def test_resilient_backend_classifies_meta_temporary_block_and_retries(self) -> None:
        url = "https://www.facebook.com/ferreteriaslaquintainc/"
        blocked = CrawlPage(
            url=url,
            text="You’re Temporarily Blocked. It looks like you were misusing this feature by going too fast.",
            links=(),
            success=True,
        )
        inner = SequenceBackend("meta", [blocked, blocked])
        backend = ResilientCrawlerBackend(
            inner,
            timeout_seconds=1,
            max_retries=1,
            retry_delay_seconds=0,
        )

        page = run(backend.fetch(url))

        self.assertFalse(page.success)
        self.assertEqual(page.error, "source_throttled:META_TEMPORARILY_BLOCKED")
        diag = backend.diagnostics()
        self.assertEqual(len(diag["retry_attempts"]), 2)
        self.assertTrue(diag["retry_attempts"][0]["source_throttled"])
        self.assertTrue(diag["retry_attempts"][1]["source_throttled"])
        self.assertEqual(len(inner.calls), 2)

    def test_resilient_backend_timeout_is_fail_closed(self) -> None:
        backend = ResilientCrawlerBackend(
            SlowBackend(),
            timeout_seconds=0.01,
            max_retries=0,
            retry_delay_seconds=0,
        )

        page = run(backend.fetch("https://example.com/"))

        self.assertFalse(page.success)
        self.assertIn("timeout_after_", page.error or "")
        diag = backend.diagnostics()
        self.assertTrue(diag["retry_attempts"][0]["timed_out"])

    def test_click_policy_allows_research_expansion_but_blocks_actions(self) -> None:
        self.assertTrue(_safe_click_label("Show contact details"))
        self.assertTrue(_safe_click_label("Equipo de compras"))
        self.assertTrue(_safe_click_label("Mais detalhes"))
        self.assertFalse(_safe_click_label("Submit order"))
        self.assertFalse(_safe_click_label("Buy now"))
        self.assertFalse(_safe_click_label("Sign in"))


if __name__ == "__main__":
    unittest.main()
