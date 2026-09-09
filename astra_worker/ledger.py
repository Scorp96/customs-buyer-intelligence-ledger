from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from typing import BinaryIO


class LedgerError(RuntimeError):
    """Base class for replay/crash-ledger failures."""


class ReplayError(LedgerError):
    """The task ID or nonce has already been claimed."""


class ReplayConflictError(ReplayError):
    """A previously claimed task ID is presented with different signed bytes."""


class LedgerStateError(LedgerError):
    """A requested ledger state transition is illegal."""


class LeaseError(LedgerError):
    """Another worker process currently holds the single-worker lease."""


_ALLOWED_STATES = frozenset({"CLAIMED", "EXECUTING", "TERMINAL", "QUARANTINED"})
_TERMINAL_STATES = frozenset({"TERMINAL", "QUARANTINED"})
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise LedgerError(f"{name} must be a non-empty string")
    return value


def _require_sha(value: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise LedgerError("base_commit_sha must be a 40-hex Git object ID")
    return value.lower()


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    nonce: str
    digest: str
    repository_id: str
    base_ref: str
    base_commit_sha: str
    state: str
    receipt_digest: str | None
    mirror_identity: str | None
    worktree: str | None
    generated_branch: str | None
    cleanup_state: str | None
    claimed_at: str
    updated_at: str
    terminal_at: str | None


class WorkerLease:
    """Process-held advisory lease. The OS lock is authoritative; the DB row is audit state."""

    def __init__(
        self,
        ledger: "TaskLedger",
        worker_id: str,
        token: str,
        handle: BinaryIO,
    ) -> None:
        self._ledger = ledger
        self.worker_id = worker_id
        self._token = token
        self._handle = handle
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        try:
            self._ledger._release_worker_lease(self._token)
        finally:
            _unlock_file(self._handle)
            self._handle.close()
            self._released = True

    def __enter__(self) -> "WorkerLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()



def _lock_file(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise LeaseError("worker lease is already held") from exc
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise LeaseError("worker lease is already held") from exc



def _unlock_file(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Releasing/closing the file descriptor is still attempted by the caller.
        pass


class TaskLedger:
    """Durable at-most-once task ledger plus a crash-safe single-worker lease."""

    def __init__(self, path: str | Path) -> None:
        raw_path = Path(path)
        if not raw_path.is_absolute():
            raw_path = raw_path.resolve()
        self.path = raw_path.resolve(strict=False)
        if not self.path.parent.exists() or not self.path.parent.is_dir():
            raise LedgerError("ledger parent directory must already exist")
        self._lease_path = self.path.with_name(self.path.name + ".lease")
        self._mutex = threading.RLock()
        try:
            self._conn = sqlite3.connect(
                str(self.path),
                timeout=0.25,
                isolation_level=None,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._configure_connection()
            self._initialize_schema()
        except sqlite3.Error as exc:
            raise LedgerError("failed to initialize task ledger") from exc

    def close(self) -> None:
        with self._mutex:
            self._conn.close()

    def __enter__(self) -> "TaskLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _configure_connection(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=250")

    def _initialize_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                nonce TEXT NOT NULL UNIQUE,
                digest TEXT NOT NULL,
                repository_id TEXT NOT NULL,
                base_ref TEXT NOT NULL,
                base_commit_sha TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('CLAIMED','EXECUTING','TERMINAL','QUARANTINED')),
                receipt_digest TEXT,
                mirror_identity TEXT,
                worktree TEXT,
                generated_branch TEXT,
                cleanup_state TEXT,
                claimed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                terminal_at TEXT
            );

            CREATE TABLE IF NOT EXISTS worker_lease (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                worker_id TEXT NOT NULL,
                lease_token TEXT NOT NULL,
                acquired_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
            """
        )

    def _begin_immediate(self) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise LedgerError("failed to begin durable ledger transaction") from exc

    def _commit(self) -> None:
        try:
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise LedgerError("failed to commit durable ledger transaction") from exc

    def _rollback(self) -> None:
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        state = row["state"]
        if state not in _ALLOWED_STATES:
            raise LedgerStateError("ledger contains an unknown task state")
        return TaskRecord(
            task_id=row["task_id"],
            nonce=row["nonce"],
            digest=row["digest"],
            repository_id=row["repository_id"],
            base_ref=row["base_ref"],
            base_commit_sha=row["base_commit_sha"],
            state=state,
            receipt_digest=row["receipt_digest"],
            mirror_identity=row["mirror_identity"],
            worktree=row["worktree"],
            generated_branch=row["generated_branch"],
            cleanup_state=row["cleanup_state"],
            claimed_at=row["claimed_at"],
            updated_at=row["updated_at"],
            terminal_at=row["terminal_at"],
        )

    def _get_task(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()

    def claim(
        self,
        task_id: str,
        nonce: str,
        digest: str,
        repository_id: str,
        base_ref: str,
        base_commit_sha: str,
    ) -> TaskRecord:
        task_id = _require_text("task_id", task_id)
        nonce = _require_text("nonce", nonce)
        digest = _require_text("digest", digest)
        repository_id = _require_text("repository_id", repository_id)
        base_ref = _require_text("base_ref", base_ref)
        base_commit_sha = _require_sha(base_commit_sha)
        now = _utc_now()

        with self._mutex:
            self._begin_immediate()
            try:
                existing_task = self._get_task(task_id)
                if existing_task is not None:
                    if existing_task["digest"] != digest:
                        raise ReplayConflictError("task ID was already bound to a different digest")
                    raise ReplayError("task ID was already claimed")

                existing_nonce = self._conn.execute(
                    "SELECT task_id, digest FROM tasks WHERE nonce = ?",
                    (nonce,),
                ).fetchone()
                if existing_nonce is not None:
                    raise ReplayError("task nonce was already claimed")

                self._conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, nonce, digest, repository_id, base_ref, base_commit_sha,
                        state, receipt_digest, mirror_identity, worktree, generated_branch,
                        cleanup_state, claimed_at, updated_at, terminal_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'CLAIMED', NULL, NULL, NULL, NULL, NULL, ?, ?, NULL)
                    """,
                    (
                        task_id,
                        nonce,
                        digest,
                        repository_id,
                        base_ref,
                        base_commit_sha,
                        now,
                        now,
                    ),
                )
                row = self._get_task(task_id)
                if row is None:
                    raise LedgerError("claimed task could not be read back")
                self._commit()
                return self._row_to_record(row)
            except (ReplayError, LedgerError):
                self._rollback()
                raise
            except sqlite3.IntegrityError as exc:
                self._rollback()
                raise ReplayError("task ID or nonce was claimed concurrently") from exc
            except sqlite3.Error as exc:
                self._rollback()
                raise LedgerError("failed to claim task") from exc

    def mark_terminal(
        self,
        task_id: str,
        receipt_digest: str,
        *,
        terminal_state: str = "TERMINAL",
    ) -> TaskRecord:
        task_id = _require_text("task_id", task_id)
        receipt_digest = _require_text("receipt_digest", receipt_digest)
        if terminal_state not in _TERMINAL_STATES:
            raise LedgerStateError("terminal state must be TERMINAL or QUARANTINED")
        now = _utc_now()

        with self._mutex:
            self._begin_immediate()
            try:
                row = self._get_task(task_id)
                if row is None:
                    raise LedgerStateError("unknown task cannot become terminal")
                if row["state"] not in {"CLAIMED", "EXECUTING"}:
                    raise LedgerStateError("terminal task cannot transition again")
                self._conn.execute(
                    """
                    UPDATE tasks
                       SET state = ?, receipt_digest = ?, terminal_at = ?, updated_at = ?
                     WHERE task_id = ?
                    """,
                    (terminal_state, receipt_digest, now, now, task_id),
                )
                updated = self._get_task(task_id)
                if updated is None:
                    raise LedgerError("terminal task could not be read back")
                self._commit()
                return self._row_to_record(updated)
            except LedgerError:
                self._rollback()
                raise
            except sqlite3.Error as exc:
                self._rollback()
                raise LedgerError("failed to mark task terminal") from exc

    def mark_cleanup(self, task_id: str, cleanup_state: str) -> TaskRecord:
        task_id = _require_text("task_id", task_id)
        cleanup_state = _require_text("cleanup_state", cleanup_state)
        now = _utc_now()
        with self._mutex:
            self._begin_immediate()
            try:
                row = self._get_task(task_id)
                if row is None:
                    raise LedgerStateError("unknown task cannot record cleanup")
                self._conn.execute(
                    "UPDATE tasks SET cleanup_state = ?, updated_at = ? WHERE task_id = ?",
                    (cleanup_state, now, task_id),
                )
                updated = self._get_task(task_id)
                if updated is None:
                    raise LedgerError("cleanup state could not be read back")
                self._commit()
                return self._row_to_record(updated)
            except LedgerError:
                self._rollback()
                raise
            except sqlite3.Error as exc:
                self._rollback()
                raise LedgerError("failed to record cleanup state") from exc

    def find_replay(self, task_id: str, nonce: str, digest: str) -> TaskRecord | None:
        task_id = _require_text("task_id", task_id)
        nonce = _require_text("nonce", nonce)
        digest = _require_text("digest", digest)
        with self._mutex:
            row = self._get_task(task_id)
            if row is None:
                nonce_row = self._conn.execute(
                    "SELECT * FROM tasks WHERE nonce = ?",
                    (nonce,),
                ).fetchone()
                if nonce_row is None:
                    return None
                raise ReplayError("task nonce is already bound to another task")
            if row["digest"] != digest:
                raise ReplayConflictError("task ID is bound to a different digest")
            if row["nonce"] != nonce:
                raise ReplayError("task ID is bound to a different nonce")
            return self._row_to_record(row)

    def list_in_progress(self) -> list[TaskRecord]:
        with self._mutex:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE state IN ('CLAIMED','EXECUTING') ORDER BY claimed_at, task_id"
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def acquire_worker_lease(self, worker_id: str) -> WorkerLease:
        worker_id = _require_text("worker_id", worker_id)
        handle = open(self._lease_path, "a+b")
        try:
            _lock_file(handle)
        except BaseException:
            handle.close()
            raise

        token = secrets.token_hex(32)
        now = _utc_now()
        try:
            with self._mutex:
                self._begin_immediate()
                try:
                    # A stale row from a crashed process is safe to replace only because
                    # this process already holds the OS-level exclusive lease file lock.
                    self._conn.execute(
                        """
                        INSERT INTO worker_lease(singleton, worker_id, lease_token, acquired_at)
                        VALUES (1, ?, ?, ?)
                        ON CONFLICT(singleton) DO UPDATE SET
                            worker_id = excluded.worker_id,
                            lease_token = excluded.lease_token,
                            acquired_at = excluded.acquired_at
                        """,
                        (worker_id, token, now),
                    )
                    self._commit()
                except LedgerError:
                    self._rollback()
                    raise
                except sqlite3.Error as exc:
                    self._rollback()
                    raise LeaseError("failed to persist worker lease") from exc
        except BaseException:
            _unlock_file(handle)
            handle.close()
            raise
        return WorkerLease(self, worker_id, token, handle)

    def _release_worker_lease(self, token: str) -> None:
        with self._mutex:
            self._begin_immediate()
            try:
                self._conn.execute(
                    "DELETE FROM worker_lease WHERE singleton = 1 AND lease_token = ?",
                    (token,),
                )
                self._commit()
            except LedgerError:
                self._rollback()
                raise
            except sqlite3.Error as exc:
                self._rollback()
                raise LeaseError("failed to release worker lease") from exc

    def durability_pragmas(self) -> dict[str, int | str]:
        with self._mutex:
            journal_mode = self._conn.execute("PRAGMA journal_mode").fetchone()[0]
            synchronous = self._conn.execute("PRAGMA synchronous").fetchone()[0]
            foreign_keys = self._conn.execute("PRAGMA foreign_keys").fetchone()[0]
        return {
            "journal_mode": journal_mode,
            "synchronous": synchronous,
            "foreign_keys": foreign_keys,
        }
