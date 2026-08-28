from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_runtime import UnifiedRuntime
from unified_runtime.resilience import digest
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_outreach_recovery.py"
PREVIOUS_SERVER = ROOT / "mcp" / "server_v61_closure_recovery.py"
LEGACY_RENDER_SERVER = ROOT / "tests" / "fixtures" / "server_v61_legacy_render_shim.py"


class V61OutreachWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-outreach-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.host_root = self.root / "host-pending"
        self.previous_host_root = os.environ.get("CBI_HOST_PENDING_ROOT")
        os.environ["CBI_HOST_PENDING_ROOT"] = str(self.host_root)
        self.addCleanup(self._restore_environment)
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)

    def _restore_environment(self) -> None:
        if self.previous_host_root is None:
            os.environ.pop("CBI_HOST_PENDING_ROOT", None)
        else:
            os.environ["CBI_HOST_PENDING_ROOT"] = self.previous_host_root

    def _env(self, crash_after_handler: str = "") -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.host_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if crash_after_handler:
            env["CBI_V61_TEST_CRASH_AFTER_HANDLER"] = crash_after_handler
        else:
            env.pop("CBI_V61_TEST_CRASH_AFTER_HANDLER", None)
        return env

    def _spawn(
        self,
        crash_after_handler: str = "",
        server: Path = SERVER,
    ) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(server), "--stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._env(crash_after_handler),
        )
        self.processes.append(process)
        self._rpc(process, 1, "initialize", {"protocolVersion": "2025-06-18"})
        return process

    @staticmethod
    def _rpc(
        process: subprocess.Popen[str],
        request_id: int,
        method: str,
        params: dict | None = None,
    ) -> dict:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }, ensure_ascii=True) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"server ended before response: {stderr}")
        return json.loads(line)

    def _tool(
        self,
        process: subprocess.Popen[str],
        request_id: int,
        name: str,
        arguments: dict,
    ) -> dict:
        response = self._rpc(
            process,
            request_id,
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if "error" in response:
            raise AssertionError(response["error"])
        return response["result"]["structuredContent"]

    @staticmethod
    def _crash_call(
        process: subprocess.Popen[str],
        request_id: int,
        name: str,
        arguments: dict,
    ) -> None:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, ensure_ascii=True) + "\n")
        process.stdin.flush()
        if process.stdout.readline() != "":
            raise AssertionError("crash-injected mutation unexpectedly returned")
        process.wait(timeout=10)
        if process.returncode != 91:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"unexpected crash code {process.returncode}: {stderr}")
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def _cleanup(self) -> None:
        for process in self.processes:
            self._stop(process)

    def _events(self, investigation_id: str) -> list[dict]:
        path = self.session_root / f"{investigation_id}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _ready_outreach(self, account_id: str) -> tuple[str, dict, dict]:
        runtime = UnifiedRuntime(self.session_root)
        start = runtime.start_investigation({
            "account": {
                "account_id": account_id,
                "country": "Canada",
                "name": f"Synthetic {account_id}",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "A",
        })
        investigation_id = start["investigation_id"]
        rows: list[dict] = []
        claim_keys = list(DEFAULT_CLAIM_CATALOG)
        for index, claim_key in enumerate(claim_keys):
            value: object = {"fixture": claim_key}
            if claim_key == "contact.named_route":
                value = {
                    "channel": "EMAIL",
                    "value": "buyer@example.invalid",
                    "person_name": "Synthetic Decision Maker",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": False,
                }
            elif claim_key == "contact.company_route":
                value = {
                    "channel": "EMAIL",
                    "value": "info@example.invalid",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": False,
                }
            rows.append({
                "claim_key": claim_key,
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": account_id,
                "value": value,
                "source": {
                    "source_family": "synthetic_official",
                    "source_type": "OFFICIAL",
                    "reference_type": "PUBLIC_URL",
                    "url": f"https://example.invalid/outreach/{index}",
                    "locator": f"https://example.invalid/outreach/{index}#record",
                    "raw_excerpt": f"Synthetic Outreach Evidence {index}",
                    "authority_level": "A1_OFFICIAL_PRIMARY",
                    "freshness": "CURRENT",
                    "observed_at": "2026-08-28T00:00:00Z",
                },
                "boundary": "Synthetic test fixture only; no live-company fact is asserted.",
                "pivots": [],
            })
        compiled = runtime.compile_and_append_research_bundle({
            "investigation_id": investigation_id,
            "bundle": {
                "bundle_id": f"BUNDLE-OUTREACH-{account_id}",
                "observations": rows,
            },
        })
        self.assertEqual(compiled["rejected_count"], 0)
        saturation = runtime.evaluate_decision_saturation({"investigation_id": investigation_id})
        self.assertTrue(saturation["decision_saturated"], saturation)
        closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
        self.assertTrue(closure["closed"], closure)
        named_index = claim_keys.index("contact.named_route")
        named = compiled["outcomes"][named_index]
        route = {
            "kind": "EMAIL",
            "value": "buyer@example.invalid",
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "owner_entity_id": account_id,
            "evidence_ids": [named["evidence_id"]],
        }
        body = (
            "Hello, I am reaching out because your public company profile suggests a possible fit with our product range. "
            "We support buyers who need consistent specifications, practical order planning, and clear production communication. "
            "If this category is relevant to your current sourcing work, I can share a concise overview for your review. "
            "Please let me know which product requirements or applications matter most, and I will tailor the information accordingly. "
            "There is no obligation, and this message is only an invitation to compare potential options when convenient for you."
        )
        prepare_args = {
            "investigation_id": investigation_id,
            "closure_id": closure["closure_id"],
            "route": route,
            "history_digest": start["history_digest"],
            "authority_digest": start["authority_digest"],
            "subject": "Synthetic product discussion",
            "body": body,
            "chinese_translation": "合成测试译文。",
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        return investigation_id, prepare_args, closure

    def _prepare_normally(self, account_id: str, suffix: str) -> tuple[str, dict, dict]:
        investigation_id, arguments, _ = self._ready_outreach(account_id)
        arguments = {**arguments, "idempotency_key": f"prepare-outreach-{suffix}-0001"}
        process = self._spawn()
        prepared = self._tool(process, 2, "prepare_outreach", arguments)
        self.assertTrue(prepared["prepared"], prepared)
        self._stop(process)
        return investigation_id, arguments, prepared

    def test_contract_exposes_outreach_recovery_and_render_race_guard(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        wal = contract["production_adapter_mutation_wal"]
        self.assertIn("prepare_outreach", wal["automatic_reconciliation_tools"])
        self.assertIn("render_outreach_action_card", wal["automatic_reconciliation_tools"])
        recovery = wal["outreach_recovery"]
        self.assertTrue(recovery["successful_results_persist_exact_snapshot"])
        self.assertEqual(recovery["blocked_no_event_results"], "FAIL_CLOSED")
        self.assertEqual(
            recovery["same_render_token_distinct_keys"],
            "AT_MOST_ONE_SENDABLE_DRAFT",
        )
        self.assertFalse(recovery["server_side_send_capability"])
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["outreach_recovery"]["status"], "ENABLED")
        self.assertFalse(health["outreach_recovery"]["sends_message"])

    def test_prepare_crash_recovers_exact_ids_route_count_and_binding(self) -> None:
        investigation_id, arguments, _ = self._ready_outreach("C-OUTREACH-WAL-001")
        arguments = {**arguments, "idempotency_key": "prepare-outreach-crash-0001"}
        crashing = self._spawn("prepare_outreach")
        self._crash_call(crashing, 2, "prepare_outreach", arguments)
        prepared_events = [
            event for event in self._events(investigation_id)
            if event["event_type"] == "OUTREACH_PREPARED"
        ]
        self.assertEqual(len(prepared_events), 1)
        event = prepared_events[0]
        snapshot = event["payload"]["prepare_result_snapshot"]
        self.assertEqual(digest(snapshot), event["payload"]["prepare_result_sha256"])
        self.assertEqual(snapshot["canonical_route_match_count"], 1)

        process = self._spawn()
        recovered = self._tool(process, 3, "prepare_outreach", arguments)
        self.assertEqual(recovered["prepared_id"], event["payload"]["prepared_id"])
        self.assertEqual(recovered["render_token"], event["payload"]["render_token"])
        self.assertEqual(recovered["canonical_route_match_count"], 1)
        self.assertEqual(
            recovered["canonical_route_binding"],
            event["payload"]["canonical_route_binding"],
        )
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        replayed = self._tool(process, 4, "prepare_outreach", arguments)
        self.assertEqual(replayed["prepared_id"], recovered["prepared_id"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            sum(event["event_type"] == "OUTREACH_PREPARED" for event in self._events(investigation_id)),
            1,
        )

    def test_blocked_prepare_crash_has_no_event_and_remains_fail_closed(self) -> None:
        investigation_id, arguments, _ = self._ready_outreach("C-OUTREACH-WAL-002")
        bad_route = dict(arguments["route"])
        bad_route["value"] = "other@example.invalid"
        arguments = {
            **arguments,
            "route": bad_route,
            "idempotency_key": "prepare-outreach-blocked-crash-0001",
        }
        crashing = self._spawn("prepare_outreach")
        self._crash_call(crashing, 2, "prepare_outreach", arguments)
        self.assertEqual(
            sum(event["event_type"] == "OUTREACH_PREPARED" for event in self._events(investigation_id)),
            0,
        )
        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "prepare_outreach", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])

    def test_render_crash_recovers_exact_sendable_draft_without_second_render(self) -> None:
        investigation_id, _, prepared = self._prepare_normally(
            "C-OUTREACH-WAL-003",
            "render-crash",
        )
        arguments = {
            "investigation_id": investigation_id,
            "prepared_id": prepared["prepared_id"],
            "render_token": prepared["render_token"],
            "idempotency_key": "render-outreach-crash-0001",
        }
        crashing = self._spawn("render_outreach_action_card")
        self._crash_call(crashing, 3, "render_outreach_action_card", arguments)
        rendered_events = [
            event for event in self._events(investigation_id)
            if event["event_type"] == "OUTREACH_RENDERED"
        ]
        self.assertEqual(len(rendered_events), 1)
        event = rendered_events[0]
        snapshot = event["payload"]["render_result_snapshot"]
        self.assertEqual(digest(snapshot), event["payload"]["render_result_sha256"])
        self.assertEqual(snapshot["terminal_state"], "SENDABLE_DRAFT")
        self.assertFalse(snapshot["action"]["sends_message"])
        self.assertFalse(snapshot["server_side_draft_created"])

        process = self._spawn()
        recovered = self._tool(process, 4, "render_outreach_action_card", arguments)
        self.assertEqual(recovered["terminal_state"], "SENDABLE_DRAFT")
        self.assertEqual(recovered["action"]["url"], snapshot["action"]["url"])
        self.assertFalse(recovered["action"]["sends_message"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            sum(event["event_type"] == "OUTREACH_RENDERED" for event in self._events(investigation_id)),
            1,
        )

        other_key = {**arguments, "idempotency_key": "render-outreach-other-key-0001"}
        blocked = self._tool(process, 5, "render_outreach_action_card", other_key)
        self.assertEqual(blocked["terminal_state"], "DRAFT_BLOCKED")
        self.assertIn("RENDER_TOKEN_REPLAY", blocked["block_reasons"])
        self.assertEqual(
            sum(event["event_type"] == "OUTREACH_RENDERED" for event in self._events(investigation_id)),
            1,
        )

    def test_blocked_render_crash_has_no_event_and_remains_fail_closed(self) -> None:
        investigation_id, _, prepared = self._prepare_normally(
            "C-OUTREACH-WAL-004",
            "render-blocked",
        )
        arguments = {
            "investigation_id": investigation_id,
            "prepared_id": prepared["prepared_id"],
            "render_token": "RENDER-wrong-token-for-test",
            "idempotency_key": "render-outreach-blocked-crash-0001",
        }
        crashing = self._spawn("render_outreach_action_card")
        self._crash_call(crashing, 3, "render_outreach_action_card", arguments)
        self.assertEqual(
            sum(event["event_type"] == "OUTREACH_RENDERED" for event in self._events(investigation_id)),
            0,
        )
        process = self._spawn()
        response = self._rpc(
            process,
            4,
            "tools/call",
            {"name": "render_outreach_action_card", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])

    def test_two_distinct_keys_cannot_both_render_one_token(self) -> None:
        investigation_id, _, prepared = self._prepare_normally(
            "C-OUTREACH-WAL-005",
            "render-race",
        )
        process_a = self._spawn()
        process_b = self._spawn()
        base = {
            "investigation_id": investigation_id,
            "prepared_id": prepared["prepared_id"],
            "render_token": prepared["render_token"],
        }

        def invoke(process: subprocess.Popen[str], request_id: int, key: str) -> dict:
            return self._tool(
                process,
                request_id,
                "render_outreach_action_card",
                {**base, "idempotency_key": key},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(invoke, process_a, 3, "render-race-key-a-0001"),
                executor.submit(invoke, process_b, 3, "render-race-key-b-0001"),
            ]
            results = [future.result(timeout=15) for future in futures]
        terminals = sorted(result["terminal_state"] for result in results)
        self.assertEqual(terminals, ["DRAFT_BLOCKED", "SENDABLE_DRAFT"])
        sendable = next(result for result in results if result["terminal_state"] == "SENDABLE_DRAFT")
        self.assertFalse(sendable["action"]["sends_message"])
        self.assertEqual(
            sum(event["event_type"] == "OUTREACH_RENDERED" for event in self._events(investigation_id)),
            1,
        )

    def test_snapshotless_historical_prepare_crash_remains_fail_closed(self) -> None:
        investigation_id, arguments, _ = self._ready_outreach("C-OUTREACH-WAL-006")
        arguments = {**arguments, "idempotency_key": "prepare-outreach-old-event-0001"}
        crashing = self._spawn("prepare_outreach", server=PREVIOUS_SERVER)
        self._crash_call(crashing, 2, "prepare_outreach", arguments)
        event = next(
            event for event in self._events(investigation_id)
            if event["event_type"] == "OUTREACH_PREPARED"
        )
        self.assertIn("mutation_correlation", event)
        self.assertNotIn("prepare_result_snapshot", event["payload"])
        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "prepare_outreach", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])

    def test_snapshotless_historical_render_crash_remains_fail_closed(self) -> None:
        investigation_id, _, prepared = self._prepare_normally(
            "C-OUTREACH-WAL-007",
            "old-render-setup",
        )
        arguments = {
            "investigation_id": investigation_id,
            "prepared_id": prepared["prepared_id"],
            "render_token": prepared["render_token"],
            "idempotency_key": "render-outreach-old-event-0001",
        }
        crashing = self._spawn(
            "render_outreach_action_card",
            server=LEGACY_RENDER_SERVER,
        )
        self._crash_call(crashing, 3, "render_outreach_action_card", arguments)
        event = next(
            event for event in self._events(investigation_id)
            if event["event_type"] == "OUTREACH_RENDERED"
        )
        self.assertIn("mutation_correlation", event)
        self.assertNotIn("render_result_snapshot", event["payload"])
        process = self._spawn()
        response = self._rpc(
            process,
            4,
            "tools/call",
            {"name": "render_outreach_action_card", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
