from __future__ import annotations

import unittest

from astra_worker.receipt_gate import ReceiptGateError
from tests import test_astra_worker_gates as gates


class ReceiptGateRecoveryTests(unittest.TestCase):
    def _fixture(self):
        helper = gates.ReceiptGateTests()
        task = gates.valid_task_mapping()
        receipt = gates.valid_receipt_mapping(task)
        api, body = helper._api_for_receipt(task=task, receipt=receipt)
        gate = helper._gate(api)
        return task, receipt, api, body, gate

    def test_verified_terminal_retry_is_idempotent_and_zero_write(self) -> None:
        _task, _receipt, api, body, gate = self._fixture()
        api.labels = {"astra-task/result-verified", "astra-task/completed"}
        writes: list[set[str]] = []
        original_replace = api.replace_astra_labels

        def recording_replace(issue_number: int, labels: set[str]) -> None:
            writes.append(set(labels))
            original_replace(issue_number, labels)

        api.replace_astra_labels = recording_replace
        result = gate.process(gates.receipt_event(body))
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.receipt_status, "APPLY_READY")
        self.assertEqual(writes, [])
        self.assertEqual(
            api.labels,
            {"astra-task/result-verified", "astra-task/completed"},
        )

    def test_verified_terminal_retry_cannot_override_conflicting_terminal_state(self) -> None:
        _task, _receipt, api, body, gate = self._fixture()
        api.labels = {"astra-task/result-verified", "astra-task/failed"}
        with self.assertRaises(ReceiptGateError):
            gate.process(gates.receipt_event(body))
        self.assertEqual(
            api.labels,
            {"astra-task/result-verified", "astra-task/failed"},
        )

    def test_verified_terminal_retry_revalidates_receipt_evidence(self) -> None:
        task = gates.valid_task_mapping()
        receipt = gates.valid_receipt_mapping(task)
        receipt["evidence"]["changed_paths"] = ["example.txt", "EXAMPLE.TXT"]
        helper = gates.ReceiptGateTests()
        api, body = helper._api_for_receipt(task=task, receipt=receipt)
        api.labels = {"astra-task/result-verified", "astra-task/completed"}
        gate = helper._gate(api)
        with self.assertRaises(ReceiptGateError):
            gate.process(gates.receipt_event(body))
        self.assertEqual(
            api.labels,
            {"astra-task/result-verified", "astra-task/completed"},
        )

    def test_case_colliding_receipt_changed_paths_fail_closed(self) -> None:
        task = gates.valid_task_mapping()
        receipt = gates.valid_receipt_mapping(task)
        receipt["evidence"]["changed_paths"] = ["example.txt", "EXAMPLE.TXT"]
        helper = gates.ReceiptGateTests()
        api, body = helper._api_for_receipt(task=task, receipt=receipt)
        gate = helper._gate(api)
        with self.assertRaises(ReceiptGateError):
            gate.process(gates.receipt_event(body))
        self.assertEqual(api.labels, {"astra-task/claimed"})


if __name__ == "__main__":
    unittest.main()
