from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_bundle_recovery.py"


class V61BundleWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-bundle-wal-")
        self.addCleanup(self.temp.cleanup)
        self.session_root = Path(self.temp.name) / "sessions"
        self.host_root = Path(self.temp.name) / "host-pending"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)
        self.runtime = UnifiedRuntime(self.session_root)
        start = self.runtime.start_investigation({
            "account": {
                "account_id": "C-BUNDLE-WAL",
                "country": "Synthetic",
                "name": "Synthetic Bundle WAL Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "A",
        })
        self.investigation_id = start["investigation_id"]

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

    def _events(self) -> list[dict]:
        path = self.session_root / f"{self.investigation_id}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _arguments(self, bundle_id: str, key: str = "") -> dict:
        arguments = {
            "investigation_id": self.investigation_id,
            "bundle": {
                "bundle_id": bundle_id,
                "observations": [{
                    "claim_key": "product.fit",
                    "result": "POSITIVE",
                    "owner_type": "ACCOUNT",
                    "owner_id": "C-BUNDLE-WAL",
                    "value": {"fixture": bundle_id},
                    "source": {
                        "source_family": "synthetic_official",
                        "source_type": "OFFICIAL",
                        "reference_type": "PUBLIC_URL",
                        "url": f"https://evidence.example.invalid/{bundle_id.lower()}",
                        "locator": f"https://evidence.example.invalid/{bundle_id.lower()}#fact",
                        "raw_excerpt": f"Synthetic bundle WAL fixture {bundle_id}",
                        "authority_level": "A1_OFFICIAL_PRIMARY",
                        "freshness": "CURRENT",
                        "observed_at": "2026-08-28T00:00:00Z",
                    },
                    "boundary": "Synthetic bundle WAL fixture only.",
                    "pivots": [],
                }],
            },
        }
        if key:
            arguments["idempotency_key"] = key
        return arguments

    def test_contract_exposes_bundle_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        wal = contract["production_adapter_mutation_wal"]
        recovery = wal["research_bundle_recovery"]
        self.assertTrue(recovery["enabled"])
        self.assertTrue(recovery["requires_exact_event_correlation"])
        self.assertTrue(recovery["requires_final_bundle_summary"])
        self.assertFalse(recovery["reexecutes_compiler"])
        self.assertIn(
            "compile_and_append_research_bundle",
            wal["automatic_reconciliation_tools"],
        )
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["research_bundle_recovery"]["status"], "ENABLED")

    def test_new_bundle_crash_recovers_exact_summary_without_duplicate(self) -> None:
        arguments = self._arguments(
            "BUNDLE-WAL-NEW-001",
            "compile-bundle-crash-0001",
        )
        crashing = self._spawn("compile_and_append_research_bundle")
        self._crash_call(
            crashing,
            2,
            "compile_and_append_research_bundle",
            arguments,
        )
        events = self._events()
        summaries = [
            event for event in events
            if event["event_type"] == "V6_RESEARCH_BUNDLE_COMPILED"
        ]
        observations = [
            event for event in events
            if event["event_type"] == "V6_OBSERVATION_COMPILED"
        ]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(len(observations), 1)
        summary = summaries[0]["payload"]
        self.assertIn("mutation_correlation", summaries[0])

        process = self._spawn()
        recovered = self._tool(
            process,
            3,
            "compile_and_append_research_bundle",
            arguments,
        )
        self.assertEqual(recovered["bundle_id"], summary["bundle_id"])
        self.assertEqual(recovered["input_sha256"], summary["input_sha256"])
        self.assertEqual(recovered["outcomes"], summary["outcomes"])
        self.assertFalse(recovered["idempotent_replay"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])

        replayed = self._tool(
            process,
            4,
            "compile_and_append_research_bundle",
            arguments,
        )
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        events_after = self._events()
        self.assertEqual(
            sum(e["event_type"] == "V6_RESEARCH_BUNDLE_COMPILED" for e in events_after),
            1,
        )
        self.assertEqual(
            sum(e["event_type"] == "V6_OBSERVATION_COMPILED" for e in events_after),
            1,
        )

    def test_preexisting_bundle_no_event_crash_remains_fail_closed(self) -> None:
        direct = self._arguments("BUNDLE-WAL-OLD-001")
        first = self.runtime.compile_and_append_research_bundle(direct)
        self.assertEqual(first["status"], "ACCEPTED")
        before_count = sum(
            e["event_type"] == "V6_RESEARCH_BUNDLE_COMPILED"
            for e in self._events()
        )
        arguments = {
            **direct,
            "idempotency_key": "compile-bundle-existing-crash-0001",
        }
        crashing = self._spawn("compile_and_append_research_bundle")
        self._crash_call(
            crashing,
            2,
            "compile_and_append_research_bundle",
            arguments,
        )
        self.assertEqual(
            sum(
                e["event_type"] == "V6_RESEARCH_BUNDLE_COMPILED"
                for e in self._events()
            ),
            before_count,
        )
        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {
                "name": "compile_and_append_research_bundle",
                "arguments": arguments,
            },
        )
        self.assertIn("error", response)
        self.assertIn(
            "MUTATION_RECONCILIATION_REQUIRED",
            response["error"]["message"],
        )


if __name__ == "__main__":
    unittest.main()
