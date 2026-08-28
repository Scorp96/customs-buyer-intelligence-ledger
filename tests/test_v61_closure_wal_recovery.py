from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime.resilience import digest
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_closure_recovery.py"
PREVIOUS_SERVER = ROOT / "mcp" / "server_v61_provider_recovery.py"


class V61ClosureWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-closure-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.host_root = self.root / "host-pending"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)

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

    def _wal_for_key(self, key: str) -> dict:
        root = self.root / "mcp-idempotency-v61"
        for path in root.glob("*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("idempotency_key") == key:
                return row
        raise AssertionError(f"WAL row not found for {key}")

    def _start(self, account_id: str) -> tuple[str, str]:
        process = self._spawn()
        started = self._tool(process, 2, "start_investigation", {
            "account": {
                "account_id": account_id,
                "country": "Canada",
                "name": f"Synthetic {account_id}",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": f"start-{account_id.lower()}-0001",
        })
        self._stop(process)
        return started["investigation_id"], account_id

    @staticmethod
    def _observation(claim_key: str, account_id: str, index: int) -> dict:
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
        return {
            "claim_key": claim_key,
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": account_id,
            "value": value,
            "source": {
                "source_family": "synthetic_official",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": f"https://example.invalid/closure/{index}",
                "locator": f"https://example.invalid/closure/{index}#record",
                "raw_excerpt": f"Synthetic Closure Evidence {index}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT",
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": "Synthetic test fixture only; no live-company fact is asserted.",
            "pivots": [],
        }

    def _saturate(self, investigation_id: str, account_id: str, suffix: str) -> dict:
        process = self._spawn()
        observations = [
            self._observation(claim_key, account_id, index)
            for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG)
        ]
        compiled = self._tool(process, 2, "compile_and_append_research_bundle", {
            "investigation_id": investigation_id,
            "bundle": {
                "bundle_id": f"BUNDLE-CLOSURE-{suffix}",
                "observations": observations,
            },
            "idempotency_key": f"compile-closure-{suffix}-0001",
        })
        self.assertEqual(compiled["rejected_count"], 0)
        saturation = self._tool(
            process,
            3,
            "evaluate_decision_saturation",
            {"investigation_id": investigation_id},
        )
        self.assertTrue(saturation["decision_saturated"], saturation)
        self.assertEqual(saturation["blockers"], [])
        self._stop(process)
        return saturation

    @staticmethod
    def _closure_args(investigation_id: str, key: str) -> dict:
        return {
            "investigation_id": investigation_id,
            "idempotency_key": key,
        }

    def test_contract_exposes_strict_closure_issuance_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        wal = contract["production_adapter_mutation_wal"]
        self.assertIn("evaluate_investigation_closure", wal["automatic_reconciliation_tools"])
        recovery = wal["closure_issuance_recovery"]
        self.assertTrue(recovery["enabled"])
        self.assertTrue(recovery["new_correlated_closure_issuance_only"])
        self.assertTrue(recovery["persists_exact_decision_saturation_snapshot"])
        self.assertEqual(recovery["unsaturated_no_event_result"], "FAIL_CLOSED")
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["closure_issuance_recovery"]["status"], "ENABLED")

    def test_new_closure_crash_recovers_exact_random_closure_and_snapshot(self) -> None:
        investigation_id, account_id = self._start("C-CLOSURE-WAL-001")
        expected_saturation = self._saturate(investigation_id, account_id, "exact")
        key = "closure-recovery-exact-0001"
        arguments = self._closure_args(investigation_id, key)
        crashing = self._spawn("evaluate_investigation_closure")
        self._crash_call(crashing, 4, "evaluate_investigation_closure", arguments)

        closures = [event for event in self._events(investigation_id) if event["event_type"] == "CLOSURE_ISSUED"]
        self.assertEqual(len(closures), 1)
        event = closures[0]
        payload = event["payload"]
        self.assertEqual(payload["decision_saturation_snapshot"], expected_saturation)
        self.assertEqual(digest(payload["decision_saturation_snapshot"]), payload["decision_saturation_sha256"])
        self.assertEqual(payload["basis_hash"], event["prev_hash"])
        wal = self._wal_for_key(key)
        self.assertEqual(wal["status"], "PREPARED")
        self.assertEqual(
            wal["mutation_correlation_id"],
            event["mutation_correlation"]["correlation_id"],
        )

        recovered_process = self._spawn()
        recovered = self._tool(recovered_process, 5, "evaluate_investigation_closure", arguments)
        self.assertEqual(recovered["closure_id"], payload["closure_id"])
        self.assertEqual(recovered["closure_expires_at"], payload["expires_at"])
        self.assertEqual(recovered["decision_saturation"], expected_saturation)
        self.assertFalse(recovered["reused_evaluation_receipt"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            recovered["mutation_meta"]["reconciliation_proof"],
            "CORRELATED_CLOSURE_EVENT_WITH_SATURATION_SNAPSHOT",
        )
        replayed = self._tool(recovered_process, 6, "evaluate_investigation_closure", arguments)
        self.assertEqual(replayed["closure_id"], payload["closure_id"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            sum(event["event_type"] == "CLOSURE_ISSUED" for event in self._events(investigation_id)),
            1,
        )

    def test_recovery_uses_issuance_snapshot_even_after_later_state_change(self) -> None:
        investigation_id, account_id = self._start("C-CLOSURE-WAL-002")
        expected_saturation = self._saturate(investigation_id, account_id, "later-state")
        key = "closure-recovery-later-state-0001"
        arguments = self._closure_args(investigation_id, key)
        crashing = self._spawn("evaluate_investigation_closure")
        self._crash_call(crashing, 4, "evaluate_investigation_closure", arguments)
        closure_event = next(
            event for event in self._events(investigation_id)
            if event["event_type"] == "CLOSURE_ISSUED"
        )

        mutating = self._spawn()
        objective = self._tool(mutating, 5, "submit_research_objective", {
            "investigation_id": investigation_id,
            "objective": {
                "objective_id": "OBJ-CLOSURE-POST-CRASH-001",
                "claim_key": "identity.legal_entity",
                "query_or_navigation": "synthetic post-crash objective",
                "source_family": "synthetic_official",
                "probability": 0.5,
                "decision_impact": 0.5,
                "evidence_quality_gain": 0.5,
                "commercial_weight": 1.0,
                "search_cost": 1.0,
            },
            "idempotency_key": "closure-post-crash-objective-0001",
        })
        self.assertTrue(objective["accepted"])
        self.assertGreater(self._events(investigation_id)[-1]["seq"], closure_event["seq"])

        recovered = self._tool(mutating, 6, "evaluate_investigation_closure", arguments)
        self.assertEqual(recovered["closure_id"], closure_event["payload"]["closure_id"])
        self.assertEqual(recovered["decision_saturation"], expected_saturation)
        self.assertEqual(
            recovered["decision_saturation"],
            closure_event["payload"]["decision_saturation_snapshot"],
        )
        self.assertEqual(
            sum(event["event_type"] == "CLOSURE_ISSUED" for event in self._events(investigation_id)),
            1,
        )

    def test_snapshotless_correlated_historical_closure_remains_fail_closed(self) -> None:
        investigation_id, account_id = self._start("C-CLOSURE-WAL-003")
        self._saturate(investigation_id, account_id, "snapshotless")
        key = "closure-recovery-snapshotless-0001"
        arguments = self._closure_args(investigation_id, key)
        crashing = self._spawn(
            "evaluate_investigation_closure",
            server=PREVIOUS_SERVER,
        )
        self._crash_call(crashing, 4, "evaluate_investigation_closure", arguments)
        closure_event = next(
            event for event in self._events(investigation_id)
            if event["event_type"] == "CLOSURE_ISSUED"
        )
        self.assertIn("mutation_correlation", closure_event)
        self.assertNotIn("decision_saturation_snapshot", closure_event["payload"])

        recovered_process = self._spawn()
        response = self._rpc(
            recovered_process,
            5,
            "tools/call",
            {"name": "evaluate_investigation_closure", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        self.assertEqual(
            sum(event["event_type"] == "CLOSURE_ISSUED" for event in self._events(investigation_id)),
            1,
        )

    def test_unsaturated_no_event_crash_remains_fail_closed(self) -> None:
        investigation_id, _ = self._start("C-CLOSURE-WAL-004")
        key = "closure-recovery-unsaturated-0001"
        arguments = self._closure_args(investigation_id, key)
        crashing = self._spawn("evaluate_investigation_closure")
        self._crash_call(crashing, 3, "evaluate_investigation_closure", arguments)
        self.assertEqual(
            sum(event["event_type"] == "CLOSURE_ISSUED" for event in self._events(investigation_id)),
            0,
        )

        recovered_process = self._spawn()
        response = self._rpc(
            recovered_process,
            4,
            "tools/call",
            {"name": "evaluate_investigation_closure", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])

    def test_reused_existing_closure_no_event_crash_remains_fail_closed(self) -> None:
        investigation_id, account_id = self._start("C-CLOSURE-WAL-005")
        self._saturate(investigation_id, account_id, "reused")
        process = self._spawn()
        first = self._tool(process, 4, "evaluate_investigation_closure", self._closure_args(
            investigation_id,
            "closure-first-issued-0001",
        ))
        self.assertTrue(first["closed"])
        self.assertFalse(first["reused_evaluation_receipt"])
        self._stop(process)

        key = "closure-reused-crash-0001"
        arguments = self._closure_args(investigation_id, key)
        crashing = self._spawn("evaluate_investigation_closure")
        self._crash_call(crashing, 5, "evaluate_investigation_closure", arguments)
        self.assertEqual(
            sum(event["event_type"] == "CLOSURE_ISSUED" for event in self._events(investigation_id)),
            1,
        )

        recovered_process = self._spawn()
        response = self._rpc(
            recovered_process,
            6,
            "tools/call",
            {"name": "evaluate_investigation_closure", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        self.assertEqual(
            sum(event["event_type"] == "CLOSURE_ISSUED" for event in self._events(investigation_id)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
