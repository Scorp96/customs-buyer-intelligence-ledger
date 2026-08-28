from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_production.py"


class V61ReceiptWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-receipt-wal-")
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

    def _start(
        self,
        account_id: str,
        *,
        provider_policy: dict | None = None,
        crm_path: str = "",
    ) -> str:
        process = self._spawn()
        arguments = {
            "account": {
                "account_id": account_id,
                "country": "Canada",
                "name": f"Synthetic {account_id}",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": f"start-{account_id.lower()}-0001",
        }
        if provider_policy is not None:
            arguments["provider_policy"] = provider_policy
        if crm_path:
            arguments["crm_path"] = crm_path
        started = self._tool(process, 2, "start_investigation", arguments)
        self._stop(process)
        return started["investigation_id"]

    def _event_count(self, investigation_id: str, event_type: str, key: str, value: str) -> int:
        session = self.session_root / f"{investigation_id}.jsonl"
        events = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        count = 0
        for event in events:
            if event.get("event_type") != event_type:
                continue
            payload = event.get("payload") or {}
            target = payload.get("attempt") or payload.get("receipt") or payload
            if isinstance(target, dict) and str(target.get(key) or "") == value:
                count += 1
        return count

    def test_production_contract_guards_hidden_mutators_and_reports_receipt_recovery(self) -> None:
        process = self._spawn()
        tools = self._rpc(process, 2, "tools/list")["result"]["tools"]
        by_name = {row["name"]: row for row in tools}
        for name in ("plan_provider_calls", "evaluate_investigation_closure"):
            schema = by_name[name]["inputSchema"]
            self.assertIn("idempotency_key", schema["required"])
            self.assertIn("expected_state_version", schema["properties"])
        contract = self._tool(process, 3, "get_runtime_contract", {})
        automatic = set(contract["production_adapter_mutation_wal"]["automatic_reconciliation_tools"])
        self.assertTrue({
            "append_execution_receipt",
            "append_provider_receipt",
            "append_crm_writeback_receipt",
        } <= automatic)

    def test_execution_receipt_crash_recovers_without_duplicate_event(self) -> None:
        account_id = "C-WAL-EXEC-SYNTH"
        investigation_id = self._start(account_id)
        started = datetime(2026, 8, 28, 2, 0, tzinfo=timezone.utc)
        completed = started + timedelta(seconds=2)
        content_hash = hashlib.sha256(b"wal-execution-negative").hexdigest()
        args = {
            "investigation_id": investigation_id,
            "attempt": {
                "attempt_id": "ATT-WAL-EXEC-001",
                "investigation_id": investigation_id,
                "owner_type": "ACCOUNT",
                "owner_id": account_id,
                "module_or_branch": "regional_peer",
                "source_family": "maps_region",
                "query": "Synthetic WAL execution regional peer maps",
                "started_at": started.isoformat(),
                "completed_at": completed.isoformat(),
                "checked_at": completed.isoformat(),
                "tool_or_operator": "wal-recovery-test",
                "execution_id": "EXEC-WAL-001",
                "result": "NEGATIVE_EXHAUSTED",
                "result_count": 0,
                "raw_result_locator": "snapshot://wal-execution-negative",
                "content_sha256": content_hash,
                "evidence_ids": [],
                "pivots_generated": [],
                "blocked_reason": "",
                "discovered_peer_ids": [],
                "relationship_evidence_ids": {},
            },
            "evidence": [],
            "pivots": [],
            "pivots_consumed": [],
            "manual_visual_items_resolved": [],
            "idempotency_key": "wal-execution-crash-0001",
        }
        crashing = self._spawn("append_execution_receipt")
        self._crash_call(crashing, 3, "append_execution_receipt", args)
        self.assertEqual(
            self._event_count(investigation_id, "EXECUTION_RECEIPT_APPENDED", "attempt_id", "ATT-WAL-EXEC-001"),
            1,
        )
        recovered = self._spawn()
        replayed = self._tool(recovered, 4, "append_execution_receipt", args)
        self.assertTrue(replayed["accepted"])
        self.assertEqual(replayed["attempt_id"], "ATT-WAL-EXEC-001")
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "ATTEMPT_EXECUTION_CONTENT_HASH_AND_EVENT_SEQ",
        )
        self.assertEqual(
            self._event_count(investigation_id, "EXECUTION_RECEIPT_APPENDED", "attempt_id", "ATT-WAL-EXEC-001"),
            1,
        )

    def test_provider_receipt_crash_recovers_without_duplicate_event(self) -> None:
        account_id = "C-WAL-PROVIDER-SYNTH"
        investigation_id = self._start(
            account_id,
            provider_policy={
                "mode": "CONNECTED_PROVIDERS_OPTIONAL",
                "allowed_providers": ["Synthetic Provider"],
                "required_capabilities": [],
                "cost_consent": False,
            },
        )
        planner = self._spawn()
        plan = self._tool(planner, 2, "plan_provider_calls", {
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
            "idempotency_key": "wal-provider-plan-0001",
        })
        self._stop(planner)
        provider_call = plan["calls"][0]
        requested = datetime.now(timezone.utc) + timedelta(seconds=1)
        completed = requested + timedelta(seconds=1)
        content_hash = hashlib.sha256(b"wal-provider-negative").hexdigest()
        args = {
            "investigation_id": investigation_id,
            "receipt": {
                "provider_receipt_id": "PR-WAL-001",
                "investigation_id": investigation_id,
                "account_id": account_id,
                "provider": "Synthetic Provider",
                "provider_class": "CONTACT_ENRICHMENT",
                "requested_capability": "email_enrichment",
                "target_module": "contact_coverage",
                "plan_id": plan["plan_id"],
                "planned_call_id": provider_call["planned_call_id"],
                "tool_name": provider_call["tool_name"],
                "tool_call_id": "PROVIDER-CALL-WAL-001",
                "query": "Synthetic WAL provider negative result",
                "requested_at": requested.isoformat(),
                "completed_at": completed.isoformat(),
                "result": "NEGATIVE",
                "result_count": 0,
                "raw_result_locator": "provider-receipt://synthetic/wal-pr-001/raw",
                "content_sha256": content_hash,
                "evidence_ids": [],
                "pivots_generated": [],
                "contacts_returned": [],
                "companies_returned": [],
                "billing_or_credit_notice": "No credit consumed.",
                "blocked_reason": "",
                "permissions": {
                    "user_authorized": True,
                    "scopes": ["read synthetic data"],
                },
                "freshness": "CURRENT",
                "conflicts": [],
                "status": "SUCCESS",
            },
            "evidence": [],
            "pivots": [],
            "pivots_consumed": [],
            "idempotency_key": "wal-provider-receipt-0001",
        }
        crashing = self._spawn("append_provider_receipt")
        self._crash_call(crashing, 3, "append_provider_receipt", args)
        self.assertEqual(
            self._event_count(investigation_id, "PROVIDER_RECEIPT_APPENDED", "provider_receipt_id", "PR-WAL-001"),
            1,
        )
        recovered = self._spawn()
        replayed = self._tool(recovered, 4, "append_provider_receipt", args)
        self.assertTrue(replayed["accepted"])
        self.assertEqual(replayed["provider_receipt_id"], "PR-WAL-001")
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "PROVIDER_RECEIPT_CALL_CONTENT_HASH_AND_EVENT_SEQ",
        )
        self.assertEqual(
            self._event_count(investigation_id, "PROVIDER_RECEIPT_APPENDED", "provider_receipt_id", "PR-WAL-001"),
            1,
        )

    def test_crm_receipt_crash_recovers_without_rewriting_workbook(self) -> None:
        account_id = "C-WAL-CRM-SYNTH"
        crm_path = self.root / "synthetic-main-crm.xlsx"
        with zipfile.ZipFile(crm_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            )
            archive.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/></workbook>',
            )
        workbook_hash = hashlib.sha256(crm_path.read_bytes()).hexdigest()
        audit_path = self.root / "synthetic-crm-audit.json"
        audit_path.write_text('{"synthetic":true,"status":"NO_CHANGE_VERIFIED"}\n', encoding="utf-8")
        audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
        investigation_id = self._start(account_id, crm_path=str(crm_path))
        args = {
            "investigation_id": investigation_id,
            "receipt": {
                "writeback_id": "WB-WAL-CRM-001",
                "investigation_id": investigation_id,
                "account_id": account_id,
                "transaction_id": "TX-WAL-CRM-001",
                "writer": "ARTIFACT_TOOL",
                "target_workbook_path": str(crm_path),
                "workbook_sha256_before": workbook_hash,
                "workbook_sha256_after": workbook_hash,
                "committed_at": datetime.now(timezone.utc).isoformat(),
                "status": "NO_CHANGE_VERIFIED",
                "atomic_commit": True,
                "sparse_patch": True,
                "history_guard_passed": True,
                "post_commit_reimport_verified": True,
                "unintended_diff_count": 0,
                "touched_sheets": [],
                "row_assertions": [],
                "cell_assertions": [],
                "previous_current_diff": [],
                "audit_artifact_locator": str(audit_path),
                "audit_artifact_sha256": audit_hash,
            },
            "idempotency_key": "wal-crm-receipt-0001",
        }
        crashing = self._spawn("append_crm_writeback_receipt")
        self._crash_call(crashing, 3, "append_crm_writeback_receipt", args)
        workbook_after_crash = hashlib.sha256(crm_path.read_bytes()).hexdigest()
        self.assertEqual(workbook_after_crash, workbook_hash)
        self.assertEqual(
            self._event_count(investigation_id, "CRM_WRITEBACK_RECEIPT_APPENDED", "writeback_id", "WB-WAL-CRM-001"),
            1,
        )
        recovered = self._spawn()
        replayed = self._tool(recovered, 4, "append_crm_writeback_receipt", args)
        self.assertTrue(replayed["accepted"])
        self.assertTrue(replayed["crm_sync_complete"])
        self.assertFalse(replayed["runtime_mutated_workbook"])
        self.assertTrue(replayed["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            replayed["mutation_meta"]["reconciliation_proof"],
            "CRM_WRITEBACK_TRANSACTION_HASH_AND_EVENT_SEQ",
        )
        self.assertEqual(hashlib.sha256(crm_path.read_bytes()).hexdigest(), workbook_hash)
        self.assertEqual(
            self._event_count(investigation_id, "CRM_WRITEBACK_RECEIPT_APPENDED", "writeback_id", "WB-WAL-CRM-001"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
