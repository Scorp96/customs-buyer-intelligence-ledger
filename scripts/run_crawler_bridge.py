from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from unified_runtime.browser_escalation import (
    EscalatingCrawlerBackend,
    PlaywrightBrowserBackend,
    ResilientCrawlerBackend,
)
from unified_runtime.crawler_execution_bridge import Crawl4AIBackend, CrawlExecutionBridge


def _load_task(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.task_json) == bool(args.task_file):
        raise SystemExit("provide exactly one of --task-json or --task-file")
    if args.task_json:
        payload = json.loads(args.task_json)
    else:
        payload = json.loads(Path(args.task_file).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("task payload must be a JSON object")
    return payload


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    task = _load_task(args)
    async with Crawl4AIBackend() as primary:
        if args.browser_escalation:
            async with PlaywrightBrowserBackend(
                navigation_timeout_ms=args.browser_navigation_timeout_ms,
                settle_ms=args.browser_settle_ms,
                scroll_steps=args.browser_scroll_steps,
                click_budget=args.browser_click_budget,
            ) as browser:
                escalated = EscalatingCrawlerBackend(
                    primary,
                    browser,
                    sparse_text_chars=args.browser_sparse_text_chars,
                )
                backend = ResilientCrawlerBackend(
                    escalated,
                    timeout_seconds=args.timeout_seconds,
                    max_retries=args.max_retries,
                    retry_delay_seconds=args.retry_delay_seconds,
                )
                bridge = CrawlExecutionBridge(backend, max_pages=args.max_pages)
                return await bridge.execute(
                    task,
                    seed_url=args.seed_url,
                    official_domain_verified=args.official_domain_verified,
                )

        backend = ResilientCrawlerBackend(
            primary,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        bridge = CrawlExecutionBridge(backend, max_pages=args.max_pages)
        return await bridge.execute(
            task,
            seed_url=args.seed_url,
            official_domain_verified=args.official_domain_verified,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one CBI source/contact task with local open-source crawling."
    )
    parser.add_argument("--seed-url", required=True)
    parser.add_argument("--task-json")
    parser.add_argument("--task-file")
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--retry-delay-seconds", type=float, default=0.15)
    parser.add_argument(
        "--browser-escalation",
        action="store_true",
        help="Escalate sparse/blocked Crawl4AI pages to local Playwright.",
    )
    parser.add_argument("--browser-sparse-text-chars", type=int, default=280)
    parser.add_argument("--browser-navigation-timeout-ms", type=int, default=15000)
    parser.add_argument("--browser-settle-ms", type=int, default=500)
    parser.add_argument("--browser-scroll-steps", type=int, default=3)
    parser.add_argument("--browser-click-budget", type=int, default=6)
    parser.add_argument(
        "--official-domain-verified",
        action="store_true",
        help="Only set when the seed domain is already proven to belong to the investigated account.",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
