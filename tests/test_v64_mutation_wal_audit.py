from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp import server_v61 as adapter
from unified_runtime import ValidationError


class MutationWalAuditTests(unittest.TestCase):
    def _write(self, root: Path, name: str, row: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _base_error(self, *, tool: str, completed_at: str, message: str) -> dict:
        return {
            "schema": adapter._WAL_SCHEMA,
            "status": "COMMITTED_ERROR",
            "tool": tool,
            "idempotency_key": "never-expose-this-idempotency-key",
            "request_sha256": hashlib.sha256(tool.encode()).hexdigest(),
            "state_version_before": 17,
            "prepared_at": "2026-09-09T01:00:00Z",
            "completed_at": completed_at,
            "resource_snapshot_before": {
                "contact": "secret-buyer@example.com",
                "phone": "+966 55 123 4567",
            },
            "error": {"type": "ValidationError", "message": message},
        }

    def test_default_returns_only_committed_errors_in_latest_first_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-audit-") as td:
            root = Path(td)
            self._write(root, "a.json", self._base_error(
                tool="tool_old",
                completed_at="2026-09-09T01:01:00Z",
                message="ROUTE_NOT_VERIFIED: old",
            ))
            self._write(root, "b.json", self._base_error(
                tool="tool_new",
                completed_at="2026-09-09T01:02:00Z",
                message="STATE_VERSION_CONFLICT: newer",
            ))
            committed = self._base_error(
                tool="tool_ok",
                completed_at="2026-09-09T01:03:00Z",
                message="unused",
            )
            committed["status"] = "COMMITTED"
            committed.pop("error")
            committed["result"] = {"contact": "must-not-leak@example.com"}
            self._write(root, "c.json", committed)

            with mock.patch.object(adapter, "_journal_path", return_value=root):
                result = adapter._mutation_wal_audit({})

        self.assertEqual(result["schema"], "cbi.mutation-wal-audit.v6.4")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["status_filter"], "COMMITTED_ERROR")
        self.assertEqual([row["tool"] for row in result["rows"]], ["tool_new", "tool_old"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["invalid_record_count"], 0)

    def test_projection_never_contains_raw_sensitive_fields(self) -> None:
        message = (
            "ROUTE_NOT_VERIFIED email=buyer@example.com phone=+966 55 123 4567 "
            "Authorization: Bearer super-secret-token api_key=sk-live-secret-value"
        )
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-redact-") as td:
            root = Path(td)
            source = self._write(root, "error.json", self._base_error(
                tool="prepare_outreach",
                completed_at="2026-09-09T02:00:00Z",
                message=message,
            ))
            before = source.read_bytes()
            with mock.patch.object(adapter, "_journal_path", return_value=root):
                result = adapter._mutation_wal_audit({"limit": 10})
            after = source.read_bytes()

        self.assertEqual(before, after, "audit must not mutate WAL bytes")
        encoded = json.dumps(result, ensure_ascii=False)
        for forbidden in (
            "never-expose-this-idempotency-key",
            "buyer@example.com",
            "+966 55 123 4567",
            "super-secret-token",
            "sk-live-secret-value",
            "resource_snapshot_before",
            '"result"',
        ):
            self.assertNotIn(forbidden, encoded)
        row = result["rows"][0]
        self.assertEqual(row["error_type"], "ValidationError")
        self.assertEqual(row["error_code"], "ROUTE_NOT_VERIFIED")
        self.assertLessEqual(len(row["error_message"]), 240)
        self.assertTrue(result["contains_raw_arguments"] is False)
        self.assertTrue(result["contains_idempotency_keys"] is False)

    def test_committed_filter_is_supported_without_returning_result_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-committed-") as td:
            root = Path(td)
            row = self._base_error(
                tool="append_information_record",
                completed_at="2026-09-09T03:00:00Z",
                message="unused",
            )
            row["status"] = "COMMITTED"
            row.pop("error")
            row["result"] = {
                "email": "secret@example.com",
                "idempotency_key": "hidden-key",
            }
            self._write(root, "committed.json", row)
            with mock.patch.object(adapter, "_journal_path", return_value=root):
                result = adapter._mutation_wal_audit({"status": "COMMITTED", "limit": 1})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["terminal_status"], "COMMITTED")
        self.assertIsNone(result["rows"][0]["error_type"])
        self.assertNotIn("secret@example.com", json.dumps(result))
        self.assertNotIn("hidden-key", json.dumps(result))

    def test_limit_is_bounded_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-limit-") as td:
            root = Path(td)
            for index in range(5):
                self._write(root, f"{index}.json", self._base_error(
                    tool=f"tool_{index}",
                    completed_at=f"2026-09-09T04:00:0{index}Z",
                    message=f"VALIDATION_FAILED: {index}",
                ))
            with mock.patch.object(adapter, "_journal_path", return_value=root):
                result = adapter._mutation_wal_audit({"limit": 2})
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["matched_count"], 5)
        self.assertEqual([r["tool"] for r in result["rows"]], ["tool_4", "tool_3"])

    def test_invalid_filters_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-invalid-") as td:
            root = Path(td)
            with mock.patch.object(adapter, "_journal_path", return_value=root):
                for args in (
                    {"status": "PREPARED"},
                    {"status": "INVALID"},
                    {"status": "COMMITTED_ERROR", "limit": 0},
                    {"status": "COMMITTED_ERROR", "limit": 501},
                    {"status": "COMMITTED_ERROR", "limit": "not-an-int"},
                ):
                    with self.subTest(args=args):
                        with self.assertRaises(ValidationError):
                            adapter._mutation_wal_audit(args)

    def test_malformed_rows_are_counted_without_raw_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-malformed-") as td:
            root = Path(td)
            (root / "broken.json").write_text("{not-json", encoding="utf-8")
            self._write(root, "unknown.json", {"schema": "wrong", "status": "COMMITTED_ERROR", "secret": "do-not-return"})
            with mock.patch.object(adapter, "_journal_path", return_value=root):
                result = adapter._mutation_wal_audit({})
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["invalid_record_count"], 2)
        self.assertNotIn("do-not-return", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
