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
PARTIAL_SERVER = ROOT / "mcp" / "server_v61_bundle_partial_crash_test.py"
RECOVERY_SERVER = ROOT / "mcp" / "server_v61_bundle_recovery.py"


class V61BundlePartialPrefixFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-bundle-partial-")
        self.addCleanup(self.temp.cleanup)
        self.session_root = Path(self.temp.name) / "sessions"
        self.host_root = Path(self.temp.name) / "host-pending"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)
        runtime = UnifiedRuntime(self.session_root)
        started = runtime.start_investigation({
            "account": {
                "account_id": "C-BUNDLE-PARTIAL",
                "country": "Synthetic",
                "name": "Synthetic Partial Bundle Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "A",
        })
        self.investigation_id = started["investigation_id"]

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.host_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        return env

    def _spawn(self, server: Path) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(server), "--stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._env(),
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

    def _arguments(self) -> dict:
        return {
            "investigation_id": self.investigation_id,
            "bundle": {
                "bundle_id": "BUNDLE-PARTIAL-WAL-001",
                "observations": [{
                    "claim_key": "product.fit",
                    "result": "POSITIVE",
                    "owner_type": "ACCOUNT",
                    "owner_id": "C-BUNDLE-PARTIAL",
                    "value": {"fixture": "partial-prefix"},
                    "source": {
                        "source_family": "synthetic_official",
                        "source_type": "OFFICIAL",
                        "reference_type": "PUBLIC_URL",
                        "url": "https://evidence.example.invalid/partial-prefix",
                        "locator": "https://evidence.example.invalid/partial-prefix#fact",
                        "raw_excerpt": "Synthetic partial bundle prefix fixture",
                        "authority_level": "A1_OFFICIAL_PRIMARY",
                        "freshness": "CURRENT",
                        "observed_at": "2026-08-28T00:00:00Z",
                    },
                    "boundary": "Synthetic partial-prefix fail-closed fixture only.",
                    "pivots": [],
                }],
            },
            "idempotency_key": "compile-bundle-partial-crash-0001",
        }

    def test_correlated_partial_observation_without_final_summary_stays_fail_closed(self) -> None:
        arguments = self._arguments()
        crashing = self._spawn(PARTIAL_SERVER)
        assert crashing.stdin is not None and crashing.stdout is not None
        crashing.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "compile_and_append_research_bundle",
                "arguments": arguments,
            },
        }, ensure_ascii=True) + "\n")
        crashing.stdin.flush()
        self.assertEqual(crashing.stdout.readline(), "")
        crashing.wait(timeout=10)
        self.assertEqual(crashing.returncode, 91)

        events = self._events()
        partial = [
            event for event in events
            if event.get("event_type") == "V6_OBSERVATION_COMPILED"
            and (event.get("payload") or {}).get("test_only_partial_prefix") is True
        ]
        summaries = [
            event for event in events
            if event.get("event_type") == "V6_RESEARCH_BUNDLE_COMPILED"
        ]
        self.assertEqual(len(partial), 1)
        self.assertEqual(len(summaries), 0)
        correlation = partial[0].get("mutation_correlation") or {}
        self.assertEqual(correlation.get("tool"), "compile_and_append_research_bundle")
        self.assertTrue(str(correlation.get("correlation_id") or "").startswith("MUTCORR-"))

        recovery = self._spawn(RECOVERY_SERVER)
        response = self._rpc(
            recovery,
            3,
            "tools/call",
            {
                "name": "compile_and_append_research_bundle",
                "arguments": arguments,
            },
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])

        events_after = self._events()
        self.assertEqual(
            sum(
                event.get("event_type") == "V6_OBSERVATION_COMPILED"
                and (event.get("payload") or {}).get("test_only_partial_prefix") is True
                for event in events_after
            ),
            1,
        )
        self.assertEqual(
            sum(event.get("event_type") == "V6_RESEARCH_BUNDLE_COMPILED" for event in events_after),
            0,
        )


if __name__ == "__main__":
    unittest.main()
