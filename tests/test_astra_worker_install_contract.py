from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import unittest

from astra_worker.cli import make_parser


INSTALLER = Path("scripts/install_astra_worker.ps1")
SERVICE_XML = Path("deploy/astra-worker/ASTRAWorker.xml.template")
PINNED_WINSW_SHA256 = "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"


def read_required(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"required installation artifact is missing: {path}")
    return path.read_text(encoding="utf-8")


def subcommands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


class InstallContractTests(unittest.TestCase):
    def test_winsw_url_and_hash_are_pinned(self) -> None:
        text = read_required(INSTALLER)
        self.assertIn("v2.12.0/WinSW-x64.exe", text)
        self.assertIn(PINNED_WINSW_SHA256, text.lower())
        self.assertNotIn("/latest/", text.lower())
        self.assertIn("Get-FileHash", text)
        self.assertIn("-Algorithm SHA256", text)
        self.assertIn("Remove-Item", text)

    def test_service_is_reconfigured_to_virtual_non_admin_identity_before_start(self) -> None:
        text = read_required(INSTALLER)
        lowered = text.lower()
        showsid_at = lowered.find("sc.exe showsid")
        xml_write_at = lowered.find("writealltext")
        install_at = lowered.find(" install")
        sidtype_at = lowered.find("sidtype")
        service_account_at = lowered.find('nt service\\astraworker')
        config_at = lowered.find("sc.exe config")
        validate_at = lowered.find("validate-install")
        start_at = lowered.find(" start")
        self.assertTrue(
            -1 not in {
                showsid_at,
                xml_write_at,
                install_at,
                sidtype_at,
                service_account_at,
                config_at,
                validate_at,
                start_at,
            },
            "installer must contain SID/render/install/sidtype/account/config/validate/start gates",
        )
        self.assertLess(showsid_at, xml_write_at)
        self.assertLess(xml_write_at, install_at)
        self.assertLess(install_at, sidtype_at)
        self.assertLess(sidtype_at, config_at)
        self.assertLess(service_account_at, start_at)
        self.assertLess(config_at, validate_at)
        self.assertLess(validate_at, start_at)
        self.assertNotRegex(lowered, r"obj=\s*[\"']?(localsystem|system)\b")
        # Windows virtual service accounts are passwordless and ChangeServiceConfig
        # requires a NULL password pointer for them. Passing `password= ""` through
        # sc.exe produces ERROR_INVALID_COMMAND_LINE (1639) on real Windows hosts.
        self.assertNotIn("password=", lowered)

    def test_installer_normalizes_config_to_utf8_without_bom(self) -> None:
        text = read_required(INSTALLER)
        lowered = text.lower()
        self.assertIn("$configtext", lowered)
        self.assertIn("writealltext($configtarget", lowered)
        self.assertIn("utf8encoding($false)", lowered)
        self.assertNotIn("copy-item -literalpath $resolvedconfig -destination $configtarget", lowered)

    def test_state_acl_is_non_inheriting_and_grants_only_trusted_identities(self) -> None:
        text = read_required(INSTALLER)
        lowered = text.lower()
        self.assertIn("icacls", lowered)
        self.assertIn("/inheritance:r", lowered)
        self.assertIn("nt service\\astraworker", lowered)
        self.assertRegex(text, r"(?i)S-1-5-18")
        self.assertRegex(text, r"(?i)S-1-5-32-544")
        self.assertNotRegex(lowered, r"\beveryone\b|authenticated users|builtin\\users")

    def test_runtime_xml_contains_no_secret_value_token_or_password(self) -> None:
        text = read_required(SERVICE_XML)
        lowered = text.lower()
        self.assertIn("astra-worker", lowered)
        self.assertIn(" run ", f" {lowered} ")
        for forbidden in (
            "github_token",
            "github-token",
            "task_hmac",
            "receipt_hmac",
            "authorization:",
            "password",
            "gh_token",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_installer_starts_only_after_configuration_validation(self) -> None:
        text = read_required(INSTALLER).lower()
        self.assertIn("config.json", text)
        self.assertIn("provision-secrets", text)
        self.assertLess(text.find("validate-install"), text.find(" start"))

    def test_cli_exposes_read_only_acl_and_install_validation_plus_admin_provisioning(self) -> None:
        choices = subcommands(make_parser())
        self.assertTrue({"run", "once", "verify-acl", "validate-install", "provision-secrets"} <= choices)

    def test_secret_values_have_no_command_line_flags(self) -> None:
        source = Path("astra_worker/cli.py").read_text(encoding="utf-8").lower()
        self.assertIn("--stdin", source)
        for forbidden in (
            "--github-token",
            "--task-hmac-key",
            "--receipt-hmac-key",
            "--task-key",
            "--receipt-key",
        ):
            self.assertNotIn(forbidden, source)

    def test_service_template_has_no_auto_update_surface(self) -> None:
        text = read_required(SERVICE_XML).lower()
        self.assertNotIn("download", text)
        self.assertNotIn("update", text)
        self.assertNotIn("latest", text)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser")
    def test_installer_has_valid_powershell_syntax(self) -> None:
        installer = str(INSTALLER.resolve()).replace("'", "''")
        command = (
            "$errors=$null;$tokens=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{installer}',[ref]$tokens,[ref]$errors)|Out-Null;"
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
