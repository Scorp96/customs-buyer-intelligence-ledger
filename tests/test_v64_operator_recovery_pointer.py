"""Recovery self-restore remains usable after public health metadata minimization."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mcp.authoritative_source_evidence_v64 import (
    AuthoritativeSourceEvidenceError,
    read_operator_recovery_pointer,
    _tool_descriptor,
    build_server_pinned_recovery_self_restore_proof,
    install_remote_authoritative_source_evidence_tool,
)


class _Storage:
    def __init__(self, pointer):
        self.pointer = pointer
        self.reads = []

    def read_pointer(self, *, required: bool):
        self.reads.append(required)
        return self.pointer


class RecoveryPointerOperatorTests(unittest.TestCase):
    def test_auth_operator_tool_exposes_exact_pointer_without_writes(self):
        pointer = SimpleNamespace(
            generation=84,
            archive_sha256="a" * 64,
            sessions_fingerprint_sha256="b" * 64,
            recovery_fingerprint_sha256="c" * 64,
            archive_format="object_state_v2",
        )
        storage = _Storage(pointer)
        result = read_operator_recovery_pointer(persistence=storage)
        self.assertEqual(storage.reads, [True])
        self.assertEqual(result["generation"], 84)
        self.assertEqual(result["recovery_fingerprint_sha256"], "c" * 64)
        self.assertEqual(result["source"], "AUTHENTICATED_MCP_ONLY")
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertNotIn("archive_key", result)

    def test_invalid_pointer_fails_closed(self):
        invalid = SimpleNamespace(
            generation=-1,
            archive_sha256="a" * 64,
            sessions_fingerprint_sha256="b" * 64,
            recovery_fingerprint_sha256="c" * 64,
            archive_format="object_state_v2",
        )
        with self.assertRaises(AuthoritativeSourceEvidenceError):
            read_operator_recovery_pointer(persistence=_Storage(invalid))
        with self.assertRaises(AuthoritativeSourceEvidenceError):
            read_operator_recovery_pointer(persistence=None)

    def test_descriptor_lists_operator_read_without_mutation_permission(self):
        schema = _tool_descriptor()["inputSchema"]
        self.assertIn("READ_RECOVERY_POINTER", schema["properties"]["operation"]["enum"])
        self.assertIn("RECOVERY_SELF_RESTORE_PROOF", schema["properties"]["operation"]["enum"])


    def test_server_side_autopin_delegates_to_existing_isolated_proof(self):
        pointer = SimpleNamespace(
            generation=84,
            archive_sha256="a" * 64,
            sessions_fingerprint_sha256="b" * 64,
            recovery_fingerprint_sha256="c" * 64,
            archive_format="object_state_v2",
        )
        storage = _Storage(pointer)
        existing = {
            "schema": "cbi.recovery-proof.v1",
            "verified": True,
            "object_store_write_performed": False,
            "production_write_performed": False,
            "restore_target_isolated": True,
        }
        with mock.patch(
            "mcp.authoritative_source_evidence_v64.build_recovery_self_restore_proof",
            return_value=existing,
        ) as proof:
            actual = build_server_pinned_recovery_self_restore_proof(
                persistence=storage,
                live_root=Path("/synthetic/never-accessed"),
            )
        self.assertEqual(storage.reads, [True])
        proof.assert_called_once_with(
            persistence=storage,
            live_root=Path("/synthetic/never-accessed"),
            expected_generation=84,
            expected_recovery_fingerprint_sha256="c" * 64,
        )
        self.assertTrue(actual["verified"])
        self.assertFalse(actual["production_write_performed"])
        self.assertFalse(actual["independent_operator_expectation_proven"])
        self.assertEqual(actual["expectation_source"], "SERVER_POINTER_READ_AT_START")

    def test_legacy_tool_enum_can_request_autopin_but_never_partial_pin(self):
        pointer = SimpleNamespace(
            generation=84,
            archive_sha256="a" * 64,
            sessions_fingerprint_sha256="b" * 64,
            recovery_fingerprint_sha256="c" * 64,
            archive_format="object_state_v2",
        )
        storage = _Storage(pointer)
        server = SimpleNamespace(tool_descriptors=lambda: [], TOOL_HANDLERS={})
        install_remote_authoritative_source_evidence_tool(
            server_module=server,
            persistence=storage,
            runtime=None,
            live_root=Path("/synthetic"),
        )
        operation = "RECOVERY_SELF_RESTORE_PROOF"
        name = _tool_descriptor()["name"]
        handler = server.TOOL_HANDLERS[name]
        with mock.patch(
            "mcp.authoritative_source_evidence_v64.build_server_pinned_recovery_self_restore_proof",
            return_value={"verified": True, "independent_operator_expectation_proven": False},
        ) as auto, mock.patch(
            "mcp.authoritative_source_evidence_v64.build_recovery_self_restore_proof",
            return_value={"verified": True},
        ) as exact:
            with self.assertRaisesRegex(
                AuthoritativeSourceEvidenceError, "explicit acknowledgement"
            ):
                handler({"operation": operation})
            auto.assert_not_called()
            self.assertTrue(handler({
                "operation": operation,
                "acknowledge_private_state": True,
            })["verified"])
            auto.assert_called_once()
            exact.assert_not_called()
            for invalid in (
                {"operation": operation, "expected_generation": 84},
                {"operation": operation, "expected_recovery_fingerprint_sha256": "c" * 64},
            ):
                with self.subTest(case=invalid):
                    with self.assertRaises(AuthoritativeSourceEvidenceError):
                        handler(invalid)
            self.assertTrue(handler({
                "operation": operation,
                "expected_generation": 84,
                "expected_recovery_fingerprint_sha256": "c" * 64,
            })["verified"])
            exact.assert_called_once()
        self.assertEqual(storage.reads, [])

    def test_invalid_pointer_blocks_autopin_before_any_restore(self):
        pointer = SimpleNamespace(
            generation=84,
            archive_sha256="a" * 64,
            sessions_fingerprint_sha256="b" * 64,
            recovery_fingerprint_sha256="not-a-hash",
            archive_format="object_state_v2",
        )
        with mock.patch(
            "mcp.authoritative_source_evidence_v64.build_recovery_self_restore_proof",
        ) as proof:
            with self.assertRaises(AuthoritativeSourceEvidenceError):
                build_server_pinned_recovery_self_restore_proof(
                    persistence=_Storage(pointer), live_root=Path("/synthetic"),
                )
            proof.assert_not_called()


if __name__ == "__main__":
    unittest.main()
