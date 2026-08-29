from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_correlated.py"


class V61MutationCorrelationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-mutation-correlation-")
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

    def _spawn(self, crash_after_handler: str = "") -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
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

    def _session_events(self, investigation_id: str) -> list[dict]:
        path = self.session_root / f"{investigation_id}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _start_provider_investigation(self, account_id: str) -> str:
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
            "provider_policy": {
                "mode": "CONNECTED_PROVIDERS_OPTIONAL",
                "allowed_providers": ["Synthetic Provider"],
                "required_capabilities": [],
                "cost_consent": False,
            },
            "idempotency_key": f"start-{account_id.lower()}-0001",
        })
        self._stop(process)
        return started["investigation_id"]

    def test_contract_and_health_expose_event_correlation_without_raw_key(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        correlation = contract["production_adapter_mutation_wal"]["durable_event_correlation"]
        self.assertTrue(correlation["enabled"])
        self.assertTrue(correlation["covers_session_store_events"])
        self.assertTrue(correlation["covers_sidecar_hash_chain_events"])
        self.assertFalse(correlation["correlation_contains_raw_idempotency_key"])
        self.assertFalse(correlation["historical_business_payloads_rewritten"])
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["mutation_event_correlation"]["status"], "ENABLED")
        self.assertFalse(
            health["mutation_event_correlation"]["correlation_contains_raw_idempotency_key"]
        )

    def test_start_binds_session_and_canonical_events_to_one_correlation(self) -> None:
        key = "correlated-start-fixture-0001"
        process = self._spawn()
        started = self._tool(process, 2, "start_investigation", {
            "account": {
                "account_id": "C-CORR-START-001",
                "country": "Canada",
                "name": "Synthetic Correlation Start Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": key,
        })
        investigation_id = started["investigation_id"]
        self._stop(process)

        events = self._session_events(investigation_id)
        start_event = events[0]
        correlation = start_event["mutation_correlation"]
        self.assertEqual(correlation["tool"], "start_investigation")
        self.assertTrue(correlation["correlation_id"].startswith("MUTCORR-"))
        self.assertNotIn("idempotency_key", correlation)
        self.assertNotIn(key, json.dumps(correlation, ensure_ascii=False))

        registry_path = self.session_root / ".runtime" / "canonical" / "accounts.jsonl"
        registry_events = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines()]
        created = next(
            event for event in registry_events
            if event["event_type"] == "CANONICAL_ACCOUNT_CREATED"
            and event["payload"]["account_id"] == "C-CORR-START-001"
        )
        self.assertEqual(created["mutation_correlation"], correlation)

    def test_random_provider_plan_event_is_exactly_bound_to_crashed_wal_intent(self) -> None:
        investigation_id = self._start_provider_investigation("C-CORR-PLAN-001")
        key = "correlated-provider-plan-0001"
        arguments = {
            "investigation_id": investigation_id,
            "requested_capabilities": ["email_enrichment"],
            "provider_inventory": [{
                "provider": "Synthetic Provider",
                "provider_class": "CONTACT_ENRICHMENT",
                "status": "CONNECTED",
                "capability_tools": {"email_enrichment": "synthetic_provider_tool"},
                "requires_paid_credit": False,
                "permissions": ["read synthetic data"],
            }],
            "cost_consent": False,
            "idempotency_key": key,
        }
        crashing = self._spawn("plan_provider_calls")
        self._crash_call(crashing, 3, "plan_provider_calls", arguments)

        events = self._session_events(investigation_id)
        plans = [event for event in events if event["event_type"] == "PROVIDER_PLAN_CREATED"]
        self.assertEqual(len(plans), 1)
        correlation = plans[0]["mutation_correlation"]
        self.assertEqual(correlation["tool"], "plan_provider_calls")
        self.assertTrue(correlation["correlation_id"].startswith("MUTCORR-"))
        self.assertNotIn(key, json.dumps(correlation, ensure_ascii=False))

        wal_files = list((self.root / "mcp-idempotency-v61").glob("plan_provider_calls-*.json"))
        self.assertEqual(len(wal_files), 1)
        wal = json.loads(wal_files[0].read_text(encoding="utf-8"))
        self.assertEqual(wal["status"], "PREPARED")
        self.assertEqual(wal["mutation_correlation_id"], correlation["correlation_id"])

        recovered = self._spawn()
        response = self._rpc(
            recovered,
            4,
            "tools/call",
            {"name": "plan_provider_calls", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        self.assertEqual(
            sum(event["event_type"] == "PROVIDER_PLAN_CREATED" for event in self._session_events(investigation_id)),
            1,
        )

    def test_same_provider_request_with_different_keys_has_distinct_correlations(self) -> None:
        investigation_id = self._start_provider_investigation("C-CORR-PLAN-002")
        base = {
            "investigation_id": investigation_id,
            "requested_capabilities": ["email_enrichment"],
            "provider_inventory": [{
                "provider": "Synthetic Provider",
                "provider_class": "CONTACT_ENRICHMENT",
                "status": "CONNECTED",
                "capability_tools": {"email_enrichment": "synthetic_provider_tool"},
                "requires_paid_credit": False,
                "permissions": ["read synthetic data"],
            }],
            "cost_consent": False,
        }
        process = self._spawn()
        first = self._tool(process, 3, "plan_provider_calls", {
            **base,
            "idempotency_key": "correlated-provider-plan-a-0001",
        })
        second = self._tool(process, 4, "plan_provider_calls", {
            **base,
            "idempotency_key": "correlated-provider-plan-b-0001",
        })
        self.assertNotEqual(first["plan_id"], second["plan_id"])
        self._stop(process)

        plans = [
            event for event in self._session_events(investigation_id)
            if event["event_type"] == "PROVIDER_PLAN_CREATED"
        ]
        self.assertEqual(len(plans), 2)
        correlation_ids = {
            event["mutation_correlation"]["correlation_id"]
            for event in plans
        }
        self.assertEqual(len(correlation_ids), 2)
        for event in plans:
            serialized = json.dumps(event["mutation_correlation"], ensure_ascii=False)
            self.assertNotIn("correlated-provider-plan-a-0001", serialized)
            self.assertNotIn("correlated-provider-plan-b-0001", serialized)


if __name__ == "__main__":
    unittest.main()
