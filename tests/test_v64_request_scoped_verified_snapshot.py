from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_v6_load_acceptance import append_batches, observation, start_runtime
from unified_runtime.errors import ValidationError
from unified_runtime.research_orchestration_hardening import (
    V61ResearchOrchestrationHardeningMixin,
)


class _MemoryOnlyBase:
    def __init__(self) -> None:
        self.account_result = {
            "investigation_id": "INV-MEMORY",
            "account": {"account_id": "C-MEMORY"},
        }
        self.outreach_result = {
            "outreach_readiness": "IDENTITY_ONLY",
            "readiness": "IDENTITY_ONLY",
            "canonical_route_view": [],
            "block_reasons": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            "sends_message": False,
        }
        self.public_plan = {
            "source_coverage_complete": False,
            "source_coverage_status": "INCOMPLETE",
            "remaining_source_attempt_count_at_least": 1,
            "truncated": False,
        }
        self.state = {"observations": {}, "peers": {}}

    def get_account_state(self, arguments):
        return dict(self.account_result)

    def evaluate_outreach_readiness(self, arguments):
        return dict(self.outreach_result)

    def plan_public_source_calls(self, arguments):
        return dict(self.public_plan)

    def _v6_state(self, investigation_id):
        return self.state

    def _route_projection_diagnostics(self, state, outreach):
        return {"status": "MEMORY_ONLY"}

    def _peer_reconciliation_view(self, state):
        return {"status": "MEMORY_ONLY"}


class _MemoryOnlyRuntime(V61ResearchOrchestrationHardeningMixin, _MemoryOnlyBase):
    pass


class RequestScopedVerifiedSnapshotTests(unittest.TestCase):
    def test_get_account_state_verifies_session_log_once_per_request(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-snapshot-") as temp:
            runtime, investigation_id = start_runtime(Path(temp) / "sessions")
            append_batches(
                runtime,
                investigation_id,
                [observation(index) for index in range(100)],
                prefix="SNAPSHOT",
            )

            original = runtime.store._read_unlocked
            calls = {"count": 0}

            def counted(inv_id):
                calls["count"] += 1
                return original(inv_id)

            runtime.store._read_unlocked = counted
            result = runtime.get_account_state({"investigation_id": investigation_id})

            self.assertEqual(result["investigation_id"], investigation_id)
            self.assertEqual(
                calls["count"],
                1,
                "one read-only account-state request must verify the durable session exactly once",
            )

    def test_next_request_revalidates_disk_and_detects_corruption(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-snapshot-corrupt-") as temp:
            runtime, investigation_id = start_runtime(Path(temp) / "sessions")
            append_batches(
                runtime,
                investigation_id,
                [observation(index) for index in range(12)],
                prefix="CORRUPT",
            )
            runtime.get_account_state({"investigation_id": investigation_id})

            path = runtime.store.path(investigation_id)
            lines = path.read_text(encoding="utf-8").splitlines()
            tail = json.loads(lines[-1])
            tail["event_hash"] = "0" * 64
            lines[-1] = json.dumps(tail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "hash mismatch"):
                runtime.get_account_state({"investigation_id": investigation_id})

    def test_memory_only_mixin_without_store_keeps_legacy_read_path(self) -> None:
        runtime = _MemoryOnlyRuntime()
        result = runtime.get_account_state({"investigation_id": "INV-MEMORY"})
        self.assertEqual(result["investigation_id"], "INV-MEMORY")
        self.assertEqual(result["route_projection_diagnostics"]["status"], "MEMORY_ONLY")
        self.assertEqual(result["peer_reconciliation"]["status"], "MEMORY_ONLY")


if __name__ == "__main__":
    unittest.main()
