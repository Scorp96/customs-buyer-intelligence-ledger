from __future__ import annotations

import re
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
            "a" * 41,
            "g" * 40,
            "refs/heads/main",
            "${{ github.sha }}",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ActivationError):
                    render_task_gate_workflow(invalid)

        text = render_task_gate_workflow("a" * 40)
        self.assertIn("ref: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", text)

    def test_task_and_receipt_triggers_are_default_branch_event_types(self) -> None:
        self.assertIn("issues:", render_task_gate_workflow("b" * 40))
        self.assertIn("issue_comment:", render_receipt_gate_workflow("b" * 40))

    def test_both_workflows_pin_checkout_to_literal_sha(self) -> None:
        sha = "c" * 40
        for text in (
            render_task_gate_workflow(sha),
            render_receipt_gate_workflow(sha),
        ):
            self.assertIn(f"ref: {sha}", text)
            ref_line = next(line for line in text.splitlines() if "ref:" in line)
            self.assertRegex(ref_line, rf"^\s*ref:\s*{sha}\s*$")
            self.assertNotIn("github.event", ref_line)
            self.assertNotIn("github.ref", ref_line)
            self.assertNotIn("github.sha", ref_line)

    def test_permissions_are_least_privilege(self) -> None:
        for text in (
            render_task_gate_workflow("d" * 40),
            render_receipt_gate_workflow("d" * 40),
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

    def test_task_workflow_runs_only_trusted_gate_script_and_fixed_secret_names(self) -> None:
        text = render_task_gate_workflow("e" * 40)
        self.assertIn('python scripts/astra_task_gate.py --event "$GITHUB_EVENT_PATH"', text)
        self.assertIn("ASTRA_TASK_HMAC_KEY_B64: ${{ secrets.ASTRA_TASK_HMAC_KEY_B64 }}", text)
        self.assertNotIn("ASTRA_RECEIPT_HMAC_KEY_B64", text)

    def test_receipt_workflow_runs_only_trusted_gate_script_and_fixed_secret_names(self) -> None:
        text = render_receipt_gate_workflow("f" * 40)
        self.assertIn('python scripts/astra_receipt_gate.py --event "$GITHUB_EVENT_PATH"', text)
        self.assertIn("ASTRA_TASK_HMAC_KEY_B64: ${{ secrets.ASTRA_TASK_HMAC_KEY_B64 }}", text)
        self.assertIn("ASTRA_RECEIPT_HMAC_KEY_B64: ${{ secrets.ASTRA_RECEIPT_HMAC_KEY_B64 }}", text)

    def test_checkout_action_and_python_setup_are_immutable_or_fixed(self) -> None:
        sha = "1" * 40
        for text in (
            render_task_gate_workflow(sha),
            render_receipt_gate_workflow(sha),
        ):
            self.assertRegex(text, r"actions/checkout@[0-9a-f]{40}")
            self.assertRegex(text, r"actions/setup-python@[0-9a-f]{40}")
            self.assertIn("persist-credentials: false", text)
            self.assertIn("python-version: '3.11'", text)

    def test_output_has_exactly_one_literal_checkout_ref(self) -> None:
        sha = "2" * 40
        for text in (
            render_task_gate_workflow(sha),
            render_receipt_gate_workflow(sha),
        ):
            refs = re.findall(r"(?m)^\s*ref:\s*(\S+)\s*$", text)
            self.assertEqual(refs, [sha])


if __name__ == "__main__":
    unittest.main()
