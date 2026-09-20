from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


class PortfolioQueueReadEfficiencyTests(unittest.TestCase):
    def test_full_visible_portfolio_verifies_each_session_once_before_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-portfolio-read-") as temp:
            runtime = UnifiedRuntime(Path(temp) / "sessions")
            investigation_ids = []
            for index in range(12):
                started = runtime.start_investigation({
                    "account": {
                        "account_id": f"C-PQ-{index:04d}",
                        "country": "US",
                        "name": f"Portfolio Queue Buyer {index}",
                    },
                    "mode": "FAST_SCAN",
                    "history": {"events": []},
                })
                investigation_ids.append(started["investigation_id"])

            original = runtime.store._read_unlocked
            reads = {"count": 0}

            def counted(investigation_id):
                reads["count"] += 1
                return original(investigation_id)

            runtime.store._read_unlocked = counted
            result = runtime.get_portfolio_queue({"limit": 5})

            self.assertEqual(result["total_scanned"], len(investigation_ids))
            self.assertEqual(len(result["queue"]), 5)
            self.assertTrue(result["canonical_identity_reconciliation"]["coverage_complete"])
            self.assertLessEqual(
                reads["count"],
                len(investigation_ids) + 1,
                "portfolio projection must not re-verify every session for each derived sub-view",
            )


if __name__ == "__main__":
    unittest.main()
