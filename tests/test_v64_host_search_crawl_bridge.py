from __future__ import annotations

import unittest
from unittest.mock import patch

from mcp import host_search_crawl_bridge_v64 as bridge


def task(**overrides):
    row = {
        "work_item_id": "PWEB-EXAMPLE-001",
        "owner_type": "ACCOUNT",
        "owner_id": "C1",
        "module_or_branch": "contact_coverage",
        "source_family": "official_contact",
        "query": '"Example Company" "Mexico" official contact',
        "execution_required": True,
        "receipt_required": True,
        "search_execution_performed": False,
    }
    row.update(overrides)
    return row


class HostSearchCrawlBridgeRankingTests(unittest.TestCase):
    def test_deduplicates_urls_and_rejects_non_public_targets(self) -> None:
        def validate(url: str) -> str:
            if "127.0.0.1" in url or "user:pass@" in url:
                raise ValueError("seed_URL targets a non-public or credentialed destination")
            return url.rstrip("/") + "/"

        rows = [
            {"url": "https://example.com/contact", "title": "Contact Example"},
            {"url": "https://example.com/contact", "title": "Duplicate"},
            {"url": "http://127.0.0.1/admin", "title": "Private"},
            {"url": "https://user:pass@example.com/", "title": "Credentialed"},
        ]
        with patch.object(bridge, "validate_public_seed_url", side_effect=validate):
            result = bridge.rank_host_search_results(task(), rows)

        self.assertEqual(result["accepted_count"], 1)
        reasons = [row["reason"] for row in result["rejected"]]
        self.assertIn("DUPLICATE_URL", reasons)
        self.assertEqual(reasons.count("PUBLIC_URL_REJECTED"), 2)

    def test_official_contact_path_beats_generic_directory_for_official_source_family(self) -> None:
        def validate(url: str) -> str:
            return url

        rows = [
            {"url": "https://findglocal.example/listing/example", "title": "Example Company"},
            {"url": "https://example.test/contact-us", "title": "Example Company Contact"},
        ]
        with patch.object(bridge, "validate_public_seed_url", side_effect=validate):
            result = bridge.rank_host_search_results(task(), rows)

        self.assertEqual(result["accepted"][0]["url"], "https://example.test/contact-us")
        self.assertGreater(result["accepted"][0]["score"], result["accepted"][1]["score"])


class HostSearchCrawlBridgeExecutionTests(unittest.TestCase):
    def positive_receipt(self, url: str) -> dict:
        return {
            "result": "POSITIVE",
            "completed_at": "2026-09-21T00:00:10Z",
            "raw_result_locator": url,
            "content_sha256": "a" * 64,
            "evidence_ids": ["CRAWLER-EVD-1"],
            "route_candidates": [
                {
                    "kind": "EMAIL",
                    "value": "sales@example.test",
                    "candidate_owner_scope": "UNVERIFIED",
                }
            ],
            "source_urls": [url],
            "pages_crawled": 1,
            "source_status": "OK",
            "verified": False,
            "owner_scope": "UNVERIFIED",
            "production_route_ownership_promoted": False,
        }

    def blocked_receipt(self, url: str) -> dict:
        return {
            "result": "BLOCKED",
            "status": "SOURCE_ACCESS_BLOCKED",
            "source_status": "SOURCE_ACCESS_BLOCKED",
            "completed_at": "2026-09-21T00:00:05Z",
            "raw_result_locator": url,
            "content_sha256": "0" * 64,
            "evidence_ids": [],
            "route_candidates": [],
            "source_urls": [],
            "pages_crawled": 0,
            "fallback_required": True,
            "negative_contact_conclusion_allowed": False,
        }

    def negative_receipt(self, url: str) -> dict:
        return {
            "result": "NEGATIVE_EXHAUSTED",
            "completed_at": "2026-09-21T00:00:08Z",
            "raw_result_locator": url,
            "content_sha256": "b" * 64,
            "evidence_ids": [],
            "route_candidates": [],
            "source_urls": [url],
            "pages_crawled": 1,
            "source_status": "OK",
        }

    def run_bridge(self, results, crawler_side_effect, **kwargs):
        with patch.object(
            bridge,
            "validate_public_seed_url",
            side_effect=lambda url: url,
        ), patch.object(
            bridge,
            "execute_public_crawl_handler",
            side_effect=crawler_side_effect,
        ):
            return bridge.execute_host_search_crawl_bridge_handler({
                "investigation_id": "INV-1",
                "task": task(),
                "host_search": {
                    "query": '"Example Company" contact',
                    "searched_at": "2026-09-21T00:00:00Z",
                },
                "search_results": results,
                **kwargs,
            })

    def test_positive_crawl_returns_append_ready_payload_without_route_promotion(self) -> None:
        url = "https://example.test/contact"
        result = self.run_bridge(
            [{"url": url, "title": "Example Company Contact"}],
            lambda args: self.positive_receipt(args["seed_url"]),
        )

        self.assertTrue(result["append_ready"])
        self.assertTrue(result["crawler_execution_performed"])
        self.assertFalse(result["server_performed_web_search"])
        self.assertFalse(result["durable_mutation_performed"])
        self.assertFalse(result["route_ownership_promoted"])
        self.assertEqual(result["planned_work_item_id"], "PWEB-EXAMPLE-001")
        self.assertEqual(result["final_result"], "POSITIVE")
        self.assertTrue(result["source_coverage_terminal"])

        payload = result["append_execution_receipt_payload"]
        attempt = payload["attempt"]
        self.assertEqual(attempt["investigation_id"], "INV-1")
        self.assertEqual(attempt["owner_id"], "C1")
        self.assertEqual(attempt["module_or_branch"], "contact_coverage")
        self.assertEqual(attempt["source_family"], "official_contact")
        self.assertEqual(attempt["result"], "POSITIVE")
        self.assertEqual(attempt["result_count"], 1)
        self.assertEqual(set(attempt["evidence_ids"]), {payload["evidence"][0]["evidence_id"]})
        self.assertEqual(payload["evidence"][0]["evidence_grade"], "C2")
        self.assertIn("does not prove Account ownership", payload["evidence"][0]["boundary"])

    def test_blocked_first_seed_can_fall_through_to_second_positive_seed(self) -> None:
        first = "https://blocked.test/contact"
        second = "https://example.test/contact"
        calls = []

        def crawler(args):
            calls.append(args["seed_url"])
            if args["seed_url"] == first:
                return self.blocked_receipt(first)
            return self.positive_receipt(second)

        result = self.run_bridge(
            [
                {"url": first, "title": "Example Company Contact"},
                {"url": second, "title": "Example Company Contact"},
            ],
            crawler,
            max_crawl_seeds=2,
        )

        self.assertEqual(calls, result["attempted_urls"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["final_result"], "POSITIVE")
        self.assertTrue(result["append_ready"])

    def test_single_site_negative_never_becomes_negative_exhausted(self) -> None:
        url = "https://example.test/contact"
        result = self.run_bridge(
            [{"url": url}],
            lambda args: self.negative_receipt(args["seed_url"]),
        )

        self.assertEqual(result["final_result"], "NEGATIVE")
        self.assertFalse(result["negative_exhaustion_proven"])
        self.assertFalse(result["source_coverage_terminal"])
        payload = result["append_execution_receipt_payload"]
        self.assertEqual(payload["attempt"]["result"], "NEGATIVE")
        self.assertEqual(payload["attempt"]["evidence_ids"], [])
        self.assertEqual(payload["evidence"], [])

    def test_all_blocked_returns_append_ready_blocked_attempt_not_false_negative(self) -> None:
        url = "https://blocked.test/contact"
        result = self.run_bridge(
            [{"url": url}],
            lambda args: self.blocked_receipt(args["seed_url"]),
        )

        self.assertEqual(result["final_result"], "BLOCKED")
        self.assertFalse(result["source_coverage_terminal"])
        attempt = result["append_execution_receipt_payload"]["attempt"]
        self.assertEqual(attempt["result"], "BLOCKED")
        self.assertTrue(attempt["blocked_reason"])
        self.assertEqual(attempt["result_count"], 0)

    def test_no_valid_public_urls_fails_closed_without_crawler_call(self) -> None:
        with patch.object(
            bridge,
            "validate_public_seed_url",
            side_effect=ValueError("seed_URL targets a private network"),
        ), patch.object(
            bridge,
            "execute_public_crawl_handler",
        ) as crawler:
            result = bridge.execute_host_search_crawl_bridge_handler({
                "investigation_id": "INV-1",
                "task": task(),
                "host_search": {
                    "query": '"Example Company" contact',
                    "searched_at": "2026-09-21T00:00:00Z",
                },
                "search_results": [{"url": "http://127.0.0.1/"}],
            })

        crawler.assert_not_called()
        self.assertFalse(result["append_ready"])
        self.assertEqual(result["status"], "NO_VALID_PUBLIC_URLS")
        self.assertEqual(result["final_result"], "NO_VALID_PUBLIC_URLS")

    def test_pivot_consumption_is_prepared_only_for_non_blocked_attempt(self) -> None:
        t = task(
            pivot_id="PIV-1",
            pivot_value="director",
            query='"Example Company" director official contact',
        )
        with patch.object(
            bridge,
            "validate_public_seed_url",
            side_effect=lambda url: url,
        ), patch.object(
            bridge,
            "execute_public_crawl_handler",
            side_effect=lambda args: self.negative_receipt(args["seed_url"]),
        ):
            result = bridge.execute_host_search_crawl_bridge_handler({
                "investigation_id": "INV-1",
                "task": t,
                "host_search": {
                    "query": '"Example Company" director',
                    "searched_at": "2026-09-21T00:00:00Z",
                },
                "search_results": [{"url": "https://example.test/team"}],
            })

        consumed = result["append_execution_receipt_payload"]["pivots_consumed"]
        self.assertEqual(consumed, [{
            "pivot_id": "PIV-1",
            "consumption_result": "HOST_SEARCH_CRAWL_NEGATIVE",
        }])


class HostSearchCrawlBridgeDescriptorTests(unittest.TestCase):
    def test_descriptor_is_remote_read_only_open_world(self) -> None:
        descriptor = bridge.tool_descriptor()
        self.assertEqual(descriptor["name"], bridge.TOOL_NAME)
        self.assertTrue(descriptor["annotations"]["readOnlyHint"])
        self.assertTrue(descriptor["annotations"]["openWorldHint"])
        self.assertEqual(
            descriptor["inputSchema"]["properties"]["max_crawl_seeds"]["maximum"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
