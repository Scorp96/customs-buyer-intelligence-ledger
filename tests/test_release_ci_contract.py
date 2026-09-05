from __future__ import annotations

import re
import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/cbi-release-ci.yml")


class ReleaseCiContractTests(unittest.TestCase):
    def _text(self) -> str:
        self.assertTrue(WORKFLOW.is_file(), f"missing release CI workflow: {WORKFLOW}")
        return WORKFLOW.read_text(encoding="utf-8")

    def test_release_candidate_trigger_and_manual_dispatch(self) -> None:
        text = self._text()
        self.assertIn("cbi-v*-release-candidate-*", text)
        self.assertIn("workflow_dispatch:", text)

        match = re.search(
            r"(?ms)^\s*push:\s*\n\s*branches:\s*\n(?P<branches>(?:\s+-\s+[^\n]+\n)+)",
            text,
        )
        self.assertIsNotNone(match, "release workflow must declare a push branch list")
        branches = match.group("branches")
        self.assertNotIn("main", branches)
        self.assertNotIn("cbi-v6-cloud-runtime-20260901", branches)

    def test_required_matrix_and_status_check_name_are_stable(self) -> None:
        text = self._text()
        for fragment in (
            "ubuntu-latest",
            "windows-latest",
            '"3.10"',
            '"3.11"',
            "fail-fast: false",
            "regression (${{ matrix.os }}, py${{ matrix.python-version }})",
        ):
            self.assertIn(fragment, text)

    def test_full_test_discovery_contract_is_preserved(self) -> None:
        text = self._text()
        self.assertIn(
            'python -m unittest discover -s tests -p "test_*.py" -v',
            text,
        )

    def test_release_workflow_is_read_only(self) -> None:
        text = self._text()
        self.assertRegex(text, r"(?ms)^permissions:\s*\n\s+contents:\s*read\s*$")


if __name__ == "__main__":
    unittest.main()
