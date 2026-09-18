from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

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
    async with Crawl4AIBackend() as backend:
        bridge = CrawlExecutionBridge(backend, max_pages=args.max_pages)
        return await bridge.execute(
            task,
            seed_url=args.seed_url,
            official_domain_verified=args.official_domain_verified,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one CBI source/contact task with local Crawl4AI."
    )
    parser.add_argument("--seed-url", required=True)
    parser.add_argument("--task-json")
    parser.add_argument("--task-file")
    parser.add_argument("--max-pages", type=int, default=8)
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
