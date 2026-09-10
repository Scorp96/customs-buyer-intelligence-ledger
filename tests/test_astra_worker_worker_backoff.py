from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from astra_worker.worker import WorkerCycleResult, WorkerError, WorkerTransportError
from tests import test_astra_worker_worker as worker_fixtures


class WorkerBackoffTests(unittest.TestCase):
    def _worker(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        helper = worker_fixtures.WorkerTests()
        worker, _queue, _ledger, _workspace, _executor = helper._worker(root)
        return temporary, worker

    def test_transport_failures_use_bounded_exponential_backoff(self) -> None:
        temporary, worker = self._worker()
        self.addCleanup(temporary.cleanup)
        sleeps: list[float] = []

        def stop_after_five(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 5:
                raise StopIteration

        worker._sleep = stop_after_five
        worker.run_once = Mock(side_effect=[WorkerTransportError("network")] * 5)
        with self.assertRaises(StopIteration):
            worker.run_forever()
        self.assertEqual(sleeps, [15.0, 30.0, 60.0, 120.0, 300.0])
        self.assertEqual(worker.run_once.call_count, 5)

    def test_success_resets_transport_backoff(self) -> None:
        temporary, worker = self._worker()
        self.addCleanup(temporary.cleanup)
        sleeps: list[float] = []

        def stop_after_four(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 4:
                raise StopIteration

        worker._sleep = stop_after_four
        worker.run_once = Mock(
            side_effect=[
                WorkerTransportError("first"),
                WorkerCycleResult(status="IDLE"),
                WorkerTransportError("second"),
                WorkerTransportError("third"),
            ]
        )
        with self.assertRaises(StopIteration):
            worker.run_forever()
        self.assertEqual(sleeps, [15.0, 15.0, 15.0, 30.0])

    def test_nontransport_worker_error_is_not_transport_retried(self) -> None:
        temporary, worker = self._worker()
        self.addCleanup(temporary.cleanup)
        sleeps: list[float] = []
        worker._sleep = sleeps.append
        worker.run_once = Mock(side_effect=WorkerError("schema/state failure"))
        with self.assertRaises(WorkerError):
            worker.run_forever()
        self.assertEqual(worker.run_once.call_count, 1)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
