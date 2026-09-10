from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
from typing import Any, Callable

from astra_supervisor.local_executor import LocalExecutor

from .compiler import TaskCompiler, intended_final_hashes, verify_pre_state
from .config import RepositoryBinding, WorkerConfig
from .evidence import (
    EvidenceLimits,
    build_signed_receipt,
    build_text_patch,
    chunk_patch,
    verify_final_state,
)
from .git_workspace import WorktreeHandle
from .github_api import GitHubApiError
from .models import TaskEnvelope
from .protocol import encode_signed_envelope, hmac_sha256_hex
from .queue import QueueError, ReadyTask


class WorkerError(RuntimeError):
    """Raised when a worker cycle cannot safely continue."""


class WorkerTransportError(WorkerError):
    """Transient outbound transport failure eligible for bounded retry."""


@dataclass(frozen=True)
class WorkerCycleResult:
    status: str
    task_id: str | None = None
    issue_number: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    task_id: str
    status: str
    cleanup_success: bool | None
    detail: str | None = None


def _utc_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise WorkerError("task timestamp is not RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise WorkerError("task timestamp is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise WorkerError("task timestamp is not UTC")
    return parsed


def _quarantine_digest(task_id: str, reason: str) -> str:
    return hashlib.sha256(
        f"astra-worker-quarantine-v1\n{task_id}\n{reason}\n".encode("utf-8")
    ).hexdigest()


class Worker:
    """Single-task outbound worker orchestrator with durable fail-closed replay handling."""

    def __init__(
        self,
        *,
        config: WorkerConfig,
        queue: Any,
        ledger: Any,
        workspace_factory: Callable[[RepositoryBinding], Any],
        compiler: TaskCompiler | Any,
        executor: LocalExecutor | Any,
        disabled_marker: Path,
        receipt_key: bytes,
        now: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if not isinstance(config, WorkerConfig):
            raise WorkerError("validated WorkerConfig is required")
        if not callable(workspace_factory):
            raise WorkerError("workspace_factory must be callable")
        marker = Path(disabled_marker)
        if not marker.is_absolute():
            marker = marker.resolve()
        if not isinstance(receipt_key, bytes) or len(receipt_key) < 32:
            raise WorkerError("receipt HMAC key must contain at least 32 bytes")
        self.config = config
        self.queue = queue
        self.ledger = ledger
        self.workspace_factory = workspace_factory
        self.compiler = compiler
        self.executor = executor
        self.disabled_marker = marker
        self.receipt_key = receipt_key
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleeper or time.sleep
        self.evidence_limits = EvidenceLimits(
            max_changed_files=config.max_changed_files,
            max_diff_bytes=config.max_diff_bytes,
            max_command_output_bytes=config.max_command_output_bytes,
        )

    def _disabled(self) -> bool:
        try:
            return self.disabled_marker.exists()
        except OSError as exc:
            raise WorkerError("kill-switch state could not be read") from exc

    def _validate_ready_task(self, item: ReadyTask) -> RepositoryBinding:
        if not isinstance(item, ReadyTask):
            raise WorkerError("queue returned an invalid ready task")
        task = item.task
        if task.worker_id != self.config.worker_id:
            raise WorkerError("task worker_id does not match this worker")
        try:
            binding = self.config.repository(task.repository_id)
        except Exception as exc:
            raise WorkerError("task repository_id is not locally trusted") from exc
        if not binding.allows_base_ref(task.base_ref):
            raise WorkerError("task base_ref is outside local trusted policy")
        if len(task.operations) > self.config.max_operations:
            raise WorkerError("task exceeds local operation limit")

        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise WorkerError("worker clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        issued = _utc_timestamp(task.issued_at)
        expires = _utc_timestamp(task.expires_at)
        if now < issued:
            raise WorkerError("task issued_at is in the future")
        if now >= expires:
            raise WorkerError("task is expired")
        if (now - issued).total_seconds() > self.config.max_task_age_seconds:
            raise WorkerError("task age exceeds local maximum")
        return binding

    def _sign_receipt(self, receipt: Any) -> tuple[str, str]:
        payload = asdict(receipt)
        signature = hmac_sha256_hex(self.receipt_key, payload)
        body = encode_signed_envelope("receipt", payload, signature)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return body, digest

    def _mark_local_quarantine(self, task_id: str, reason: str) -> None:
        try:
            self.ledger.mark_terminal(
                task_id,
                _quarantine_digest(task_id, reason),
                terminal_state="QUARANTINED",
            )
        except Exception:
            # The earlier durable state remains fail-closed even if a secondary
            # quarantine annotation cannot be committed.
            pass

    def reconcile_in_progress(self) -> list[ReconciliationResult]:
        try:
            records = self.ledger.list_in_progress()
        except Exception as exc:
            raise WorkerError("in-progress ledger state could not be read") from exc
        if not isinstance(records, list):
            raise WorkerError("in-progress ledger state has an unexpected shape")

        results: list[ReconciliationResult] = []
        for record in records:
            task_id = getattr(record, "task_id", None)
            if not isinstance(task_id, str) or not task_id:
                raise WorkerError("in-progress ledger row has no task identity")
            cleanup_success: bool | None = None
            detail = "ambiguous prior execution was not re-run"

            state = getattr(record, "state", None)
            if state == "EXECUTING":
                repository_id = getattr(record, "repository_id", None)
                worktree = getattr(record, "worktree", None)
                branch = getattr(record, "generated_branch", None)
                base_sha = getattr(record, "base_commit_sha", None)
                if all(isinstance(value, str) and value for value in (repository_id, worktree, branch, base_sha)):
                    try:
                        binding = self.config.repository(repository_id)
                        workspace = self.workspace_factory(binding)
                        handle = WorktreeHandle(
                            task_id=task_id,
                            path=Path(worktree),
                            branch=branch,
                            base_commit_sha=base_sha,
                            mirror_identity=getattr(record, "mirror_identity", None)
                            or f"{repository_id}@{base_sha}",
                        )
                        cleanup = workspace.cleanup(handle)
                        cleanup_success = bool(cleanup.success)
                        self.ledger.mark_cleanup(
                            task_id,
                            "RECONCILED" if cleanup_success else "RECONCILIATION_CLEANUP_FAILED",
                        )
                        if not cleanup_success:
                            detail = "ambiguous prior execution quarantined; cleanup could not be proven"
                    except Exception:
                        cleanup_success = False
                        detail = "ambiguous prior execution quarantined; cleanup reconciliation failed"
                else:
                    cleanup_success = False
                    detail = "ambiguous prior execution quarantined; workspace identity is incomplete"

            self._mark_local_quarantine(task_id, detail)
            results.append(
                ReconciliationResult(
                    task_id=task_id,
                    status="QUARANTINED",
                    cleanup_success=cleanup_success,
                    detail=detail,
                )
            )
        return results

    def _execute_ready(self, item: ReadyTask, binding: RepositoryBinding) -> WorkerCycleResult:
        task = item.task
        try:
            replay = self.ledger.find_replay(task.task_id, task.nonce, item.task_digest)
        except Exception as exc:
            return WorkerCycleResult(
                status="REJECTED",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail=f"replay state rejected task: {type(exc).__name__}",
            )
        if replay is not None:
            return WorkerCycleResult(
                status="REPLAY_BLOCKED",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail="task already has durable local history",
            )

        try:
            self.ledger.claim(
                task.task_id,
                task.nonce,
                item.task_digest,
                task.repository_id,
                task.base_ref,
                task.base_commit_sha,
            )
        except Exception as exc:
            return WorkerCycleResult(
                status="REJECTED",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail=f"durable claim failed: {type(exc).__name__}",
            )

        try:
            self.queue.claim(item)
        except Exception as exc:
            reason = f"remote claim failed after durable local claim: {type(exc).__name__}"
            self._mark_local_quarantine(task.task_id, reason)
            return WorkerCycleResult(
                status="QUARANTINED",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail=reason,
            )

        workspace = None
        handle: WorktreeHandle | None = None
        try:
            workspace = self.workspace_factory(binding)
            workspace.sync_exact(task.base_ref, task.base_commit_sha)
            handle = workspace.create_task_worktree(task.task_id, task.base_commit_sha)
            self.ledger.mark_executing(
                task.task_id,
                mirror_identity=handle.mirror_identity,
                worktree=str(handle.path),
                generated_branch=handle.branch,
            )
            verify_pre_state(task, handle.path)
            manifest = self.compiler.compile(task, handle.path, handle.branch)
            execution = self.executor.execute(manifest, apply=True)
            intended = intended_final_hashes(task)
            change_evidence = verify_final_state(
                task,
                handle.path,
                intended,
                self.evidence_limits,
            )
            patch_bytes = build_text_patch(task, handle.path, change_evidence)
            chunks = chunk_patch(patch_bytes)
        except Exception as exc:
            cleanup_success: bool | None = None
            if workspace is not None and handle is not None:
                try:
                    cleanup = workspace.cleanup(handle)
                    cleanup_success = bool(cleanup.success)
                    self.ledger.mark_cleanup(
                        task.task_id,
                        "CLEAN" if cleanup_success else "FAILED",
                    )
                except Exception:
                    cleanup_success = False
            reason = f"execution evidence could not reach a safe terminal state: {type(exc).__name__}"
            if cleanup_success is False:
                reason += "; cleanup unproven"
            self._mark_local_quarantine(task.task_id, reason)
            return WorkerCycleResult(
                status="QUARANTINED",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail=reason,
            )

        assert workspace is not None and handle is not None
        try:
            cleanup = workspace.cleanup(handle)
            cleanup_success = bool(cleanup.success)
            self.ledger.mark_cleanup(
                task.task_id,
                "CLEAN" if cleanup_success else "FAILED",
            )
        except Exception:
            cleanup_success = False

        if not cleanup_success:
            receipt_status = "QUARANTINED"
            terminal_state = "QUARANTINED"
            cycle_status = "QUARANTINED"
        elif execution.success:
            receipt_status = "APPLY_READY"
            terminal_state = "TERMINAL"
            cycle_status = "COMPLETED"
        else:
            receipt_status = "NOT_APPLY_READY"
            terminal_state = "TERMINAL"
            cycle_status = "NOT_APPLY_READY"

        try:
            receipt = build_signed_receipt(
                task,
                status=receipt_status,
                change_evidence=change_evidence,
                patch_chunks=chunks,
                cleanup_success=cleanup_success,
                execution_result=execution,
                max_command_output_bytes=self.config.max_command_output_bytes,
            )
            signed_receipt, receipt_digest = self._sign_receipt(receipt)
            self.ledger.mark_terminal(
                task.task_id,
                receipt_digest,
                terminal_state=terminal_state,
            )
        except Exception as exc:
            reason = f"terminal receipt could not be durably committed: {type(exc).__name__}"
            self._mark_local_quarantine(task.task_id, reason)
            return WorkerCycleResult(
                status="QUARANTINED",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail=reason,
            )

        try:
            self.queue.post_patch_chunks(item.issue_number, task.task_id, chunks)
            self.queue.post_receipt(item.issue_number, signed_receipt)
        except Exception as exc:
            # Local terminal state remains authoritative for at-most-once execution.
            # A later reconciliation may inspect transport state, but must never rerun.
            return WorkerCycleResult(
                status="RESULT_POST_UNCERTAIN",
                task_id=task.task_id,
                issue_number=item.issue_number,
                detail=f"terminal result is locally durable but remote posting is uncertain: {type(exc).__name__}",
            )

        return WorkerCycleResult(
            status=cycle_status,
            task_id=task.task_id,
            issue_number=item.issue_number,
        )

    def run_once(self) -> WorkerCycleResult:
        if self._disabled():
            return WorkerCycleResult(status="DISABLED")

        with self.ledger.acquire_worker_lease(self.config.worker_id):
            reconciled = self.reconcile_in_progress()
            if reconciled:
                return WorkerCycleResult(
                    status="RECONCILED",
                    task_id=reconciled[0].task_id,
                    detail=f"reconciled {len(reconciled)} ambiguous task(s); no new task claimed",
                )

            try:
                candidates = self.queue.find_ready(self.config.worker_id)
            except QueueError as exc:
                if isinstance(exc.__cause__, GitHubApiError):
                    raise WorkerTransportError("ready-task transport failed") from exc
                raise WorkerError("ready-task queue state failed closed") from exc
            except GitHubApiError as exc:
                raise WorkerTransportError("ready-task transport failed") from exc
            except (OSError, TimeoutError) as exc:
                raise WorkerTransportError("ready-task transport failed") from exc
            except Exception as exc:
                raise WorkerError("ready-task discovery failed") from exc
            if not candidates:
                return WorkerCycleResult(status="IDLE")

            first_rejection: WorkerCycleResult | None = None
            for item in candidates:
                try:
                    binding = self._validate_ready_task(item)
                except WorkerError as exc:
                    if first_rejection is None:
                        first_rejection = WorkerCycleResult(
                            status="REJECTED",
                            task_id=getattr(getattr(item, "task", None), "task_id", None),
                            issue_number=getattr(item, "issue_number", None),
                            detail=str(exc),
                        )
                    continue
                return self._execute_ready(item, binding)

            assert first_rejection is not None
            return first_rejection

    def run_forever(self) -> None:
        transport_delays = (15.0, 30.0, 60.0, 120.0, 300.0)
        transport_index = 0
        while True:
            try:
                result = self.run_once()
            except WorkerTransportError:
                self._sleep(transport_delays[transport_index])
                transport_index = min(transport_index + 1, len(transport_delays) - 1)
                continue

            transport_index = 0
            if result.status == "DISABLED":
                return
            self._sleep(float(self.config.poll_interval_seconds))
