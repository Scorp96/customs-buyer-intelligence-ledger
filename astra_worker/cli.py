from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Sequence

from astra_supervisor.local_executor import LocalExecutor

from .compiler import TaskCompiler
from .config import ConfigError, WorkerConfig
from .git_workspace import GitWorkspaceError, GitWorkspaceManager
from .github_api import GitHubApiError, GitHubIssueClient
from .ledger import LedgerError, TaskLedger
from .queue import QueueError, TaskQueue
from .windows_security import (
    SecretBundle,
    WindowsSecurityError,
    default_worker_state_root,
    read_secret_bundle,
    require_elevated_administrator,
    resolve_service_sid,
    validate_worker_state_location,
    verify_worker_acl,
    write_secret_bundle,
)
from .worker import Worker, WorkerError


class WorkerCliError(RuntimeError):
    """Raised when trusted local worker startup cannot be assembled safely."""


_MAX_PROVISION_INPUT_BYTES = 16 * 1024


@dataclass(frozen=True)
class RuntimePaths:
    state_root: Path
    config: Path
    secrets: Path
    ledger: Path
    disabled: Path

    @classmethod
    def from_root(cls, state_root: Path) -> "RuntimePaths":
        root = Path(state_root)
        if not root.is_absolute():
            root = root.resolve()
        root = root.resolve(strict=False)
        return cls(
            state_root=root,
            config=root / "config.json",
            secrets=root / "secrets.bin",
            ledger=root / "ledger.sqlite",
            disabled=root / "DISABLED",
        )


@dataclass
class WorkerRuntime:
    worker: Worker
    ledger: TaskLedger

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> "WorkerRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def build_runtime(state_root: Path, service_sid: str) -> WorkerRuntime:
    """Build the unattended runtime only after local state/ACL trust is established.

    All mutable local runtime paths are derived from one installer-owned state root.
    Remote task data never reaches this function's path, SID, token, or executable choices.
    """

    paths = RuntimePaths.from_root(state_root)

    # Fail closed before reading config or decrypting secrets. The ACL verifier runs
    # in a separate sanitized Python process and checks the complete worker state tree.
    validate_worker_state_location(paths.state_root, service_sid)

    config = WorkerConfig.load(paths.config)
    secrets = read_secret_bundle(paths.secrets)

    api = GitHubIssueClient(config.queue_repository, secrets.github_token)
    queue = TaskQueue(api=api, task_key=secrets.task_hmac_key)
    ledger = TaskLedger(paths.ledger)
    try:
        worker = Worker(
            config=config,
            queue=queue,
            ledger=ledger,
            workspace_factory=lambda binding: GitWorkspaceManager(
                binding,
                secrets.github_token,
                "git",
            ),
            compiler=TaskCompiler(),
            executor=LocalExecutor(),
            disabled_marker=paths.disabled,
            receipt_key=secrets.receipt_hmac_key,
        )
    except BaseException:
        ledger.close()
        raise
    return WorkerRuntime(worker=worker, ledger=ledger)


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-root",
        required=True,
        type=Path,
        help="installer-owned ASTRAWorker state root",
    )
    parser.add_argument(
        "--service-sid",
        required=True,
        help="installed ASTRAWorker Windows service SID",
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astra-worker",
        description="Outbound-only ASTRA Phase 2A worker runtime",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the unattended polling loop")
    _add_runtime_arguments(run_parser)

    once_parser = subparsers.add_parser("once", help="run exactly one polling cycle")
    _add_runtime_arguments(once_parser)

    verify_parser = subparsers.add_parser(
        "verify-acl",
        help="read-only verifier for the installed worker state ACL",
    )
    verify_parser.add_argument("--path", required=True, type=Path)
    verify_parser.add_argument("--service-sid", required=True)

    subparsers.add_parser(
        "validate-install",
        help="validate the fixed ProgramData installation before service start",
    )

    provision_parser = subparsers.add_parser(
        "provision-secrets",
        help="trusted one-time DPAPI secret provisioning from standard input",
    )
    provision_parser.add_argument(
        "--stdin",
        action="store_true",
        required=True,
        help="read exactly one secret JSON object from standard input",
    )
    return parser


def _result_json(result: object) -> str:
    if not hasattr(result, "__dataclass_fields__"):
        raise WorkerCliError("worker cycle returned an unexpected result")
    return json.dumps(
        asdict(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _validate_install() -> None:
    root = default_worker_state_root()
    service_sid = resolve_service_sid()
    verify_worker_acl(root, service_sid)
    paths = RuntimePaths.from_root(root)

    required_directories = (
        root / "log",
        root / "repos",
        root / "worktrees",
        root / "empty-hooks",
    )
    for directory in required_directories:
        if not directory.is_dir():
            raise WorkerCliError(f"required worker directory is missing: {directory.name}")

    for required_file in (
        paths.config,
        paths.secrets,
        root / "ASTRAWorker.exe",
        root / "ASTRAWorker.xml",
    ):
        if not required_file.is_file():
            raise WorkerCliError(f"required worker file is missing: {required_file.name}")

    WorkerConfig.load(paths.config)
    read_secret_bundle(paths.secrets)


def _provision_secrets_from_stdin() -> None:
    require_elevated_administrator()
    root = default_worker_state_root()
    service_sid = resolve_service_sid()
    verify_worker_acl(root, service_sid)
    paths = RuntimePaths.from_root(root)

    raw = bytearray(sys.stdin.buffer.read(_MAX_PROVISION_INPUT_BYTES + 1))
    try:
        if not raw:
            raise WorkerCliError("secret provisioning input is empty")
        if len(raw) > _MAX_PROVISION_INPUT_BYTES:
            raise WorkerCliError("secret provisioning input exceeds the fixed limit")
        bundle = SecretBundle.from_clear_bytes(bytes(raw))
        write_secret_bundle(paths.secrets, bundle)
        # The newly-created file must inherit the same exact trusted ACL before success.
        verify_worker_acl(root, service_sid)
    finally:
        for index in range(len(raw)):
            raw[index] = 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "verify-acl":
            verify_worker_acl(args.path, args.service_sid)
            sys.stdout.write("ASTRA_ACL_OK\n")
            return 0
        if args.command == "validate-install":
            _validate_install()
            sys.stdout.write("ASTRA_INSTALL_OK\n")
            return 0
        if args.command == "provision-secrets":
            if not args.stdin:
                raise WorkerCliError("secret provisioning requires --stdin")
            _provision_secrets_from_stdin()
            return 0

        with build_runtime(args.state_root, args.service_sid) as runtime:
            if args.command == "once":
                result = runtime.worker.run_once()
                sys.stdout.write(_result_json(result) + "\n")
                return 0
            if args.command == "run":
                runtime.worker.run_forever()
                return 0
            raise WorkerCliError("unsupported runtime command")
    except (
        ConfigError,
        WindowsSecurityError,
        GitHubApiError,
        QueueError,
        LedgerError,
        GitWorkspaceError,
        WorkerError,
        WorkerCliError,
        OSError,
    ) as exc:
        # No secret input is echoed. Credential-bearing GitHub client errors are redacted.
        sys.stderr.write(f"ASTRA worker failed closed: {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
