from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp.object_store_recovery_v63 import _recovery_fingerprint
from mcp.authoritative_source_evidence_v64 import (
    AuthoritativeSourceEvidenceError,
    build_recovery_self_restore_proof,
    capture_exact_session_source,
    install_remote_authoritative_source_evidence_tool,
)


class _FakePersistence:
    def __init__(self, live_root: Path, *, mutate_live: bool = False) -> None:
        self.live_root = live_root
        self.mutate_live = mutate_live
        self.read_calls = 0
        self.restore_calls = 0
        self.write_calls = 0
        self.pointer = SimpleNamespace(
            generation=1093,
            archive_key="cbi-v61/state/00000000000000001093-example.tar.gz",
            archive_sha256="a" * 64,
            sessions_fingerprint_sha256="b" * 64,
            recovery_fingerprint_sha256=_recovery_fingerprint(live_root),
            archive_format="object_state_v2",
            etag="etag-1093",
        )

    def read_pointer(self, *, required: bool = False):
        self.read_calls += 1
        return self.pointer

    def restore_into(self, target: Path) -> bool:
        self.restore_calls += 1
        target.mkdir(parents=True)
        shutil.copytree(self.live_root / "sessions", target / "sessions")
        shutil.copytree(self.live_root / "mcp-idempotency-v61", target / "mcp-idempotency-v61")
        if self.mutate_live:
            (self.live_root / "sessions" / "INV-LIVE.jsonl").write_text("changed\n", encoding="utf-8")
        return True

    def sync_if_changed(self, _root: Path) -> bool:
        self.write_calls += 1
        raise AssertionError("read-only evidence proof must never sync object-store state")


class _FakeStore:
    def __init__(self, root: Path, *, mutate_during_read: bool = False) -> None:
        self.root = root
        self.mutate_during_read = mutate_during_read

    def read_valid_prefix(self, investigation_id: str):
        path = self.root / f"{investigation_id}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if self.mutate_during_read:
            with path.open("ab") as handle:
                handle.write(b'{"seq":30,"event_hash":"' + b"f" * 64 + b'"}\n')
        return rows, None


class _FakeRuntime:
    def __init__(self, root: Path, *, mutate_during_read: bool = False) -> None:
        self.store = _FakeStore(root, mutate_during_read=mutate_during_read)


class AuthoritativeSourceEvidenceV64Test(unittest.TestCase):
    def _live_root(self, base: Path) -> Path:
        root = base / "live"
        (root / "sessions").mkdir(parents=True)
        (root / "mcp-idempotency-v61").mkdir(parents=True)
        (root / "sessions" / "INV-LIVE.jsonl").write_text("stable\n", encoding="utf-8")
        (root / "mcp-idempotency-v61" / "wal.json").write_text("{}\n", encoding="utf-8")
        return root

    def _session_root(self, base: Path, investigation_id: str = "INV-TEST") -> Path:
        root = base / "sessions"
        root.mkdir(parents=True)
        rows = [
            {"seq": 28, "event_hash": "d" * 64, "event_type": "EVIDENCE"},
            {"seq": 29, "event_hash": "e" * 64, "event_type": "EVIDENCE"},
        ]
        payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")
        (root / f"{investigation_id}.jsonl").write_bytes(payload)
        return root

    def test_recovery_self_restore_is_read_only_and_returns_archive_binding(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            live_root = self._live_root(Path(tmp_name))
            persistence = _FakePersistence(live_root)
            before = _recovery_fingerprint(live_root)
            result = build_recovery_self_restore_proof(
                persistence=persistence,
                live_root=live_root,
                expected_generation=1093,
                expected_recovery_fingerprint_sha256=before,
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["generation"], 1093)
            self.assertEqual(result["production_source_archive_sha256"], "a" * 64)
            self.assertEqual(result["recovery_fingerprint_sha256"], before)
            self.assertTrue(result["restore_target_isolated"])
            self.assertTrue(result["production_live_root_unchanged"])
            self.assertFalse(result["object_store_write_performed"])
            self.assertEqual(persistence.write_calls, 0)
            self.assertGreaterEqual(persistence.read_calls, 2)
            self.assertEqual(persistence.restore_calls, 1)
            self.assertEqual(_recovery_fingerprint(live_root), before)
            self.assertNotIn("archive_key", result)

    def test_recovery_self_restore_fails_closed_on_generation_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            live_root = self._live_root(Path(tmp_name))
            persistence = _FakePersistence(live_root)
            with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "generation"):
                build_recovery_self_restore_proof(
                    persistence=persistence,
                    live_root=live_root,
                    expected_generation=1092,
                    expected_recovery_fingerprint_sha256=_recovery_fingerprint(live_root),
                )
            self.assertEqual(persistence.restore_calls, 0)
            self.assertEqual(persistence.write_calls, 0)

    def test_recovery_self_restore_detects_live_state_change(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            live_root = self._live_root(Path(tmp_name))
            persistence = _FakePersistence(live_root, mutate_live=True)
            with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "changed"):
                build_recovery_self_restore_proof(
                    persistence=persistence,
                    live_root=live_root,
                    expected_generation=1093,
                    expected_recovery_fingerprint_sha256=_recovery_fingerprint(live_root),
                )
            self.assertEqual(persistence.write_calls, 0)

    def _capture_env(self, investigation_id: str) -> dict[str, str]:
        expires = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
        return {
            "CBI_V64_AUTHORITATIVE_SESSION_EXPORT_ENABLED": "true",
            "CBI_V64_AUTHORITATIVE_SESSION_EXPORT_INVESTIGATION_ID": investigation_id,
            "CBI_V64_AUTHORITATIVE_SESSION_EXPORT_EXPIRES_AT": expires,
            "CBI_V64_AUTHORITATIVE_SESSION_EXPORT_MAX_BYTES": "2097152",
        }

    def test_exact_session_capture_requires_explicit_window(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = self._session_root(Path(tmp_name))
            with patch.dict(os.environ, {"CBI_V64_AUTHORITATIVE_SESSION_EXPORT_ENABLED": "false"}, clear=False):
                with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "disabled"):
                    capture_exact_session_source(
                        runtime=_FakeRuntime(root),
                        investigation_id="INV-TEST",
                        expected_last_safe_seq=29,
                        expected_last_safe_event_hash="e" * 64,
                        acknowledge_private_state=True,
                    )

    def test_exact_session_capture_is_single_session_tail_pinned_and_byte_exact(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = self._session_root(Path(tmp_name))
            original = (root / "INV-TEST.jsonl").read_bytes()
            with patch.dict(os.environ, self._capture_env("INV-TEST"), clear=False):
                result = capture_exact_session_source(
                    runtime=_FakeRuntime(root),
                    investigation_id="INV-TEST",
                    expected_last_safe_seq=29,
                    expected_last_safe_event_hash="e" * 64,
                    acknowledge_private_state=True,
                )
            self.assertEqual(base64.b64decode(result["payload_base64"]), original)
            self.assertEqual(result["last_safe_seq"], 29)
            self.assertEqual(result["last_safe_event_hash"], "e" * 64)
            self.assertTrue(result["source_stable_through_capture"])
            self.assertTrue(result["contains_private_state"])
            self.assertFalse(result["production_write_performed"])
            self.assertEqual((root / "INV-TEST.jsonl").read_bytes(), original)

    def test_exact_session_capture_rejects_wrong_allowlist_tail_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = self._session_root(Path(tmp_name))
            with patch.dict(os.environ, self._capture_env("INV-OTHER"), clear=False):
                with self.assertRaises(AuthoritativeSourceEvidenceError):
                    capture_exact_session_source(
                        runtime=_FakeRuntime(root),
                        investigation_id="INV-TEST",
                        expected_last_safe_seq=29,
                        expected_last_safe_event_hash="e" * 64,
                        acknowledge_private_state=True,
                    )
            with patch.dict(os.environ, self._capture_env("../INV-TEST"), clear=False):
                with self.assertRaises(AuthoritativeSourceEvidenceError):
                    capture_exact_session_source(
                        runtime=_FakeRuntime(root),
                        investigation_id="../INV-TEST",
                        expected_last_safe_seq=29,
                        expected_last_safe_event_hash="e" * 64,
                        acknowledge_private_state=True,
                    )
            with patch.dict(os.environ, self._capture_env("INV-TEST"), clear=False):
                with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "tail"):
                    capture_exact_session_source(
                        runtime=_FakeRuntime(root),
                        investigation_id="INV-TEST",
                        expected_last_safe_seq=29,
                        expected_last_safe_event_hash="c" * 64,
                        acknowledge_private_state=True,
                    )

    def test_exact_session_capture_detects_concurrent_change_and_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = self._session_root(Path(tmp_name))
            with patch.dict(os.environ, self._capture_env("INV-TEST"), clear=False):
                with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "changed"):
                    capture_exact_session_source(
                        runtime=_FakeRuntime(root, mutate_during_read=True),
                        investigation_id="INV-TEST",
                        expected_last_safe_seq=29,
                        expected_last_safe_event_hash="e" * 64,
                        acknowledge_private_state=True,
                    )
            root = self._session_root(Path(tmp_name) / "large", "INV-LARGE")
            (root / "INV-LARGE.jsonl").write_bytes(b"x" * 4096)
            env = self._capture_env("INV-LARGE")
            env["CBI_V64_AUTHORITATIVE_SESSION_EXPORT_MAX_BYTES"] = "1024"
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "size"):
                    capture_exact_session_source(
                        runtime=_FakeRuntime(root),
                        investigation_id="INV-LARGE",
                        expected_last_safe_seq=29,
                        expected_last_safe_event_hash="e" * 64,
                        acknowledge_private_state=True,
                    )

    def test_remote_installer_adds_one_read_only_operator_tool(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            live_root = self._live_root(base)
            session_root = self._session_root(base / "runtime")
            persistence = _FakePersistence(live_root)
            runtime = _FakeRuntime(session_root)

            class FakeServer:
                TOOL_HANDLERS = {"existing": lambda _args: {"ok": True}}

                @staticmethod
                def tool_descriptors():
                    return [{"name": "existing", "description": "existing", "inputSchema": {"type": "object"}}]

            install_remote_authoritative_source_evidence_tool(
                server_module=FakeServer,
                persistence=persistence,
                runtime=runtime,
                live_root=live_root,
            )
            tools = FakeServer.tool_descriptors()
            matching = [row for row in tools if row.get("name") == "capture_authoritative_source_evidence"]
            self.assertEqual(len(matching), 1)
            schema = matching[0]["inputSchema"]
            self.assertNotIn("idempotency_key", (schema.get("properties") or {}))
            self.assertIn("capture_authoritative_source_evidence", FakeServer.TOOL_HANDLERS)


if __name__ == "__main__":
    unittest.main()
