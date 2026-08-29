from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from unified_runtime import UnifiedRuntime, ValidationError
from unified_runtime.backup_recovery_hardened import ProductionBackupRecoveryManager
from unified_runtime.resilience import canonical_json, digest


ROOT = Path(__file__).resolve().parents[1]


def start(runtime: UnifiedRuntime, account_id: str = "C-BACKUP-001") -> str:
    return runtime.start_investigation(
        {
            "account": {
                "account_id": account_id,
                "country": "Synthetic",
                "name": f"Synthetic Backup Buyer {account_id}",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        }
    )["investigation_id"]


def file_manifest(root: Path) -> dict[str, str]:
    import hashlib

    rows: dict[str, str] = {}
    if not root.is_dir():
        return rows
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and not item.name.endswith(".lock")
    ):
        rows[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return rows


def same_filesystem_path(left: Path, right: Path) -> bool:
    """Compare path identity instead of Windows long/8.3 path spelling."""

    try:
        if left.exists() and right.exists():
            return os.path.samefile(left, right)
    except OSError:
        pass
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


class V61BackupRecoveryTests(unittest.TestCase):
    def test_daily_snapshot_deduplicates_and_does_not_mutate_live_session(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-backup-daily-") as temp:
            base = Path(temp)
            sessions = base / "live" / "sessions"
            runtime = UnifiedRuntime(sessions)
            investigation_id = start(runtime)
            live_path = runtime.store.path(investigation_id)
            before = live_path.read_bytes()
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")

            first = manager.ensure_daily_snapshot()
            second = manager.ensure_daily_snapshot()

            self.assertEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertTrue(second["deduplicated"])
            self.assertEqual(live_path.read_bytes(), before)
            self.assertTrue(manager.validate_snapshot(first["snapshot_id"])["valid"])

    def test_corrupt_tail_snapshot_preserves_last_valid_prefix_and_live_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-backup-corrupt-") as temp:
            base = Path(temp)
            runtime = UnifiedRuntime(base / "live" / "sessions")
            investigation_id = start(runtime)
            live_path = runtime.store.path(investigation_id)
            valid_before = runtime.store.read(investigation_id)
            with live_path.open("a", encoding="utf-8") as handle:
                handle.write('{"seq":')
                handle.flush()
            corrupt_bytes = live_path.read_bytes()
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")

            snapshot = manager.create_snapshot("MANUAL_CORRUPT_TAIL_TEST")
            snap_path = (
                Path(snapshot["path"]) / "sessions" / f"{investigation_id}.jsonl"
            )
            snap_events = [
                json.loads(line)
                for line in snap_path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(live_path.read_bytes(), corrupt_bytes)
            self.assertEqual(len(snap_events), len(valid_before))
            self.assertEqual(
                snap_events[-1]["event_hash"], valid_before[-1]["event_hash"]
            )
            self.assertTrue(
                any(row["component"] == investigation_id for row in snapshot["warnings"])
            )
            self.assertTrue(manager.validate_snapshot(snapshot["snapshot_id"])["valid"])

    def test_restore_replays_proven_tails_into_isolated_runtime_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-restore-tail-") as temp:
            base = Path(temp)
            sessions = base / "live" / "sessions"
            runtime = UnifiedRuntime(sessions)
            investigation_id = start(runtime)
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")
            snapshot = manager.create_snapshot("BEFORE_TAIL_TEST")

            runtime.store.append(
                investigation_id, "TEST_APPEND_ONLY_EVENT", {"value": 1}
            )
            queued = runtime.queue_host_bundle(
                {
                    "payload": {
                        "investigation_id": investigation_id,
                        "bundle": {"bundle_id": "BUNDLE-BACKUP-TAIL"},
                    }
                }
            )
            live_queue_root = runtime._v6_queue().root.resolve()
            live_queue_before = file_manifest(live_queue_root)

            target = base / "restored"
            result = manager.restore_latest_valid_snapshot(
                target,
                snapshot_id=snapshot["snapshot_id"],
                replay_live_tail=True,
            )

            target_session = target / f"{investigation_id}.jsonl"
            target_events = [
                json.loads(line)
                for line in target_session.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(target_events[-1]["event_type"], "TEST_APPEND_ONLY_EVENT")
            target_host = target / ".runtime" / "host-pending-v6"
            self.assertTrue(
                (target_host / f"{queued['bundle_queue_id']}.json").is_file()
            )
            self.assertNotEqual(target_host.resolve(), live_queue_root)
            self.assertEqual(file_manifest(live_queue_root), live_queue_before)
            self.assertTrue(result["hash_chains_valid"])
            self.assertTrue(result["activation_ready"])
            self.assertTrue(result["target_not_activated"])
            self.assertFalse(result["live_root_overwritten"])

    def test_restore_ignores_environment_root_aliases_and_never_writes_live_custom_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-restore-env-") as temp:
            base = Path(temp)
            sessions = base / "live" / "sessions"
            canonical = base / "live-custom" / "canonical"
            pending = base / "live-custom" / "pending"
            host = base / "live-custom" / "host"
            backup = base / "backups"
            env = {
                "CBI_CANONICAL_ROOT": str(canonical),
                "CBI_PENDING_ROOT": str(pending),
                "CBI_HOST_PENDING_ROOT": str(host),
                "CBI_BACKUP_ROOT": str(backup),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                runtime = UnifiedRuntime(sessions)
                investigation_id = start(runtime, "C-BACKUP-ENV")
                runtime.queue_host_bundle(
                    {
                        "payload": {
                            "investigation_id": investigation_id,
                            "bundle": {"bundle_id": "BUNDLE-BACKUP-ENV"},
                        }
                    }
                )
                manager = ProductionBackupRecoveryManager.from_runtime(runtime)
                snapshot = manager.create_snapshot("ENV_ISOLATION")
                live_before = {
                    "canonical": file_manifest(canonical),
                    "pending": file_manifest(pending),
                    "host": file_manifest(host),
                }
                target = base / "restore-env"
                result = manager.restore_latest_valid_snapshot(
                    target,
                    snapshot_id=snapshot["snapshot_id"],
                    replay_live_tail=True,
                )

                self.assertEqual(file_manifest(canonical), live_before["canonical"])
                self.assertEqual(file_manifest(pending), live_before["pending"])
                self.assertEqual(file_manifest(host), live_before["host"])
                self.assertTrue(
                    same_filesystem_path(
                        Path(result["activation_environment"]["CBI_CANONICAL_ROOT"]),
                        target / ".runtime" / "canonical",
                    )
                )
                self.assertTrue(
                    same_filesystem_path(
                        Path(result["activation_environment"]["CBI_PENDING_ROOT"]),
                        target / ".runtime" / "pending",
                    )
                )
                self.assertTrue(
                    same_filesystem_path(
                        Path(result["activation_environment"]["CBI_HOST_PENDING_ROOT"]),
                        target / ".runtime" / "host-pending-v6",
                    )
                )

    @unittest.skipUnless(os.name == "nt", "Windows-only 8.3 alias overlap regression")
    def test_windows_short_path_alias_cannot_bypass_protected_root_overlap(self) -> None:
        import ctypes

        with tempfile.TemporaryDirectory(prefix="cbi-v61-restore-shortpath-") as temp:
            base = Path(temp)
            runtime = UnifiedRuntime(base / "live" / "sessions")
            start(runtime, "C-BACKUP-SHORTPATH")
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")
            manager.create_snapshot("SHORT_PATH_GUARD")

            source = runtime.store.root.resolve()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_short_path = kernel32.GetShortPathNameW
            get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            get_short_path.restype = ctypes.c_uint32
            required = get_short_path(str(source), None, 0)
            if required == 0:
                self.skipTest("GetShortPathNameW unavailable for the CI filesystem")
            buffer = ctypes.create_unicode_buffer(required + 1)
            written = get_short_path(str(source), buffer, len(buffer))
            if written == 0:
                self.skipTest("short path alias unavailable for the CI filesystem")
            short_source = Path(buffer.value)
            if "~" not in str(short_source):
                self.skipTest("8.3 short-name generation disabled on the CI volume")

            non_existing_child = short_source / "restore-child-must-be-rejected"
            self.assertFalse(non_existing_child.exists())
            with self.assertRaisesRegex(ValidationError, "overlaps protected root"):
                manager.restore_latest_valid_snapshot(non_existing_child)

    def test_divergent_live_chain_keeps_snapshot_and_blocks_activation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-restore-diverge-") as temp:
            base = Path(temp)
            runtime = UnifiedRuntime(base / "live" / "sessions")
            investigation_id = start(runtime, "C-BACKUP-DIVERGE")
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")
            snapshot = manager.create_snapshot("DIVERGENCE_BASE")
            snap_file = (
                Path(snapshot["path"]) / "sessions" / f"{investigation_id}.jsonl"
            )
            expected_snapshot_bytes = snap_file.read_bytes()

            live_path = runtime.store.path(investigation_id)
            events = [
                json.loads(line)
                for line in live_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertGreaterEqual(len(events), 2)
            events[-1]["payload"] = {
                **events[-1]["payload"],
                "divergence_fixture": True,
            }
            unsigned = {
                key: value
                for key, value in events[-1].items()
                if key != "event_hash"
            }
            events[-1]["event_hash"] = digest(unsigned)
            live_path.write_text(
                "".join(canonical_json(event) + "\n" for event in events),
                encoding="utf-8",
            )

            target = base / "restore-diverged"
            result = manager.restore_latest_valid_snapshot(
                target,
                snapshot_id=snapshot["snapshot_id"],
                replay_live_tail=True,
            )

            self.assertFalse(result["activation_ready"])
            self.assertTrue(
                any(
                    row["component"] == investigation_id
                    and row["reason"] == "LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT"
                    for row in result["replay_conflicts"]
                )
            )
            self.assertEqual(
                (target / f"{investigation_id}.jsonl").read_bytes(),
                expected_snapshot_bytes,
            )

    def test_invalid_live_sidecar_is_reported_and_blocks_activation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-restore-sidecar-") as temp:
            base = Path(temp)
            runtime = UnifiedRuntime(base / "live" / "sessions")
            investigation_id = start(runtime, "C-BACKUP-SIDECAR")
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")
            snapshot = manager.create_snapshot("SIDECAR_BASE")
            host_root = runtime._v6_queue().root
            host_root.mkdir(parents=True, exist_ok=True)
            bad = host_root / "HOSTQ-20260829T000000Z-012345abcdef.json"
            bad.write_text(
                json.dumps(
                    {
                        "schema": "cbi.host-pending-bundle.v6.1",
                        "bundle_queue_id": bad.stem,
                        "queued_at": "2026-08-29T00:00:00Z",
                        "request_sha256": "0" * 64,
                        "payload": {
                            "investigation_id": investigation_id,
                            "bundle": {"bundle_id": "BROKEN"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = manager.restore_latest_valid_snapshot(
                base / "restore-sidecar",
                snapshot_id=snapshot["snapshot_id"],
                replay_live_tail=True,
            )

            self.assertFalse(result["activation_ready"])
            self.assertTrue(
                any(
                    row["reason"] == "INVALID_LIVE_SIDECAR_SKIPPED"
                    and row["component"].startswith("host_queue:")
                    for row in result["replay_conflicts"]
                )
            )

    def test_snapshot_inventory_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-backup-tamper-") as temp:
            base = Path(temp)
            runtime = UnifiedRuntime(base / "live" / "sessions")
            start(runtime, "C-BACKUP-TAMPER")
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")
            snapshot = manager.create_snapshot("TAMPER_TEST")
            (Path(snapshot["path"]) / "untracked.txt").write_text(
                "tamper", encoding="utf-8"
            )

            with self.assertRaises(ValidationError):
                manager.validate_snapshot(snapshot["snapshot_id"])

    def test_restore_rejects_overlapping_live_or_existing_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-restore-safety-") as temp:
            base = Path(temp)
            runtime = UnifiedRuntime(base / "live" / "sessions")
            start(runtime, "C-BACKUP-SAFE")
            manager = ProductionBackupRecoveryManager.from_runtime(runtime, base / "backups")
            manager.create_snapshot("SAFETY_TEST")

            with self.assertRaises(ValidationError):
                manager.restore_latest_valid_snapshot(runtime.store.root)
            existing = base / "existing"
            existing.mkdir()
            with self.assertRaises(ValidationError):
                manager.restore_latest_valid_snapshot(existing)


class V61BackupRecoveryEntryTests(unittest.TestCase):
    def run_entry_script(
        self, body: str, session_root: Path, backup_root: Path
    ) -> dict:
        env = os.environ.copy()
        env["CBI_SESSION_ROOT"] = str(session_root)
        env["CBI_BACKUP_ROOT"] = str(backup_root)
        completed = subprocess.run(
            [sys.executable, "-c", body],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_production_entry_daily_backup_precedes_mutation_and_contract_exposes_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-backup-entry-") as temp:
            base = Path(temp)
            result = self.run_entry_script(
                r'''
import json
import time
from mcp import server_v61_backup_recovery as entry
handlers = entry._v61._server.TOOL_HANDLERS
started = time.perf_counter()
mutation = handlers["resolve_or_create_account"]({
    "idempotency_key": "backup-entry-resolve-0001",
    "candidate": {"name": "Backup Entry Buyer", "country": "Synthetic"},
})
first_mutation_seconds = time.perf_counter() - started
started = time.perf_counter()
second_mutation = handlers["resolve_or_create_account"]({
    "idempotency_key": "backup-entry-resolve-0002",
    "candidate": {"name": "Backup Entry Buyer 2", "country": "Synthetic"},
})
second_mutation_seconds = time.perf_counter() - started
contract = handlers["get_runtime_contract"]({})
status = entry._BACKUP.status(validate_latest=True)
snapshot_count = sum(1 for p in entry._BACKUP.backup_root.iterdir() if p.is_dir() and p.name.startswith("SNAP-"))
print(json.dumps({
    "mutation": mutation,
    "second_mutation": second_mutation,
    "first_mutation_seconds": first_mutation_seconds,
    "second_mutation_seconds": second_mutation_seconds,
    "snapshot_count": snapshot_count,
    "contract": contract["backup_recovery_v6_1"],
    "status": status,
}))
''',
                base / "sessions",
                base / "backups",
            )
            self.assertEqual(result["status"]["latest"]["reasons"], ["DAILY"])
            self.assertEqual(result["snapshot_count"], 1)
            self.assertGreaterEqual(result["first_mutation_seconds"], 0.0)
            self.assertGreaterEqual(result["second_mutation_seconds"], 0.0)
            print(
                "BACKUP_DAILY_MUTATION_LATENCY "
                + json.dumps(
                    {
                        "first_mutation_seconds": result["first_mutation_seconds"],
                        "second_mutation_seconds": result["second_mutation_seconds"],
                        "snapshot_count": result["snapshot_count"],
                    },
                    sort_keys=True,
                )
            )
            self.assertIn(
                "DAILY_BEFORE_FIRST_PRODUCTION_MUTATION",
                result["contract"]["automatic_triggers"],
            )
            self.assertFalse(result["contract"]["restore_overwrites_live_root"])

    def test_prepare_crm_writeback_binds_deduplicated_precommit_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-backup-crm-") as temp:
            base = Path(temp)
            sessions = base / "sessions"
            runtime = UnifiedRuntime(sessions)
            investigation_id = start(runtime, "C-BACKUP-CRM")
            body = f'''
import json
from mcp import server_v61_backup_recovery as entry
handlers = entry._v61._server.TOOL_HANDLERS
args = {{
    "investigation_id": {investigation_id!r},
    "target_workbook_path": "synthetic-crm.xlsx",
    "records": [{{"field": "commercial_value", "value": "A"}}],
}}
first = handlers["prepare_crm_writeback"](args)
second = handlers["prepare_crm_writeback"](args)
print(json.dumps({{"first": first, "second": second}}))
'''
            result = self.run_entry_script(body, sessions, base / "backups")
            first = result["first"]
            second = result["second"]
            self.assertEqual(
                first["pre_commit_backup"]["reasons"],
                ["BEFORE_CRM_COMMIT"],
            )
            self.assertEqual(
                first["pre_commit_backup"]["snapshot_id"],
                second["pre_commit_backup"]["snapshot_id"],
            )
            self.assertTrue(second["pre_commit_backup"]["deduplicated"])
            self.assertIn("PRE_COMMIT_BACKUP_SNAPSHOT", first["requirements"])
            self.assertFalse(first["crm_commit_without_bound_backup_supported"])

    def test_schema_upgrade_and_migration_guards_are_durable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-backup-guards-") as temp:
            base = Path(temp)
            sessions = base / "sessions"
            from unified_runtime.core import UnifiedRuntime as LegacyRuntime

            legacy = LegacyRuntime(sessions)
            legacy_id = legacy.start_investigation(
                {
                    "account": {
                        "account_id": "C-BACKUP-LEGACY",
                        "country": "Synthetic",
                        "name": "Legacy Backup Buyer",
                    },
                    "mode": "EXHAUSTIVE",
                    "history": {"events": []},
                }
            )["investigation_id"]
            target = base / "migration-target"
            body = f'''
import json
from mcp import server_v61_backup_recovery as entry
handlers = entry._v61._server.TOOL_HANDLERS
objective = handlers["submit_research_objective"]({{
    "idempotency_key": "backup-schema-upgrade-0001",
    "investigation_id": {legacy_id!r},
    "objective": {{
        "objective_id": "OBJ-BACKUP-SCHEMA-001",
        "claim_key": "product.fit",
        "query_or_navigation": "synthetic product fit evidence",
        "source_family": "official_products",
    }},
}})
migration = handlers["migrate_v5_4_1_to_v6"]({{
    "idempotency_key": "backup-migration-0001",
    "source_session_root": {str(sessions)!r},
    "target_root": {str(target)!r},
}})
snapshots = []
for path in sorted(entry._BACKUP.backup_root.iterdir()):
    if path.is_dir() and path.name.startswith("SNAP-"):
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        snapshots.append({{"snapshot_id": path.name, "reasons": manifest["reasons"]}})
print(json.dumps({{"objective": objective, "migration": migration, "snapshots": snapshots}}))
'''
            result = self.run_entry_script(body, sessions, base / "backups")
            reasons = [set(row["reasons"]) for row in result["snapshots"]]
            self.assertIn({"BEFORE_SCHEMA_UPGRADE"}, reasons)
            self.assertIn(
                {"BEFORE_MIGRATION", "BEFORE_SCHEMA_UPGRADE"},
                reasons,
            )
            self.assertTrue(result["migration"]["verified"])


if __name__ == "__main__":
    unittest.main()
