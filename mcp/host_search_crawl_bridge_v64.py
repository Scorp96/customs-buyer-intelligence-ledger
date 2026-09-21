from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from mcp.crawler_tool_v64 import execute_public_crawl_handler, validate_public_seed_url


TOOL_NAME = "execute_host_search_crawl_bridge"
SCHEMA = "cbi.host-search-crawl-bridge.v6.4"
_MAX_SEARCH_RESULTS = 20
_MAX_CRAWL_SEEDS = 2
_MAX_PAGES_PER_SEED = 4

_DIRECTORY_HOST_HINTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "yellowpages",
    "yelp.",
    "findglocal.",
    "kompass.",
)
_SOURCE_PATH_HINTS: dict[str, tuple[str, ...]] = {
    "official_contact": ("contact", "contact-us", "about", "team", "company"),
    "official_about_footer_mobile": ("about", "contact", "company", "team"),
    "official_home": ("", "home"),
    "official_products": ("product", "products", "catalog", "solution"),
    "official_catalog": ("catalog", "download", "product"),
    "catalog_pdf": ("catalog", ".pdf", "download"),
    "public_social": ("facebook", "instagram", "linkedin"),
    "linkedin_company": ("linkedin.com/company",),
    "linkedin_people": ("linkedin.com/in",),
    "facebook": ("facebook.com",),
    "instagram_x_youtube": ("instagram.com", "youtube.com", "x.com"),
    "google_maps_business": ("google.", "maps"),
}
_CONTACT_MODULES = {"contact_coverage", "buying_group"}
_CLAIM_TYPE_BY_MODULE = {
    "customs_integrity": "CUSTOMS",
    "buyer_entity_resolution": "IDENTITY",
    "ultimate_buyer_resolution": "IDENTITY",
    "product_identity_boundary": "PRODUCT",
    "company_profile": "BUSINESS_PROFILE",
    "trade_supplier_continuity": "TRADE",
    "buying_group": "AUTHORITY",
    "contact_coverage": "CONTACT",
    "evidence_conflict_resolution": "FACT",
    "history_and_account_lock": "FACT",
    "sales_crm_outreach_readiness": "FACT",
}
_CLAIM_KEY_BY_MODULE = {
    "customs_integrity": "trade.import_activity",
    "buyer_entity_resolution": "identity.legal_entity",
    "ultimate_buyer_resolution": "identity.ultimate_buyer",
    "product_identity_boundary": "product.fit",
    "company_profile": "company.operating_status",
    "trade_supplier_continuity": "trade.import_activity",
    "buying_group": "buying_group.decision_chain",
    "contact_coverage": "contact.company_route",
    "evidence_conflict_resolution": "company.operating_status",
    "history_and_account_lock": "identity.legal_entity",
    "sales_crm_outreach_readiness": "outreach.route_safety",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalized_words(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", str(value or "").casefold())
        if token not in {"https", "http", "www", "com", "the", "and", "for"}
    }


def _task_identity(task: dict[str, Any]) -> str:
    for key in ("work_item_id", "call_id", "task_id", "objective_id"):
        value = str(task.get(key) or "").strip()
        if value:
            return value
    raise ValueError("task must contain work_item_id, call_id, task_id, or objective_id")


def _require_task(arguments: dict[str, Any]) -> dict[str, Any]:
    task = arguments.get("task")
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    _task_identity(task)
    for key in ("owner_type", "owner_id", "module_or_branch", "source_family", "query"):
        if not str(task.get(key) or "").strip():
            raise ValueError(f"task.{key} is required")
    owner_type = str(task.get("owner_type") or "").upper()
    if owner_type not in {"ACCOUNT", "PEER"}:
        raise ValueError("task.owner_type must be ACCOUNT or PEER")
    return dict(task)


def _score_candidate(task: dict[str, Any], row: dict[str, Any], url: str, index: int) -> int:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").casefold()
    source_family = str(task.get("source_family") or "").casefold()
    score = 100 - min(index, 50)
    if parsed.scheme == "https":
        score += 3

    task_words = _normalized_words(task.get("query"))
    row_words = _normalized_words(
        " ".join(
            str(row.get(key) or "")
            for key in ("title", "snippet", "display_url")
        )
    )
    score += min(30, 5 * len(task_words & row_words))

    for hint in _SOURCE_PATH_HINTS.get(source_family, ()):
        if hint and (hint in host or hint in path):
            score += 20
        elif not hint and path in {"", "/"}:
            score += 8

    if source_family.startswith("official_") or source_family in {"catalog_pdf", "official_site"}:
        if any(hint in host for hint in _DIRECTORY_HOST_HINTS):
            score -= 35
        if path in {"", "/"}:
            score += 10

    if source_family in {"facebook", "public_social"} and "facebook.com" in host:
        score += 30
    if source_family in {"instagram_x_youtube", "public_social"} and any(
        name in host for name in ("instagram.com", "youtube.com", "x.com")
    ):
        score += 25
    if source_family.startswith("linkedin") and "linkedin.com" in host:
        score += 30

    return score


def rank_host_search_results(
    task: dict[str, Any],
    search_results: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(search_results, list):
        raise ValueError("search_results must be an array")
    if not 1 <= len(search_results) <= _MAX_SEARCH_RESULTS:
        raise ValueError(f"search_results must contain 1-{_MAX_SEARCH_RESULTS} rows")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(search_results):
        if not isinstance(raw, dict):
            rejected.append({"index": index, "url": "", "reason": "RESULT_NOT_OBJECT"})
            continue
        raw_url = str(raw.get("url") or "").strip()
        if not raw_url:
            rejected.append({"index": index, "url": "", "reason": "URL_MISSING"})
            continue
        try:
            url = validate_public_seed_url(raw_url)
        except ValueError as exc:
            rejected.append({
                "index": index,
                "url": raw_url[:500],
                "reason": "PUBLIC_URL_REJECTED",
                "detail": str(exc)[:240],
            })
            continue
        dedupe_key = url.casefold()
        if dedupe_key in seen:
            rejected.append({"index": index, "url": url, "reason": "DUPLICATE_URL"})
            continue
        seen.add(dedupe_key)
        accepted.append({
            "index": index,
            "url": url,
            "title": str(raw.get("title") or "")[:500],
            "snippet": str(raw.get("snippet") or "")[:1200],
            "score": _score_candidate(task, raw, url, index),
        })

    accepted.sort(key=lambda row: (-int(row["score"]), int(row["index"]), str(row["url"])))
    return {
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }


def _crawler_task(task: dict[str, Any], bridge_identity: str) -> dict[str, Any]:
    normalized = dict(task)
    normalized.pop("work_item_id", None)
    normalized.pop("objective_id", None)
    if str(task.get("module_or_branch") or "") in _CONTACT_MODULES:
        normalized["task_id"] = bridge_identity
        normalized.pop("call_id", None)
    else:
        normalized["call_id"] = bridge_identity
        normalized.pop("task_id", None)
    return normalized


def _positive_evidence(
    *,
    task: dict[str, Any],
    receipt: dict[str, Any],
    seed_url: str,
    index: int,
) -> dict[str, Any] | None:
    content_sha = str(receipt.get("content_sha256") or "").lower()
    completed_at = str(receipt.get("completed_at") or "")
    if not _SHA256_RE.fullmatch(content_sha) or not completed_at:
        return None
    evidence_id = "EVD-HSC-" + _digest({
        "task": _task_identity(task),
        "seed_url": seed_url,
        "content_sha256": content_sha,
        "index": index,
    })[:20].upper()
    module = str(task.get("module_or_branch") or "")
    return {
        "evidence_id": evidence_id,
        "owner_type": str(task.get("owner_type") or "").upper(),
        "owner_id": str(task.get("owner_id") or ""),
        "claim_key": str(task.get("claim_key") or _CLAIM_KEY_BY_MODULE.get(module, module)),
        "module_or_branch": module,
        "source_type": str(task.get("source_family") or ""),
        "source_family": str(task.get("source_family") or ""),
        "reference_type": "PUBLIC_URL",
        "url": seed_url,
        "locator": seed_url,
        "observed_at": completed_at,
        "content_sha256": content_sha,
        "snapshot_locator": seed_url,
        "claim_type": _CLAIM_TYPE_BY_MODULE.get(module, "FACT"),
        "freshness": "CURRENT",
        "evidence_grade": "C2",
        "boundary": (
            "Self-hosted public crawler confirmed page content reachable from this public URL only. "
            "This bridge does not prove Account ownership of the domain, route ownership, named-person authority, "
            "or procurement intent without separate corroboration."
        ),
        "conflict": None,
        "commercial_gate_tags": [],
    }


def _append_ready_payload(
    *,
    investigation_id: str,
    task: dict[str, Any],
    receipts: list[dict[str, Any]],
    attempted_urls: list[str],
    started_at: str,
) -> dict[str, Any] | None:
    if not attempted_urls or not receipts:
        return None

    positive_rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, (url, receipt) in enumerate(zip(attempted_urls, receipts)):
        if str(receipt.get("result") or "").upper() != "POSITIVE":
            continue
        evidence = _positive_evidence(task=task, receipt=receipt, seed_url=url, index=index)
        if evidence is not None:
            positive_rows.append((index, receipt, evidence))

    if positive_rows:
        result = "POSITIVE"
        evidence = [row[2] for row in positive_rows]
        blocked_reason = ""
    else:
        evidence = []
        crawler_results = {str(row.get("result") or "").upper() for row in receipts}
        # One or two crawled URLs cannot prove source-family exhaustion. Preserve
        # the distinction between a real negative observation and access failure.
        if "NEGATIVE_EXHAUSTED" in crawler_results:
            result = "NEGATIVE"
            blocked_reason = ""
        else:
            result = "BLOCKED"
            statuses = sorted({
                str(row.get("source_status") or row.get("status") or "CRAWL_INCOMPLETE")
                for row in receipts
            })
            blocked_reason = "HOST_SEARCH_CRAWL_INCOMPLETE:" + ",".join(statuses)

    completed_at = max(
        (str(row.get("completed_at") or "") for row in receipts if str(row.get("completed_at") or "")),
        default=_now(),
    )
    aggregate_sha = _digest({
        "task": _task_identity(task),
        "urls": attempted_urls,
        "receipts": [
            {
                "result": row.get("result"),
                "source_status": row.get("source_status"),
                "content_sha256": row.get("content_sha256"),
                "source_urls": row.get("source_urls"),
            }
            for row in receipts
        ],
    })
    identity_material = {
        "investigation_id": investigation_id,
        "work_item_id": _task_identity(task),
        "query": task.get("query"),
        "source_family": task.get("source_family"),
        "attempted_urls": attempted_urls,
        "aggregate_sha": aggregate_sha,
    }
    attempt_id = "ATTEMPT-HSC-" + _digest(identity_material)[:20].upper()
    execution_id = "EXEC-HSC-" + _digest({"attempt": identity_material})[:20].upper()
    evidence_ids = [row["evidence_id"] for row in evidence]

    pivots_consumed: list[dict[str, Any]] = []
    pivot_id = str(task.get("pivot_id") or "").strip()
    pivot_value = str(task.get("pivot_value") or "").strip()
    if pivot_id and result != "BLOCKED" and (not pivot_value or pivot_value.casefold() in str(task.get("query") or "").casefold()):
        pivots_consumed.append({
            "pivot_id": pivot_id,
            "consumption_result": f"HOST_SEARCH_CRAWL_{result}",
        })

    return {
        "investigation_id": investigation_id,
        "attempt": {
            "attempt_id": attempt_id,
            "investigation_id": investigation_id,
            "owner_type": str(task.get("owner_type") or "").upper(),
            "owner_id": str(task.get("owner_id") or ""),
            "module_or_branch": str(task.get("module_or_branch") or ""),
            "source_family": str(task.get("source_family") or ""),
            "query": str(task.get("query") or ""),
            "started_at": started_at,
            "completed_at": completed_at,
            "checked_at": completed_at,
            "tool_or_operator": TOOL_NAME,
            "execution_id": execution_id,
            "result": result,
            "result_count": len(evidence) if result == "POSITIVE" else 0,
            "raw_result_locator": attempted_urls[0],
            "content_sha256": aggregate_sha,
            "evidence_ids": evidence_ids,
            "pivots_generated": [],
            "blocked_reason": blocked_reason,
            "discovered_peer_ids": [],
            "relationship_evidence_ids": {},
        },
        "evidence": evidence,
        "pivots": [],
        "pivots_consumed": pivots_consumed,
        "manual_visual_items_resolved": [],
    }


def execute_host_search_crawl_bridge_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    if not investigation_id:
        raise ValueError("investigation_id is required")
    task = _require_task(arguments)

    host_search = arguments.get("host_search")
    if not isinstance(host_search, dict):
        raise ValueError("host_search must be an object")
    host_query = str(host_search.get("query") or "").strip()
    searched_at = str(host_search.get("searched_at") or "").strip()
    if not host_query or not searched_at:
        raise ValueError("host_search.query and host_search.searched_at are required")

    ranked = rank_host_search_results(task, arguments.get("search_results"))
    max_seeds = arguments.get("max_crawl_seeds", 1)
    if isinstance(max_seeds, bool) or not isinstance(max_seeds, int) or not 1 <= max_seeds <= _MAX_CRAWL_SEEDS:
        raise ValueError(f"max_crawl_seeds must be an integer from 1 to {_MAX_CRAWL_SEEDS}")
    max_pages = arguments.get("max_pages_per_seed", 3)
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= _MAX_PAGES_PER_SEED:
        raise ValueError(f"max_pages_per_seed must be an integer from 1 to {_MAX_PAGES_PER_SEED}")

    bridge_identity = _task_identity(task)
    started_at = _now()
    receipts: list[dict[str, Any]] = []
    attempted_urls: list[str] = []
    selected = ranked["accepted"][:max_seeds]
    crawler_task = _crawler_task(task, bridge_identity)

    for candidate in selected:
        url = str(candidate["url"])
        attempted_urls.append(url)
        receipt = execute_public_crawl_handler({
            "task": crawler_task,
            "seed_url": url,
            "max_pages": max_pages,
            "browser_escalation": arguments.get("browser_escalation", True) is not False,
            "timeout_seconds": float(arguments.get("timeout_seconds", 6.0)),
            "max_retries": int(arguments.get("max_retries", 0)),
        })
        receipts.append(receipt)
        if str(receipt.get("result") or "").upper() == "POSITIVE":
            break

    append_payload = _append_ready_payload(
        investigation_id=investigation_id,
        task=task,
        receipts=receipts,
        attempted_urls=attempted_urls,
        started_at=started_at,
    )
    append_ready = append_payload is not None
    final_result = (
        str((append_payload or {}).get("attempt", {}).get("result") or "")
        if append_ready
        else "NO_VALID_PUBLIC_URLS"
    )

    return {
        "schema": SCHEMA,
        "status": "BRIDGE_EXECUTED" if append_ready else "NO_VALID_PUBLIC_URLS",
        "investigation_id": investigation_id,
        "planned_work_item_id": bridge_identity,
        "planned_query": str(task.get("query") or ""),
        "host_search_query": host_query,
        "host_search_searched_at": searched_at,
        "host_search_results_supplied": True,
        "host_search_result_count": len(arguments.get("search_results") or []),
        "server_performed_web_search": False,
        "crawler_execution_performed": bool(receipts),
        "planning_is_execution_proof": False,
        "search_result_ranking": ranked,
        "attempted_urls": attempted_urls,
        "crawl_receipts": receipts,
        "continuation_candidates": [
            row["url"] for row in ranked["accepted"] if row["url"] not in attempted_urls
        ],
        "final_result": final_result,
        "negative_exhaustion_proven": False,
        "source_coverage_terminal": final_result == "POSITIVE",
        "append_ready": append_ready,
        "append_tool": "append_execution_receipt" if append_ready else None,
        "append_execution_receipt_payload": append_payload,
        "durable_mutation_performed": False,
        "route_ownership_promoted": False,
    }


def tool_descriptor() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Bridge host-supplied public web search results into bounded self-hosted Crawl4AI execution for one existing "
            "CBI planned public-source work item. The server does not perform the web search itself. It validates and "
            "deduplicates public URLs, ranks source-family-relevant candidates, crawls at most two seeds, and returns an "
            "append_execution_receipt-ready payload without mutating Runtime. Unknown/blocked results never become "
            "NEGATIVE_EXHAUSTED and route ownership is never promoted by this bridge."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["investigation_id", "task", "host_search", "search_results"],
            "properties": {
                "investigation_id": {"type": "string", "minLength": 1},
                "task": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "One existing plan_public_source_calls work item or equivalent planned source task.",
                },
                "host_search": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query", "searched_at"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "searched_at": {"type": "string", "minLength": 1},
                    },
                },
                "search_results": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_SEARCH_RESULTS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["url"],
                        "properties": {
                            "url": {"type": "string", "minLength": 8},
                            "title": {"type": "string"},
                            "snippet": {"type": "string"},
                            "display_url": {"type": "string"},
                        },
                    },
                },
                "max_crawl_seeds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_CRAWL_SEEDS,
                    "default": 1,
                },
                "max_pages_per_seed": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_PAGES_PER_SEED,
                    "default": 3,
                },
                "browser_escalation": {"type": "boolean", "default": True},
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 2,
                    "maximum": 15,
                    "default": 6,
                },
                "max_retries": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0,
                },
            },
        },
        "outputSchema": {"type": "object", "additionalProperties": True},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    }


def install_remote_host_search_crawl_bridge_tool(*, server_module: Any) -> None:
    if getattr(server_module, "_host_search_crawl_bridge_v64_installed", False):
        return
    base_descriptors = server_module.tool_descriptors

    def descriptors() -> list[dict[str, Any]]:
        tools = list(base_descriptors())
        if not any(isinstance(row, dict) and row.get("name") == TOOL_NAME for row in tools):
            tools.append(tool_descriptor())
        return tools

    server_module.tool_descriptors = descriptors
    server_module.TOOL_HANDLERS[TOOL_NAME] = execute_host_search_crawl_bridge_handler
    server_module._host_search_crawl_bridge_v64_installed = True


__all__ = [
    "SCHEMA",
    "TOOL_NAME",
    "execute_host_search_crawl_bridge_handler",
    "install_remote_host_search_crawl_bridge_tool",
    "rank_host_search_results",
    "tool_descriptor",
]
