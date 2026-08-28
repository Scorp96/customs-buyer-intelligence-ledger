from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_unified_runtime import NETWORK_BRANCHES, SOURCE_PROFILE_BY_BRANCH, RuntimeHarness


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_peer_receipt_recovery.py"


class V61PeerReceiptWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-peer-receipt-wal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.host_root = self.root / "host-pending"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)
        self.h = RuntimeHarness(self.session_root)
        self.investigation_id = self.h.investigation_id

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

    @staticmethod
    def _section(attempt_id: str, evidence_id: str | None) -> dict:
        return {
            "passed": True,
            "attempt_ids": [attempt_id],
            "evidence_ids": [evidence_id] if evidence_id else [],
        }

    def _peer_validation_arguments(self, key: str) -> dict:
        peer_id = "PEER-RECEIPT-WAL-1"
        discovery_id, relationship_eid, _ = self.h.add_attempt(
            "regional_peer",
            "maps_region",
            result="POSITIVE",
            discovered_peers=[peer_id],
            relationship_bindings={peer_id: ["E-ATT-0001"]},
            evidence_overrides={"claim_key": "network.regional_peer.relationship"},
        )
        entity_a, entity_e, _ = self.h.add_attempt(
            "buyer_entity_resolution",
            "government_registry",
            owner_id=peer_id,
            result="POSITIVE",
        )
        product_a, product_e, _ = self.h.add_attempt(
            "product_identity_boundary",
            "hs_authority",
            owner_id=peer_id,
            result="POSITIVE",
        )
        trade_a, trade_e, _ = self.h.add_attempt(
            "trade_supplier_continuity",
            "trade_history",
            owner_id=peer_id,
            result="POSITIVE",
        )
        company_a, company_e, _ = self.h.add_attempt(
            "company_profile",
            "official_home",
            owner_id=peer_id,
            result="POSITIVE",
        )
        contact_attempts: list[str] = []
        for family in self.h.start["source_profile"]["contact_coverage"]:
            attempt_id, _, _ = self.h.add_attempt(
                "contact_coverage",
                family,
                owner_id=peer_id,
            )
            contact_attempts.append(attempt_id)
        receipt = {
            "peer_id": peer_id,
            "canonical_key": "synthetic-peer-receipt-wal-us",
            "discovered_by_attempt_id": discovery_id,
            "branch": "regional_peer",
            "inherited_anchor_facts": False,
            "canonical_dedup_checked": True,
            "entity": self._section(entity_a, entity_e),
            "product": self._section(product_a, product_e),
            "trade_business": self._section(trade_a, trade_e),
            "relationship": {"passed": True, "evidence_ids": [relationship_eid]},
            "company_profile": self._section(company_a, company_e),
            "contact_coverage": {
                "passed": True,
                "attempt_ids": contact_attempts,
                "evidence_ids": [],
            },
            "promotion_decision": "do_not_promote",
            "promotion_reason": "Synthetic exact WAL recovery fixture remains a non-promoted peer.",
        }
        return {
            "investigation_id": self.investigation_id,
            "receipt_type": "PEER_VALIDATION",
            "receipt": receipt,
            "idempotency_key": key,
        }

    def _anchor_expansion_arguments(self, key: str) -> dict:
        for branch in NETWORK_BRANCHES:
            for family in SOURCE_PROFILE_BY_BRANCH[branch]:
                self.h.add_attempt(branch, family)
        return {
            "investigation_id": self.investigation_id,
            "receipt_type": "ANCHOR_EXPANSION",
            "anchor_id": "ACCT-SYNTH-001",
            "cycle_dedup_checked": True,
            "idempotency_key": key,
        }

    def test_contract_exposes_peer_receipt_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        wal = contract["production_adapter_mutation_wal"]
        recovery = wal["peer_receipt_recovery"]
        self.assertTrue(recovery["enabled"])
        self.assertTrue(recovery["requires_exact_event_correlation"])
        self.assertFalse(recovery["reexecutes_side_effect"])
        self.assertIn("append_peer_receipt", wal["automatic_reconciliation_tools"])
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["peer_receipt_recovery"]["status"], "ENABLED")

    def test_peer_validation_crash_recovers_exact_result_without_duplicate(self) -> None:
        arguments = self._peer_validation_arguments("peer-receipt-crash-0001")
        crashing = self._spawn("append_peer_receipt")
        self._crash_call(crashing, 2, "append_peer_receipt", arguments)
        events = [e for e in self._events() if e["event_type"] == "PEER_RECEIPT_APPENDED"]
        self.assertEqual(len(events), 1)
        self.assertIn("mutation_correlation", events[0])
        persisted = events[0]["payload"]["receipt"]

        process = self._spawn()
        recovered = self._tool(process, 3, "append_peer_receipt", arguments)
        self.assertEqual(recovered["peer_id"], persisted["peer_id"])
        self.assertEqual(recovered["promotion_decision"], "DO_NOT_PROMOTE")
        self.assertEqual(recovered["promotion_gate"], "NOT_REQUIRED")
        self.assertTrue(recovered["independent"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])

        replayed = self._tool(process, 4, "append_peer_receipt", arguments)
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            sum(e["event_type"] == "PEER_RECEIPT_APPENDED" for e in self._events()),
            1,
        )

    def test_same_content_different_key_cannot_claim_peer_receipt_event(self) -> None:
        arguments = self._peer_validation_arguments("peer-receipt-owner-0001")
        crashing = self._spawn("append_peer_receipt")
        self._crash_call(crashing, 2, "append_peer_receipt", arguments)

        other = {**arguments, "idempotency_key": "peer-receipt-other-0002"}
        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "append_peer_receipt", "arguments": other},
        )
        self.assertIn("error", response)
        self.assertNotIn("reconciled_after_crash", json.dumps(response))

        recovered = self._tool(process, 4, "append_peer_receipt", arguments)
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            sum(e["event_type"] == "PEER_RECEIPT_APPENDED" for e in self._events()),
            1,
        )

    def test_anchor_expansion_crash_recovers_exact_branch_status_without_duplicate(self) -> None:
        arguments = self._anchor_expansion_arguments("anchor-expansion-crash-0001")
        crashing = self._spawn("append_peer_receipt")
        self._crash_call(crashing, 2, "append_peer_receipt", arguments)
        events = [e for e in self._events() if e["event_type"] == "ANCHOR_EXPANSION_CLOSED"]
        self.assertEqual(len(events), 1)
        self.assertIn("mutation_correlation", events[0])
        expected_status = events[0]["payload"]["branch_status"]

        process = self._spawn()
        recovered = self._tool(process, 3, "append_peer_receipt", arguments)
        self.assertEqual(recovered["receipt_type"], "ANCHOR_EXPANSION")
        self.assertEqual(recovered["anchor_id"], "ACCT-SYNTH-001")
        self.assertEqual(recovered["branch_status"], expected_status)
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])

        replayed = self._tool(process, 4, "append_peer_receipt", arguments)
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            sum(e["event_type"] == "ANCHOR_EXPANSION_CLOSED" for e in self._events()),
            1,
        )

    def test_different_key_cannot_claim_closed_anchor_event(self) -> None:
        arguments = self._anchor_expansion_arguments("anchor-expansion-owner-0001")
        crashing = self._spawn("append_peer_receipt")
        self._crash_call(crashing, 2, "append_peer_receipt", arguments)

        other = {**arguments, "idempotency_key": "anchor-expansion-other-0002"}
        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "append_peer_receipt", "arguments": other},
        )
        self.assertIn("error", response)
        self.assertNotIn("reconciled_after_crash", json.dumps(response))

        recovered = self._tool(process, 4, "append_peer_receipt", arguments)
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            sum(e["event_type"] == "ANCHOR_EXPANSION_CLOSED" for e in self._events()),
            1,
        )


if __name__ == "__main__":
    unittest.main()
