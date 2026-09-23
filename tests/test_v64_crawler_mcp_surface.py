from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mcp import crawler_tool_v64
from mcp import server_v61 as adapter
from unified_runtime.production_tool_surface_v64 import CRAWLER_EXECUTION_TOOL_NAME


class CrawlerMcpSurfaceTests(unittest.TestCase):
    def test_crawler_tool_is_declared_and_registered_read_only(self) -> None:
        descriptors = {
            str(item.get("name") or ""): item
            for item in adapter._server.tool_descriptors()
            if isinstance(item, dict)
        }
        self.assertIn(CRAWLER_EXECUTION_TOOL_NAME, descriptors)
        self.assertIn(CRAWLER_EXECUTION_TOOL_NAME, adapter._server.TOOL_HANDLERS)
        self.assertNotIn(CRAWLER_EXECUTION_TOOL_NAME, adapter._MUTATING_TOOLS)

        descriptor = descriptors[CRAWLER_EXECUTION_TOOL_NAME]
        self.assertTrue(descriptor["annotations"]["readOnlyHint"])
        self.assertFalse(descriptor["annotations"]["destructiveHint"])
        self.assertFalse(descriptor["contract"]["paid_api_required"])
        self.assertFalse(descriptor["contract"]["route_ownership_promoted"])
        self.assertTrue(descriptor["contract"]["source_throttle_fail_closed"])
        self.assertTrue(descriptor["contract"]["source_throttle_retry_backoff"])
        self.assertTrue(descriptor["contract"]["host_fallback_plan_on_throttle"])
        self.assertTrue(descriptor["contract"]["source_access_blocked_fail_closed"])
        self.assertTrue(descriptor["contract"]["host_fallback_plan_on_access_blocked"])
        self.assertTrue(descriptor["contract"]["source_unavailable_fail_closed"])
        self.assertTrue(descriptor["contract"]["host_fallback_plan_on_unavailable"])
        self.assertTrue(descriptor["contract"]["bounded_wall_clock"])
        self.assertTrue(descriptor["contract"]["partial_failure_fail_closed"])

    def test_disabled_runtime_returns_structured_non_mutating_result(self) -> None:
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "0"}, clear=False):
            result = crawler_tool_v64.execute_public_crawl_handler(
                {
                    "task": {"call_id": "V64-CRAWL-DISABLED"},
                    "seed_url": "https://8.8.8.8/",
                }
            )

        self.assertEqual(result["status"], "CRAWLER_DISABLED")
        self.assertFalse(result["runtime"]["enabled"])
        self.assertFalse(result["paid_api_required"])

    def test_source_throttle_receipt_surfaces_top_level_status(self) -> None:
        class OneShotSemaphore:
            def acquire(self, timeout=None):
                return True

            def release(self):
                return None

        receipt = {
            "result": "BLOCKED",
            "source_status": "SOURCE_THROTTLED",
            "retryable": True,
            "fallback_required": True,
            "fallback_search_plan": {"host_action": "WEB_SEARCH_AND_PUBLIC_SOURCE_FALLBACK"},
        }
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64,
            "_CRAWLER_SEMAPHORE",
            OneShotSemaphore(),
        ), patch.object(
            crawler_tool_v64,
            "_run_coroutine_sync",
            return_value=dict(receipt),
        ):
            result = crawler_tool_v64.execute_public_crawl_handler(
                {
                    "task": {"task_id": "V64-FB-THROTTLED"},
                    "seed_url": "https://www.facebook.com/ferreteriaslaquintainc/",
                }
            )

        self.assertEqual(result["status"], "SOURCE_THROTTLED")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertTrue(result["fallback_required"])
        self.assertFalse(result["production_route_ownership_promoted"])

    def test_source_access_blocked_receipt_surfaces_top_level_status(self) -> None:
        class OneShotSemaphore:
            def acquire(self, timeout=None):
                return True

            def release(self):
                return None

        receipt = {
            "result": "BLOCKED",
            "source_status": "SOURCE_ACCESS_BLOCKED",
            "retryable": True,
            "fallback_required": True,
            "fallback_search_plan": {"host_action": "WEB_SEARCH_AND_PUBLIC_SOURCE_FALLBACK"},
        }
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64,
            "_CRAWLER_SEMAPHORE",
            OneShotSemaphore(),
        ), patch.object(
            crawler_tool_v64,
            "_run_coroutine_sync",
            return_value=dict(receipt),
        ):
            result = crawler_tool_v64.execute_public_crawl_handler(
                {
                    "task": {"task_id": "V64-403-BLOCKED"},
                    "seed_url": "https://www.findglocal.com/example",
                }
            )

        self.assertEqual(result["status"], "SOURCE_ACCESS_BLOCKED")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertTrue(result["fallback_required"])
        self.assertFalse(result["production_route_ownership_promoted"])

    def test_source_unavailable_receipt_surfaces_top_level_status(self) -> None:
        class OneShotSemaphore:
            def acquire(self, timeout=None):
                return True

            def release(self):
                return None

        receipt = {
            "result": "BLOCKED",
            "source_status": "SOURCE_UNAVAILABLE",
            "retryable": True,
            "fallback_required": True,
            "fallback_search_plan": {"host_action": "WEB_SEARCH_AND_PUBLIC_SOURCE_FALLBACK"},
        }
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64,
            "_CRAWLER_SEMAPHORE",
            OneShotSemaphore(),
        ), patch.object(
            crawler_tool_v64,
            "_run_coroutine_sync",
            return_value=dict(receipt),
        ):
            result = crawler_tool_v64.execute_public_crawl_handler(
                {
                    "task": {"task_id": "V64-FB-UNAVAILABLE"},
                    "seed_url": "https://www.facebook.com/ferreteriaslaquintainc/",
                }
            )

        self.assertEqual(result["status"], "SOURCE_UNAVAILABLE")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertTrue(result["fallback_required"])
        self.assertFalse(result["production_route_ownership_promoted"])

    def test_public_seed_guard_rejects_private_local_and_credentials(self) -> None:
        blocked = [
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost/",
            "http://metadata.google.internal/",
            "https://user:pass@example.com/",
            "file:///tmp/test.html",
        ]
        for url in blocked:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    crawler_tool_v64.validate_public_seed_url(url)

    def test_public_seed_guard_accepts_global_literal_without_dns(self) -> None:
        self.assertEqual(
            crawler_tool_v64.validate_public_seed_url("https://8.8.8.8/path"),
            "https://8.8.8.8/path",
        )

    def test_runtime_status_never_claims_paid_api_requirement(self) -> None:
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False):
            status = crawler_tool_v64.crawler_runtime_status()
        self.assertFalse(status["paid_api_required"])
        self.assertTrue(status["public_network_only"])

    def test_enabled_is_false_when_optional_runtime_dependencies_are_missing(self) -> None:
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64.importlib.util,
            "find_spec",
            return_value=None,
        ):
            status = crawler_tool_v64.crawler_runtime_status()

        self.assertFalse(status["enabled"])
        self.assertTrue(status["configured_enabled"])
        self.assertFalse(status["runtime_ready"])
        self.assertIn("CRAWL4AI_NOT_IMPORTABLE", status["readiness_blockers"])
        self.assertIn("PLAYWRIGHT_NOT_IMPORTABLE", status["browser_readiness_blockers"])
        self.assertFalse(status["crawl4ai_present"])
        self.assertFalse(status["playwright_present"])

    def test_import_failures_are_not_reported_as_dependency_ready(self) -> None:
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64.importlib.util,
            "find_spec",
            return_value=SimpleNamespace(submodule_search_locations=None),
        ), patch.object(
            crawler_tool_v64.importlib,
            "import_module",
            side_effect=ImportError("optional dependency is broken"),
        ):
            status = crawler_tool_v64.crawler_runtime_status()

        self.assertTrue(status["crawl4ai_present"])
        self.assertTrue(status["playwright_present"])
        self.assertFalse(status["crawl4ai_importable"])
        self.assertFalse(status["playwright_importable"])
        self.assertFalse(status["enabled"])
        self.assertEqual(status["crawl4ai_error_type"], "ImportError")
        self.assertEqual(status["playwright_error_type"], "ImportError")

    def test_missing_runtime_fails_closed_before_crawl_execution(self) -> None:
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64.importlib.util,
            "find_spec",
            return_value=None,
        ):
            result = crawler_tool_v64.execute_public_crawl_handler(
                {
                    "task": {"call_id": "V64-RUNTIME-MISSING"},
                    "seed_url": "https://8.8.8.8/",
                }
            )

        self.assertEqual(result["status"], "CRAWLER_RUNTIME_MISSING")
        self.assertEqual(result["missing"], ["crawl4ai"])
        self.assertFalse(result["runtime"]["enabled"])

    def test_browser_executable_readiness_is_fail_closed(self) -> None:
        def fake_import(module_name: str):
            if module_name == "crawl4ai":
                return SimpleNamespace(AsyncWebCrawler=lambda: None)
            return SimpleNamespace(async_playwright=lambda: None)

        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64.importlib.util,
            "find_spec",
            return_value=SimpleNamespace(submodule_search_locations=None),
        ), patch.object(
            crawler_tool_v64.importlib,
            "import_module",
            side_effect=fake_import,
        ), patch.object(
            crawler_tool_v64,
            "_find_playwright_browser_executable",
            return_value=None,
        ):
            status = crawler_tool_v64.crawler_runtime_status()

        self.assertTrue(status["crawl4ai_importable"])
        self.assertTrue(status["playwright_importable"])
        self.assertFalse(status["browser_executable_ready"])
        self.assertFalse(status["browser_escalation_supported"])
        self.assertTrue(status["runtime_ready"])
        self.assertTrue(status["enabled"])
        self.assertFalse(status["browser_runtime_ready"])
        self.assertIn("PLAYWRIGHT_BROWSER_NOT_READY", status["browser_readiness_blockers"])

    def test_crawl4ai_can_run_without_optional_browser_escalation(self) -> None:
        def fake_import(module_name: str):
            if module_name == "crawl4ai":
                return SimpleNamespace(AsyncWebCrawler=lambda: None)
            raise ImportError("browser escalation is not installed")

        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64.importlib.util,
            "find_spec",
            return_value=SimpleNamespace(submodule_search_locations=None),
        ), patch.object(
            crawler_tool_v64.importlib,
            "import_module",
            side_effect=fake_import,
        ):
            status = crawler_tool_v64.crawler_runtime_status()

        self.assertTrue(status["crawl4ai_importable"])
        self.assertFalse(status["playwright_importable"])
        self.assertTrue(status["runtime_ready"])
        self.assertTrue(status["enabled"])
        self.assertFalse(status["browser_runtime_ready"])
        self.assertFalse(status["browser_escalation_supported"])
        self.assertNotIn("CRAWL4AI_NOT_IMPORTABLE", status["readiness_blockers"])
        self.assertIn("PLAYWRIGHT_NOT_IMPORTABLE", status["browser_readiness_blockers"])

    def test_execution_uses_core_crawler_when_browser_escalation_is_disabled(self) -> None:
        class FakePrimary:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeBridge:
            def __init__(self, backend, max_pages):
                self.backend = backend
                self.max_pages = max_pages

            async def execute(self, task, *, seed_url, official_domain_verified, max_elapsed_seconds):
                return {
                    "result": "NEGATIVE_EXHAUSTED",
                    "task_id": task.get("task_id"),
                    "seed_url": seed_url,
                    "pages_crawled": 0,
                    "official_domain_verified": official_domain_verified,
                    "max_elapsed_seconds": max_elapsed_seconds,
                }

        runtime = {
            "interpreter_ready": True,
            "crawl4ai_importable": True,
            "browser_escalation_supported": False,
            "enabled": True,
        }
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64,
            "crawler_runtime_status",
            return_value=runtime,
        ), patch.object(
            crawler_tool_v64,
            "Crawl4AIBackend",
            return_value=FakePrimary(),
        ), patch.object(
            crawler_tool_v64,
            "CrawlExecutionBridge",
            FakeBridge,
        ), patch.object(
            crawler_tool_v64,
            "PlaywrightBrowserBackend",
        ) as browser_backend:
            result = asyncio.run(crawler_tool_v64._execute({
                "task": {"task_id": "V64-CORE-ONLY"},
                "seed_url": "https://8.8.8.8/",
                "browser_escalation": False,
                "max_pages": 1,
                "timeout_seconds": 2,
                "max_retries": 0,
            }))

        self.assertEqual(result["status"], "CRAWL_EXECUTED")
        self.assertEqual(result["task_id"], "V64-CORE-ONLY")
        browser_backend.assert_not_called()

    def test_unsupported_interpreter_is_not_runtime_ready(self) -> None:
        version_info = SimpleNamespace(major=3, minor=9)
        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64.sys,
            "version_info",
            version_info,
        ):
            status = crawler_tool_v64.crawler_runtime_status()

        self.assertFalse(status["interpreter_ready"])
        self.assertFalse(status["enabled"])
        self.assertIn("INTERPRETER_UNSUPPORTED", status["readiness_blockers"])

    def test_playwright_browser_path_probe_uses_installed_chromium_layout(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executable = (
                Path(temp_dir)
                / "chromium-1234"
                / "chrome-linux"
                / "chrome"
            )
            executable.parent.mkdir(parents=True)
            executable.write_text("synthetic executable", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"PLAYWRIGHT_BROWSERS_PATH": temp_dir},
                clear=False,
            ):
                found = crawler_tool_v64._find_playwright_browser_executable(None)

        self.assertEqual(found, executable)

    def test_runtime_status_exposes_resource_and_ssrf_guards(self) -> None:
        status = crawler_tool_v64.crawler_runtime_status()
        self.assertTrue(status["request_interception_guard"])
        self.assertTrue(status["redirect_revalidation"])
        self.assertEqual(status["max_pages_per_call"], 12)
        self.assertGreaterEqual(status["max_concurrency"], 1)
        self.assertGreaterEqual(status["max_wall_seconds"], 15.0)
        self.assertLessEqual(status["max_wall_seconds"], 100.0)

        descriptors = {
            str(item.get("name") or ""): item
            for item in adapter._server.tool_descriptors()
            if isinstance(item, dict)
        }
        maximum = descriptors[CRAWLER_EXECUTION_TOOL_NAME]["inputSchema"]["properties"]["max_pages"]["maximum"]
        self.assertEqual(maximum, 12)

    def test_busy_runtime_fails_closed_without_execution(self) -> None:
        class BusySemaphore:
            def acquire(self, timeout=None):
                return False

            def release(self):
                raise AssertionError("release must not be called when acquire failed")

        with patch.dict(os.environ, {"CBI_CRAWLER_ENABLED": "1"}, clear=False), patch.object(
            crawler_tool_v64,
            "_CRAWLER_SEMAPHORE",
            BusySemaphore(),
        ):
            result = crawler_tool_v64.execute_public_crawl_handler(
                {
                    "task": {"call_id": "V64-CRAWL-BUSY"},
                    "seed_url": "https://8.8.8.8/",
                }
            )
        self.assertEqual(result["status"], "CRAWLER_BUSY")
        self.assertTrue(result["retryable"])
        self.assertFalse(result["paid_api_required"])


if __name__ == "__main__":
    unittest.main()
