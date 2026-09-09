from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from astra_worker.config import ConfigError, RepositoryBinding, WorkerConfig
from astra_worker.windows_security import (
    SecretBundle,
    WindowsSecurityError,
    protect_machine_secret,
    read_secret_bundle,
    unprotect_machine_secret,
    validate_worker_state_location,
    write_secret_bundle,
)


def valid_config_mapping() -> dict:
    return {
        "schema_version": "astra.worker.config.v1",
        "worker_id": "scorp-windows-01",
        "queue_repository": "Scorp96/customs-buyer-intelligence-ledger",
        "repositories": {
            "cbi-primary": {
                "github_repository": "Scorp96/customs-buyer-intelligence-ledger",
                "expected_origin": "https://github.com/Scorp96/customs-buyer-intelligence-ledger",
                "mirror_root": "D:/ASTRAWorker/repos/cbi-primary.git",
                "allowed_base_refs_exact": ["cbi-v6-3-demand-expansion"],
                "allowed_base_ref_prefixes": ["astra-"],
                "ephemeral_branch_prefix": "astra-worker/",
            }
        },
        "poll_interval_seconds": 15,
        "max_task_age_seconds": 1800,
        "max_task_payload_bytes": 49152,
        "max_operations": 32,
        "max_changed_files": 20,
        "max_diff_bytes": 262144,
        "max_command_output_bytes": 262144,
    }


class RefPolicyTests(unittest.TestCase):
    def test_exact_and_prefix_rules_are_distinct(self) -> None:
        binding = RepositoryBinding.from_mapping(
            "cbi-primary",
            valid_config_mapping()["repositories"]["cbi-primary"],
        )
        self.assertTrue(binding.allows_base_ref("cbi-v6-3-demand-expansion"))
        self.assertFalse(binding.allows_base_ref("cbi-v6-3-demand-expansion-evil"))
        self.assertTrue(binding.allows_base_ref("astra-feature-x"))
        self.assertFalse(binding.allows_base_ref("main"))

    def test_duplicate_or_empty_ref_rules_fail_closed(self) -> None:
        payload = valid_config_mapping()["repositories"]["cbi-primary"].copy()
        payload["allowed_base_refs_exact"] = ["x", "x"]
        with self.assertRaises(ConfigError):
            RepositoryBinding.from_mapping("cbi-primary", payload)
        payload = valid_config_mapping()["repositories"]["cbi-primary"].copy()
        payload["allowed_base_ref_prefixes"] = [""]
        with self.assertRaises(ConfigError):
            RepositoryBinding.from_mapping("cbi-primary", payload)

    def test_origin_suffix_confusion_is_rejected(self) -> None:
        payload = valid_config_mapping()["repositories"]["cbi-primary"].copy()
        payload["expected_origin"] = (
            "https://github.com/attacker/Scorp96/customs-buyer-intelligence-ledger"
        )
        with self.assertRaises(ConfigError):
            RepositoryBinding.from_mapping("cbi-primary", payload)


class WorkerConfigTests(unittest.TestCase):
    def _load(self, payload: dict) -> WorkerConfig:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "worker.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return WorkerConfig.load(path)

    def _load_raw(self, raw: str) -> WorkerConfig:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "worker.json"
            path.write_text(raw, encoding="utf-8")
            return WorkerConfig.load(path)

    def test_valid_config_resolves_only_known_repository_id(self) -> None:
        config = self._load(valid_config_mapping())
        binding = config.repository("cbi-primary")
        self.assertEqual(binding.github_repository, config.queue_repository)
        with self.assertRaises(ConfigError):
            config.repository("unknown")

    def test_queue_repository_mismatch_is_rejected(self) -> None:
        payload = valid_config_mapping()
        payload["repositories"]["cbi-primary"]["github_repository"] = "Scorp96/other"
        with self.assertRaises(ConfigError):
            self._load(payload)

    def test_relative_mirror_path_is_rejected_cross_platform(self) -> None:
        payload = valid_config_mapping()
        payload["repositories"]["cbi-primary"]["mirror_root"] = "repos/cbi.git"
        with self.assertRaises(ConfigError):
            self._load(payload)

    def test_nonpositive_limits_and_unsafe_worker_branch_prefix_are_rejected(self) -> None:
        payload = valid_config_mapping()
        payload["poll_interval_seconds"] = 0
        with self.assertRaises(ConfigError):
            self._load(payload)

        payload = valid_config_mapping()
        payload["repositories"]["cbi-primary"]["ephemeral_branch_prefix"] = "main/"
        with self.assertRaises(ConfigError):
            self._load(payload)

    def test_unknown_top_level_config_field_is_rejected(self) -> None:
        payload = valid_config_mapping()
        payload["remote_repository_root"] = "C:/escape"
        with self.assertRaises(ConfigError):
            self._load(payload)

    def test_duplicate_json_config_key_is_rejected(self) -> None:
        raw = json.dumps(valid_config_mapping())
        raw = raw.replace(
            '"worker_id": "scorp-windows-01",',
            '"worker_id": "scorp-windows-01", "worker_id": "scorp-windows-01",',
            1,
        )
        with self.assertRaises(ConfigError):
            self._load_raw(raw)


class SecretBundleContractTests(unittest.TestCase):
    def test_task_and_receipt_hmac_keys_must_be_independent(self) -> None:
        with self.assertRaises(WindowsSecurityError):
            SecretBundle(
                task_hmac_key=b"x" * 32,
                receipt_hmac_key=b"x" * 32,
                github_token="github-token",
            )

    def test_plaintext_or_wrong_magic_secret_file_is_rejected_before_decrypt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "secrets.bin"
            path.write_text('{"github_token":"plain"}', encoding="utf-8")
            with self.assertRaises(WindowsSecurityError):
                read_secret_bundle(path)


@unittest.skipIf(os.name == "nt", "non-Windows fail-closed contract")
class NonWindowsSecretTests(unittest.TestCase):
    def test_dpapi_functions_fail_closed_off_windows(self) -> None:
        with self.assertRaises(WindowsSecurityError):
            protect_machine_secret(b"secret")
        with self.assertRaises(WindowsSecurityError):
            unprotect_machine_secret(b"ciphertext")

    def test_state_location_validation_fails_closed_off_windows(self) -> None:
        with self.assertRaises(WindowsSecurityError):
            validate_worker_state_location(Path("/tmp/ASTRAWorker"), "S-1-5-21-1")


@unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
class WindowsSecretTests(unittest.TestCase):
    def test_dpapi_machine_scope_round_trip(self) -> None:
        clear = b"task-key\0receipt-key\0github-token"
        protected = protect_machine_secret(clear)
        self.assertNotEqual(protected, clear)
        self.assertEqual(unprotect_machine_secret(protected), clear)

    def test_secret_bundle_file_is_dpapi_protected_and_round_trips(self) -> None:
        bundle = SecretBundle(
            task_hmac_key=b"t" * 32,
            receipt_hmac_key=b"r" * 32,
            github_token="github-token-secret",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "secrets.bin"
            write_secret_bundle(path, bundle)
            stored = path.read_bytes()
            self.assertNotIn(bundle.github_token.encode("utf-8"), stored)
            self.assertEqual(read_secret_bundle(path), bundle)

    def test_state_path_outside_programdata_worker_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(WindowsSecurityError):
                validate_worker_state_location(Path(temp_dir), "S-1-5-21-1")


if __name__ == "__main__":
    unittest.main()
