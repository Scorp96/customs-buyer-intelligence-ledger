from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from astra_worker.ledger import (
    LedgerStateError,
    LeaseError,
    ReplayConflictError,
    ReplayError,
    TaskLedger,
)


BASE_SHA = "a" * 40


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.db = Path(self._td.name) / "worker-ledger.sqlite3"

    def open_ledger(self) -> TaskLedger:
        ledger = TaskLedger(self.db)
        self.addCleanup(ledger.close)
        return ledger

    def claim(self, ledger: TaskLedger, task_id: str = "t1", nonce: str = "n1", digest: str = "d1"):
        return ledger.claim(task_id, nonce, digest, "cbi-primary", "astra-test", BASE_SHA)

    def test_same_task_or_nonce_cannot_execute_twice(self) -> None:
        ledger = self.open_ledger()
        self.claim(ledger)
        with self.assertRaises(ReplayError):
            ledger.claim("t1", "n2", "d1", "cbi-primary", "astra-test", BASE_SHA)
        with self.assertRaises(ReplayError):
            ledger.claim("t2", "n1", "d2", "cbi-primary", "astra-test", BASE_SHA)

    def test_conflicting_digest_for_task_id_is_rejected(self) -> None:
        ledger = self.open_ledger()
        self.claim(ledger)
        with self.assertRaises(ReplayConflictError):
            ledger.claim("t1", "n1", "DIFFERENT", "cbi-primary", "astra-test", BASE_SHA)

    def test_claimed_row_survives_reopen_and_is_not_reclaimed_as_fresh(self) -> None:
        first = self.open_ledger()
        record = self.claim(first)
        self.assertEqual(record.state, "CLAIMED")
        first.close()

        reopened = self.open_ledger()
        in_progress = reopened.list_in_progress()
        self.assertEqual([item.task_id for item in in_progress], ["t1"])
        self.assertEqual(in_progress[0].state, "CLAIMED")
        with self.assertRaises(ReplayError):
            self.claim(reopened)

    def test_mark_executing_persists_workspace_identity_and_is_monotonic(self) -> None:
        ledger = self.open_ledger()
        self.claim(ledger)
        executing = ledger.mark_executing(
            "t1",
            mirror_identity="cbi-primary.git@a" + BASE_SHA[1:],
            worktree="D:/ASTRAWorker/worktrees/task-t1",
            generated_branch="astra-worker/task-t1",
        )
        self.assertEqual(executing.state, "EXECUTING")
        self.assertEqual(executing.mirror_identity, "cbi-primary.git@a" + BASE_SHA[1:])
        self.assertEqual(executing.worktree, "D:/ASTRAWorker/worktrees/task-t1")
        self.assertEqual(executing.generated_branch, "astra-worker/task-t1")
        with self.assertRaises(LedgerStateError):
            ledger.mark_executing(
                "t1",
                mirror_identity="other",
                worktree="other",
                generated_branch="other",
            )
        ledger.close()

        reopened = self.open_ledger()
        in_progress = reopened.list_in_progress()
        self.assertEqual(len(in_progress), 1)
        self.assertEqual(in_progress[0].state, "EXECUTING")
        self.assertEqual(in_progress[0].worktree, "D:/ASTRAWorker/worktrees/task-t1")

    def test_executing_row_can_transition_terminal_exactly_once(self) -> None:
        ledger = self.open_ledger()
        self.claim(ledger)
        ledger.mark_executing(
            "t1",
            mirror_identity="mirror-identity",
            worktree="D:/ASTRAWorker/worktrees/task-t1",
            generated_branch="astra-worker/task-t1",
        )
        terminal = ledger.mark_terminal("t1", "receipt-digest-1")
        self.assertEqual(terminal.state, "TERMINAL")
        self.assertEqual(terminal.worktree, "D:/ASTRAWorker/worktrees/task-t1")
        with self.assertRaises(LedgerStateError):
            ledger.mark_terminal("t1", "receipt-digest-2")

    def test_terminal_record_is_replayable_but_never_executable_again(self) -> None:
        ledger = self.open_ledger()
        self.claim(ledger)
        terminal = ledger.mark_terminal("t1", "receipt-digest-1", terminal_state="TERMINAL")
        self.assertEqual(terminal.state, "TERMINAL")
        replay = ledger.find_replay("t1", "n1", "d1")
        self.assertIsNotNone(replay)
        self.assertEqual(replay.receipt_digest, "receipt-digest-1")
        with self.assertRaises(ReplayError):
            self.claim(ledger)
        with self.assertRaises(LedgerStateError):
            ledger.mark_terminal("t1", "receipt-digest-2", terminal_state="TERMINAL")

    def test_cleanup_state_is_durable_and_does_not_reopen_terminal_record(self) -> None:
        ledger = self.open_ledger()
        self.claim(ledger)
        ledger.mark_terminal("t1", "receipt-digest-1", terminal_state="QUARANTINED")
        updated = ledger.mark_cleanup("t1", "FAILED")
        self.assertEqual(updated.state, "QUARANTINED")
        self.assertEqual(updated.cleanup_state, "FAILED")
        ledger.close()

        reopened = self.open_ledger()
        replay = reopened.find_replay("t1", "n1", "d1")
        self.assertEqual(replay.state, "QUARANTINED")
        self.assertEqual(replay.cleanup_state, "FAILED")

    def test_worker_lease_allows_only_one_active_holder(self) -> None:
        first = self.open_ledger()
        second = self.open_ledger()
        lease = first.acquire_worker_lease("worker-1")
        with self.assertRaises(LeaseError):
            second.acquire_worker_lease("worker-2")
        lease.release()
        replacement = second.acquire_worker_lease("worker-2")
        replacement.release()

    def test_worker_lease_is_recoverable_after_process_hard_exit(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        script = (
            "from pathlib import Path; import os, sys; "
            "from astra_worker.ledger import TaskLedger; "
            "ledger=TaskLedger(Path(sys.argv[1])); "
            "ledger.acquire_worker_lease('crashed-worker'); "
            "os._exit(0)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(self.db)],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        reopened = self.open_ledger()
        replacement = reopened.acquire_worker_lease("replacement-worker")
        replacement.release()

    def test_sqlite_durability_pragmas_are_enabled(self) -> None:
        ledger = self.open_ledger()
        pragmas = ledger.durability_pragmas()
        self.assertEqual(pragmas["journal_mode"].lower(), "wal")
        self.assertEqual(pragmas["synchronous"], 2)
        self.assertEqual(pragmas["foreign_keys"], 1)


if __name__ == "__main__":
    unittest.main()
