from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin

from .crawler_execution_bridge import CrawlPage


CLICK_INTENT_TERMS = (
    "contact", "contacto", "contato", "fale conosco",
    "about", "nosotros", "empresa", "company",
    "team", "equipo", "equipe", "management", "leadership",
    "procurement", "purchasing", "sourcing", "compras",
    "importaciones", "importacao", "importação", "suprimentos",
    "more", "más", "mais", "details", "detalles", "detalhes",
    "show", "mostrar", "view", "ver",
)

CLICK_BLOCK_TERMS = (
    "buy", "comprar", "checkout", "cart", "carrinho",
    "submit", "enviar", "send", "login", "log in", "sign in",
    "register", "cadastro", "delete", "remove", "cancel order",
    "pay", "payment", "subscribe",
)

SPA_SHELL_MARKERS = (
    "__next_data__", "id=\"root\"", "id='root'",
    "id=\"app\"", "id='app'", "javascript required",
    "enable javascript", "loading...",
)


class AsyncPageBackend(Protocol):
    name: str

    async def fetch(self, url: str) -> CrawlPage:
        ...


@dataclass(frozen=True)
class BrowserEscalationEvent:
    url: str
    escalated: bool
    reason: str | None
    selected_backend: str
    primary_success: bool
    browser_success: bool | None
    primary_text_chars: int
    browser_text_chars: int | None


def _normalize_label(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _safe_click_label(label: str) -> bool:
    normalized = _normalize_label(label)
    if not normalized:
        return False
    if any(term in normalized for term in CLICK_BLOCK_TERMS):
        return False
    return any(term in normalized for term in CLICK_INTENT_TERMS)


def _quality_score(page: CrawlPage) -> int:
    if not page.success:
        return -10_000
    text_chars = len(page.text or "")
    unique_links = len(set(page.links or ()))
    hints = len(page.link_hints or ())
    return min(text_chars, 20_000) + min(unique_links, 100) * 35 + min(hints, 100) * 10


def _escalation_reason(page: CrawlPage, *, sparse_text_chars: int) -> str | None:
    if not page.success:
        return "PRIMARY_FETCH_FAILED"
    text = (page.text or "").strip()
    if len(text) < sparse_text_chars:
        return "PRIMARY_CONTENT_SPARSE"
    lowered = text.lower()
    if any(marker in lowered for marker in SPA_SHELL_MARKERS):
        return "PRIMARY_SPA_SHELL"
    if not page.links and len(text) < sparse_text_chars * 2:
        return "PRIMARY_NO_LINKS"
    return None


class PlaywrightBrowserBackend:
    """Local browser renderer for round-2 escalation.

    This backend uses only local Playwright and Chromium. It does not log in,
    submit forms, purchase, send messages, or bypass access controls. Interaction
    is restricted to low-risk expandable controls matching contact/about/team/
    procurement-style research intent.
    """

    name = "playwright-local"

    def __init__(
        self,
        *,
        headless: bool = True,
        navigation_timeout_ms: int = 15_000,
        settle_ms: int = 500,
        scroll_steps: int = 3,
        click_budget: int = 6,
    ) -> None:
        if navigation_timeout_ms < 1_000:
            raise ValueError("navigation_timeout_ms must be >= 1000")
        if settle_ms < 0 or settle_ms > 10_000:
            raise ValueError("settle_ms must be between 0 and 10000")
        if scroll_steps < 0 or scroll_steps > 10:
            raise ValueError("scroll_steps must be between 0 and 10")
        if click_budget < 0 or click_budget > 20:
            raise ValueError("click_budget must be between 0 and 20")
        self.headless = bool(headless)
        self.navigation_timeout_ms = int(navigation_timeout_ms)
        self.settle_ms = int(settle_ms)
        self.scroll_steps = int(scroll_steps)
        self.click_budget = int(click_budget)
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._session_page_count = 0

    async def __aenter__(self) -> "PlaywrightBrowserBackend":
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Playwright is not installed. Install requirements-crawler.txt "
                "and run python -m playwright install chromium."
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            java_script_enabled=True,
            accept_downloads=False,
        )
        self._context.set_default_timeout(self.navigation_timeout_ms)
        self._session_page_count = 0
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = None
        self._browser = None
        self._playwright = None
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    @property
    def session_page_count(self) -> int:
        return self._session_page_count

    async def _ensure_started(self) -> bool:
        if self._context is not None:
            return False
        await self.__aenter__()
        return True

    async def _safe_expand(self, page: Any) -> list[str]:
        if self.click_budget <= 0:
            return []
        clicked: list[str] = []
        selectors = "button, [role='button'], summary, [aria-expanded='false']"
        locator = page.locator(selectors)
        try:
            count = min(await locator.count(), 80)
        except Exception:
            return clicked

        for index in range(count):
            if len(clicked) >= self.click_budget:
                break
            item = locator.nth(index)
            try:
                if not await item.is_visible():
                    continue
                label = (
                    (await item.inner_text(timeout=800))
                    or (await item.get_attribute("aria-label"))
                    or (await item.get_attribute("title"))
                    or ""
                )
                if not _safe_click_label(label):
                    continue
                await item.click(timeout=1_500)
                clicked.append(_normalize_label(label)[:120])
                if self.settle_ms:
                    await page.wait_for_timeout(min(self.settle_ms, 800))
            except Exception:
                continue
        return clicked

    async def _scroll(self, page: Any) -> None:
        if self.scroll_steps <= 0:
            return
        for step in range(1, self.scroll_steps + 1):
            fraction = step / self.scroll_steps
            try:
                await page.evaluate(
                    "(fraction) => window.scrollTo(0, Math.max(0, "
                    "(document.documentElement.scrollHeight - window.innerHeight) * fraction))",
                    fraction,
                )
                await page.wait_for_timeout(250)
            except Exception:
                return

    async def fetch(self, url: str) -> CrawlPage:
        owned_session = await self._ensure_started()
        assert self._context is not None
        page = await self._context.new_page()
        self._session_page_count += 1
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            if self.settle_ms:
                await page.wait_for_timeout(self.settle_ms)
            await self._safe_expand(page)
            await self._scroll(page)
            if self.settle_ms:
                await page.wait_for_timeout(min(self.settle_ms, 1_000))

            final_url = page.url or url
            body = page.locator("body")
            text = await body.inner_text(timeout=self.navigation_timeout_ms)

            rows = await page.locator("a[href]").evaluate_all(
                """els => els.slice(0, 500).map(a => ({
                    href: a.href || a.getAttribute('href') || '',
                    text: (a.innerText || a.textContent || a.getAttribute('aria-label') || '').trim()
                }))"""
            )
            links: list[str] = []
            hints: list[tuple[str, str]] = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                href = str(row.get("href") or "").strip()
                if not href:
                    continue
                absolute = urljoin(final_url, href)
                links.append(absolute)
                label = " ".join(str(row.get("text") or "").split())[:240]
                if label:
                    hints.append((absolute, label))

            status = getattr(response, "status", None)
            success = status is None or int(status) < 400
            return CrawlPage(
                url=final_url,
                text=text or "",
                links=tuple(dict.fromkeys(links)),
                link_hints=tuple(hints),
                success=success,
                error=None if success else f"http_status_{status}",
            )
        except Exception as exc:  # pragma: no cover - live-browser dependent
            return CrawlPage(
                url=page.url or url,
                text="",
                links=(),
                link_hints=(),
                success=False,
                error=f"playwright:{type(exc).__name__}:{exc}",
            )
        finally:
            await page.close()
            if owned_session:
                await self.__aexit__(None, None, None)


class EscalatingCrawlerBackend:
    """Use the normal crawler first and escalate sparse/blocked pages to browser."""

    name = "crawler-with-browser-escalation"

    def __init__(
        self,
        primary: AsyncPageBackend,
        browser: AsyncPageBackend,
        *,
        sparse_text_chars: int = 280,
    ) -> None:
        if sparse_text_chars < 50 or sparse_text_chars > 10_000:
            raise ValueError("sparse_text_chars must be between 50 and 10000")
        self.primary = primary
        self.browser = browser
        self.sparse_text_chars = int(sparse_text_chars)
        self._events: list[BrowserEscalationEvent] = []

    async def fetch(self, url: str) -> CrawlPage:
        primary_page = await self.primary.fetch(url)
        reason = _escalation_reason(primary_page, sparse_text_chars=self.sparse_text_chars)
        if reason is None:
            self._events.append(BrowserEscalationEvent(
                url=url,
                escalated=False,
                reason=None,
                selected_backend=getattr(self.primary, "name", type(self.primary).__name__),
                primary_success=primary_page.success,
                browser_success=None,
                primary_text_chars=len(primary_page.text or ""),
                browser_text_chars=None,
            ))
            return primary_page

        browser_page = await self.browser.fetch(url)
        if _quality_score(browser_page) > _quality_score(primary_page):
            selected = browser_page
            selected_name = getattr(self.browser, "name", type(self.browser).__name__)
        else:
            selected = primary_page
            selected_name = getattr(self.primary, "name", type(self.primary).__name__)

        self._events.append(BrowserEscalationEvent(
            url=url,
            escalated=True,
            reason=reason,
            selected_backend=selected_name,
            primary_success=primary_page.success,
            browser_success=browser_page.success,
            primary_text_chars=len(primary_page.text or ""),
            browser_text_chars=len(browser_page.text or ""),
        ))
        return selected

    def diagnostics(self) -> dict[str, Any]:
        return {
            "browser_escalation_count": sum(1 for event in self._events if event.escalated),
            "events": [event.__dict__.copy() for event in self._events],
        }


class ResilientCrawlerBackend:
    """Bound fetch latency and retry transient backend failures."""

    name = "resilient-crawler"

    def __init__(
        self,
        backend: AsyncPageBackend,
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 1,
        retry_delay_seconds: float = 0.15,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be in (0, 120]")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        if retry_delay_seconds < 0 or retry_delay_seconds > 10:
            raise ValueError("retry_delay_seconds must be between 0 and 10")
        self.backend = backend
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.retry_delay_seconds = float(retry_delay_seconds)
        self._attempts: list[dict[str, Any]] = []

    async def fetch(self, url: str) -> CrawlPage:
        last_page: CrawlPage | None = None
        for attempt in range(self.max_retries + 1):
            timed_out = False
            try:
                page = await asyncio.wait_for(
                    self.backend.fetch(url),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                timed_out = True
                page = CrawlPage(
                    url=url,
                    text="",
                    links=(),
                    link_hints=(),
                    success=False,
                    error=f"timeout_after_{self.timeout_seconds:g}s",
                )
            except Exception as exc:
                page = CrawlPage(
                    url=url,
                    text="",
                    links=(),
                    link_hints=(),
                    success=False,
                    error=f"backend_exception:{type(exc).__name__}:{exc}",
                )

            self._attempts.append({
                "url": url,
                "attempt": attempt + 1,
                "success": bool(page.success),
                "timed_out": timed_out,
                "error": page.error,
            })
            last_page = page
            if page.success:
                return page
            if attempt < self.max_retries and self.retry_delay_seconds:
                await asyncio.sleep(self.retry_delay_seconds)

        assert last_page is not None
        return last_page

    def diagnostics(self) -> dict[str, Any]:
        nested = getattr(self.backend, "diagnostics", None)
        return {
            "retry_attempts": list(self._attempts),
            "nested": nested() if callable(nested) else None,
        }
