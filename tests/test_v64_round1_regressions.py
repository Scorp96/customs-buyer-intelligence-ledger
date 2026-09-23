"""Round 1 regression contracts for CBI v6.4 opportunity and crawler findings.

These tests capture the Round 1 regression contract and the Round 2 legacy-peer
candidate bridge. They stay deliberately read-only and fail closed when durable
identity or evidence is missing.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from unified_runtime.demand_expansion import V63DemandExpansionMixin
from unified_runtime.existing_production_store_backend_v63 import ExistingProductionStoreBackend
from unified_runtime.production_integration_bindings_v63 import V63ProductionIntegrationBindingMixin
from unified_runtime.product_profiles import get_product_profile
from unified_runtime.recovery_semantics_v63 import snapshot_sha256
from unified_runtime.core import SessionStore, digest
from unified_runtime.crawler_execution_bridge import Crawl4AIBackend, CrawlExecutionBridge, CrawlPage
from unified_runtime.legacy_peer_projection import project_legacy_peer_receipt
from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors


def create_event(
    opportunity_id: str,
    account_id: str,
    investigation_id: str,
    product_profile_id: str,
    ordinal: int,
) -> dict:
    profile = get_product_profile(product_profile_id)
    snapshot = {
        "status": "CREATED",
        "opportunity_id": opportunity_id,
        "account_id": account_id,
        "product_profile_id": product_profile_id,
        "product_profile_version": profile["profile_version"],
        "product_profile_sha256": profile["profile_sha256"],
        "stage": "OPPORTUNITY_CREATED",
    }
    return {
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "investigation_id": investigation_id,
        "correlation_id": f"MUTCORR-ROUND1-{ordinal}",
        "request_sha256": f"{ordinal:064x}",
        "result_snapshot": snapshot,
        "result_snapshot_sha256": snapshot_sha256(snapshot),
        "raw_idempotency_key_persisted": False,
    }


def promotion_event(opportunity_id: str, investigation_id: str, ordinal: int) -> dict:
    return {
        "event_type": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
        "investigation_id": investigation_id,
        "correlation_id": f"MUTCORR-ROUND1-PROMOTE-{ordinal}",
        "request_sha256": f"{ordinal:064x}",
        "opportunity_id": opportunity_id,
        "anchor_id": "ANCHOR-" + opportunity_id,
        "promotion_reason": "UPGRADE_TARGET",
        "stage": "PROMOTED_ANCHOR",
        "anchor_eligibility_snapshot": {"anchor_eligible": True},
        "cycle_dedup_snapshot": {"cycle_dedup_complete": True},
        "raw_idempotency_key_persisted": False,
    }


class OpportunityRuntime(V63DemandExpansionMixin):
    def __init__(self, events: list[dict]) -> None:
        self.events = copy.deepcopy(events)

    def _query_v63_opportunity_events(self, filters: dict) -> list[dict]:
        # Mimic a shared/global event source: projection must isolate records
        # before validating unrelated accounts and product profiles.
        return copy.deepcopy(self.events)

    def _read_v63_durable_events(self, investigation_id: str) -> list[dict]:
        return [
            copy.deepcopy(row)
            for row in self.events
            if row.get("investigation_id") == investigation_id
        ]


class ProductionLocatorRuntime(V63DemandExpansionMixin, V63ProductionIntegrationBindingMixin):
    """Run the real lazy locator rebuild against isolated synthetic sessions."""

    def __init__(self, events_by_investigation: dict[str, list[dict]]) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cbi-v64-round1-")
        self.add_cleanup = self._tmp.cleanup
        root = Path(self._tmp.name)
        self.store = SimpleNamespace(root=root)
        self.events_by_investigation = copy.deepcopy(events_by_investigation)
        for investigation_id in events_by_investigation:
            (root / f"{investigation_id}.jsonl").write_text("isolated synthetic test fixture\n", encoding="utf-8")

    def _v63_locator_index_path(self) -> Path:
        return Path(self.store.root) / "locator-index.json"

    def _read_v63_durable_events(self, investigation_id: str) -> list[dict]:
        return copy.deepcopy(self.events_by_investigation.get(investigation_id, []))


class FakeBackend:
    name = "round1-fake"

    def __init__(self, error: str) -> None:
        self.error = error

    async def fetch(self, url: str) -> CrawlPage:
        return CrawlPage(url=url, text="", links=(), success=False, error=self.error)


def run(coro):
    return asyncio.run(coro)


class OpportunityIsolationRegressionTests(unittest.TestCase):
    def test_t1_duplicate_in_c364_does_not_break_c363_read(self) -> None:
        runtime = ProductionLocatorRuntime({
            "INV-C364": [
                create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 1),
                create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 2),
            ],
            "INV-C363": [create_event("OPP-C363-PVC-1", "C363", "INV-C363", "PVC", 3)],
        })
        self.addCleanup(runtime.add_cleanup)

        try:
            result = runtime.get_product_opportunities({"account_id": "C363"})
        except RuntimeError as exc:
            self.fail(f"unrelated C364 duplicate escaped the C363 account filter: {exc}")

        self.assertEqual(
            [row["opportunity_id"] for row in result["opportunities"]],
            ["OPP-C363-PVC-1"],
        )

    def test_t2_pvc_duplicate_does_not_break_other_product_queries(self) -> None:
        runtime = ProductionLocatorRuntime({
            "INV-C364": [
                create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 10),
                create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 11),
            ],
            "INV-C363-WPC": [create_event("OPP-C363-WPC-1", "C363", "INV-C363-WPC", "WPC", 12)],
            "INV-C363-SPC": [create_event("OPP-C363-SPC-1", "C363", "INV-C363-SPC", "SPC", 13)],
            "INV-C363-ACRYLIC": [create_event("OPP-C363-ACRYLIC-1", "C363", "INV-C363-ACRYLIC", "ACRYLIC_PMMA", 14)],
        })
        self.addCleanup(runtime.add_cleanup)

        for product_profile_id, opportunity_id in (
            ("WPC", "OPP-C363-WPC-1"),
            ("SPC", "OPP-C363-SPC-1"),
            ("ACRYLIC_PMMA", "OPP-C363-ACRYLIC-1"),
        ):
            with self.subTest(product_profile_id=product_profile_id):
                try:
                    result = runtime.get_product_opportunities({"product_profile_id": product_profile_id})
                except RuntimeError as exc:
                    self.fail(f"unrelated PVC duplicate escaped the {product_profile_id} product filter: {exc}")
                self.assertEqual(
                    [row["opportunity_id"] for row in result["opportunities"]],
                    [opportunity_id],
                )

    def test_t2b_hash_consistent_invalid_profile_pin_is_quarantined_by_scope(self) -> None:
        corrupt = create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 15)
        corrupt["result_snapshot"]["product_profile_sha256"] = "b" * 64
        corrupt["result_snapshot_sha256"] = snapshot_sha256(corrupt["result_snapshot"])
        runtime = ProductionLocatorRuntime({
            "INV-C364": [corrupt],
            "INV-C363": [create_event("OPP-C363-PVC-1", "C363", "INV-C363", "PVC", 16)],
        })
        self.addCleanup(runtime.add_cleanup)

        result = runtime.get_product_opportunities({"account_id": "C363"})
        self.assertEqual(
            [row["opportunity_id"] for row in result["opportunities"]],
            ["OPP-C363-PVC-1"],
        )
        with self.assertRaisesRegex(RuntimeError, "V63_OPPORTUNITY_PROJECTION_BLOCKED:INV-C364"):
            runtime.get_product_opportunities({"account_id": "C364"})

    def test_t3_identity_scoped_anchor_read_does_not_turn_projection_failure_into_ready_empty(self) -> None:
        events = [
            create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 20),
            create_event("OPP-C364-PVC-20260921", "C364", "INV-C364", "PVC", 21),
        ]

        result = OpportunityRuntime(events).get_demand_anchors({
            "investigation_id": "INV-C364",
            "account_id": "C364",
            "opportunity_id": "OPP-C364-PVC-20260921",
        })

        self.assertNotEqual(
            result["status"],
            "READY",
            "A requested identity was ignored and an empty result was reported as a successful read.",
        )

    def test_empty_anchor_list_means_only_no_verified_procurement_in_that_input(self) -> None:
        runtime = OpportunityRuntime([])
        anchors = runtime.get_demand_anchors({"account_id": "C364"})

        market = runtime.evaluate_market_acceptance(anchors)

        self.assertEqual(anchors["status"], "READY")
        self.assertEqual(anchors["anchors"], [])
        self.assertEqual(market["level"], "M0")
        self.assertEqual(market["reason"], "NO_VERIFIED_PROCUREMENT")


class CrawlerResponseRegressionTests(unittest.TestCase):
    """The redirect test covers typed handling after a guard error is raised.

    It does not claim that this fake backend proves a real browser request was
    blocked before connection; that needs a real-browser integration probe.
    """

    def test_t4_explicit_private_redirect_guard_failure_is_not_retryable_source_outage(self) -> None:
        bridge = CrawlExecutionBridge(
            FakeBackend("public_network_redirect_guard: private destination rejected"),
            max_pages=1,
        )

        receipt = run(bridge.execute(
            {"task_id": "ROUND1-REDIRECT", "source_family": "official_contact"},
            seed_url="https://public.example/",
            official_domain_verified=True,
        ))

        self.assertEqual(receipt["result"], "BLOCKED")
        self.assertEqual(receipt["source_status"], "REDIRECT_TARGET_BLOCKED")
        self.assertFalse(receipt["retryable"])

    def test_existing_crawl4ai_route_hook_aborts_private_http_request(self) -> None:
        class FakeStrategy:
            def __init__(self) -> None:
                self.hooks = {}

            def set_hook(self, name, callback) -> None:
                self.hooks[name] = callback

        class FakeCrawler:
            def __init__(self) -> None:
                self.crawler_strategy = FakeStrategy()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        class FakePage:
            async def route(self, _pattern, callback) -> None:
                self.guard_route = callback

        class FakeRoute:
            def __init__(self) -> None:
                self.aborted = False
                self.continued = False

            async def abort(self) -> None:
                self.aborted = True

            async def continue_(self) -> None:
                self.continued = True

        class FakeRequest:
            url = "http://127.0.0.1:8080/internal"
            resource_type = "document"

        fake_module = types.ModuleType("crawl4ai")
        fake_module.AsyncWebCrawler = FakeCrawler

        async def exercise_route_guard() -> FakeRoute:
            backend = Crawl4AIBackend(public_network_only=True)
            await backend.__aenter__()
            page = FakePage()
            hook = backend._crawler.crawler_strategy.hooks["on_page_context_created"]
            await hook(page, object())
            route = FakeRoute()
            await page.guard_route(route, FakeRequest())
            await backend.__aexit__(None, None, None)
            return route

        with patch.dict(sys.modules, {"crawl4ai": fake_module}):
            route = run(exercise_route_guard())

        self.assertTrue(route.aborted)
        self.assertFalse(route.continued)

    def test_t5_failed_crawl_response_does_not_expose_traceback_or_internal_paths(self) -> None:
        internal_error = (
            "Traceback (most recent call last):\n"
            "  File 'C:/runtime/Lib/site-packages/crawler/runner.py', line 123\n"
            "Code context: internal request headers and implementation detail"
        )
        bridge = CrawlExecutionBridge(FakeBackend(internal_error), max_pages=1)

        receipt = run(bridge.execute(
            {"task_id": "ROUND1-SANITIZER", "source_family": "official_products"},
            seed_url="https://public.example/",
        ))
        response_text = repr(receipt)

        for forbidden in ("Traceback", "site-packages", "Code context", "runner.py"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response_text)


class ExpansionContractRegressionTests(unittest.TestCase):
    def test_t6_advertised_top_level_opportunity_id_is_resolved_for_recursive_preview(self) -> None:
        events = [
            create_event("OPP-C363-PVC-1", "C363", "INV-C363", "PVC", 40),
            promotion_event("OPP-C363-PVC-1", "INV-C363", 41),
        ]
        runtime = OpportunityRuntime(events)

        try:
            result = runtime.preview_recursive_anchor_expansion({
                "investigation_id": "INV-C363",
                "opportunity_id": "OPP-C363-PVC-1",
                "account_id": "C363",
                "product_profile_id": "PVC",
                "market_cell": {
                    "market_cell_id": "CELL-C363-MEXICO-PVC",
                    "geography": "Mexico",
                    "product_profile_id": "PVC",
                    "market_acceptance": "M0",
                    "application_ids": [],
                    "buyer_archetype_ids": [],
                },
            })
        except ValueError as exc:
            self.fail(f"published top-level opportunity context was not bound to the anchor: {exc}")

        self.assertEqual(result["status"], "PLANNED")
        self.assertEqual(result["anchor_opportunity_id"], "OPP-C363-PVC-1")

    def test_t7_top_level_limit_five_bounds_returned_planner_work(self) -> None:
        result = OpportunityRuntime([]).plan_candidate_expansion({
            "account_id": "C363",
            "product_profile_id": "PVC",
            "geography": "Mexico",
            "market_acceptance": "M0",
            "anchor_grade": None,
            "anchor_score": None,
            "applications": [],
            "buyer_archetypes": [],
            "limit": 5,
        })

        self.assertLessEqual(result["discovery_plan"]["returned_count"], 5)
        self.assertLessEqual(result["source_plan"]["returned_count"], 5)

    def test_t8_source_task_continuation_is_stable_and_non_overlapping(self) -> None:
        from unified_runtime.expansion_planner import plan_expansion, generate_discovery_queries
        from unified_runtime.source_execution import plan_public_source_tasks

        context = {
            "product_profile_id": "PVC",
            "market_acceptance": "M0",
            "geography": "Mexico",
            "applications": [],
            "buyer_archetypes": [],
            "limit": 54,
        }
        expansion = plan_expansion(context)
        discovery = generate_discovery_queries(context)
        first = plan_public_source_tasks(expansion, discovery, max_tasks=5)
        self.assertTrue(first["continuation_token"])
        second = plan_public_source_tasks(
            expansion,
            discovery,
            max_tasks=5,
            continuation_token=first["continuation_token"],
        )
        first_ids = {row["call_id"] for row in first["tasks"]}
        second_ids = {row["call_id"] for row in second["tasks"]}
        self.assertTrue(first_ids)
        self.assertTrue(second_ids)
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertEqual(first["plan_fingerprint"], second["plan_fingerprint"])
        self.assertEqual(second["offset"], first["offset"] + first["returned_count"])


class OpportunityMutationRegressionTests(unittest.TestCase):
    class Store:
        def __init__(self) -> None:
            self.events = []

        def append(self, investigation_id, event_type, payload):
            previous = self.events[-1].get("event_hash") if self.events else "0" * 64
            event = {
                "seq": len(self.events) + 1,
                "prev_hash": previous,
                "event_type": event_type,
                "payload": copy.deepcopy(payload),
                "mutation_correlation": {
                    "schema": "cbi.mutation-correlation.v6.1",
                    "correlation_id": f"MUTCORR-ROUND2-{len(self.events) + 1}",
                    "tool": "create_product_opportunity",
                },
            }
            event["event_hash"] = hashlib.sha256(
                repr(sorted(event.items())).encode("utf-8")
            ).hexdigest()
            self.events.append(event)
            return copy.deepcopy(event)

        def append_if_tail(self, investigation_id, expected_tail_hash, event_type, payload):
            current = self.events[-1].get("event_hash") if self.events else None
            if current != expected_tail_hash:
                raise RuntimeError("tail changed")
            return self.append(investigation_id, event_type, payload)

        def read(self, investigation_id):
            return [
                copy.deepcopy(row)
                for row in self.events
                if row.get("investigation_id") == investigation_id
                or (isinstance(row.get("payload"), dict) and row["payload"].get("investigation_id") == investigation_id)
            ]

    class Runtime:
        def __init__(self) -> None:
            self.store = OpportunityMutationRegressionTests.Store()

    class CorrelatedSessionStore(SessionStore):
        @staticmethod
        def _event(seq, previous, event_type, payload):
            event = SessionStore._event(seq, previous, event_type, payload)
            event["mutation_correlation"] = {
                "schema": "cbi.mutation-correlation.v6.1",
                "correlation_id": f"MUTCORR-ROUND2-{seq}",
                "tool": "create_product_opportunity",
            }
            event["event_hash"] = digest({
                key: value for key, value in event.items() if key != "event_hash"
            })
            return event

    def _arguments(
        self,
        *,
        account_id: str = "C363",
        profile_id: str = "PVC",
        investigation_id: str = "INV-C363",
    ) -> dict:
        profile = get_product_profile(profile_id)
        return {
            "investigation_id": investigation_id,
            "canonical_resolution": {
                "canonical_status": "CONFIRMED",
                "canonical_account_id": account_id,
                "resolver_authority": "EXACT_ACCOUNT_ID",
                "resolver_is_existing_production_authority": True,
                "ambiguous": False,
                "address_only_match": False,
                "alias_only_match": False,
            },
            "opportunity": {
                "opportunity_id": "OPP-C363-PVC-1",
                "account_id": account_id,
                "product_profile_id": profile_id,
                "product_profile_version": profile["profile_version"],
                "product_profile_sha256": profile["profile_sha256"],
            },
        }

    def test_same_business_identity_is_replayed_without_second_durable_event(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        first = backend.create_product_opportunity(runtime, self._arguments())
        second = backend.create_product_opportunity(runtime, self._arguments())
        self.assertEqual(first["opportunity_id"], second["opportunity_id"])
        self.assertEqual(second["status"], "REPLAYED")
        self.assertEqual(len(runtime.store.events), 1)

    def test_existing_proof_with_different_request_hash_fails_closed(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        backend.create_product_opportunity(runtime, self._arguments())

        changed_arguments = self._arguments()
        changed_arguments["unexpected_marker"] = "different-canonical-request"
        with self.assertRaisesRegex(ValueError, "V63_OPPORTUNITY_IDENTITY_CONFLICT:request_sha256"):
            backend.create_product_opportunity(runtime, changed_arguments)
        self.assertEqual(len(runtime.store.events), 1)

    def test_existing_proof_requires_exact_mutation_correlation_binding(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        backend.create_product_opportunity(runtime, self._arguments())
        runtime.store.events[0]["mutation_correlation"]["tool"] = "append_candidate_discovery"

        with self.assertRaisesRegex(ValueError, "CORRELATION_BINDING_INVALID"):
            backend.create_product_opportunity(runtime, self._arguments())
        self.assertEqual(len(runtime.store.events), 1)

    def test_existing_proof_rejects_wrong_mutation_correlation_schema(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        backend.create_product_opportunity(runtime, self._arguments())
        runtime.store.events[0]["mutation_correlation"]["schema"] = "cbi.mutation-correlation.v5.3"

        with self.assertRaisesRegex(ValueError, "CORRELATION_BINDING_INVALID"):
            backend.create_product_opportunity(runtime, self._arguments())
        self.assertEqual(len(runtime.store.events), 1)

    def test_existing_proof_rejects_blank_mutation_correlation_id(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        backend.create_product_opportunity(runtime, self._arguments())
        runtime.store.events[0]["mutation_correlation"]["correlation_id"] = ""

        with self.assertRaisesRegex(ValueError, "CORRELATION_BINDING_INVALID"):
            backend.create_product_opportunity(runtime, self._arguments())
        self.assertEqual(len(runtime.store.events), 1)

    def test_multiple_matching_durable_proofs_fail_closed_as_ambiguous(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        backend.create_product_opportunity(runtime, self._arguments())
        runtime.store.events.append(copy.deepcopy(runtime.store.events[0]))

        with self.assertRaisesRegex(ValueError, "V63_OPPORTUNITY_DUPLICATE_DURABLE_PROOF"):
            backend.create_product_opportunity(runtime, self._arguments())
        self.assertEqual(len(runtime.store.events), 2)

    def test_same_opportunity_id_with_different_identity_fails_closed(self) -> None:
        runtime = self.Runtime()
        backend = ExistingProductionStoreBackend()
        backend.create_product_opportunity(runtime, self._arguments())
        with self.assertRaisesRegex(ValueError, "V63_OPPORTUNITY_IDENTITY_CONFLICT"):
            backend.create_product_opportunity(runtime, self._arguments(account_id="C364"))
        self.assertEqual(len(runtime.store.events), 1)

    def test_real_session_store_envelope_replays_exact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-round2-store-") as root:
            store = self.CorrelatedSessionStore(Path(root) / "sessions")
            investigation_id = "INV-20260923T000000Z-abcdefabcdef"
            store.create({
                "investigation_id": investigation_id,
                "account": {"account_id": "C363", "country": "Synthetic", "name": "Fixture"},
            })
            runtime = SimpleNamespace(store=store)
            backend = ExistingProductionStoreBackend()
            first = backend.create_product_opportunity(
                runtime, self._arguments(investigation_id=investigation_id)
            )
            replay = backend.create_product_opportunity(
                runtime, self._arguments(investigation_id=investigation_id)
            )
            self.assertEqual(first["status"], "CREATED")
            self.assertEqual(replay["status"], "REPLAYED")
            events = store.read(investigation_id)
            creates = [row for row in events if row.get("event_type") == "V63_PRODUCT_OPPORTUNITY_CREATED"]
            self.assertEqual(len(creates), 1)
            self.assertIsInstance(creates[0].get("payload", {}).get("result_snapshot"), dict)

    def test_concurrent_same_identity_has_one_create_and_one_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-round2-concurrent-") as root:
            store = self.CorrelatedSessionStore(Path(root) / "sessions")
            investigation_id = "INV-20260923T000001Z-abcdefabcdef"
            store.create({
                "investigation_id": investigation_id,
                "account": {"account_id": "C363", "country": "Synthetic", "name": "Fixture"},
            })
            runtime = SimpleNamespace(store=store)
            backend = ExistingProductionStoreBackend()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda _: backend.create_product_opportunity(
                        runtime, self._arguments(investigation_id=investigation_id)
                    ),
                    range(2),
                ))
            self.assertEqual(sorted(row["status"] for row in results), ["CREATED", "REPLAYED"])
            creates = [
                row for row in store.read(investigation_id)
                if row.get("event_type") == "V63_PRODUCT_OPPORTUNITY_CREATED"
            ]
            self.assertEqual(len(creates), 1)

    def test_concurrent_conflicting_identity_has_one_create_and_one_fail_closed_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-round2-conflict-") as root:
            store = self.CorrelatedSessionStore(Path(root) / "sessions")
            investigation_id = "INV-20260923T000002Z-abcdefabcdef"
            store.create({
                "investigation_id": investigation_id,
                "account": {"account_id": "C363", "country": "Synthetic", "name": "Fixture"},
            })
            runtime = SimpleNamespace(store=store)
            backend = ExistingProductionStoreBackend()
            arguments = [
                self._arguments(investigation_id=investigation_id),
                self._arguments(account_id="C364", investigation_id=investigation_id),
            ]

            def invoke(item):
                try:
                    return ("OK", backend.create_product_opportunity(runtime, item))
                except ValueError as exc:
                    return ("ERROR", str(exc))

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(invoke, arguments))
            self.assertEqual([kind for kind, _ in results].count("OK"), 1)
            errors = [value for kind, value in results if kind == "ERROR"]
            self.assertEqual(len(errors), 1)
            self.assertIn("V63_OPPORTUNITY_IDENTITY_CONFLICT", errors[0])
            creates = [
                row for row in store.read(investigation_id)
                if row.get("event_type") == "V63_PRODUCT_OPPORTUNITY_CREATED"
            ]
            self.assertEqual(len(creates), 1)

    def test_legacy_peer_with_explicit_profile_and_evidence_gets_read_only_candidate_signal(self) -> None:
        result = project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "PEER-LEGACY-001",
            "company_name": "Legacy Buyer LLC",
            "promotion_decision": "PROMOTE",
            "canonical_status": "NEW",
            "product_profile_id": "PVC",
            "product_evidence_ids": ["E-PRODUCT-1"],
            "procurement_evidence_ids": ["E-TRADE-1"],
            "procurement_proven": True,
            "product_or_application_signal": True,
            "signal_tier": "D1",
            "eiv": 0.62,
        })

        candidate = result["candidate_projection"]
        self.assertEqual(candidate["status"], "PROJECTED")
        self.assertTrue(candidate["projection_is_read_only"])
        self.assertFalse(candidate["persistent_mutation_performed"])
        self.assertEqual(candidate["candidate_researchability"]["product_profile_id"], "PVC")
        self.assertEqual(candidate["candidate_researchability"]["research_state"], "RESEARCH_ACTIVE")
        self.assertIn("CANONICAL_IDENTITY_UNRESOLVED", candidate["candidate_researchability"]["qualification_gaps"])
        self.assertEqual(candidate["evidence_ids"], ["E-PRODUCT-1", "E-TRADE-1"])

    def test_legacy_peer_without_explicit_product_profile_stays_blocked_not_invented(self) -> None:
        result = project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "PEER-LEGACY-002",
            "company_name": "Legacy Buyer LLC",
            "promotion_decision": "PROMOTE",
            "canonical_status": "NEW",
            "product_evidence_ids": ["E-PRODUCT-2"],
            "procurement_evidence_ids": ["E-TRADE-2"],
        })

        candidate = result["candidate_projection"]
        self.assertEqual(candidate["status"], "BLOCKED")
        self.assertIsNone(candidate["candidate_researchability"])
        self.assertIn("PRODUCT_PROFILE_ID_MISSING", candidate["blockers"])
        self.assertTrue(candidate["projection_is_read_only"])

    def test_legacy_peer_with_missing_evidence_stays_unresolved(self) -> None:
        result = project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "PEER-LEGACY-003",
            "company_name": "Legacy Buyer LLC",
            "promotion_decision": "DO_NOT_PROMOTE",
            "canonical_status": "UNRESOLVED",
            "product_profile_id": "PVC",
        })

        candidate = result["candidate_projection"]
        self.assertEqual(candidate["status"], "BLOCKED")
        self.assertIn("PRODUCT_EVIDENCE_MISSING", candidate["blockers"])
        self.assertIn("PROCUREMENT_EVIDENCE_MISSING", candidate["blockers"])

    def test_v63_read_only_schemas_declare_domain_required_inputs(self) -> None:
        tools = {row["name"]: row for row in build_v63_tool_descriptors()}
        required_properties = {
            "assess_candidate_researchability": {"candidate_id", "company_name", "product_profile_id"},
            "plan_candidate_expansion": {"product_profile_id", "geography"},
            "evaluate_relative_opportunity": {"anchor_grade", "candidate_grade"},
            "project_legacy_peer_receipt": {"source_event", "peer_id"},
            "preview_customs_seed_expansion": {
                "investigation_id", "account_id", "opportunity_id",
                "source_evidence_ids", "product_profile_id", "geography",
            },
        }
        for name, fields in required_properties.items():
            with self.subTest(tool=name):
                properties = set(tools[name]["inputSchema"].get("properties", {}))
                missing = sorted(fields - properties)
                self.assertFalse(missing, f"{name} schema omits domain inputs: {missing}")

        for name in ("plan_contact_exhaustion", "evaluate_route_reuse", "evaluate_sales_readiness"):
            with self.subTest(tool=name):
                schema = tools[name]["inputSchema"]
                declared_id_pair = {"investigation_id", "opportunity_id"} <= set(schema.get("required", []))
                declared_opportunity_object = schema.get("properties", {}).get("opportunity", {}).get("type") == "object"
                self.assertTrue(
                    declared_id_pair or declared_opportunity_object,
                    f"{name} must declare either scoped identity or a supplied opportunity object",
                )


if __name__ == "__main__":
    unittest.main()
