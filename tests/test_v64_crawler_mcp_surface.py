from __future__ import annotations

import os
import unittest
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
        self.assertTrue(status["enabled"])
        self.assertFalse(status["paid_api_required"])
        self.assertTrue(status["public_network_only"])

    def test_runtime_status_exposes_resource_and_ssrf_guards(self) -> None:
        status = crawler_tool_v64.crawler_runtime_status()
        self.assertTrue(status["request_interception_guard"])
        self.assertTrue(status["redirect_revalidation"])
        self.assertEqual(status["max_pages_per_call"], 12)
        self.assertGreaterEqual(status["max_concurrency"], 1)

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
