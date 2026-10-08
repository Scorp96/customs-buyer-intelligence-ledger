"""Recovery self-restore remains usable after public health metadata minimization."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from mcp.authoritative_source_evidence_v64 import (
    AuthoritativeSourceEvidenceError,
    read_operator_recovery_pointer,
    _tool_descriptor,
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


if __name__ == "__main__":
    unittest.main()
