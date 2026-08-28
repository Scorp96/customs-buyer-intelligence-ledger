from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61.py"


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

    def test_crash_after_handler_never_blindly_replays_mutation(self) -> None:
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
        assert crashing.stdin is not None and crashing.stdout is not None
        crashing.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "submit_research_objective",
                "arguments": objective_args,
            },
        }, ensure_ascii=True) + "\n")
        crashing.stdin.flush()
        self.assertEqual(crashing.stdout.readline(), "")
        crashing.wait(timeout=10)
        self.assertEqual(crashing.returncode, 91)
        for stream in (crashing.stdin, crashing.stdout, crashing.stderr):
            if stream is not None and not stream.closed:
                stream.close()

        wal_files = list((self.root / "mcp-idempotency-v61").glob("submit_research_objective-*.json"))
        self.assertEqual(len(wal_files), 1)
        wal = json.loads(wal_files[0].read_text(encoding="utf-8"))
        self.assertEqual(wal["status"], "PREPARED")
        self.assertEqual(wal["state_version_before"], before_version)

        recovered = self._spawn()
        replay = self._rpc(recovered, 5, "tools/call", {
            "name": "submit_research_objective",
            "arguments": objective_args,
        })
        self.assertIn("error", replay)
        self.assertIn(
            "MUTATION_RECONCILIATION_REQUIRED",
            str(replay["error"].get("message") or ""),
        )

        after = self._tool(
            recovered,
            6,
            "get_investigation_state",
            {"investigation_id": investigation_id},
        )
        self.assertEqual(after["objective_count"], 1)
        self.assertEqual(after["last_safe_seq"], before_version + 1)


if __name__ == "__main__":
    unittest.main()
