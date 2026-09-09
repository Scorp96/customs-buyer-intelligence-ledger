from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astra_worker.config import ConfigError, RepositoryBinding, WorkerConfig


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


class WorkerConfigTests(unittest.TestCase):
    def _load(self, payload: dict) -> WorkerConfig:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "worker.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
