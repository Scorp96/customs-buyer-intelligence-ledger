from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "astra_stage2_windows.ps1"


class AstraWorkerStage2RunnerContractTests(unittest.TestCase):
    def _text(self) -> str:
        self.assertTrue(SCRIPT.is_file(), "Stage 2 Windows runner must exist")
        return SCRIPT.read_text(encoding="utf-8")

    def test_self_elevates_and_pins_exact_remote_head_before_secret_mutation(self) -> None:
        text = self._text()
        self.assertIn("-Verb RunAs", text)
        self.assertIn("git fetch origin $FeatureBranch", text)
        self.assertIn('git rev-parse "origin/$FeatureBranch"', text)
        self.assertIn("git checkout --detach $remoteHead", text)
        exact_index = text.index("ASTRA_EXACT_HEAD=")
        task_secret_index = text.index("ASTRA_TASK_HMAC_KEY_B64")
        self.assertLess(exact_index, task_secret_index)

    def test_generates_independent_random_hmac_keys_and_sends_actions_secrets_via_stdin(self) -> None:
        text = self._text()
        self.assertIn("RandomNumberGenerator", text)
        self.assertIn("ASTRA_TASK_HMAC_KEY_B64", text)
        self.assertIn("ASTRA_RECEIPT_HMAC_KEY_B64", text)
        self.assertIn("gh secret set", text)
        self.assertNotIn("--body", text)
        self.assertIn("StandardInput", text)
        self.assertNotIn("ASTRA_WORKER_GITHUB_TOKEN=", text)

    def test_worker_token_is_secure_prompted_and_dpapi_provisioning_uses_stdin_only(self) -> None:
        text = self._text()
        self.assertIn("Read-Host", text)
        self.assertIn("-AsSecureString", text)
        self.assertIn("provision-secrets", text)
        self.assertIn('"--stdin"', text)
        self.assertNotIn("github_token.json", text.lower())
        self.assertNotIn("secrets-clear", text.lower())

    def test_validates_then_starts_service_and_has_single_terminal_success_marker(self) -> None:
        text = self._text()
        validate_index = text.index("validate-install")
        start_index = text.index("ASTRAWorker.exe")
        success_index = text.index('Write-Host "ASTRA_STAGE2_OK"')
        self.assertLess(validate_index, start_index)
        self.assertLess(start_index, success_index)
        self.assertEqual(text.count('Write-Host "ASTRA_STAGE2_OK"'), 1)
        self.assertIn("Status -ne", text)
        self.assertIn("Running", text)

    @unittest.skipUnless(os.name == "nt", "PowerShell 5.1 parser validation is Windows-only")
    def test_parses_under_windows_powershell_51(self) -> None:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"$null = [scriptblock]::Create((Get-Content -LiteralPath '{SCRIPT}' -Raw)); 'ASTRA_STAGE2_PARSE_OK'",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ASTRA_STAGE2_PARSE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
