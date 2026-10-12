"""Pure fixture tests for disabled-by-default operator projection health probe."""
from __future__ import annotations

import copy
import os
import hashlib
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch

from mcp.operator_projection_diagnostic_v64 import inspect_authoritative_projection
from unified_runtime.product_profiles import get_product_profile
from unified_runtime.recovery_semantics_v63 import snapshot_sha256

INV = "INV-SYNTHETIC-DIAG-001"
TAIL = "e" * 64


def event(seq=1, corr="MUTCORR-SYNTHETIC-1", *, account="C-FAKE", tamper=False):
    prof = get_product_profile("PVC")
    snapshot = {
        "status": "CREATED", "stage": "OPPORTUNITY_CREATED",
        "opportunity_id": "OPP-FAKE-001", "account_id": account,
        "product_profile_id": "PVC",
        "product_profile_version": prof["profile_version"],
        "product_profile_sha256": prof["profile_sha256"],
    }
    return {
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "seq": seq,
        "event_hash": TAIL if seq == 2 else "d" * 64,
        "payload": {
            "investigation_id": INV,
            "request_sha256": "a" * 64,
            "result_snapshot": snapshot,
            "result_snapshot_sha256": "b" * 64 if tamper else snapshot_sha256(snapshot),
            "raw_idempotency_key_persisted": False,
        },
        "mutation_correlation": {
            "schema": "cbi.mutation-correlation.v6.1",
            "tool": "create_product_opportunity",
            "correlation_id": corr,
        },
    }


class FakeStore:
    def __init__(self, values, change_on_second_read=False):
        self.values = copy.deepcopy(values)
        self.read_count = 0
        self.change = change_on_second_read

    def read(self, name):
        assert name == INV
        self.read_count += 1
        values = copy.deepcopy(self.values)
        if self.change and self.read_count > 1:
            values[-1]["event_hash"] = "c" * 64
        return values


class FakeRuntime:
    def __init__(self, values, change_on_second_read=False):
        self.store = FakeStore(values, change_on_second_read=change_on_second_read)

    def _normalize_v63_opportunity_event(self, inv, row):
        if row.get("event_type") != "V63_PRODUCT_OPPORTUNITY_CREATED":
            return None
        p = copy.deepcopy(row["payload"])
        p["event_type"] = row["event_type"]
        p["investigation_id"] = inv
        p["seq"] = row["seq"]
        p["correlation_id"] = row["mutation_correlation"]["correlation_id"]
        return p


def args(**override):
    value = {
        "investigation_id": INV,
        "expected_last_safe_seq": 2,
        "expected_last_safe_event_hash": TAIL,
        "acknowledge_private_state": True,
    }
    value.update(override)
    return value


def operator_env(*, inv=INV, minutes=5):
    return {
        "CBI_V64_OPERATOR_PROJECTION_DIAGNOSTIC_ENABLED": "1",
        "CBI_V64_OPERATOR_DIAG_SESSION_SHA256": hashlib.sha256(inv.encode("utf-8")).hexdigest(),
        "CBI_V64_OPERATOR_DIAG_EXPIRES_AT": (
            datetime.now(timezone.utc) + timedelta(minutes=minutes)
        ).isoformat(),
    }


class OperatorProjectionDiagnosticTests(unittest.TestCase):
    def test_disabled_by_default_never_reads_any_session(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DIAGNOSTIC_DISABLED"):
                inspect_authoritative_projection(runtime, args())
        self.assertEqual(runtime.store.read_count, 0)

    def test_enabled_exact_replay_returns_sanitized_candidate(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env()):
            result = inspect_authoritative_projection(runtime, args())
        self.assertEqual(result["status"], "REPLAY_CANDIDATES_NEED_INDEPENDENT_WAL_PROOF")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["duplicate_opportunity_groups"], 1)
        self.assertFalse(result["authoritative_wal_independently_reconciled"])
        self.assertFalse(result["raw_events_exported"])
        self.assertFalse(result["safe_to_autorepair"])
        self.assertEqual(runtime.store.read_count, 2)
        self.assertNotIn("opportunity_id_sha256", str(result))
        self.assertNotIn("C-FAKE", str(result))
        self.assertNotIn("MUTCORR-SYNTHETIC-1", str(result))

    def test_distinct_correlation_remains_conflict(self):
        runtime = FakeRuntime([event(1), event(2, corr="MUTCORR-SYNTHETIC-2")])
        with patch.dict(os.environ, operator_env()):
            result = inspect_authoritative_projection(runtime, args())
        self.assertEqual(result["status"], "CONFLICT")
        self.assertEqual(result["counts"]["distinct_correlation_conflicts"], 1)

    def test_tampered_result_snapshot_fails_closed(self):
        runtime = FakeRuntime([event(1, tamper=True), event(2)])
        with patch.dict(os.environ, operator_env()):
            result = inspect_authoritative_projection(runtime, args())
        self.assertEqual(result["status"], "INVALID_EVENT_PROOF")
        self.assertFalse(result["recovery_acceptance_achieved"])

    def test_tail_changed_between_reads_fails_closed(self):
        runtime = FakeRuntime([event(1), event(2)], change_on_second_read=True)
        with patch.dict(os.environ, operator_env()):
            with self.assertRaisesRegex(RuntimeError, "CHAIN_CHANGED"):
                inspect_authoritative_projection(runtime, args())

    def test_wrong_tail_hash_refused(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env()):
            with self.assertRaisesRegex(RuntimeError, "EXPECTATION_MISMATCH"):
                inspect_authoritative_projection(runtime, args(expected_last_safe_event_hash="a" * 64))

    def test_bool_sequence_not_accepted_as_integer(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env()):
            with self.assertRaisesRegex(ValueError, "SEQ_REQUIRED"):
                inspect_authoritative_projection(runtime, args(expected_last_safe_seq=True))

    def test_arbitrary_file_paths_and_event_arguments_rejected(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env()):
            with self.assertRaisesRegex(ValueError, "UNKNOWN_ARGUMENTS"):
                inspect_authoritative_projection(runtime, args(source_path="/var/lib/cbi/live/sessions"))

    def test_explicit_ack_required(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env()):
            with self.assertRaisesRegex(ValueError, "ACK_REQUIRED"):
                inspect_authoritative_projection(runtime, args(acknowledge_private_state=False))

    def test_malformed_session_identity_rejected(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env()):
            with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
                inspect_authoritative_projection(runtime, args(investigation_id="../../etc/passwd"))

    def test_enabled_without_exact_session_allowlist_fails_closed(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, {"CBI_V64_OPERATOR_PROJECTION_DIAGNOSTIC_ENABLED": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALLOWLIST_MISSING"):
                inspect_authoritative_projection(runtime, args())
        self.assertEqual(runtime.store.read_count, 0)

    def test_wrong_session_allowlist_denied_before_data_read(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env(inv="INV-SYNTHETIC-OTHER"), clear=True):
            with self.assertRaisesRegex(RuntimeError, "SESSION_NOT_ALLOWED"):
                inspect_authoritative_projection(runtime, args())
        self.assertEqual(runtime.store.read_count, 0)

    def test_expired_operator_window_fails_closed(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env(minutes=-1), clear=True):
            with self.assertRaisesRegex(RuntimeError, "WINDOW_CLOSED"):
                inspect_authoritative_projection(runtime, args())
        self.assertEqual(runtime.store.read_count, 0)

    def test_window_longer_than_15_minutes_fails_closed(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env(minutes=45), clear=True):
            with self.assertRaisesRegex(RuntimeError, "WINDOW_CLOSED"):
                inspect_authoritative_projection(runtime, args())
        self.assertEqual(runtime.store.read_count, 0)

    def test_expiry_without_timezone_fails_closed(self):
        runtime = FakeRuntime([event(1), event(2)])
        env = operator_env()
        env["CBI_V64_OPERATOR_DIAG_EXPIRES_AT"] = "2026-10-12T17:00:00"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "EXPIRY_INVALID"):
                inspect_authoritative_projection(runtime, args())
        self.assertEqual(runtime.store.read_count, 0)

    def test_collision_positions_are_not_exported(self):
        runtime = FakeRuntime([event(1), event(2)])
        with patch.dict(os.environ, operator_env(), clear=True):
            report = inspect_authoritative_projection(runtime, args())
        self.assertNotIn("input_indices", str(report))
        self.assertNotIn("input_index", str(report))
        self.assertTrue(report["operator_window_expiry_enforced"])
        self.assertTrue(report["exact_session_allowlist_enforced"])

    def test_no_duplicate_healthy_session(self):
        only = [event(2)]
        runtime = FakeRuntime(only)
        with patch.dict(os.environ, operator_env()):
            result = inspect_authoritative_projection(runtime, args())
        self.assertEqual(result["status"], "NO_DUPLICATE_CREATE_EVENTS")
        self.assertEqual(result["duplicate_opportunity_groups"], 0)
        self.assertFalse(result["production_write_performed"])


if __name__ == "__main__":
    unittest.main()
