from __future__ import annotations

import unittest

from astra_worker.gate_activation import (
    ActivationError,
    render_receipt_gate_workflow,
    render_task_gate_workflow,
)


class GateActivationTests(unittest.TestCase):
    def test_only_exact_40_hex_sha_is_accepted(self) -> None:
        for invalid in (
            "astra-phase2-current",
            "a" * 39,
            "g" * 40,
            "a" * 41,
            "refs/heads/main",
        ):
            with self.assertRaises(ActivationError):
                render_task_gate_workflow(invalid)
        text = render_task_gate_workflow("a" * 40)
        self.assertIn("ref: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", text)

    def test_task_and_receipt_triggers_are_default_branch_event_types(self) -> None:
        task = render_task_gate_workflow("b" * 40)
        receipt = render_receipt_gate_workflow("b" * 40)
        self.assertIn("issues:", task)
        self.assertNotIn("issue_comment:", task)
        self.assertIn("issue_comment:", receipt)
        self.assertNotIn("\n  issues:\n", receipt)

    def test_shims_have_minimal_permissions_and_literal_checkout_ref(self) -> None:
        for text in (
            render_task_gate_workflow("c" * 40),
            render_receipt_gate_workflow("c" * 40),
        ):
            self.assertIn("contents: read", text)
            self.assertIn("issues: write", text)
            for forbidden in (
                "contents: write",
                "pull-requests: write",
                "actions: write",
                "administration: write",
            ):
                self.assertNotIn(forbidden, text)
            ref_line = next(line for line in text.splitlines() if line.strip().startswith("ref:"))
            self.assertEqual(ref_line.strip(), "ref: cccccccccccccccccccccccccccccccccccccccc")
            self.assertNotIn("github.event", ref_line)

    def test_shims_run_only_reviewed_phase2_gate_entrypoints(self) -> None:
        task = render_task_gate_workflow("d" * 40)
        receipt = render_receipt_gate_workflow("d" * 40)
        self.assertIn('python scripts/astra_task_gate.py --event "$GITHUB_EVENT_PATH"', task)
        self.assertIn('python scripts/astra_receipt_gate.py --event "$GITHUB_EVENT_PATH"', receipt)
        self.assertNotIn("curl ", task.lower())
        self.assertNotIn("curl ", receipt.lower())


if __name__ == "__main__":
    unittest.main()
