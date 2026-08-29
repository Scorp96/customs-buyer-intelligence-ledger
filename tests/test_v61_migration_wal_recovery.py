from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime.core import UnifiedRuntime as V54Runtime


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_migration_recovery.py"


class V61MigrationWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-migration-wal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live_sessions = self.root / "live-sessions"
        self.source_sessions = self.root / "source-sessions"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)
        source = V54Runtime(self.source_sessions)
        self.source_start = source.start_investigation({
            "account": {
                "account_id": "C-MIGRATION-WAL-SOURCE",
                "country": "Synthetic",
                "name": "Synthetic Migration WAL Source Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "provider_policy": {"mode": "PUBLIC_ONLY"},
        })
        self.source_hash_before = self._source_manifest_hash()

    def _source_manifest_hash(self) -> str:
        rows: list[tuple[str, str]] = []
        for path in sorted(
            item for item in self.source_sessions.rglob("*")
            if item.is_file() and not item.name.endswith(".lock")
        ):
            rows.append((
                path.relative_to(self.source_sessions).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ))
        payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _env(
        self,
        *,
        crash_after_handler: bool = False,
        crash_before_proof: bool = False,
    ) -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "CBI_SESSION_ROOT": str(self.live_sessions),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if crash_after_handler:
            env["CBI_V61_TEST_CRASH_AFTER_HANDLER"] = "migrate_v5_4_1_to_v6"
        else:
            env.pop("CBI_V61_TEST_CRASH_AFTER_HANDLER", None)
        if crash_before_proof:
            env["CBI_V61_TEST_CRASH_AFTER_MIGRATION_BEFORE_PROOF"] = "1"
        else:
            env.pop("CBI_V61_TEST_CRASH_AFTER_MIGRATION_BEFORE_PROOF", None)
        return env

    def _spawn(
        self,
        *,
        crash_after_handler: bool = False,
        crash_before_proof: bool = False,
    ) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._env(
                crash_after_handler=crash_after_handler,
                crash_before_proof=crash_before_proof,
            ),
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
        arguments: dict,
    ) -> None:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "migrate_v5_4_1_to_v6",
                "arguments": arguments,
            },
        }, ensure_ascii=True) + "\n")
        process.stdin.flush()
        if process.stdout.readline() != "":
            raise AssertionError("crash-injected migration unexpectedly returned")
        process.wait(timeout=15)
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

    def _arguments(self, target: Path, key: str) -> dict:
        return {
            "source_session_root": str(self.source_sessions),
            "target_root": str(target),
            "idempotency_key": key,
        }

    def test_contract_exposes_strict_migration_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        recovery = contract["production_adapter_mutation_wal"]["migration_recovery"]
        self.assertTrue(recovery["enabled"])
        self.assertTrue(recovery["target_specific_serialization"])
        self.assertTrue(recovery["requires_exact_correlation_bound_proof"])
        self.assertFalse(recovery["automatic_activation"])
        self.assertFalse(recovery["reexecutes_migration"])
        self.assertIn(
            "migrate_v5_4_1_to_v6",
            contract["production_adapter_mutation_wal"]["automatic_reconciliation_tools"],
        )

    def test_migration_crash_after_proof_recovers_exact_report_without_reexecution(self) -> None:
        target = self.root / "migrated-owner"
        arguments = self._arguments(target, "migration-crash-owner-0001")
        crashing = self._spawn(crash_after_handler=True)
        self._crash_call(crashing, 2, arguments)

        report_path = target / "V6_MIGRATION_REPORT.json"
        self.assertTrue(report_path.is_file())
        report_before = json.loads(report_path.read_text(encoding="utf-8"))
        target_files_before = sorted(
            p.relative_to(target).as_posix()
            for p in target.rglob("*") if p.is_file()
        )
        proof_files = list((self.root / "mcp-idempotency-v61" / "migration-proofs").glob("*.json"))
        self.assertEqual(len(proof_files), 1)

        process = self._spawn()
        recovered = self._tool(process, 3, "migrate_v5_4_1_to_v6", arguments)
        raw_recovered = {k: v for k, v in recovered.items() if k != "mutation_meta"}
        self.assertEqual(raw_recovered, report_before)
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertFalse(recovered["switched"])
        self.assertEqual(self._source_manifest_hash(), self.source_hash_before)
        target_files_after = sorted(
            p.relative_to(target).as_posix()
            for p in target.rglob("*") if p.is_file()
        )
        self.assertEqual(target_files_after, target_files_before)

        replayed = self._tool(process, 4, "migrate_v5_4_1_to_v6", arguments)
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            {k: v for k, v in replayed.items() if k != "mutation_meta"},
            report_before,
        )

    def test_same_target_different_key_cannot_claim_owner_proof(self) -> None:
        target = self.root / "migrated-different-key"
        owner = self._arguments(target, "migration-proof-owner-0001")
        crashing = self._spawn(crash_after_handler=True)
        self._crash_call(crashing, 2, owner)

        other = self._arguments(target, "migration-proof-other-0002")
        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "migrate_v5_4_1_to_v6", "arguments": other},
        )
        self.assertIn("error", response)
        self.assertNotIn("reconciled_after_crash", json.dumps(response))

        recovered = self._tool(process, 4, "migrate_v5_4_1_to_v6", owner)
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])

    def test_report_without_mutation_proof_remains_fail_closed(self) -> None:
        target = self.root / "migrated-no-proof"
        arguments = self._arguments(target, "migration-no-proof-0001")
        crashing = self._spawn(crash_before_proof=True)
        self._crash_call(crashing, 2, arguments)
        self.assertTrue((target / "V6_MIGRATION_REPORT.json").is_file())
        proof_root = self.root / "mcp-idempotency-v61" / "migration-proofs"
        self.assertFalse(proof_root.is_dir() and any(proof_root.glob("*.json")))

        process = self._spawn()
        response = self._rpc(
            process,
            3,
            "tools/call",
            {"name": "migrate_v5_4_1_to_v6", "arguments": arguments},
        )
        self.assertIn("error", response)
        self.assertIn("MUTATION_RECONCILIATION_REQUIRED", response["error"]["message"])
        self.assertEqual(self._source_manifest_hash(), self.source_hash_before)


if __name__ == "__main__":
    unittest.main()
