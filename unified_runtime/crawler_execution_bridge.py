from __future__ import annotations

import asyncio
import hashlib
import heapq
import re
import time
from html import unescape
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from .public_network_guard import is_public_http_url, validate_public_http_url


EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])", re.I)
PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-/]{7,}\d)(?!\w)")
PHONE_CONTEXT_RE = re.compile(r"\b(?:phone|tel|telephone|mobile|cell|call|telefono|teléfono|telefone|celular|whatsapp)\b", re.I)
MANIFEST_PHONE_CONTEXT_RE = re.compile(
    r"(?:COMM\s+Number\s+Qualifier\s*[:|]?\s*(?:TE|FX)|COMM\s+Number\s*[:|])",
    re.I,
)
MANIFEST_PARTY_FIELD_RE = re.compile(
    r"(?i)^(?:Consignee|Importer|Buyer|Notify\s+Party)\s+Name\s*(?::|\|)?\s*(.*)$"
)
MANIFEST_QUALIFIER_FIELD_RE = re.compile(
    r"(?i)^COMM\s+Number\s+Qualifier\s*(?::|\|)?\s*(.*)$"
)
MANIFEST_NUMBER_FIELD_RE = re.compile(
    r"(?i)^COMM\s+Number\s*(?::|\|)?\s*(.*)$"
)

# Round 1 intentionally stays deterministic and local. These terms only rank
# same-site links; they are not evidence by themselves.
LINK_PRIORITY_TERMS: dict[str, int] = {
    "contact": 30,
    "contacto": 30,
    "contato": 30,
    "contatos": 30,
    "contact-us": 30,
    "fale-conosco": 30,
    "whatsapp": 28,
    "telefono": 25,
    "telefone": 25,
    "phone": 25,
    "email": 25,
    "about": 9,
    "about-us": 9,
    "nosotros": 9,
    "empresa": 8,
    "company": 8,
    "team": 20,
    "equipo": 20,
    "equipe": 20,
    "management": 20,
    "leadership": 20,
    "staff": 9,
    "procurement": 28,
    "purchasing": 28,
    "sourcing": 28,
    "compras": 28,
    "importaciones": 28,
    "importacao": 28,
    "importação": 28,
    "suprimentos": 26,
    "products": 10,
    "product": 10,
    "productos": 10,
    "produtos": 10,
    "catalog": 7,
    "catalogo": 7,
    "catalogue": 7,
    "pvc": 5,
    "wpc": 5,
}

SKIP_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".zip", ".rar", ".7z", ".mp4", ".mp3", ".avi", ".mov",
}


@dataclass(frozen=True)
class CrawlPage:
    url: str
    text: str
    links: tuple[str, ...] = ()
    link_hints: tuple[tuple[str, str], ...] = ()
    success: bool = True
    error: str | None = None


class CrawlerBackend(Protocol):
    name: str

    async def fetch(self, url: str) -> CrawlPage:
        ...


class Crawl4AIBackend:
    """Thin, optional adapter over the self-hosted Crawl4AI Python package.

    No hosted API, key, credit, or external paid provider is used. Import is
    lazy so the CBI core and unit tests remain dependency-free unless crawling
    is explicitly enabled.
    """

    name = "crawl4ai-local"

    def __init__(
        self,
        *,
        public_network_only: bool = False,
        block_heavy_resources: bool = False,
    ) -> None:
        self.public_network_only = bool(public_network_only)
        self.block_heavy_resources = bool(block_heavy_resources)
        self._crawler: Any | None = None

    async def __aenter__(self) -> "Crawl4AIBackend":
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Crawl4AI is not installed. Install requirements-crawler.txt "
                "and run crawl4ai-setup before using the crawler bridge."
            ) from exc
        self._crawler = AsyncWebCrawler()

        if self.public_network_only:
            async def on_page_context_created(page: Any, context: Any, **kwargs: Any) -> Any:
                async def guard_route(route: Any, request: Any) -> None:
                    if self.block_heavy_resources and str(getattr(request, "resource_type", "")) in {
                        "image", "media", "font",
                    }:
                        await route.abort()
                        return
                    request_url = str(getattr(request, "url", "") or "")
                    scheme = urlsplit(request_url).scheme.lower()
                    if scheme in {"data", "blob", "about"}:
                        await route.continue_()
                        return
                    if scheme not in {"http", "https"}:
                        await route.abort()
                        return
                    allowed, _reason = await asyncio.to_thread(
                        is_public_http_url,
                        request_url,
                        resolve_dns=True,
                    )
                    if allowed:
                        await route.continue_()
                    else:
                        await route.abort()

                await page.route("**/*", guard_route)
                return page

            async def before_goto(page: Any, context: Any, url: str, **kwargs: Any) -> Any:
                await asyncio.to_thread(
                    validate_public_http_url,
                    url,
                    resolve_dns=True,
                )
                return page

            async def after_goto(
                page: Any,
                context: Any,
                url: str,
                response: Any,
                **kwargs: Any,
            ) -> Any:
                await asyncio.to_thread(
                    validate_public_http_url,
                    str(getattr(page, "url", "") or url),
                    resolve_dns=True,
                )
                return page

            self._crawler.crawler_strategy.set_hook(
                "on_page_context_created",
                on_page_context_created,
            )
            self._crawler.crawler_strategy.set_hook("before_goto", before_goto)
            self._crawler.crawler_strategy.set_hook("after_goto", after_goto)

        await self._crawler.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        crawler = self._crawler
        self._crawler = None
        if crawler is not None:
            await crawler.__aexit__(exc_type, exc, tb)

    async def fetch(self, url: str) -> CrawlPage:
        if self.public_network_only:
            try:
                await asyncio.to_thread(
                    validate_public_http_url,
                    url,
                    resolve_dns=True,
                )
            except ValueError as exc:
                return CrawlPage(
                    url=url,
                    text="",
                    links=(),
                    link_hints=(),
                    success=False,
                    error=f"public_network_guard:{exc}",
                )

        if self._crawler is None:
            async with self:
                return await self.fetch(url)

        try:
            result = await self._crawler.arun(url=url)
        except Exception as exc:  # pragma: no cover - exercised by live crawl
            return CrawlPage(url=url, text="", links=(), success=False, error=str(exc))

        success = bool(getattr(result, "success", True))
        error = getattr(result, "error_message", None) or getattr(result, "error", None)
        markdown = _combined_result_text(result)
        links, link_hints = _result_link_data(getattr(result, "links", None), url)
        final_url = str(getattr(result, "url", None) or url)
        if self.public_network_only:
            try:
                await asyncio.to_thread(
                    validate_public_http_url,
                    final_url,
                    resolve_dns=True,
                )
            except ValueError as exc:
                return CrawlPage(
                    url=final_url,
                    text="",
                    links=(),
                    link_hints=(),
                    success=False,
                    error=f"public_network_redirect_guard:{exc}",
                )
        return CrawlPage(
            url=final_url,
            text=markdown,
            links=tuple(links),
            link_hints=tuple(link_hints),
            success=success,
            error=str(error) if error else None,
        )


def _markdown_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for attr in ("raw_markdown", "fit_markdown", "markdown"):
        candidate = getattr(value, attr, None)
        if isinstance(candidate, str) and candidate:
            return candidate
    return str(value)


class _VisibleHTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "template"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "template"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(unescape(str(data or "")).split())
        if cleaned:
            self._parts.append(cleaned)

    def text(self) -> str:
        return "\n".join(self._parts)


def _html_visible_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = _VisibleHTMLTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return ""
    return parser.text()


def _combined_result_text(result: Any) -> str:
    """Preserve markdown and recover visible HTML omitted by markdown extraction."""
    candidates: list[str] = []
    markdown = _markdown_text(getattr(result, "markdown", ""))
    if markdown.strip():
        candidates.append(markdown.strip())

    structured_html_texts: list[str] = []
    for attr in ("cleaned_html", "fit_html"):
        html_text = _html_visible_text(getattr(result, attr, ""))
        if html_text.strip():
            structured_html_texts.append(html_text.strip())
            candidates.append(html_text.strip())

    if not structured_html_texts:
        raw_html_text = _html_visible_text(getattr(result, "html", ""))
        if raw_html_text.strip():
            candidates.append(raw_html_text.strip())

    unique: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(value)
    return "\n\n".join(unique)


def _result_link_data(value: Any, base_url: str) -> tuple[list[str], list[tuple[str, str]]]:
    if value is None:
        return [], []

    rows: list[Any] = []
    if isinstance(value, dict):
        for group in value.values():
            if isinstance(group, (list, tuple)):
                rows.extend(group)
    elif isinstance(value, (list, tuple)):
        rows.extend(value)

    links: list[str] = []
    hints: list[tuple[str, str]] = []
    for row in rows:
        href = ""
        label = ""
        if isinstance(row, str):
            href = row
        elif isinstance(row, dict):
            href = str(row.get("href") or row.get("url") or "")
            label = str(row.get("text") or row.get("title") or row.get("label") or "")
        else:
            href = str(getattr(row, "href", "") or getattr(row, "url", "") or "")
            label = str(
                getattr(row, "text", "")
                or getattr(row, "title", "")
                or getattr(row, "label", "")
                or ""
            )
        if href:
            absolute = urljoin(base_url, href)
            links.append(absolute)
            cleaned_label = " ".join(label.split())[:240]
            if cleaned_label:
                hints.append((absolute, cleaned_label))
    return list(dict.fromkeys(links)), hints


def _clean_url(url: str) -> str | None:
    try:
        split = urlsplit(str(url).strip())
    except ValueError:
        return None
    if split.scheme.lower() not in {"http", "https"} or not split.netloc:
        return None
    path_lower = split.path.lower()
    if any(path_lower.endswith(suffix) for suffix in SKIP_SUFFIXES):
        return None
    return urlunsplit((split.scheme.lower(), split.netloc.lower(), split.path or "/", split.query, ""))


def _same_site(candidate: str, root_host: str) -> bool:
    host = (urlsplit(candidate).hostname or "").lower()
    root = root_host.lower()
    return host == root or host.endswith("." + root) or root.endswith("." + host)


def _tokenize_goal_text(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9][a-zA-ZÀ-ÿ0-9_-]{1,}", str(value or "").lower())
        if len(token) >= 3
    }


def _task_goal_terms(task: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for key in ("query", "source_family", "route_target", "branch", "branch_group"):
        terms.update(_tokenize_goal_text(str(task.get(key) or "")))

    route_target = str(task.get("route_target") or "").upper()
    source_family = str(task.get("source_family") or "").lower()
    if route_target in {"COMPANY", "NAMED"} or "contact" in source_family:
        terms.update({
            "contact", "contacto", "contato", "whatsapp", "email", "phone",
            "team", "equipo", "equipe", "procurement", "purchasing",
            "sourcing", "compras", "importaciones", "suprimentos",
        })
    if "product" in source_family or "catalog" in source_family:
        terms.update({"product", "products", "producto", "productos", "produto", "produtos", "catalog", "catalogo"})
    return terms


def _score_link(
    url: str,
    source_family: str = "",
    *,
    label: str = "",
    goal_terms: set[str] | None = None,
) -> int:
    split = urlsplit(url)
    haystack = f"{split.path} {split.query} {label}".lower().replace("_", "-")
    score = 0
    for term, weight in LINK_PRIORITY_TERMS.items():
        if term in haystack:
            score += weight

    if goal_terms:
        haystack_tokens = _tokenize_goal_text(haystack)
        exact_overlap = haystack_tokens & goal_terms
        score += min(len(exact_overlap), 8) * 12
        # Partial multilingual/path overlap helps localized URLs without making
        # every task term a blanket score boost.
        for term in sorted(goal_terms):
            if len(term) >= 5 and term in haystack and term not in exact_overlap:
                score += 4

    depth = len([part for part in split.path.split("/") if part])
    score -= max(0, depth - 3)
    return score


def _normalize_email(value: str) -> str:
    return value.strip().strip(".,;:<>[](){}").lower()


def _normalize_phone(value: str) -> str:
    raw = value.strip().strip(".,;:")
    leading_plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 8 or len(digits) > 16:
        return ""
    return ("+" if leading_plus else "") + digits


def _whatsapp_phone(url: str) -> str:
    split = urlsplit(url)
    host = (split.hostname or "").lower()
    if host == "wa.me" or host.endswith(".wa.me"):
        candidate = split.path.strip("/").split("/", 1)[0]
        digits = "".join(ch for ch in candidate if ch.isdigit())
        return "+" + digits if 8 <= len(digits) <= 16 else ""
    if "whatsapp.com" in host:
        values = parse_qs(split.query).get("phone") or []
        if values:
            digits = "".join(ch for ch in values[0] if ch.isdigit())
            return "+" + digits if 8 <= len(digits) <= 16 else ""
    return ""


def _evidence_id(kind: str, value: str, url: str) -> str:
    raw = f"{kind}\n{value}\n{url}".encode("utf-8")
    return "CRAWL-EV-" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _aggregate_sha(pages: list[CrawlPage]) -> str:
    payload = "\n\n".join(
        f"{page.url}\n{page.text}" for page in sorted(pages, key=lambda item: item.url)
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_entity_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _target_name_matches(observed: str, expected: str) -> bool:
    left = _normalize_entity_name(observed)
    right = _normalize_entity_name(expected)
    return bool(left and right and (left in right or right in left))


def _page_host(page: CrawlPage) -> str:
    return (urlsplit(page.url).hostname or "").lower().removeprefix("www.")


def _email_domain(value: str) -> str:
    if "@" not in value:
        return ""
    return value.rsplit("@", 1)[-1].lower().removeprefix("www.")


def _manifest_lines(text: str) -> list[str]:
    rows: list[str] = []
    for raw in str(text or "").splitlines():
        cleaned = raw.strip().strip("|").strip()
        cleaned = re.sub(r"[*_`#>]", "", cleaned)
        cleaned = " ".join(cleaned.split())
        if cleaned:
            rows.append(cleaned)
    return rows


def _manifest_field_value(
    rows: list[str],
    index: int,
    field_pattern: re.Pattern[str],
) -> tuple[str | None, int]:
    match = field_pattern.match(rows[index])
    if not match:
        return None, index
    inline = str(match.group(1) or "").strip().strip("|").strip()
    if inline:
        return inline, index
    if index + 1 >= len(rows):
        return "", index
    next_row = rows[index + 1]
    if (
        MANIFEST_PARTY_FIELD_RE.match(next_row)
        or MANIFEST_QUALIFIER_FIELD_RE.match(next_row)
        or MANIFEST_NUMBER_FIELD_RE.match(next_row)
    ):
        return "", index
    return next_row, index + 1


def _task_company_name(task: dict[str, Any]) -> str:
    for key in ("company_name", "account_name", "legal_name", "buyer_name", "entity_name"):
        value = " ".join(str(task.get(key) or "").split())
        if value:
            return value
    query = str(task.get("query") or "")
    quoted = re.search(r'"([^"\r\n]{2,180})"', query)
    return " ".join(quoted.group(1).split()) if quoted else ""


def _manifest_route_candidates(page: CrawlPage, task: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = _task_company_name(task)
    rows = _manifest_lines(page.text)
    active_party = ""
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    index = 0
    while index < len(rows):
        party_value, party_index = _manifest_field_value(
            rows, index, MANIFEST_PARTY_FIELD_RE
        )
        if party_value is not None:
            active_party = " ".join(party_value.split())
            index = max(index, party_index) + 1
            continue

        qualifier_value, qualifier_index = _manifest_field_value(
            rows, index, MANIFEST_QUALIFIER_FIELD_RE
        )
        if qualifier_value is None:
            index += 1
            continue

        qualifier = qualifier_value.upper().strip()
        search_index = qualifier_index + 1
        raw_value = ""
        consumed_index = qualifier_index
        if search_index < len(rows):
            number_value, number_index = _manifest_field_value(
                rows, search_index, MANIFEST_NUMBER_FIELD_RE
            )
            if number_value is not None:
                raw_value = number_value.strip()
                consumed_index = max(consumed_index, number_index)

        target_associated = _target_name_matches(active_party, company_name)
        kind = ""
        value = ""
        if qualifier == "EM":
            email_match = EMAIL_RE.search(raw_value)
            if email_match:
                kind = "EMAIL"
                value = _normalize_email(email_match.group(1))
        elif qualifier in {"TE", "FX"}:
            kind = "PHONE"
            value = _normalize_phone(raw_value)

        key = (kind, value)
        if kind and value and key not in seen:
            seen.add(key)
            candidates.append({
                "kind": kind,
                "value": value,
                "source_url": page.url,
                "evidence_id": _evidence_id(kind, value, page.url),
                "candidate_owner_scope": (
                    "TARGET_ASSOCIATED" if target_associated else "UNVERIFIED"
                ),
                "current_company_association": bool(target_associated),
                "association_basis": [
                    "STRUCTURED_MANIFEST_PARTY",
                    f"PARTY_NAME={active_party}",
                    f"COMM_QUALIFIER={qualifier}",
                ],
            })
        index = max(index, consumed_index) + 1

    return candidates


def _route_candidates(page: CrawlPage, task: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    manifest_candidates = _manifest_route_candidates(page, task)
    manifest_by_key = {
        (row["kind"], row["value"]): row for row in manifest_candidates
    }

    for match in EMAIL_RE.finditer(page.text):
        email = _normalize_email(match.group(1))
        key = ("EMAIL", email)
        if not email or key in seen:
            continue
        seen.add(key)
        structured = manifest_by_key.get(key)
        if structured is not None:
            candidates.append(structured)
            continue
        source_site = _email_domain(email) == _page_host(page)
        candidates.append({
            "kind": "EMAIL",
            "value": email,
            "source_url": page.url,
            "evidence_id": _evidence_id("EMAIL", email, page.url),
            "candidate_owner_scope": "SOURCE_SITE" if source_site else "UNVERIFIED",
            "current_company_association": False,
            "association_basis": ["GENERIC_TEXT_ROUTE"],
        })

    for match in PHONE_RE.finditer(page.text):
        raw_phone = match.group(1)
        phone = _normalize_phone(raw_phone)
        context_start = max(0, match.start() - 80)
        context_end = min(len(page.text), match.end() + 40)
        context = page.text[context_start:context_end]
        phone_context_ok = (
            raw_phone.lstrip().startswith("+")
            or bool(PHONE_CONTEXT_RE.search(context))
            or bool(MANIFEST_PHONE_CONTEXT_RE.search(context))
        )
        key = ("PHONE", phone)
        if phone and phone_context_ok and key not in seen:
            seen.add(key)
            structured = manifest_by_key.get(key)
            if structured is not None:
                candidates.append(structured)
            else:
                candidates.append({
                    "kind": "PHONE",
                    "value": phone,
                    "source_url": page.url,
                    "evidence_id": _evidence_id("PHONE", phone, page.url),
                    "candidate_owner_scope": "UNVERIFIED",
                    "current_company_association": False,
                    "association_basis": ["GENERIC_TEXT_ROUTE"],
                })

    for structured in manifest_candidates:
        key = (structured["kind"], structured["value"])
        if key not in seen:
            seen.add(key)
            candidates.append(structured)

    for link in page.links:
        phone = _whatsapp_phone(link)
        key = ("WHATSAPP", phone)
        if phone and key not in seen:
            seen.add(key)
            candidates.append({
                "kind": "WHATSAPP",
                "value": phone,
                "source_url": page.url,
                "channel_url": link,
                "evidence_id": _evidence_id("WHATSAPP", phone, page.url),
                "candidate_owner_scope": "SOURCE_SITE",
                "current_company_association": False,
                "association_basis": ["PUBLIC_WHATSAPP_LINK"],
            })

    return candidates


def _source_throttle_failure(row: dict[str, str]) -> bool:
    error = str(row.get("error") or "").lower()
    return (
        error.startswith("source_throttled:")
        or "http_status_429" in error
        or "too many requests" in error
        or "rate limit" in error
    )


def _source_access_blocked_failure(row: dict[str, str]) -> bool:
    error = str(row.get("error") or "").lower()
    return bool(error) and (
        "anti-bot protection" in error
        or "http_status_403" in error
        or "http 403" in error
        or "status code 403" in error
        or "forbidden" in error
        or "access denied" in error
    )


def _redirect_target_blocked_failure(row: dict[str, str]) -> bool:
    error = str(row.get("error") or "").lower()
    return bool(error) and (
        "redirect_guard" in error
        or "redirect target" in error
        or "private destination" in error
        or "non-public destination" in error
    )


def _source_unavailable_failure(row: dict[str, str]) -> bool:
    error = str(row.get("error") or "").lower()
    return bool(error) and (
        error.startswith("timeout_after_")
        or error.startswith("backend_exception:")
        or error.startswith("playwright:")
        or error.startswith("http_status_5")
        or "connection reset" in error
        or "connection refused" in error
        or "temporarily unavailable" in error
    )


def _sanitize_crawl_error(error: Any) -> str:
    """Return a stable public error class without backend internals."""
    raw = " ".join(str(error or "").split())
    lowered = raw.lower()
    if not raw:
        return "CRAWL_FAILED"
    if lowered.startswith("execution_budget_exceeded_after_"):
        return raw.split()[0]
    if (
        "redirect_guard" in lowered
        or "redirect target" in lowered
        or "private destination" in lowered
        or "non-public destination" in lowered
    ):
        return "REDIRECT_TARGET_BLOCKED"
    if "http_status_403" in lowered or "http 403" in lowered or "status code 403" in lowered:
        return "HTTP 403"
    if "http_status_429" in lowered or "http 429" in lowered or "too many requests" in lowered:
        return "HTTP 429"
    if "http_status_5" in lowered:
        return "HTTP 5XX"
    if lowered.startswith("timeout_after_") or "timed out" in lowered:
        return "TIMEOUT"
    if lowered.startswith("source_throttled:") or "rate limit" in lowered:
        return "SOURCE_THROTTLED"
    if "anti-bot protection" in lowered or "access denied" in lowered or "forbidden" in lowered:
        return "SOURCE_ACCESS_BLOCKED"
    return "SOURCE_UNAVAILABLE"


def _sanitize_diagnostics(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_diagnostics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_diagnostics(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_diagnostics(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in ("traceback", "site-packages", "code context", "runner.py")):
            return "REDACTED_INTERNAL_ERROR"
    return value


def _fallback_subject(task: dict[str, Any], seed_url: str) -> str:
    for key in ("company_name", "account_name", "legal_name", "buyer_name", "entity_name"):
        value = " ".join(str(task.get(key) or "").split())
        if value:
            return value[:180]
    parsed = urlsplit(seed_url)
    slug = parsed.path.strip("/").split("/", 1)[0]
    if slug:
        return slug.replace("-", " ").replace("_", " ")[:180]
    return (parsed.hostname or seed_url)[:180]


def _fallback_search_plan(
    task: dict[str, Any],
    seed_url: str,
    *,
    reason: str = "SOURCE_THROTTLED",
) -> dict[str, Any]:
    subject = _fallback_subject(task, seed_url)
    parsed = urlsplit(seed_url)
    slug = parsed.path.strip("/").split("/", 1)[0]
    host = (parsed.hostname or "").lower()
    queries = [
        f'"{subject}" email',
        f'"{subject}" phone whatsapp',
        f'"{subject}" contact',
    ]
    if slug and (host == "facebook.com" or host.endswith(".facebook.com")):
        facebook_pivot = slug
    else:
        facebook_pivot = subject
    if facebook_pivot:
        queries.append(f'site:facebook.com "{facebook_pivot}"')
    return {
        "reason": reason,
        "host_action": "WEB_SEARCH_AND_PUBLIC_SOURCE_FALLBACK",
        "subject": subject,
        "queries": queries,
        "source_families": [
            "SEARCH_INDEX",
            "OFFICIAL_WEBSITE",
            "PUBLIC_DIRECTORY",
            "INSTAGRAM",
            "LINKEDIN",
            "PUBLIC_SOCIAL_MIRROR",
        ],
        "contact_conclusion_if_unresolved": "NOT_VERIFIED",
        "instructions": (
            "Do not conclude that an email/phone does not exist. Use host web search and public "
            "fallback sources, then feed discovered public URLs back into execute_public_crawl."
        ),
    }


class CrawlExecutionBridge:
    """Execute an existing v6.3 source/contact task against one verified site.

    Round 1 deliberately does not perform search-engine discovery. A host or the
    existing CBI planner supplies the task and a seed URL. The bridge follows
    only same-site links, prioritizes contact/about/team/product paths, and
    returns receipt-shaped output compatible with the current CBI evidence flow.
    """

    def __init__(self, backend: CrawlerBackend, *, max_pages: int = 8) -> None:
        if max_pages < 1 or max_pages > 50:
            raise ValueError("max_pages must be between 1 and 50")
        self.backend = backend
        self.max_pages = int(max_pages)

    async def execute(
        self,
        task: dict[str, Any],
        *,
        seed_url: str,
        official_domain_verified: bool = False,
        max_elapsed_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("task must be an object")
        cleaned_seed = _clean_url(seed_url)
        if not cleaned_seed:
            raise ValueError("seed_url must be an absolute http(s) URL")

        task_key = "task_id" if task.get("task_id") else "call_id"
        task_id = str(task.get(task_key) or "").strip()
        if not task_id:
            raise ValueError("task must contain task_id or call_id")

        root_host = (urlsplit(cleaned_seed).hostname or "").lower()
        queue: list[tuple[int, int, str]] = [(0, 0, cleaned_seed)]
        enqueued: set[str] = {cleaned_seed}
        visited: set[str] = set()
        pages: list[CrawlPage] = []
        failed_urls: list[dict[str, str]] = []
        source_family = str(task.get("source_family") or "")
        goal_terms = _task_goal_terms(task)
        is_contact_task = task_key == "task_id"

        if max_elapsed_seconds is not None:
            max_elapsed_seconds = float(max_elapsed_seconds)
            if max_elapsed_seconds <= 0 or max_elapsed_seconds > 300:
                raise ValueError("max_elapsed_seconds must be in (0, 300]")
            deadline = time.monotonic() + max_elapsed_seconds
        else:
            deadline = None
        execution_budget_exhausted = False

        while queue and len(pages) < self.max_pages:
            neg_score, depth, url = heapq.heappop(queue)
            if url in visited:
                continue
            visited.add(url)

            remaining_seconds: float | None = None
            if deadline is not None:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    execution_budget_exhausted = True
                    failed_urls.append({
                        "url": url,
                        "error": f"execution_budget_exceeded_after_{max_elapsed_seconds:g}s",
                    })
                    break

            try:
                if remaining_seconds is None:
                    page = await self.backend.fetch(url)
                else:
                    page = await asyncio.wait_for(
                        self.backend.fetch(url),
                        timeout=remaining_seconds,
                    )
            except asyncio.TimeoutError:
                execution_budget_exhausted = True
                failed_urls.append({
                    "url": url,
                    "error": f"execution_budget_exceeded_after_{max_elapsed_seconds:g}s",
                })
                break

            # Some third-party crawler stacks delay or suppress cancellation.
            # Detect that overrun after control returns so an over-budget
            # contact crawl can never be mistaken for complete exhaustion.
            if deadline is not None and time.monotonic() >= deadline:
                execution_budget_exhausted = True
                failed_urls.append({
                    "url": url,
                    "error": f"execution_budget_exceeded_after_{max_elapsed_seconds:g}s",
                })

            if not page.success:
                failed_urls.append({"url": url, "error": page.error or "crawl_failed"})
                continue

            canonical = _clean_url(page.url) or url
            page = CrawlPage(
                url=canonical,
                text=page.text or "",
                links=tuple(page.links or ()),
                link_hints=tuple(page.link_hints or ()),
                success=True,
                error=None,
            )
            pages.append(page)

            ranked: list[tuple[int, str]] = []
            hint_by_url: dict[str, str] = {}
            for hint_url, hint_label in page.link_hints:
                cleaned_hint_url = _clean_url(hint_url)
                if cleaned_hint_url and hint_label:
                    hint_by_url.setdefault(cleaned_hint_url, hint_label)

            for raw_link in page.links:
                candidate = _clean_url(raw_link)
                if not candidate or candidate in visited or candidate in enqueued:
                    continue
                if not _same_site(candidate, root_host):
                    continue
                ranked.append((
                    _score_link(
                        candidate,
                        source_family,
                        label=hint_by_url.get(candidate, ""),
                        goal_terms=goal_terms,
                    ),
                    candidate,
                ))

            # High-value links first, but retain a small exploration tail so an
            # unusual localized contact path can still be reached.
            ranked.sort(key=lambda item: (-item[0], item[1]))
            for score, candidate in ranked[:24]:
                enqueued.add(candidate)
                heapq.heappush(queue, (-score, depth + 1, candidate))

        route_candidates: list[dict[str, Any]] = []
        seen_routes: set[tuple[str, str]] = set()
        for page in pages:
            for candidate in _route_candidates(page, task):
                key = (candidate["kind"], candidate["value"])
                if key not in seen_routes:
                    seen_routes.add(key)
                    route_candidates.append(candidate)

        evidence_ids = sorted({
            _evidence_id("PAGE", hashlib.sha256(page.text.encode("utf-8")).hexdigest(), page.url)
            for page in pages
        })
        route_evidence_ids = sorted({row["evidence_id"] for row in route_candidates})
        evidence_ids = sorted(set(evidence_ids) | set(route_evidence_ids))

        # A failed fetch is completion-blocking only when this task has not
        # already obtained the evidence that makes the task positive. This
        # prevents partial crawls from becoming false NEGATIVE_EXHAUSTED while
        # allowing a positive contact/page result to remain positive even if an
        # unrelated trailing link later fails.
        positive_evidence = bool(route_candidates) if is_contact_task else bool(pages)
        failure_relevant = bool(failed_urls) and not positive_evidence
        source_throttled = (
            failure_relevant
            and not execution_budget_exhausted
            and any(_source_throttle_failure(row) for row in failed_urls)
        )
        source_access_blocked = (
            failure_relevant
            and not execution_budget_exhausted
            and not source_throttled
            and not any(_redirect_target_blocked_failure(row) for row in failed_urls)
            and any(_source_access_blocked_failure(row) for row in failed_urls)
        )
        redirect_target_blocked = (
            failure_relevant
            and not execution_budget_exhausted
            and any(_redirect_target_blocked_failure(row) for row in failed_urls)
        )
        # Budget exhaustion takes precedence over a late lower-level response:
        # once the bounded request window has been exceeded, the source was not
        # available in time for this synchronous MCP execution.
        source_unavailable = (
            failure_relevant
            and (
                execution_budget_exhausted
                or (
                    not source_throttled
                    and not source_access_blocked
                    and not redirect_target_blocked
                )
            )
        )
        source_blocked = source_throttled or source_access_blocked or redirect_target_blocked or source_unavailable
        source_status = (
            "SOURCE_THROTTLED"
            if source_throttled
            else (
                "REDIRECT_TARGET_BLOCKED"
                if redirect_target_blocked
                else (
                    "SOURCE_ACCESS_BLOCKED"
                    if source_access_blocked
                    else ("SOURCE_UNAVAILABLE" if source_unavailable else "OK")
                )
            )
        )

        if is_contact_task:
            if route_candidates:
                result = "POSITIVE"
            elif source_blocked:
                result = "BLOCKED"
            else:
                result = "BLOCKED" if not pages else "NEGATIVE_EXHAUSTED"
        else:
            result = "POSITIVE" if pages else "BLOCKED"

        verified_route = bool(official_domain_verified and route_candidates)
        fallback_plan = (
            _fallback_search_plan(task, cleaned_seed, reason=source_status)
            if source_blocked
            else None
        )
        receipt: dict[str, Any] = {
            task_key: task_id,
            "result": result,
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "raw_result_locator": cleaned_seed,
            "content_sha256": _aggregate_sha(pages),
            "evidence_ids": evidence_ids,
            "route_evidence_ids": route_evidence_ids,
            "route_candidates": route_candidates,
            "source_urls": [page.url for page in pages],
            "pages_crawled": len(pages),
            "failed_urls": [
                {
                    "url": str(row.get("url") or ""),
                    "error": _sanitize_crawl_error(row.get("error")),
                }
                for row in failed_urls
            ],
            "source_status": source_status,
            "execution_budget_seconds": max_elapsed_seconds,
            "execution_budget_exhausted": execution_budget_exhausted,
            "retryable": bool(source_throttled or source_access_blocked or source_unavailable),
            "fallback_required": bool(source_blocked),
            "fallback_search_plan": fallback_plan,
            "negative_contact_conclusion_allowed": not source_blocked,
            "crawler_backend": getattr(self.backend, "name", type(self.backend).__name__),
            "search_execution_performed": True,
            "planning_is_execution_proof": False,
            "official_domain_verified": bool(official_domain_verified),
            "verified": verified_route,
            "guessed": False,
            "owner_scope": "ACCOUNT" if verified_route else "UNVERIFIED",
            "current_company_association": False,
            "goal_terms": sorted(goal_terms),
        }
        diagnostics = getattr(self.backend, "diagnostics", None)
        if callable(diagnostics):
            receipt["backend_diagnostics"] = _sanitize_diagnostics(diagnostics())
        return receipt
