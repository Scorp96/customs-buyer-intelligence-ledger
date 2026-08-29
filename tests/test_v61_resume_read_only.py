from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime
from unified_runtime.core import UnifiedRuntime as CompatibilityRuntime


class V61ResumeReadOnlyTests(unittest.TestCase):
    def test_legacy_resume_is_byte_for_byte_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-resume-read-only-") as temp:
            session_root = Path(temp) / "sessions"
            legacy = CompatibilityRuntime(session_root)
            started = legacy.start_investigation({
                "account": {
                    "account_id": "C-RESUME-LEGACY-001",
                    "country": "Canada",
                    "name": "Legacy Resume Fixture Buyer",
                },
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
            })
            investigation_id = started["investigation_id"]
            session_path = legacy.store.path(investigation_id)
            before_bytes = session_path.read_bytes()
            before_hash = hashlib.sha256(before_bytes).hexdigest()
            before_events = legacy.store.read(investigation_id)

            runtime = UnifiedRuntime(session_root)
            result = runtime.resume_investigation({"investigation_id": investigation_id})

            after_bytes = session_path.read_bytes()
            after_hash = hashlib.sha256(after_bytes).hexdigest()
            after_events = runtime.store.read(investigation_id)

            self.assertEqual(result["status"], "RESUMED")
            self.assertFalse(result["resume_mutated_durable_state"])
            self.assertTrue(result["legacy_adapter_read_only"])
            self.assertEqual(result["last_safe_seq"], before_events[-1]["seq"])
            self.assertEqual(result["last_safe_event_hash"], before_events[-1]["event_hash"])
            self.assertEqual(
                result["last_safe_state"]["last_committed_mutation"]["seq"],
                before_events[-1]["seq"],
            )
            self.assertEqual(before_bytes, after_bytes)
            self.assertEqual(before_hash, after_hash)
            self.assertEqual(len(before_events), len(after_events))
            self.assertEqual(before_events[-1]["event_hash"], after_events[-1]["event_hash"])
            self.assertFalse(any(
                event["event_type"] == "V6_RUNTIME_INITIALIZED"
                for event in after_events
            ))


if __name__ == "__main__":
    unittest.main()
