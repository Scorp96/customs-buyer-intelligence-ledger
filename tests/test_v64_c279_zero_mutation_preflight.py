from __future__ import annotations

import unittest

from scripts import run_v64_c279_zero_mutation_preflight as preflight


TAIL = "a" * 64


class FakeClient:
    def __init__(self, *, queue=None, health=None, state=None, readiness=None):
        self.calls: list[tuple[str, object]] = []
        self.queue = queue if queue is not None else {
            "schema": "cbi.portfolio-queue.v6.1",
            "count": 1,
            "queue": [{"investigation_id": "INV-TEST-C279", "account_id": "C279"}],
        }
        self.health = health if health is not None else {
            "investigation_id": "INV-TEST-C279",
            "status": "READY",
            "read_only": False,
            "last_safe_seq": 27,
            "last_safe_event_hash": TAIL,
        }
        self.state = state if state is not None else {
            "schema": "cbi.investigation-state.v6.1",
            "investigation_id": "INV-TEST-C279",
            "account_id": "C279",
            "last_safe_seq": 27,
            "last_safe_event_hash": TAIL,
            "claims": {"contact.company_route": {"state": "SUPPORTED"}},
        }
        self.readiness = readiness if readiness is not None else {
            "schema": "cbi.outreach-readiness.v6.1",
            "investigation_id": "INV-TEST-C279",
            "outreach_readiness": "IDENTITY_ONLY",
            "block_reasons": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            "sends_message": False,
        }

    def read_health(self):
        self.calls.append(("read_health", None))
        return {"status": "ok", "deployment_identity": {"git_sha": "b" * 40}}

    def initialize(self):
        self.calls.append(("initialize", None))
        return {"protocolVersion": "2025-06-18"}

    def call_tool(self, name, arguments):
        self.calls.append((str(name), dict(arguments)))
        return {
            "get_portfolio_queue": self.queue,
            "get_investigation_health": self.health,
            "get_investigation_state": self.state,
            "evaluate_outreach_readiness": self.readiness,
        }[name]


class C279ZeroMutationPreflightTests(unittest.TestCase):
    def test_happy_path_uses_only_read_only_tools_and_returns_sanitized_receipt(self) -> None:
        client = FakeClient()
        result = preflight.run_preflight(client)
        self.assertEqual(result["schema"], "cbi.v64-c279-zero-mutation-preflight.v1")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertIs(result["verified"], True)
        self.assertIs(result["production_mutation_performed"], False)
        self.assertEqual(result["account_id"], "C279")
        self.assertEqual(result["investigation_id"], "INV-TEST-C279")
        self.assertEqual(result["last_safe_seq"], 27)
        self.assertEqual(result["last_safe_event_hash"], TAIL)
        self.assertEqual(result["pre_patch_outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(
            [name for name, _ in client.calls],
            [
                "read_health",
                "initialize",
                "get_portfolio_queue",
                "get_investigation_health",
                "get_investigation_state",
                "evaluate_outreach_readiness",
            ],
        )
        self.assertNotIn("claims", result)
        self.assertNotIn("route", str(result).casefold())
        self.assertNotIn("contact", str(result).casefold())

    def test_zero_or_multiple_c279_targets_fail_closed(self) -> None:
        for rows in (
            [],
            [
                {"investigation_id": "INV-A", "account_id": "C279"},
                {"investigation_id": "INV-B", "account_id": "C279"},
            ],
        ):
            with self.subTest(rows=len(rows)):
                client = FakeClient(queue={"count": len(rows), "queue": rows})
                with self.assertRaisesRegex(preflight.PreflightError, "C279_TARGET_NOT_UNIQUE"):
                    preflight.run_preflight(client)

    def test_tail_mismatch_fails_closed(self) -> None:
        client = FakeClient(
            state={
                "investigation_id": "INV-TEST-C279",
                "account_id": "C279",
                "last_safe_seq": 28,
                "last_safe_event_hash": "c" * 64,
                "claims": {"contact.company_route": {"state": "SUPPORTED"}},
            }
        )
        with self.assertRaisesRegex(preflight.PreflightError, "C279_TAIL_MISMATCH"):
            preflight.run_preflight(client)

    def test_unexpected_pre_patch_baseline_fails_closed(self) -> None:
        cases = [
            FakeClient(state={
                "investigation_id": "INV-TEST-C279",
                "account_id": "C279",
                "last_safe_seq": 27,
                "last_safe_event_hash": TAIL,
                "claims": {"contact.company_route": {"state": "UNSEEN"}},
            }),
            FakeClient(readiness={
                "investigation_id": "INV-TEST-C279",
                "outreach_readiness": "COMPANY_ROUTE_READY",
                "block_reasons": [],
                "sends_message": False,
            }),
        ]
        for client in cases:
            with self.subTest(client=client):
                with self.assertRaisesRegex(preflight.PreflightError, "C279_PREPATCH_BASELINE_MISMATCH"):
                    preflight.run_preflight(client)


if __name__ == "__main__":
    unittest.main()
