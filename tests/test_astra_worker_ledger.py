from __future__ import annotations

from pathlib import Path
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

    def claim(self, ledger: TaskLedger, task_id: str = "t1", nonce: str = "n1", digest: str = "d1"):
        return ledger.claim(task_id, nonce, digest, "cbi-primary", "astra-test", BASE_SHA)

    def test_same_task_or_nonce_cannot_execute_twice(self) -> None:
        ledger = TaskLedger(self.db)
        self.claim(ledger)
        with self.assertRaises(ReplayError):
            ledger.claim("t1", "n2", "d1", "cbi-primary", "astra-test", BASE_SHA)
        with self.assertRaises(ReplayError):
            ledger.claim("t2", "n1", "d2", "cbi-primary", "astra-test", BASE_SHA)

    def test_conflicting_digest_for_task_id_is_rejected(self) -> None:
        ledger = TaskLedger(self.db)
        self.claim(ledger)
        with self.assertRaises(ReplayConflictError):
            ledger.claim("t1", "n1", "DIFFERENT", "cbi-primary", "astra-test", BASE_SHA)

    def test_claimed_row_survives_reopen_and_is_not_reclaimed_as_fresh(self) -> None:
        first = TaskLedger(self.db)
        record = self.claim(first)
        self.assertEqual(record.state, "CLAIMED")
        first.close()

        reopened = TaskLedger(self.db)
        in_progress = reopened.list_in_progress()
        self.assertEqual([item.task_id for item in in_progress], ["t1"])
        self.assertEqual(in_progress[0].state, "CLAIMED")
        with self.assertRaises(ReplayError):
            self.claim(reopened)

    def test_terminal_record_is_replayable_but_never_executable_again(self) -> None:
        ledger = TaskLedger(self.db)
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
        ledger = TaskLedger(self.db)
        self.claim(ledger)
        ledger.mark_terminal("t1", "receipt-digest-1", terminal_state="QUARANTINED")
        updated = ledger.mark_cleanup("t1", "FAILED")
        self.assertEqual(updated.state, "QUARANTINED")
        self.assertEqual(updated.cleanup_state, "FAILED")
        ledger.close()

        reopened = TaskLedger(self.db)
        replay = reopened.find_replay("t1", "n1", "d1")
        self.assertEqual(replay.state, "QUARANTINED")
        self.assertEqual(replay.cleanup_state, "FAILED")

    def test_worker_lease_allows_only_one_active_holder(self) -> None:
        first = TaskLedger(self.db)
        second = TaskLedger(self.db)
        lease = first.acquire_worker_lease("worker-1")
        with self.assertRaises(LeaseError):
            second.acquire_worker_lease("worker-2")
        lease.release()
        replacement = second.acquire_worker_lease("worker-2")
        replacement.release()

    def test_sqlite_durability_pragmas_are_enabled(self) -> None:
        ledger = TaskLedger(self.db)
        pragmas = ledger.durability_pragmas()
        self.assertEqual(pragmas["journal_mode"].lower(), "wal")
        self.assertEqual(pragmas["synchronous"], 2)
        self.assertEqual(pragmas["foreign_keys"], 1)


if __name__ == "__main__":
    unittest.main()
