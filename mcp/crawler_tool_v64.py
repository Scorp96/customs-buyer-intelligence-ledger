from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Any

from unified_runtime.browser_escalation import (
    EscalatingCrawlerBackend,
    PlaywrightBrowserBackend,
    ResilientCrawlerBackend,
)
from unified_runtime.crawler_execution_bridge import Crawl4AIBackend, CrawlExecutionBridge
from unified_runtime.public_network_guard import validate_public_http_url


CRAWLER_TOOL_NAME = "execute_public_crawl"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}
_MAX_PRODUCTION_PAGES = 12
_MAX_ATTEMPT_ENVELOPE_SECONDS = 30.0
_MIN_CRAWLER_PYTHON = (3, 10)
_PLAYWRIGHT_EXECUTABLE_RELATIVE_PATHS = (
    Path("chrome-win") / "chrome.exe",
    Path("chrome-linux") / "chrome",
    Path("chrome-linux") / "headless_shell",
    Path("chrome-mac") / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
    Path("chrome-mac") / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
)


def _env_enabled() -> bool:
    raw = str(os.environ.get("CBI_CRAWLER_ENABLED") or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return False


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _crawler_max_concurrency() -> int:
    return _env_int("CBI_CRAWLER_MAX_CONCURRENCY", 1, 1, 4)


def _crawler_acquire_timeout() -> float:
    return _env_float("CBI_CRAWLER_ACQUIRE_TIMEOUT_SECONDS", 2.0, 0.0, 15.0)


def _crawler_max_wall_seconds() -> float:
    # This is a soft cross-page budget. Individual third-party fetch stacks can
    # delay cancellation, so the per-page attempt envelope below supplies the
    # second bound needed to stay materially below the outer HTTP gateway.
    return _env_float("CBI_CRAWLER_MAX_WALL_SECONDS", 50.0, 15.0, 55.0)


def _validate_attempt_envelope(timeout_seconds: float, max_retries: int) -> float:
    envelope = float(timeout_seconds) * (int(max_retries) + 1)
    if envelope > _MAX_ATTEMPT_ENVELOPE_SECONDS:
        raise ValueError(
            "timeout_seconds * (max_retries + 1) must be <= "
            f"{_MAX_ATTEMPT_ENVELOPE_SECONDS:g} seconds"
        )
    return envelope


def _probe_optional_dependency(
    module_name: str,
    import_name: str,
    required_symbol: str,
) -> dict[str, Any]:
    """Report package presence and importability without making network calls."""
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception as exc:
        return {
            "present": False,
            "importable": False,
            "error_type": type(exc).__name__,
            "package_root": None,
        }

    if spec is None:
        return {
            "present": False,
            "importable": False,
            "error_type": "MODULE_NOT_FOUND",
            "package_root": None,
        }

    package_root: Path | None = None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        try:
            package_root = Path(next(iter(locations))).resolve()
        except (OSError, StopIteration, TypeError, ValueError):
            package_root = None

    try:
        module = importlib.import_module(import_name)
        if not callable(getattr(module, required_symbol, None)):
            return {
                "present": True,
                "importable": False,
                "error_type": "REQUIRED_SYMBOL_MISSING",
                "package_root": package_root,
            }
    except Exception as exc:
        return {
            "present": True,
            "importable": False,
            "error_type": type(exc).__name__,
            "package_root": package_root,
        }

    return {
        "present": True,
        "importable": True,
        "error_type": None,
        "package_root": package_root,
    }


def _playwright_browser_roots(package_root: Path | None) -> list[Path]:
    configured = str(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if configured == "0":
        return [package_root / ".local-browsers"] if package_root is not None else []
    if configured:
        return [Path(configured).expanduser()]

    if os.name == "nt":
        base = str(os.environ.get("LOCALAPPDATA") or "").strip()
        return [
            (Path(base) if base else Path.home() / "AppData" / "Local")
            / "ms-playwright"
        ]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Caches" / "ms-playwright"]
    cache_root = str(os.environ.get("XDG_CACHE_HOME") or "").strip()
    return [
        (Path(cache_root) if cache_root else Path.home() / ".cache")
        / "ms-playwright"
    ]


def _find_playwright_browser_executable(package_root: Path | None) -> Path | None:
    for root in _playwright_browser_roots(package_root):
        try:
            browser_dirs = sorted(root.glob("chromium*"))
        except (OSError, ValueError):
            continue
        for browser_dir in browser_dirs:
            if not browser_dir.is_dir():
                continue
            for relative_path in _PLAYWRIGHT_EXECUTABLE_RELATIVE_PATHS:
                candidate = browser_dir / relative_path
                try:
                    if candidate.is_file():
                        return candidate
                except OSError:
                    continue
    return None


def _interpreter_status() -> dict[str, Any]:
    version = (sys.version_info.major, sys.version_info.minor)
    return {
        "python_executable": str(sys.executable or ""),
        "python_version": platform.python_version(),
        "interpreter_ready": bool(sys.executable) and version >= _MIN_CRAWLER_PYTHON,
    }


_CRAWLER_CONCURRENCY_LIMIT = _crawler_max_concurrency()
_CRAWLER_SEMAPHORE = threading.BoundedSemaphore(_CRAWLER_CONCURRENCY_LIMIT)


def validate_public_seed_url(url: str) -> str:
    try:
        return validate_public_http_url(
            str(url or "").strip(),
            resolve_dns=True,
            allow_url_credentials=False,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("URL "):
            message = "seed_" + message[4:]
        raise ValueError(message) from exc


def crawler_runtime_status() -> dict[str, Any]:
    configured_enabled = _env_enabled()
    interpreter = _interpreter_status()
    crawl4ai = _probe_optional_dependency(
        "crawl4ai",
        "crawl4ai",
        "AsyncWebCrawler",
    )
    playwright = _probe_optional_dependency(
        "playwright",
        "playwright.async_api",
        "async_playwright",
    )
    browser_executable = _find_playwright_browser_executable(playwright["package_root"])
    browser_escalation_supported = bool(
        configured_enabled and playwright["importable"] and browser_executable
    )
    readiness_blockers: list[str] = []
    if not interpreter["interpreter_ready"]:
        readiness_blockers.append("INTERPRETER_UNSUPPORTED")
    if not crawl4ai["importable"]:
        readiness_blockers.append("CRAWL4AI_NOT_IMPORTABLE")
    if not playwright["importable"]:
        readiness_blockers.append("PLAYWRIGHT_NOT_IMPORTABLE")
    elif not browser_executable:
        readiness_blockers.append("PLAYWRIGHT_BROWSER_NOT_READY")
    runtime_ready = not readiness_blockers
    enabled = bool(configured_enabled and runtime_ready)
    return {
        "schema": "cbi.crawler-runtime-status.v6.4",
        "enabled": enabled,
        "configured_enabled": configured_enabled,
        "runtime_ready": runtime_ready,
        "readiness_blockers": readiness_blockers,
        "python_executable": interpreter["python_executable"],
        "python_version": interpreter["python_version"],
        "interpreter_ready": interpreter["interpreter_ready"],
        "crawl4ai_present": crawl4ai["present"],
        "crawl4ai_importable": crawl4ai["importable"],
        "crawl4ai_error_type": crawl4ai["error_type"],
        "playwright_present": playwright["present"],
        "playwright_importable": playwright["importable"],
        "playwright_error_type": playwright["error_type"],
        "browser_executable_ready": bool(browser_executable),
        "browser_executable_path": str(browser_executable) if browser_executable else None,
        "browser_escalation_supported": browser_escalation_supported,
        "paid_api_required": False,
        "public_network_only": True,
        "request_interception_guard": True,
        "redirect_revalidation": True,
        "max_pages_per_call": _MAX_PRODUCTION_PAGES,
        "max_concurrency": _CRAWLER_CONCURRENCY_LIMIT,
        "acquire_timeout_seconds": _crawler_acquire_timeout(),
        "max_wall_seconds": _crawler_max_wall_seconds(),
        "max_attempt_envelope_seconds": _MAX_ATTEMPT_ENVELOPE_SECONDS,
    }


def crawler_tool_descriptor() -> dict[str, Any]:
    return {
        "name": CRAWLER_TOOL_NAME,
        "description": (
            "Execute one existing CBI public-source/contact research task against a supplied public website seed "
            "using the self-hosted Crawl4AI path with optional local Playwright escalation. This is execution, not "
            "planning proof; it never sends messages, logs in, bypasses access controls, or promotes a discovered "
            "route to verified Account ownership by itself. Source HTTP 429 / anti-bot throttle pages are fail-closed "
            "as SOURCE_THROTTLED; explicit HTTP 403 / anti-bot denial is SOURCE_ACCESS_BLOCKED; repeated fetch "
            "timeouts/unavailability are SOURCE_UNAVAILABLE. All fail closed with a host-web-search fallback plan "
            "rather than a false negative."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["task", "seed_url"],
            "properties": {
                "task": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Existing CBI task object containing a task_id or call_id plus its research intent.",
                },
                "seed_url": {
                    "type": "string",
                    "minLength": 8,
                    "description": "Absolute public http(s) company/source URL. Private, loopback and local targets are rejected.",
                },
                "max_pages": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_PRODUCTION_PAGES,
                    "default": 8,
                },
                "browser_escalation": {
                    "type": "boolean",
                    "default": True,
                    "description": "Escalate failed/sparse/SPA-shell pages to local Playwright.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 2,
                    "maximum": 30,
                    "default": 15,
                },
                "max_retries": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 2,
                    "default": 1,
                },
            },
        },
        "outputSchema": {"type": "object"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        "contract": {
            "planning_is_execution_proof": False,
            "host_execution_required": False,
            "sends_message": False,
            "server_side_draft_created": False,
            "mutation_boundary": None,
            "paid_api_required": False,
            "public_network_only": True,
            "route_ownership_promoted": False,
            "bounded_concurrency": True,
            "bounded_pages": True,
            "bounded_wall_clock": True,
            "bounded_attempt_envelope": True,
            "partial_failure_fail_closed": True,
            "source_throttle_fail_closed": True,
            "source_throttle_retry_backoff": True,
            "host_fallback_plan_on_throttle": True,
            "source_access_blocked_fail_closed": True,
            "host_fallback_plan_on_access_blocked": True,
            "source_unavailable_fail_closed": True,
            "host_fallback_plan_on_unavailable": True,
        },
    }


async def _execute(arguments: dict[str, Any]) -> dict[str, Any]:
    if not _env_enabled():
        return {
            "status": "CRAWLER_DISABLED",
            "runtime": crawler_runtime_status(),
            "paid_api_required": False,
        }

    runtime = crawler_runtime_status()
    browser_requested = arguments.get("browser_escalation", True) is not False
    if not runtime["interpreter_ready"]:
        return {
            "status": "CRAWLER_RUNTIME_MISSING",
            "runtime": runtime,
            "missing": ["python"],
            "retryable": False,
            "paid_api_required": False,
        }
    if not runtime["crawl4ai_importable"]:
        return {
            "status": "CRAWLER_RUNTIME_MISSING",
            "runtime": runtime,
            "missing": ["crawl4ai"],
            "retryable": False,
            "paid_api_required": False,
        }

    if browser_requested and not runtime["browser_escalation_supported"]:
        return {
            "status": "CRAWLER_RUNTIME_MISSING",
            "runtime": runtime,
            "missing": ["playwright"],
            "retryable": False,
            "paid_api_required": False,
        }

    task = arguments.get("task")
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    if not str(task.get("task_id") or task.get("call_id") or "").strip():
        raise ValueError("task must contain task_id or call_id")

    seed_url = validate_public_seed_url(str(arguments.get("seed_url") or ""))
    max_pages = int(arguments.get("max_pages", 8))
    if max_pages < 1 or max_pages > _MAX_PRODUCTION_PAGES:
        raise ValueError(f"max_pages must be between 1 and {_MAX_PRODUCTION_PAGES}")

    timeout_seconds = float(arguments.get("timeout_seconds", 15.0))
    if timeout_seconds < 2 or timeout_seconds > 30:
        raise ValueError("timeout_seconds must be between 2 and 30")

    max_retries = int(arguments.get("max_retries", 1))
    if max_retries < 0 or max_retries > 2:
        raise ValueError("max_retries must be between 0 and 2")
    _validate_attempt_envelope(timeout_seconds, max_retries)

    browser_escalation = browser_requested

    async with Crawl4AIBackend(
        public_network_only=True,
        block_heavy_resources=True,
    ) as primary:
        if browser_escalation:
            async with PlaywrightBrowserBackend(
                navigation_timeout_ms=min(int(timeout_seconds * 1000), 30_000),
                settle_ms=500,
                scroll_steps=3,
                click_budget=6,
                public_network_only=True,
                block_heavy_resources=True,
            ) as browser:
                escalated = EscalatingCrawlerBackend(
                    primary,
                    browser,
                    sparse_text_chars=280,
                )
                backend = ResilientCrawlerBackend(
                    escalated,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    retry_delay_seconds=0.15,
                )
                bridge = CrawlExecutionBridge(backend, max_pages=max_pages)
                receipt = await bridge.execute(
                    task,
                    seed_url=seed_url,
                    official_domain_verified=False,
                    max_elapsed_seconds=_crawler_max_wall_seconds(),
                )
        else:
            backend = ResilientCrawlerBackend(
                primary,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_delay_seconds=0.15,
            )
            bridge = CrawlExecutionBridge(backend, max_pages=max_pages)
            receipt = await bridge.execute(
                task,
                seed_url=seed_url,
                official_domain_verified=False,
                max_elapsed_seconds=_crawler_max_wall_seconds(),
            )

    return _finalize_receipt(receipt)


def _finalize_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    source_status = str(receipt.get("source_status") or "")
    if source_status in {"SOURCE_THROTTLED", "SOURCE_ACCESS_BLOCKED", "SOURCE_UNAVAILABLE"}:
        receipt["status"] = source_status
    elif not str(receipt.get("status") or "").strip():
        receipt["status"] = "CRAWL_EXECUTED"
    receipt.setdefault("runtime", crawler_runtime_status())
    receipt.setdefault("production_route_ownership_promoted", False)
    return receipt


def _run_coroutine_sync(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_execute(arguments))

    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def worker() -> None:
        try:
            result.update(asyncio.run(_execute(arguments)))
        except BaseException as exc:  # pragma: no cover - unusual host embedding
            error.append(exc)

    thread = threading.Thread(target=worker, name="cbi-crawler-tool", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result


def execute_public_crawl_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    if not _env_enabled():
        return _finalize_receipt(_run_coroutine_sync(arguments))

    acquired = _CRAWLER_SEMAPHORE.acquire(timeout=_crawler_acquire_timeout())
    if not acquired:
        return {
            "status": "CRAWLER_BUSY",
            "runtime": crawler_runtime_status(),
            "retryable": True,
            "paid_api_required": False,
        }
    try:
        return _finalize_receipt(_run_coroutine_sync(arguments))
    finally:
        _CRAWLER_SEMAPHORE.release()


__all__ = [
    "CRAWLER_TOOL_NAME",
    "crawler_runtime_status",
    "crawler_tool_descriptor",
    "execute_public_crawl_handler",
    "validate_public_seed_url",
]
