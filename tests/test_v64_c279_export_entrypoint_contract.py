from __future__ import annotations

import base64
import datetime as dt
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from unified_runtime.core import UnifiedRuntime as CompatibilityRuntime
from mcp import c279_single_session_export_v64 as export_mod
from mcp.c279_single_session_export_v64 import C279ExportError, build_export_callback


UTC = dt.timezone.utc
STARTED = dt.datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
EXPORT_SCHEMA_KEYS = {
    "schema",
    "snapshot_sha256",
    "byte_length",
    "tail_seq",
    "tail_event_hash",
    "payload_encoding",
    "payload",
}


def _inventory(root: Path) -> list[tuple[str, int, str]]:
    return sorted(
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    )


class V64C279ExportEntrypointContractTests(unittest.TestCase):
    def _fixture(self, root: Path):
        sessions = root / "sessions"
        runtime = CompatibilityRuntime(sessions)
        started = runtime.start_investigation({
            "account": {
                "account_id": "C-C279-ENTRYPOINT-001",
                "country": "Canada",
                "name": "C279 Entrypoint Fixture Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        investigation_id = started["investigation_id"]
        events = runtime.store.read(investigation_id)
        path = runtime.store.path(investigation_id)
        return sessions, investigation_id, events, path

    @staticmethod
    def _env(investigation_id: str, events: list[dict]) -> dict[str, str]:
        return {
            "CBI_V64_C279_EXPORT_ENABLED": "true",
            "CBI_V64_C279_EXPORT_EXPIRES_AT": "2026-09-05T09:20:00Z",
            "CBI_V64_C279_EXPORT_INVESTIGATION_ID": investigation_id,
            "CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ": str(events[-1]["seq"]),
            "CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH": str(events[-1]["event_hash"]),
        }

    def test_empty_or_invalid_env_disables_callback(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-entrypoint-disabled-") as temp:
            sessions = Path(temp) / "sessions"
            sessions.mkdir()
            self.assertIsNone(build_export_callback(sessions, {}, process_started_at=STARTED))
            self.assertIsNone(build_export_callback(
                sessions,
                {"CBI_V64_C279_EXPORT_ENABLED": "true"},
                process_started_at=STARTED,
            ))

    def test_valid_callback_returns_exact_export_schema_without_live_mutation(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-entrypoint-") as temp:
            sessions, investigation_id, events, session_path = self._fixture(Path(temp))
            before_payload = session_path.read_bytes()
            before_inventory = _inventory(sessions)
            callback = build_export_callback(
                sessions,
                self._env(investigation_id, events),
                process_started_at=STARTED,
            )
            self.assertTrue(callable(callback))
            assert callback is not None

            with mock.patch.object(export_mod, "_utc_now", return_value=STARTED + dt.timedelta(minutes=10)):
                response = callback()

            self.assertEqual(set(response), EXPORT_SCHEMA_KEYS)
            self.assertEqual(response["schema"], "cbi.v64-c279-single-session-export.v1")
            self.assertEqual(response["snapshot_sha256"], hashlib.sha256(before_payload).hexdigest())
            self.assertEqual(response["byte_length"], len(before_payload))
            self.assertEqual(response["tail_seq"], events[-1]["seq"])
            self.assertEqual(response["tail_event_hash"], events[-1]["event_hash"])
            self.assertEqual(response["payload_encoding"], "base64")
            self.assertEqual(base64.b64decode(response["payload"], validate=True), before_payload)
            self.assertEqual(_inventory(sessions), before_inventory)

    def test_runtime_expiry_makes_existing_callback_unavailable_and_returns_no_payload(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-entrypoint-expiry-") as temp:
            sessions, investigation_id, events, _session_path = self._fixture(Path(temp))
            callback = build_export_callback(
                sessions,
                self._env(investigation_id, events),
                process_started_at=STARTED,
            )
            self.assertTrue(callable(callback))
            assert callback is not None
            availability = getattr(callback, "is_available")

            with mock.patch.object(export_mod, "_utc_now", return_value=STARTED + dt.timedelta(minutes=19)):
                self.assertTrue(availability())
            with mock.patch.object(export_mod, "_utc_now", return_value=STARTED + dt.timedelta(minutes=20)):
                self.assertFalse(availability())
                with self.assertRaises(C279ExportError) as caught:
                    callback()
            self.assertEqual(caught.exception.code, "EXPORT_UNAVAILABLE")
            self.assertEqual(caught.exception.http_status, 404)

    def test_entrypoint_binds_exporter_to_existing_runtime_root_without_r2_export_path(self):
        source_path = Path(__file__).resolve().parents[1] / "mcp" / "server_v61_remote.py"
        source = source_path.read_text(encoding="utf-8")

        self.assertIn("_PROCESS_STARTED_AT =", source)
        self.assertIn("build_export_callback(", source)
        self.assertIn("_RUNTIME.store.root", source)
        self.assertIn("diagnostic_export=", source)
        self.assertIn("diagnostic_static_bearer=", source)

        main_start = source.index("def main() -> int:")
        main_source = source[main_start:]
        self.assertNotIn("restore_into", main_source)
        self.assertNotIn("sync_if_changed", main_source)
        self.assertNotIn("RecoveryObjectStoreStateManagerV63.from_env", main_source)


if __name__ == "__main__":
    unittest.main()
