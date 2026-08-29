from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_recovery.py"


class V61QueueCorrelationWalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-queue-correlation-")
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
            raise RuntimeError(f"adapter ended before response: {stderr}")
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

    def _start(self, account_id: str) -> str:
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
        return started["investigation_id"]

    @staticmethod
    def _hash_chain_event_count(path: Path, event_type: str) -> int:
        if not path.is_file():
            return 0
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return sum(row.get("event_type") == event_type for row in rows)

    def test_contract_exposes_strict_pending_queue_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        automatic = set(contract["production_adapter_mutation_wal"]["automatic_reconciliation_tools"])
        self.assertIn("queue_pending_receipt", automatic)
        self.assertIn("queue_host_bundle", automatic)
        self.assertNotIn("plan_provider_calls", automatic)

    def test_pending_queue_crash_recovers_only_adapter_derived_id(self) -> None:
        investigation_id = self._start("C-WAL-PENDING-STRICT")
        arguments = {
            "target_tool": "append_information_record",
            "payload": {
                "investigation_id": investigation_id,
                "record": {"information_id": "INFO-PENDING-STRICT-001"},
            },
            "idempotency_key": "wal-pending-strict-0001",
        }
        crashing = self._spawn("queue_pending_receipt")
        self._crash_call(crashing, 3, "queue_pending_receipt", arguments)

        recovered = self._spawn()
        replayed = self._tool(recovered, 4, "queue_pending_receipt", arguments)
        self.assertTrue(replayed["journal_id"].startswith("PEND-00000000T000000Z-"))
        self.assertTrue(replayed["queued"])
        self.assertFalse(replayed["deduplicated"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "WAL_DERIVED_PENDING_ID_AND_QUEUED_EVENT",
        )
        status = self._tool(
            recovered,
            5,
            "get_pending_journal_status",
            {"investigation_id": investigation_id},
        )
        self.assertEqual(len(status["entries"]), 1)
        pending_events = self.session_root / ".runtime" / "pending" / "journal-events.jsonl"
        self.assertEqual(
            self._hash_chain_event_count(pending_events, "PENDING_RECEIPT_QUEUED"),
            1,
        )

    def test_host_queue_crash_recovers_only_adapter_derived_id(self) -> None:
        investigation_id = self._start("C-WAL-HOST-STRICT")
        arguments = {
            "payload": {
                "investigation_id": investigation_id,
                "bundle": {"bundle_id": "BUNDLE-HOST-STRICT-001"},
            },
            "idempotency_key": "wal-host-strict-0001",
        }
        crashing = self._spawn("queue_host_bundle")
        self._crash_call(crashing, 3, "queue_host_bundle", arguments)

        recovered = self._spawn()
        replayed = self._tool(recovered, 4, "queue_host_bundle", arguments)
        self.assertTrue(replayed["bundle_queue_id"].startswith("HOSTQ-00000000T000000Z-"))
        self.assertTrue(replayed["queued"])
        self.assertFalse(replayed["deduplicated"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "WAL_DERIVED_HOST_ID_AND_QUEUED_EVENT",
        )
        host_events = self.host_root / "queue-events.jsonl"
        self.assertEqual(
            self._hash_chain_event_count(host_events, "HOST_BUNDLE_QUEUED"),
            1,
        )

    def test_explicit_queue_ids_remain_fail_closed_after_crash(self) -> None:
        investigation_id = self._start("C-WAL-QUEUE-EXPLICIT")
        arguments = {
            "payload": {
                "investigation_id": investigation_id,
                "bundle": {"bundle_id": "BUNDLE-HOST-EXPLICIT-001"},
            },
            "bundle_queue_id": "HOSTQ-20260828T000000Z-abcdef123456",
            "idempotency_key": "wal-host-explicit-0001",
        }
        crashing = self._spawn("queue_host_bundle")
        self._crash_call(crashing, 3, "queue_host_bundle", arguments)

        recovered = self._spawn()
        response = self._rpc(
            recovered,
            4,
            "tools/call",
            {"name": "queue_host_bundle", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        host_events = self.host_root / "queue-events.jsonl"
        self.assertEqual(
            self._hash_chain_event_count(host_events, "HOST_BUNDLE_QUEUED"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
