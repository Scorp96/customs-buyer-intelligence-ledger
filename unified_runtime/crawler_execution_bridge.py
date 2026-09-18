from __future__ import annotations

import hashlib
import heapq
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit


EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])", re.I)
PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-/]{7,}\d)(?!\w)")
PHONE_CONTEXT_RE = re.compile(r"\b(?:phone|tel|telephone|mobile|cell|call|telefono|teléfono|telefone|celular|whatsapp)\b", re.I)

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

    def __init__(self) -> None:
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
        await self._crawler.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        crawler = self._crawler
        self._crawler = None
        if crawler is not None:
            await crawler.__aexit__(exc_type, exc, tb)

    async def fetch(self, url: str) -> CrawlPage:
        if self._crawler is None:
            async with self:
                return await self.fetch(url)

        try:
            result = await self._crawler.arun(url=url)
        except Exception as exc:  # pragma: no cover - exercised by live crawl
            return CrawlPage(url=url, text="", links=(), success=False, error=str(exc))

        success = bool(getattr(result, "success", True))
        error = getattr(result, "error_message", None) or getattr(result, "error", None)
        markdown = _markdown_text(getattr(result, "markdown", ""))
        links, link_hints = _result_link_data(getattr(result, "links", None), url)
        final_url = str(getattr(result, "url", None) or url)
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


def _route_candidates(page: CrawlPage) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for match in EMAIL_RE.finditer(page.text):
        email = _normalize_email(match.group(1))
        key = ("EMAIL", email)
        if email and key not in seen:
            seen.add(key)
            candidates.append({
                "kind": "EMAIL",
                "value": email,
                "source_url": page.url,
                "evidence_id": _evidence_id("EMAIL", email, page.url),
            })

    for match in PHONE_RE.finditer(page.text):
        raw_phone = match.group(1)
        phone = _normalize_phone(raw_phone)
        context_start = max(0, match.start() - 40)
        context_end = min(len(page.text), match.end() + 20)
        context = page.text[context_start:context_end]
        # A leading + is strong syntax evidence for an international number.
        # Local-looking digit groups require nearby phone/channel context so
        # dates, dimensions and order numbers are not promoted as routes.
        phone_context_ok = raw_phone.lstrip().startswith("+") or bool(PHONE_CONTEXT_RE.search(context))
        key = ("PHONE", phone)
        if phone and phone_context_ok and key not in seen:
            seen.add(key)
            candidates.append({
                "kind": "PHONE",
                "value": phone,
                "source_url": page.url,
                "evidence_id": _evidence_id("PHONE", phone, page.url),
            })

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
            })

    return candidates


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

        while queue and len(pages) < self.max_pages:
            neg_score, depth, url = heapq.heappop(queue)
            if url in visited:
                continue
            visited.add(url)

            page = await self.backend.fetch(url)
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
            for candidate in _route_candidates(page):
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

        is_contact_task = task_key == "task_id"
        if is_contact_task:
            result = "POSITIVE" if route_candidates else ("BLOCKED" if not pages else "NEGATIVE_EXHAUSTED")
        else:
            result = "POSITIVE" if pages else "BLOCKED"

        verified_route = bool(official_domain_verified and route_candidates)
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
            "failed_urls": failed_urls,
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
            receipt["backend_diagnostics"] = diagnostics()
        return receipt
