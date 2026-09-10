from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp.authoritative_source_evidence_v64 import (
    AuthoritativeSourceEvidenceError,
    build_recovery_self_restore_proof,
)


class AuthoritativeSourceEvidenceNoStoreTest(unittest.TestCase):
    def test_recovery_self_restore_fails_closed_when_object_store_is_unbound(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            live_root = Path(tmp_name) / "live"
            (live_root / "sessions").mkdir(parents=True)
            (live_root / "mcp-idempotency-v61").mkdir(parents=True)
            with self.assertRaisesRegex(AuthoritativeSourceEvidenceError, "object store.*not bound"):
                build_recovery_self_restore_proof(
                    persistence=None,
                    live_root=live_root,
                    expected_generation=0,
                    expected_recovery_fingerprint_sha256="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
