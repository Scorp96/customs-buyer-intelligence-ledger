from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61.py"


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class V61AdapterWalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-adapter-wal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.host_root = self.root / "host-pending"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup_processes)

    def _environment(self, crash_after_handler: str = "") -> dict[str, str]:
        environment = dict(os.environ)
        environment.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.host_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if crash_after_handler:
            environment["CBI_V61_TEST_CRASH_AFTER_HANDLER"] = crash_after_handler
        else:
            environment.pop("CBI_V61_TEST_CRASH_AFTER_HANDLER", None)
        return environment

    def _spawn(self, crash_after_handler: str = "") -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._environment(crash_after_handler),
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
            raise RuntimeError(f"adapter ended before response: {stderr}")
        return json.loads(line)

    def _tool(
        self,
        process: subprocess.Popen[str],
        request_id: int,
        name: str,
        arguments: dict,
    ) -> dict:
        response = self._rpc(process, request_id, "tools/call", {
            "name": name,
            "arguments": arguments,
        })
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
            raise AssertionError("crash-injected mutation unexpectedly returned a response")
        process.wait(timeout=10)
        if process.returncode != 91:
            raise AssertionError(f"crash-injected adapter exit code was {process.returncode}")
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            if process.stdin is not None:
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

    def _cleanup_processes(self) -> None:
        for process in self.processes:
            self._stop(process)

    def test_objective_crash_is_mechanically_reconciled_without_duplicate(self) -> None:
        bootstrap = self._spawn()
        start_args = {
            "account": {
                "account_id": "C-WAL-SYNTH",
                "country": "Synthetic",
                "name": "Synthetic WAL Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": "wal-start-0001",
        }
        started = self._tool(bootstrap, 2, "start_investigation", start_args)
        investigation_id = started["investigation_id"]
        state = self._tool(
            bootstrap,
            3,
            "get_investigation_state",
            {"investigation_id": investigation_id},
        )
        before_version = int(state["last_safe_seq"])
        self._stop(bootstrap)

        objective_args = {
            "investigation_id": investigation_id,
            "expected_state_version": before_version,
            "idempotency_key": "wal-objective-crash-0001",
            "objective": {
                "claim_key": "identity.legal_entity",
                "query_or_navigation": "Verify synthetic WAL legal entity fixture",
                "source_family": "synthetic_official",
            },
        }

        crashing = self._spawn("submit_research_objective")
        self._crash_call(crashing, 4, "submit_research_objective", objective_args)

        wal_files = list((self.root / "mcp-idempotency-v61").glob("submit_research_objective-*.json"))
        self.assertEqual(len(wal_files), 1)
        wal = json.loads(wal_files[0].read_text(encoding="utf-8"))
        self.assertEqual(wal["status"], "PREPARED")
        self.assertEqual(wal["state_version_before"], before_version)

        recovered = self._spawn()
        contract = self._tool(recovered, 5, "get_runtime_contract", {})
        wal_contract = contract["production_adapter_mutation_wal"]
        self.assertTrue(wal_contract["write_ahead_intent_required"])
        self.assertFalse(wal_contract["prepared_auto_replay_without_proof"])
        for tool_name in {
            "submit_research_objective",
            "resolve_or_create_account",
            "queue_host_bundle",
        }:
            self.assertIn(tool_name, wal_contract["automatic_reconciliation_tools"])
        self.assertFalse(wal_contract["exact_automatic_reconciliation_complete"])

        degraded = self._tool(recovered, 6, "get_runtime_health", {})
        self.assertEqual(degraded["status"], "DEGRADED_RECONCILIATION_REQUIRED")
        self.assertEqual(degraded["mutation_wal"]["prepared_count"], 1)
        self.assertTrue(degraded["mutation_wal"]["reconciliation_required"])
        self.assertTrue(
            degraded["mutation_wal"]["prepared_intents"][0]["automatic_reconciliation_supported"]
        )

        replayed = self._tool(
            recovered,
            7,
            "submit_research_objective",
            objective_args,
        )
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "OBJECTIVE_ID_INPUT_HASH_AND_EVENT_SEQ",
        )

        after = self._tool(
            recovered,
            8,
            "get_investigation_state",
            {"investigation_id": investigation_id},
        )
        self.assertEqual(after["objective_count"], 1)
        self.assertEqual(after["last_safe_seq"], before_version + 1)

        healthy = self._tool(recovered, 9, "get_runtime_health", {})
        self.assertEqual(healthy["mutation_wal"]["prepared_count"], 0)
        self.assertFalse(healthy["mutation_wal"]["reconciliation_required"])

    def test_canonical_create_crash_is_reconciled_from_registry_tail(self) -> None:
        args = {
            "candidate": {
                "account_id": "C-WAL-CANONICAL",
                "country": "Synthetic",
                "name": "Synthetic Canonical WAL Buyer",
            },
            "requested_account_id": "C-WAL-CANONICAL",
            "create_if_missing": True,
            "idempotency_key": "wal-canonical-crash-0001",
        }
        crashing = self._spawn("resolve_or_create_account")
        self._crash_call(crashing, 2, "resolve_or_create_account", args)

        canonical_log = self.session_root / ".runtime" / "canonical" / "accounts.jsonl"
        self.assertTrue(canonical_log.is_file())
        self.assertEqual(len(canonical_log.read_text(encoding="utf-8").splitlines()), 1)

        recovered = self._spawn()
        replayed = self._tool(recovered, 3, "resolve_or_create_account", args)
        self.assertEqual(replayed["status"], "CREATED")
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "CANONICAL_ACCOUNT_CREATED_AFTER_PREPARED_REGISTRY_TAIL",
        )
        self.assertEqual(len(canonical_log.read_text(encoding="utf-8").splitlines()), 1)
        health = self._tool(recovered, 4, "get_runtime_health", {})
        self.assertEqual(health["mutation_wal"]["prepared_count"], 0)

    def test_host_queue_crash_is_reconciled_from_persisted_request_hash(self) -> None:
        args = {
            "bundle_queue_id": "HOSTQ-20260828T000000Z-abcdef123456",
            "payload": {
                "investigation_id": "INV-WAL-HOST-QUEUE-SYNTH",
                "bundle": {
                    "bundle_id": "BUNDLE-WAL-HOST-QUEUE",
                    "observations": [],
                },
            },
            "idempotency_key": "wal-host-queue-crash-0001",
        }
        crashing = self._spawn("queue_host_bundle")
        self._crash_call(crashing, 2, "queue_host_bundle", args)
        queue_files = list(self.host_root.glob("HOSTQ-*.json"))
        self.assertEqual(len(queue_files), 1)

        recovered = self._spawn()
        replayed = self._tool(recovered, 3, "queue_host_bundle", args)
        self.assertTrue(replayed["queued"])
        self.assertFalse(replayed["deduplicated"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "HOST_QUEUE_REQUEST_HASH_PERSISTED_AFTER_PREPARED",
        )
        self.assertEqual(len(list(self.host_root.glob("HOSTQ-*.json"))), 1)
        health = self._tool(recovered, 4, "get_runtime_health", {})
        self.assertEqual(health["mutation_wal"]["prepared_count"], 0)

    def test_unknown_prepared_mutation_family_stays_fail_closed(self) -> None:
        bootstrap = self._spawn()
        self._stop(bootstrap)
        args = {
            "investigation_id": "INV-UNPROVEN-PROMOTION",
            "peer_id": "PEER-UNPROVEN",
            "promotion_reason": "Synthetic unproven PREPARED fixture for adapter fail-closed behavior.",
            "idempotency_key": "wal-unproven-promote-0001",
        }
        request_arguments = {
            key: value for key, value in args.items() if key != "idempotency_key"
        }
        request_hash = digest({
            "tool": "promote_anchor",
            "arguments": request_arguments,
        })
        wal_root = self.root / "mcp-idempotency-v61"
        wal_root.mkdir(parents=True, exist_ok=True)
        wal_path = wal_root / (
            "promote_anchor-"
            + hashlib.sha256(args["idempotency_key"].encode("utf-8")).hexdigest()
            + ".json"
        )
        wal_path.write_text(
            canonical({
                "schema": "cbi.mutation-wal.v6.1",
                "status": "PREPARED",
                "tool": "promote_anchor",
                "idempotency_key": args["idempotency_key"],
                "request_sha256": request_hash,
                "state_version_before": 0,
                "prepared_at": "2026-08-28T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )

        recovered = self._spawn()
        response = self._rpc(recovered, 2, "tools/call", {
            "name": "promote_anchor",
            "arguments": args,
        })
        self.assertIn("error", response)
        self.assertIn(
            "MUTATION_RECONCILIATION_REQUIRED",
            str(response["error"].get("message") or ""),
        )
        health = self._tool(recovered, 3, "get_runtime_health", {})
        self.assertEqual(health["status"], "DEGRADED_RECONCILIATION_REQUIRED")
        self.assertEqual(health["mutation_wal"]["prepared_count"], 1)
        self.assertFalse(
            health["mutation_wal"]["prepared_intents"][0]["automatic_reconciliation_supported"]
        )


if __name__ == "__main__":
    unittest.main()
