from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


RUNNER = Path("scripts/astra_stage1_windows.ps1")


def read_runner() -> str:
    if not RUNNER.is_file():
        raise AssertionError(f"required Stage 1 runner is missing: {RUNNER}")
    return RUNNER.read_text(encoding="utf-8")


class Stage1RunnerContractTests(unittest.TestCase):
    def test_runner_self_elevates_and_waits_for_single_controlled_process(self) -> None:
        text = read_runner()
        lowered = text.lower()
        self.assertIn("windowsprincipal", lowered)
        self.assertIn("administrator", lowered)
        self.assertIn("start-process", lowered)
        self.assertIn("-verb runas", lowered)
        self.assertIn("-wait", lowered)
        self.assertIn("-passthru", lowered)
        self.assertIn("$pscommandpath", lowered)
        self.assertIn("-elevated", lowered)

    def test_runner_enforces_real_gates_and_never_emits_unconditional_ok_markers(self) -> None:
        text = read_runner()
        lowered = text.lower()
        self.assertIn("install_astra_worker.ps1", lowered)
        self.assertIn("astra_acl_hardened", lowered)
        self.assertIn("protected secrets are not present", lowered)
        self.assertIn("verify-acl", lowered)
        self.assertIn("astra_acl_ok", lowered)
        self.assertIn("secrets.bin", lowered)
        self.assertIn("get-service astraworker", lowered)
        self.assertIn("throw", lowered)
        self.assertNotIn('write-host "[ok] two_stage_acl_hardening"', lowered)
        self.assertNotIn('write-host "[ok] installer_reached_secret_gate"', lowered)
        self.assertNotIn('write-host "[ok] independent_acl_verified"', lowered)

    def test_runner_requires_exact_remote_feature_head_before_install(self) -> None:
        text = read_runner().lower()
        self.assertIn("astra-phase2-pull-worker-design-20260909", text)
        self.assertIn("git fetch", text)
        self.assertIn("git rev-parse head", text)
        self.assertIn("git rev-parse origin/", text)
        self.assertIn("git checkout --detach", text)
        self.assertLess(text.find("git checkout --detach"), text.find("install_astra_worker.ps1"))

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser")
    def test_runner_has_valid_windows_powershell_51_syntax(self) -> None:
        runner = str(RUNNER.resolve()).replace("'", "''")
        command = (
            "$errors=$null;$tokens=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{runner}',[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count -ne 0){$errors|ForEach-Object{$_.ToString()};exit 2}"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
