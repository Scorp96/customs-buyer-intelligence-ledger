from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_entry.py"


class V61StartWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-start-wal-")
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
            raise AssertionError("crash-injected start unexpectedly returned a response")
        process.wait(timeout=10)
        if process.returncode != 91:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(
                f"crash-injected adapter exit code was {process.returncode}: {stderr}"
            )
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

    def _cleanup(self) -> None:
        for process in self.processes:
            self._stop(process)

    def test_start_crash_reuses_exact_session_and_never_duplicates_account(self) -> None:
        start_args = {
            "account": {
                "account_id": "C-WAL-START-SYNTH",
                "country": "Synthetic",
                "name": "Synthetic Start WAL Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": "wal-start-crash-0001",
        }

        crashing = self._spawn("start_investigation")
        self._crash_call(crashing, 2, "start_investigation", start_args)

        wal_files = list(
            (self.root / "mcp-idempotency-v61").glob("start_investigation-*.json")
        )
        self.assertEqual(len(wal_files), 1)
        wal = json.loads(wal_files[0].read_text(encoding="utf-8"))
        self.assertEqual(wal["status"], "PREPARED")
        self.assertEqual(
            wal["resource_snapshot_before"]["kind"],
            "START_INVESTIGATION",
        )
        self.assertEqual(
            wal["resource_snapshot_before"]["matching_investigation_ids_before"],
            [],
        )

        session_files = sorted(self.session_root.glob("INV-*.jsonl"))
        self.assertEqual(len(session_files), 1)
        investigation_id = session_files[0].stem
        first_event = json.loads(
            session_files[0].read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(
            first_event["payload"]["start_idempotency_key"],
            start_args["idempotency_key"],
        )

        canonical_log = (
            self.session_root / ".runtime" / "canonical" / "accounts.jsonl"
        )
        self.assertTrue(canonical_log.is_file())
        canonical_lines_before = canonical_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(canonical_lines_before), 1)

        recovered = self._spawn()
        contract = self._tool(recovered, 3, "get_runtime_contract", {})
        self.assertIn(
            "start_investigation",
            contract["production_adapter_mutation_wal"][
                "automatic_reconciliation_tools"
            ],
        )
        degraded = self._tool(recovered, 4, "get_runtime_health", {})
        self.assertEqual(degraded["status"], "DEGRADED_RECONCILIATION_REQUIRED")
        self.assertEqual(degraded["mutation_wal"]["prepared_count"], 1)
        self.assertTrue(
            degraded["mutation_wal"]["prepared_intents"][0][
                "automatic_reconciliation_supported"
            ]
        )

        replayed = self._tool(recovered, 5, "start_investigation", start_args)
        self.assertEqual(replayed["investigation_id"], investigation_id)
        self.assertFalse(replayed["resumed_existing"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "START_IDEMPOTENCY_KEY_AND_SESSION_HEADER",
        )

        self.assertEqual(len(list(self.session_root.glob("INV-*.jsonl"))), 1)
        canonical_lines_after = canonical_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(canonical_lines_after, canonical_lines_before)

        healthy = self._tool(recovered, 6, "get_runtime_health", {})
        self.assertEqual(healthy["mutation_wal"]["prepared_count"], 0)
        self.assertFalse(healthy["mutation_wal"]["reconciliation_required"])

        replay_again = self._tool(recovered, 7, "start_investigation", start_args)
        self.assertEqual(replay_again["investigation_id"], investigation_id)
        self.assertTrue(replay_again["mutation_meta"]["replayed"])
        self.assertEqual(len(list(self.session_root.glob("INV-*.jsonl"))), 1)


if __name__ == "__main__":
    unittest.main()
