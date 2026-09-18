from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from astra_worker.cli import RuntimePaths, build_runtime, make_parser
from astra_worker.config import WorkerConfig
from astra_worker.windows_security import SecretBundle


class WorkerCliTests(unittest.TestCase):
    def test_runtime_paths_are_fixed_below_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            paths = RuntimePaths.from_root(root)
            self.assertEqual(paths.state_root, root)
            self.assertEqual(paths.config, root / "config.json")
            self.assertEqual(paths.secrets, root / "secrets.bin")
            self.assertEqual(paths.ledger, root / "ledger.sqlite")
            self.assertEqual(paths.disabled, root / "DISABLED")

    def test_runtime_startup_validates_acl_before_reading_config_or_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            order: list[str] = []
            fake_config = Mock(spec=WorkerConfig)
            fake_config.queue_repository = "Scorp96/customs-buyer-intelligence-ledger"
            fake_config.repositories = {}
            fake_config.max_changed_files = 10
            fake_config.max_diff_bytes = 4096
            fake_config.max_command_output_bytes = 4096
            fake_config.max_operations = 8
            fake_config.max_task_age_seconds = 1800
            fake_config.worker_id = "scorp-windows-01"
            fake_config.poll_interval_seconds = 15
            bundle = SecretBundle(
                task_hmac_key=b"t" * 32,
                receipt_hmac_key=b"r" * 32,
                github_token="github-token",
            )

            def validate(path, sid):
                order.append("acl")
                self.assertEqual(Path(path), root)
                self.assertEqual(sid, "S-1-5-80-1234")

            def load_config(path):
                order.append("config")
                self.assertEqual(Path(path), root / "config.json")
                return fake_config

            def load_secrets(path):
                order.append("secrets")
                self.assertEqual(Path(path), root / "secrets.bin")
                return bundle

            fake_ledger = Mock()
            fake_worker = Mock()
            with (
                patch("astra_worker.cli.validate_worker_state_location", side_effect=validate),
                patch("astra_worker.cli.WorkerConfig.load", side_effect=load_config),
                patch("astra_worker.cli.read_secret_bundle", side_effect=load_secrets),
                patch("astra_worker.cli.GitHubIssueClient"),
                patch("astra_worker.cli.TaskQueue"),
                patch("astra_worker.cli.TaskLedger", return_value=fake_ledger) as ledger_type,
                patch("astra_worker.cli.Worker", return_value=fake_worker),
            ):
                runtime = build_runtime(root, "S-1-5-80-1234")

            self.assertEqual(order, ["acl", "config", "secrets"])
            ledger_type.assert_called_once_with(root / "ledger.sqlite")
            self.assertIs(runtime.worker, fake_worker)
            self.assertIs(runtime.ledger, fake_ledger)

    def test_parser_has_only_local_runtime_commands_and_no_remote_authority_flags(self) -> None:
        parser = make_parser()
        parsed = parser.parse_args(
            ["once", "--state-root", "C:/ProgramData/ASTRAWorker", "--service-sid", "S-1-5-80-1234"]
        )
        self.assertEqual(parsed.command, "once")
        help_text = parser.format_help().lower()
        for forbidden in (
            "repository-root",
            "remote-url",
            "refspec",
            "shell",
            "executable",
            "github-token",
            "task-hmac-key",
            "receipt-hmac-key",
        ):
            self.assertNotIn(forbidden, help_text)

    def test_repository_root_launcher_delegates_only_to_cli_main(self) -> None:
        launcher = Path("scripts/astra_worker.py")
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("REPOSITORY_ROOT", text)
        self.assertIn("from astra_worker.cli import main", text)
        self.assertIn("raise SystemExit(main())", text)
        for forbidden in ("subprocess", "powershell", "cmd.exe", "socket"):
            self.assertNotIn(forbidden, text.lower())


if __name__ == "__main__":
    unittest.main()
