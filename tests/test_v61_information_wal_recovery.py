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
SERVER = ROOT / "mcp" / "server_v61_entry.py"


class V61InformationWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-info-wal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)

    def _env(self, crash_after_handler: str = "") -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.root / "host-pending"),
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
    def _rpc(process: subprocess.Popen[str], request_id: int, method: str, params: dict | None = None) -> dict:
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

    def _tool(self, process: subprocess.Popen[str], request_id: int, name: str, arguments: dict) -> dict:
        response = self._rpc(process, request_id, "tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise AssertionError(response["error"])
        return response["result"]["structuredContent"]

    @staticmethod
    def _crash_call(process: subprocess.Popen[str], request_id: int, name: str, arguments: dict) -> None:
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

    def test_information_crash_reconstructs_original_append_without_duplicate_event(self) -> None:
        bootstrap = self._spawn()
        start = self._tool(bootstrap, 2, "start_investigation", {
            "account": {
                "account_id": "C-WAL-INFO-SYNTH",
                "country": "Synthetic",
                "name": "Synthetic Information WAL Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": "wal-info-start-0001",
        })
        investigation_id = start["investigation_id"]
        self._stop(bootstrap)

        content_hash = hashlib.sha256(b"synthetic historical supplier route").hexdigest()
        record = {
            "information_id": "INFO-WAL-CRASH-001",
            "investigation_id": investigation_id,
            "related_account_id": "C-WAL-INFO-SYNTH",
            "subject_type": "SUPPLIER",
            "subject_owner_id": "SUPPLIER-WAL-SYNTH",
            "relationship_to_account": "SUPPLIER_OF_ACCOUNT",
            "information_type": "CONTACT",
            "claim_key": "historical.supplier.email",
            "value": {
                "channel": "EMAIL",
                "value": "sales@synthetic.invalid",
                "verified": True,
            },
            "source_type": "LEGACY_CRM",
            "source_reference_type": "LEGACY_CRM",
            "source_url": "",
            "source_locator": "legacy-crm://synthetic/wal/info/1",
            "observed_at": "2025-08-22T00:00:00Z",
            "content_sha256": content_hash,
            "confidence": "MEDIUM_HIGH",
            "temporal_status": "HISTORICAL",
            "route_scope": "SUPPLIER_REFERRAL",
            "outreach_eligible_claimed": True,
            "supersedes_information_ids": [],
            "conflicts_with_information_ids": [],
            "evidence_ids": [],
            "notes": "Synthetic historical route for WAL recovery.",
        }
        args = {
            "investigation_id": investigation_id,
            "record": record,
            "idempotency_key": "wal-info-crash-0001",
        }

        crashing = self._spawn("append_information_record")
        self._crash_call(crashing, 3, "append_information_record", args)

        session = self.session_root / f"{investigation_id}.jsonl"
        events_before = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        information_events_before = [
            event for event in events_before
            if event.get("event_type") == "INFORMATION_RECORD_APPENDED"
            and (event.get("payload") or {}).get("record", {}).get("information_id") == record["information_id"]
        ]
        self.assertEqual(len(information_events_before), 1)

        recovered = self._spawn()
        contract = self._tool(recovered, 4, "get_runtime_contract", {})
        self.assertIn(
            "append_information_record",
            contract["production_adapter_mutation_wal"]["automatic_reconciliation_tools"],
        )
        replayed = self._tool(recovered, 5, "append_information_record", args)
        self.assertTrue(replayed["accepted"])
        self.assertEqual(replayed["information_id"], record["information_id"])
        self.assertEqual(replayed["historical_records_preserved"], 1)
        self.assertEqual(replayed["total_information_records"], 1)
        self.assertFalse(replayed["effective_outreach_eligible"])
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "INFORMATION_ID_CONTENT_HASH_AND_EVENT_SEQ",
        )

        events_after = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        information_events_after = [
            event for event in events_after
            if event.get("event_type") == "INFORMATION_RECORD_APPENDED"
            and (event.get("payload") or {}).get("record", {}).get("information_id") == record["information_id"]
        ]
        self.assertEqual(len(information_events_after), 1)
        health = self._tool(recovered, 6, "get_runtime_health", {})
        self.assertEqual(health["mutation_wal"]["prepared_count"], 0)


if __name__ == "__main__":
    unittest.main()
