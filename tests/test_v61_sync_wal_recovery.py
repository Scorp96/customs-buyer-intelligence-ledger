from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.test_unified_runtime import RuntimeHarness
from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_sync_recovery.py"


class V61SyncWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-sync-wal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.host_root = self.root / "host-pending"
        self.previous_host_root = os.environ.get("CBI_HOST_PENDING_ROOT")
        os.environ["CBI_HOST_PENDING_ROOT"] = str(self.host_root)
        self.addCleanup(self._restore_environment)
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)

    def _restore_environment(self) -> None:
        if self.previous_host_root is None:
            os.environ.pop("CBI_HOST_PENDING_ROOT", None)
        else:
            os.environ["CBI_HOST_PENDING_ROOT"] = self.previous_host_root

    def _env(
        self,
        *,
        crash_after_handler: str = "",
        crash_after_child_prepared: str = "",
        crash_after_child_handler: str = "",
        crash_after_item_recorded: str = "",
    ) -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.host_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        names = {
            "CBI_V61_TEST_CRASH_AFTER_HANDLER": crash_after_handler,
            "CBI_V61_TEST_CRASH_SYNC_AFTER_CHILD_PREPARED": crash_after_child_prepared,
            "CBI_V61_TEST_CRASH_SYNC_AFTER_CHILD_HANDLER": crash_after_child_handler,
            "CBI_V61_TEST_CRASH_SYNC_AFTER_ITEM_RECORDED": crash_after_item_recorded,
        }
        for name, value in names.items():
            if value:
                env[name] = value
            else:
                env.pop(name, None)
        return env

    def _spawn(self, **crash: str) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._env(**crash),
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
        expected_code: int,
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
            raise AssertionError("crash-injected sync unexpectedly returned")
        process.wait(timeout=15)
        if process.returncode != expected_code:
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

    @staticmethod
    def _information_record(h: RuntimeHarness, information_id: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.sha256(f"sync-wal:{information_id}".encode("utf-8")).hexdigest()
        return {
            "information_id": information_id,
            "investigation_id": h.investigation_id,
            "related_account_id": "ACCT-SYNTH-001",
            "subject_type": "ACCOUNT",
            "subject_owner_id": "ACCT-SYNTH-001",
            "relationship_to_account": "SELF",
            "information_type": "FACT",
            "claim_key": f"sync_wal.{information_id}",
            "value": {"field": "synthetic", "value": information_id},
            "source_type": "USER_INPUT",
            "source_reference_type": "USER_INPUT",
            "source_url": "",
            "source_locator": f"user-input://synthetic/{information_id}",
            "observed_at": now,
            "content_sha256": content_hash,
            "confidence": "HIGH",
            "temporal_status": "CURRENT",
            "route_scope": "NOT_A_ROUTE",
            "outreach_eligible_claimed": False,
            "supersedes_information_ids": [],
            "conflicts_with_information_ids": [],
            "evidence_ids": [],
            "notes": "Synthetic sync WAL recovery fixture only.",
        }

    def _pending_fixture(self, count: int = 1) -> tuple[RuntimeHarness, list[dict]]:
        h = RuntimeHarness(self.session_root)
        queued: list[dict] = []
        for index in range(1, count + 1):
            information_id = f"INFO-SYNC-WAL-{index:03d}"
            payload = {
                "investigation_id": h.investigation_id,
                "record": self._information_record(h, information_id),
            }
            queued.append(h.runtime.queue_pending_receipt({
                "target_tool": "append_information_record",
                "payload": payload,
            }))
        return h, queued

    def _host_fixture(self, bundle_id: str = "BUNDLE-SYNC-WAL-001") -> tuple[UnifiedRuntime, str, dict]:
        runtime = UnifiedRuntime(self.session_root)
        started = runtime.start_investigation({
            "account": {
                "account_id": "C-SYNC-WAL-HOST",
                "country": "United States",
                "name": "Sync WAL Host Synthetic Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        investigation_id = started["investigation_id"]
        payload = {
            "investigation_id": investigation_id,
            "bundle": {
                "bundle_id": bundle_id,
                "observations": [
                    {
                        "claim_key": "identity.legal_entity",
                        "result": "POSITIVE",
                        "owner_type": "ACCOUNT",
                        "owner_id": "C-SYNC-WAL-HOST",
                        "value": {"legal_entity": "Sync WAL Host Synthetic Buyer LLC"},
                        "source": {
                            "source_family": "synthetic_sync_wal_registry",
                            "source_type": "OFFICIAL",
                            "reference_type": "PUBLIC_URL",
                            "url": "https://example.invalid/sync-wal/legal",
                            "locator": "https://example.invalid/sync-wal/legal#entity",
                            "raw_excerpt": "Synthetic host bundle exact recovery fixture",
                            "authority_level": "A1_OFFICIAL_PRIMARY",
                            "freshness": "CURRENT_CONFIRMED",
                            "observed_at": "2026-08-28T00:00:00Z",
                        },
                        "boundary": "Synthetic sync WAL host fixture only.",
                    }
                ],
            },
        }
        queued = runtime.queue_host_bundle({"payload": payload})
        return runtime, investigation_id, queued

    def test_contract_exposes_strict_batch_sync_recovery(self) -> None:
        self._pending_fixture()
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        recovery = contract["production_adapter_mutation_wal"]["batch_sync_recovery"]
        self.assertTrue(recovery["enabled"])
        self.assertTrue(recovery["batch_membership_frozen_before_execution"])
        self.assertTrue(recovery["item_child_wal"])
        self.assertTrue(recovery["item_exact_outcome_snapshot"])
        self.assertFalse(recovery["current_queue_reselection_on_retry"])
        self.assertEqual(recovery["child_prepared_without_exact_proof"], "FAIL_CLOSED")
        for tool in (
            "sync_pending_receipts",
            "sync_pending_bundles",
            "sync_pending_research_bundles",
        ):
            self.assertIn(tool, recovery["tools"])
            self.assertIn(tool, contract["production_adapter_mutation_wal"]["automatic_reconciliation_tools"])
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["batch_sync_recovery"]["status"], "ENABLED")
        self.assertFalse(health["batch_sync_recovery"]["unproven_child_prepared_reexecution"])

    def test_pending_child_handler_crash_recovers_from_correlated_target_event(self) -> None:
        h, _ = self._pending_fixture()
        arguments = {
            "investigation_id": h.investigation_id,
            "limit": 10,
            "idempotency_key": "sync-pending-handler-crash-0001",
        }
        crashing = self._spawn(crash_after_child_handler="sync_pending_receipts")
        self._crash_call(crashing, 2, "sync_pending_receipts", arguments, 92)
        history_after_crash = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(len(history_after_crash["records"]), 1)

        process = self._spawn()
        recovered = self._tool(process, 3, "sync_pending_receipts", arguments)
        self.assertEqual(recovered["processed"], 1)
        self.assertEqual(recovered["counts"], {"SYNCED": 1})
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        history_after_recovery = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(len(history_after_recovery["records"]), 1)
        replayed = self._tool(process, 4, "sync_pending_receipts", arguments)
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(replayed["outcomes"], recovered["outcomes"])

    def test_pending_child_prepared_without_proof_stays_fail_closed(self) -> None:
        h, _ = self._pending_fixture()
        arguments = {
            "investigation_id": h.investigation_id,
            "limit": 10,
            "idempotency_key": "sync-pending-prepared-only-0001",
        }
        crashing = self._spawn(crash_after_child_prepared="sync_pending_receipts")
        self._crash_call(crashing, 2, "sync_pending_receipts", arguments, 93)
        self.assertEqual(
            h.runtime.get_information_history({"investigation_id": h.investigation_id})["records"],
            [],
        )

        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "sync_pending_receipts", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        self.assertEqual(
            h.runtime.get_information_history({"investigation_id": h.investigation_id})["records"],
            [],
        )

    def test_pending_sidecar_crash_resumes_only_frozen_batch_and_not_new_queue_item(self) -> None:
        h, queued = self._pending_fixture()
        arguments = {
            "investigation_id": h.investigation_id,
            "limit": 10,
            "idempotency_key": "sync-pending-frozen-batch-0001",
        }
        crashing = self._spawn(crash_after_item_recorded="sync_pending_receipts")
        self._crash_call(crashing, 2, "sync_pending_receipts", arguments, 94)

        later_id = "INFO-SYNC-WAL-LATER"
        later_payload = {
            "investigation_id": h.investigation_id,
            "record": self._information_record(h, later_id),
        }
        later = h.runtime.queue_pending_receipt({
            "target_tool": "append_information_record",
            "payload": later_payload,
        })
        self.assertNotEqual(later["journal_id"], queued[0]["journal_id"])

        process = self._spawn()
        recovered = self._tool(process, 3, "sync_pending_receipts", arguments)
        self.assertEqual(recovered["processed"], 1)
        self.assertEqual(recovered["counts"], {"SYNCED": 1})
        self.assertEqual(recovered["outcomes"][0]["journal_id"], queued[0]["journal_id"])
        status = h.runtime.get_pending_journal_status({"investigation_id": h.investigation_id})
        self.assertEqual(status["counts"].get("SYNCED", 0), 1)
        self.assertEqual(status["counts"].get("PENDING", 0), 1)
        ids = {
            row["information_id"]
            for row in h.runtime.get_information_history({"investigation_id": h.investigation_id})["records"]
        }
        self.assertNotIn(later_id, ids)

    def test_host_child_handler_crash_recovers_bundle_without_duplicate(self) -> None:
        runtime, investigation_id, queued = self._host_fixture()
        arguments = {
            "investigation_id": investigation_id,
            "limit": 10,
            "idempotency_key": "sync-host-handler-crash-0001",
        }
        crashing = self._spawn(crash_after_child_handler="sync_pending_bundles")
        self._crash_call(crashing, 2, "sync_pending_bundles", arguments, 92)
        state_after_crash = runtime.get_investigation_state({"investigation_id": investigation_id})
        self.assertEqual(state_after_crash["bundle_count"], 1)
        self.assertEqual(state_after_crash["observation_count"], 1)

        process = self._spawn()
        recovered = self._tool(process, 3, "sync_pending_bundles", arguments)
        self.assertEqual(recovered["processed"], 1)
        self.assertEqual(recovered["counts"], {"SYNCED": 1})
        self.assertEqual(recovered["outcomes"][0]["bundle_queue_id"], queued["bundle_queue_id"])
        self.assertEqual(recovered["outcomes"][0]["result"]["bundle_id"], "BUNDLE-SYNC-WAL-001")
        state_after_recovery = runtime.get_investigation_state({"investigation_id": investigation_id})
        self.assertEqual(state_after_recovery["bundle_count"], 1)
        self.assertEqual(state_after_recovery["observation_count"], 1)

    def test_host_sidecar_crash_recovers_exact_outcome(self) -> None:
        runtime, investigation_id, queued = self._host_fixture("BUNDLE-SYNC-WAL-SIDECAR")
        arguments = {
            "investigation_id": investigation_id,
            "limit": 10,
            "idempotency_key": "sync-host-sidecar-crash-0001",
        }
        crashing = self._spawn(crash_after_item_recorded="sync_pending_bundles")
        self._crash_call(crashing, 2, "sync_pending_bundles", arguments, 94)

        process = self._spawn()
        recovered = self._tool(process, 3, "sync_pending_bundles", arguments)
        self.assertEqual(recovered["counts"], {"SYNCED": 1})
        self.assertEqual(recovered["outcomes"][0]["bundle_queue_id"], queued["bundle_queue_id"])
        self.assertEqual(recovered["outcomes"][0]["result"]["bundle_id"], "BUNDLE-SYNC-WAL-SIDECAR")
        queue_events = runtime._v6_queue().events.read()
        correlated = [
            event for event in queue_events
            if event.get("event_type") == "HOST_BUNDLE_SYNC_RESULT"
            and isinstance((event.get("payload") or {}).get("outcome_snapshot"), dict)
        ]
        self.assertEqual(len(correlated), 1)
        self.assertEqual(
            correlated[0]["payload"]["outcome_sha256"],
            hashlib.sha256(
                json.dumps(
                    correlated[0]["payload"]["outcome_snapshot"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_research_bundle_alias_dry_run_crash_recovers_frozen_result(self) -> None:
        _, investigation_id, queued = self._host_fixture("BUNDLE-SYNC-WAL-ALIAS")
        arguments = {
            "investigation_id": investigation_id,
            "limit": 10,
            "dry_run": True,
            "idempotency_key": "sync-host-alias-dry-run-0001",
        }
        crashing = self._spawn(crash_after_handler="sync_pending_research_bundles")
        self._crash_call(
            crashing,
            2,
            "sync_pending_research_bundles",
            arguments,
            91,
        )

        process = self._spawn()
        recovered = self._tool(process, 3, "sync_pending_research_bundles", arguments)
        self.assertEqual(recovered["processed"], 1)
        self.assertEqual(recovered["counts"], {"WOULD_SYNC": 1})
        self.assertEqual(recovered["outcomes"], [{
            "bundle_queue_id": queued["bundle_queue_id"],
            "status": "WOULD_SYNC",
        }])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])


if __name__ == "__main__":
    unittest.main()
