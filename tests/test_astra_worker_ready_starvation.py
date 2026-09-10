from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_worker.evidence import ChangeEvidence
from astra_worker.worker import Worker
from tests.test_astra_worker_worker import (
    FakeCompiler,
    FakeExecutor,
    FakeLedger,
    FakeQueue,
    FakeWorkspace,
    NOW,
    RECEIPT_KEY,
    config,
    ready,
    typed_task,
)


class ReadyQueueStarvationTests(unittest.TestCase):
    def test_expired_first_ready_does_not_starve_later_valid_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expired = typed_task(
                task_id="expired-task",
                nonce="expired-nonce",
                issued_at="2026-09-09T02:00:00Z",
                expires_at="2026-09-09T02:30:00Z",
            )
            valid = typed_task(task_id="valid-task", nonce="valid-nonce")
            queue = FakeQueue([ready(expired, 32), ready(valid, 35)])
            ledger = FakeLedger()
            workspace = FakeWorkspace(root)
            executor = FakeExecutor()
            worker = Worker(
                config=config(),
                queue=queue,
                ledger=ledger,
                workspace_factory=lambda _binding: workspace,
                compiler=FakeCompiler(),
                executor=executor,
                disabled_marker=root / "DISABLED",
                receipt_key=RECEIPT_KEY,
                now=lambda: NOW,
            )
            intended = {"example.txt": hashlib.sha256(b"hello\n").hexdigest()}
            evidence = ChangeEvidence(
                changed_paths=("example.txt",),
                observed_final_hashes=intended,
                patch_sha256=hashlib.sha256(b"").hexdigest(),
                diff_bytes=0,
            )
            with (
                patch("astra_worker.worker.verify_pre_state", return_value=None),
                patch("astra_worker.worker.verify_final_state", return_value=evidence),
                patch("astra_worker.worker.build_text_patch", return_value=b""),
            ):
                result = worker.run_once()

            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.issue_number, 35)
            self.assertEqual(queue.claimed, [35])
            self.assertEqual(ledger.claimed, [valid.task_id])
            self.assertEqual(executor.calls, 1)
            self.assertNotIn(expired.task_id, ledger.claimed)


if __name__ == "__main__":
    unittest.main()
