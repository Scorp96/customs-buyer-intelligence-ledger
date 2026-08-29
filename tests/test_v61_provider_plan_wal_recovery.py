from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_provider_recovery.py"
UNCORRELATED_SERVER = ROOT / "mcp" / "server_v61_recovery.py"


class V61ProviderPlanWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-provider-plan-recovery-")
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

    def _wal_rows(self) -> list[dict]:
        root = self.root / "mcp-idempotency-v61"
        if not root.is_dir():
            return []
        return [json.loads(path.read_text(encoding="utf-8")) for path in root.glob("*.json")]

    def _start(self, account_id: str, provider_mode: str) -> str:
        process = self._spawn()
        provider_policy: dict = {
            "mode": provider_mode,
            "allowed_providers": [],
            "required_capabilities": [],
            "cost_consent": False,
        }
        if provider_mode != "PUBLIC_ONLY":
            provider_policy["allowed_providers"] = ["Synthetic Provider"]
        started = self._tool(process, 2, "start_investigation", {
            "account": {
                "account_id": account_id,
                "country": "Canada",
                "name": f"Synthetic {account_id}",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "provider_policy": provider_policy,
            "idempotency_key": f"start-{account_id.lower()}-0001",
        })
        self._stop(process)
        return started["investigation_id"]

    @staticmethod
    def _connected_plan_args(investigation_id: str, key: str) -> dict:
        return {
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

    def test_contract_exposes_provider_plan_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        wal = contract["production_adapter_mutation_wal"]
        self.assertIn("plan_provider_calls", wal["automatic_reconciliation_tools"])
        recovery = wal["provider_plan_recovery"]
        self.assertTrue(recovery["enabled"])
        self.assertTrue(recovery["requires_exact_event_correlation_for_random_plan_ids"])
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["provider_plan_recovery"]["status"], "ENABLED")

    def test_connected_provider_plan_crash_recovers_exact_random_plan(self) -> None:
        investigation_id = self._start("C-PPLAN-CONN-001", "CONNECTED_PROVIDERS_OPTIONAL")
        key = "provider-plan-recovery-connected-0001"
        arguments = self._connected_plan_args(investigation_id, key)
        crashing = self._spawn("plan_provider_calls")
        self._crash_call(crashing, 3, "plan_provider_calls", arguments)

        plans = [event for event in self._events(investigation_id) if event["event_type"] == "PROVIDER_PLAN_CREATED"]
        self.assertEqual(len(plans), 1)
        persisted = plans[0]["payload"]
        self.assertTrue(persisted["plan_id"].startswith("PPLAN-"))
        wal = next(row for row in self._wal_rows() if row.get("idempotency_key") == key)
        self.assertEqual(wal["status"], "PREPARED")
        self.assertEqual(
            wal["mutation_correlation_id"],
            plans[0]["mutation_correlation"]["correlation_id"],
        )

        recovered_process = self._spawn()
        recovered = self._tool(recovered_process, 4, "plan_provider_calls", arguments)
        self.assertEqual(recovered["plan_id"], persisted["plan_id"])
        self.assertEqual(recovered["calls"], persisted["calls"])
        self.assertEqual(recovered["issued_at"], persisted["issued_at"])
        self.assertEqual(recovered["expires_at"], persisted["expires_at"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            recovered["mutation_meta"]["reconciliation_proof"],
            "CORRELATED_PROVIDER_PLAN_EVENT_AND_REQUEST_MATERIAL",
        )
        replayed = self._tool(recovered_process, 5, "plan_provider_calls", arguments)
        self.assertEqual(replayed["plan_id"], persisted["plan_id"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            sum(event["event_type"] == "PROVIDER_PLAN_CREATED" for event in self._events(investigation_id)),
            1,
        )

    def test_same_content_other_key_cannot_be_stolen_during_recovery(self) -> None:
        investigation_id = self._start("C-PPLAN-CONN-002", "CONNECTED_PROVIDERS_OPTIONAL")
        key_a = "provider-plan-recovery-key-a-0001"
        key_b = "provider-plan-recovery-key-b-0001"
        args_a = self._connected_plan_args(investigation_id, key_a)
        crashing = self._spawn("plan_provider_calls")
        self._crash_call(crashing, 3, "plan_provider_calls", args_a)

        normal = self._spawn()
        result_b = self._tool(
            normal,
            4,
            "plan_provider_calls",
            self._connected_plan_args(investigation_id, key_b),
        )
        wal_a = next(row for row in self._wal_rows() if row.get("idempotency_key") == key_a)
        plans = [event for event in self._events(investigation_id) if event["event_type"] == "PROVIDER_PLAN_CREATED"]
        plan_a = next(
            event for event in plans
            if event.get("mutation_correlation", {}).get("correlation_id") == wal_a["mutation_correlation_id"]
        )
        self.assertNotEqual(plan_a["payload"]["plan_id"], result_b["plan_id"])

        recovered = self._tool(normal, 5, "plan_provider_calls", args_a)
        self.assertEqual(recovered["plan_id"], plan_a["payload"]["plan_id"])
        self.assertNotEqual(recovered["plan_id"], result_b["plan_id"])
        self.assertEqual(len([event for event in self._events(investigation_id) if event["event_type"] == "PROVIDER_PLAN_CREATED"]), 2)

    def test_public_only_plan_crash_recovers_deterministic_no_side_effect_result(self) -> None:
        investigation_id = self._start("C-PPLAN-PUBLIC-001", "PUBLIC_ONLY")
        key = "provider-plan-recovery-public-only-0001"
        arguments = {
            "investigation_id": investigation_id,
            "requested_capabilities": ["email_enrichment", "company_lookup"],
            "provider_inventory": [],
            "cost_consent": False,
            "idempotency_key": key,
        }
        crashing = self._spawn("plan_provider_calls")
        self._crash_call(crashing, 3, "plan_provider_calls", arguments)
        self.assertEqual(
            sum(event["event_type"] == "PROVIDER_PLAN_CREATED" for event in self._events(investigation_id)),
            0,
        )

        recovered_process = self._spawn()
        recovered = self._tool(recovered_process, 4, "plan_provider_calls", arguments)
        self.assertEqual(recovered["status"], "PROVIDER_USE_DISABLED")
        self.assertEqual(recovered["provider_mode"], "PUBLIC_ONLY")
        self.assertIsNone(recovered["plan_id"])
        self.assertEqual(recovered["calls"], [])
        self.assertEqual(recovered["missing_capabilities"], ["company_lookup", "email_enrichment"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            recovered["mutation_meta"]["reconciliation_proof"],
            "IMMUTABLE_PUBLIC_ONLY_POLICY_AND_REQUEST",
        )

    def test_uncorrelated_connected_prepared_intent_remains_fail_closed(self) -> None:
        investigation_id = self._start("C-PPLAN-LEGACY-001", "CONNECTED_PROVIDERS_OPTIONAL")
        key = "provider-plan-legacy-prepared-0001"
        arguments = self._connected_plan_args(investigation_id, key)
        crashing = self._spawn(
            "plan_provider_calls",
            server=UNCORRELATED_SERVER,
        )
        self._crash_call(crashing, 3, "plan_provider_calls", arguments)
        wal = next(row for row in self._wal_rows() if row.get("idempotency_key") == key)
        self.assertEqual(wal["status"], "PREPARED")
        self.assertNotIn("mutation_correlation_id", wal)

        recovered_process = self._spawn()
        response = self._rpc(
            recovered_process,
            4,
            "tools/call",
            {"name": "plan_provider_calls", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        self.assertEqual(
            sum(event["event_type"] == "PROVIDER_PLAN_CREATED" for event in self._events(investigation_id)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
