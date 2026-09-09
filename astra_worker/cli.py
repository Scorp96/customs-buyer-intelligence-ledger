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
    WindowsSecurityError,
    read_secret_bundle,
    validate_worker_state_location,
)
from .worker import Worker, WorkerError


class WorkerCliError(RuntimeError):
    """Raised when trusted local worker startup cannot be assembled safely."""


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

    # Fail closed before reading config or decrypting secrets.  Task 12 supplies the
    # trusted installer-owned verify-acl CLI surface that this validator invokes.
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
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
        # Startup/runtime errors may contain local diagnostics, but credential-bearing
        # exception bodies are never emitted by the narrow GitHub client.
        sys.stderr.write(f"ASTRA worker failed closed: {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
