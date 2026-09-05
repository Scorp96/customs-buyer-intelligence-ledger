from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from unified_runtime.core import UnifiedRuntime as CompatibilityRuntime
from mcp import c279_single_session_export_v64 as export_mod
from mcp.c279_single_session_export_v64 import (
    C279ExportConfig,
    C279ExportError,
    capture_stable_session,
    load_export_config,
)


UTC = dt.timezone.utc
STARTED = dt.datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
VALID_ID = "INV-20260905T090000Z-aaaaaaaaaaaa"
TARGET_ID = "INV-20260905T090001Z-bbbbbbbbbbbb"


class V64C279SingleSessionExportTests(unittest.TestCase):
    def _fixture(self, root: Path):
        sessions = root / "sessions"
        runtime = CompatibilityRuntime(sessions)
        started = runtime.start_investigation({
            "account": {
                "account_id": "C-C279-EXPORT-001",
                "country": "Canada",
                "name": "C279 Export Fixture Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        investigation_id = started["investigation_id"]
        session_path = runtime.store.path(investigation_id)
        events = runtime.store.read(investigation_id)
        return sessions, investigation_id, session_path, events

    @staticmethod
    def _config(investigation_id: str, events: list[dict], *, max_bytes: int = 2 * 1024 * 1024):
        return C279ExportConfig(
            investigation_id=investigation_id,
            expected_tail_seq=events[-1]["seq"],
            expected_tail_hash=events[-1]["event_hash"],
            expires_at=STARTED + dt.timedelta(minutes=15),
            max_bytes=max_bytes,
        )

    def test_config_is_disabled_or_invalid_fail_closed(self):
        self.assertIsNone(load_export_config({}, process_started_at=STARTED))
        self.assertIsNone(load_export_config(
            {"CBI_V64_C279_EXPORT_ENABLED": "true"},
            process_started_at=STARTED,
        ))
        invalid_expiry = {
            "CBI_V64_C279_EXPORT_ENABLED": "true",
            "CBI_V64_C279_EXPORT_EXPIRES_AT": "2026-09-05T10:00:00Z",
            "CBI_V64_C279_EXPORT_INVESTIGATION_ID": VALID_ID,
            "CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ": "1",
            "CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH": "0" * 64,
        }
        self.assertIsNone(load_export_config(invalid_expiry, process_started_at=STARTED))

    def test_valid_config_uses_default_cap(self):
        env = {
            "CBI_V64_C279_EXPORT_ENABLED": "true",
            "CBI_V64_C279_EXPORT_EXPIRES_AT": "2026-09-05T09:20:00Z",
            "CBI_V64_C279_EXPORT_INVESTIGATION_ID": VALID_ID,
            "CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ": "7",
            "CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH": "a" * 64,
        }
        config = load_export_config(env, process_started_at=STARTED)
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.max_bytes, 2 * 1024 * 1024)
        self.assertEqual(config.expected_tail_seq, 7)
        self.assertEqual(config.expected_tail_hash, "a" * 64)

    def test_stable_capture_is_exact_and_zero_write(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-snapshot-") as temp:
            sessions, investigation_id, session_path, events = self._fixture(Path(temp))
            before_bytes = session_path.read_bytes()
            before_inventory = sorted(
                (p.relative_to(sessions).as_posix(), p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sessions.rglob("*") if p.is_file()
            )
            snapshot = capture_stable_session(self._config(investigation_id, events), sessions)
            after_inventory = sorted(
                (p.relative_to(sessions).as_posix(), p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sessions.rglob("*") if p.is_file()
            )
            self.assertEqual(snapshot.payload, before_bytes)
            self.assertEqual(snapshot.snapshot_sha256, hashlib.sha256(before_bytes).hexdigest())
            self.assertEqual(snapshot.byte_length, len(before_bytes))
            self.assertEqual(snapshot.tail_seq, events[-1]["seq"])
            self.assertEqual(snapshot.tail_event_hash, events[-1]["event_hash"])
            self.assertEqual(before_inventory, after_inventory)

    def test_commitment_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-commitment-") as temp:
            sessions, investigation_id, _path, events = self._fixture(Path(temp))
            config = C279ExportConfig(
                investigation_id=investigation_id,
                expected_tail_seq=events[-1]["seq"],
                expected_tail_hash="f" * 64,
                expires_at=STARTED + dt.timedelta(minutes=15),
                max_bytes=2 * 1024 * 1024,
            )
            with self.assertRaises(C279ExportError) as caught:
                capture_stable_session(config, sessions)
            self.assertEqual(caught.exception.code, "SNAPSHOT_COMMITMENT_MISMATCH")
            self.assertEqual(caught.exception.http_status, 409)

    def test_size_limit_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-size-") as temp:
            sessions, investigation_id, _path, events = self._fixture(Path(temp))
            with self.assertRaises(C279ExportError) as caught:
                capture_stable_session(self._config(investigation_id, events, max_bytes=1), sessions)
            self.assertEqual(caught.exception.code, "SNAPSHOT_TOO_LARGE")
            self.assertEqual(caught.exception.http_status, 413)

    def test_invalid_payload_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-invalid-") as temp:
            sessions, investigation_id, session_path, events = self._fixture(Path(temp))
            session_path.write_bytes(b"not-json\n")
            with self.assertRaises(C279ExportError) as caught:
                capture_stable_session(self._config(investigation_id, events), sessions)
            self.assertEqual(caught.exception.code, "SNAPSHOT_INVALID")
            self.assertEqual(caught.exception.http_status, 409)

    def test_unstable_double_read_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-race-") as temp:
            sessions, investigation_id, session_path, events = self._fixture(Path(temp))
            stable = session_path.read_bytes()
            with mock.patch.object(export_mod, "_bounded_read", side_effect=[stable, stable + b" "]):
                with self.assertRaises(C279ExportError) as caught:
                    capture_stable_session(self._config(investigation_id, events), sessions)
            self.assertEqual(caught.exception.code, "SNAPSHOT_NOT_STABLE")
            self.assertEqual(caught.exception.http_status, 409)

    def test_non_regular_target_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-target-") as temp:
            sessions = Path(temp) / "sessions"
            sessions.mkdir()
            (sessions / f"{TARGET_ID}.jsonl").mkdir()
            config = C279ExportConfig(
                investigation_id=TARGET_ID,
                expected_tail_seq=1,
                expected_tail_hash="0" * 64,
                expires_at=STARTED + dt.timedelta(minutes=15),
                max_bytes=1024,
            )
            with self.assertRaises(C279ExportError) as caught:
                capture_stable_session(config, sessions)
            self.assertEqual(caught.exception.code, "SNAPSHOT_TARGET_INVALID")
            self.assertEqual(caught.exception.http_status, 409)


if __name__ == "__main__":
    unittest.main()
