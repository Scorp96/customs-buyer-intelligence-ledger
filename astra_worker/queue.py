from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from .models import TaskEnvelope
from .protocol import (
    ProtocolError,
    canonical_json_v1,
    decode_signed_envelope,
    verify_hmac_sha256,
)


class QueueError(RuntimeError):
    """Raised when GitHub queue state is ambiguous or no longer safely claimable."""


_READY = "astra-task/ready"
_CLAIMED = "astra-task/claimed"
_CLAIM_PREFIX = "ASTRA_CLAIM_V1 "
_BOT_LOGIN = "github-actions[bot]"


@dataclass(frozen=True)
class ReadyTask:
    issue_number: int
    task: TaskEnvelope
    task_digest: str


def _label_names(issue: dict[str, Any]) -> set[str]:
    labels = issue.get("labels", [])
    if not isinstance(labels, list):
        raise QueueError("issue labels have an unexpected shape")
    result: set[str] = set()
    for item in labels:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name")
        else:
            raise QueueError("issue label has an unexpected shape")
        if not isinstance(name, str) or not name:
            raise QueueError("issue label name is malformed")
        result.add(name)
    return result


def _astra_labels(issue: dict[str, Any]) -> set[str]:
    return {name for name in _label_names(issue) if name.startswith("astra-task/")}


def _comment_author(comment: dict[str, Any]) -> str:
    user = comment.get("user")
    if not isinstance(user, dict):
        return ""
    login = user.get("login")
    return login if isinstance(login, str) else ""


def _comment_body(comment: dict[str, Any]) -> str:
    body = comment.get("body")
    return body if isinstance(body, str) else ""


class TaskQueue:
    def __init__(self, *, api: Any, task_key: bytes) -> None:
        if not isinstance(task_key, bytes) or not task_key:
            raise QueueError("task HMAC key must be non-empty bytes")
        self._api = api
        self._task_key = task_key

    def _valid_task(self, issue_number: int) -> tuple[TaskEnvelope, str] | None:
        try:
            comments = self._api.list_issue_comments(issue_number)
        except Exception as exc:
            raise QueueError("issue comments could not be read") from exc
        if not isinstance(comments, list):
            raise QueueError("issue comments have an unexpected shape")

        valid_by_digest: dict[str, TaskEnvelope] = {}
        for comment in comments:
            if not isinstance(comment, dict) or _comment_author(comment) != _BOT_LOGIN:
                continue
            body = _comment_body(comment)
            if not body.startswith("ASTRA_TASK_V1 "):
                continue
            try:
                payload, signature = decode_signed_envelope(body, "task")
                verify_hmac_sha256(self._task_key, payload, signature)
                task = TaskEnvelope.from_mapping(payload)
                digest = hashlib.sha256(canonical_json_v1(payload)).hexdigest()
            except (ProtocolError, ValueError):
                continue
            valid_by_digest.setdefault(digest, task)

        if not valid_by_digest:
            return None
        if len(valid_by_digest) != 1:
            raise QueueError("issue contains conflicting valid signed tasks")
        digest, task = next(iter(valid_by_digest.items()))
        return task, digest

    def find_ready(self, worker_id: str) -> list[ReadyTask]:
        if not isinstance(worker_id, str) or not worker_id:
            raise QueueError("worker_id must be non-empty text")
        try:
            issues = self._api.list_open_issues_by_label(_READY)
        except Exception as exc:
            raise QueueError("ready issue discovery failed") from exc
        if not isinstance(issues, list):
            raise QueueError("ready issue listing has an unexpected shape")

        ready: list[ReadyTask] = []
        for issue in issues:
            if not isinstance(issue, dict):
                raise QueueError("ready issue has an unexpected shape")
            number = issue.get("number")
            if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
                raise QueueError("ready issue number is malformed")
            if issue.get("state", "open") != "open":
                continue
            if _astra_labels(issue) != {_READY}:
                continue
            resolved = self._valid_task(number)
            if resolved is None:
                continue
            task, digest = resolved
            if task.worker_id != worker_id:
                continue
            ready.append(ReadyTask(issue_number=number, task=task, task_digest=digest))
        ready.sort(key=lambda item: item.issue_number)
        return ready

    def claim(self, ready: ReadyTask) -> None:
        if not isinstance(ready, ReadyTask):
            raise QueueError("ReadyTask is required")
        try:
            issue = self._api.get_issue(ready.issue_number)
        except Exception as exc:
            raise QueueError("issue could not be re-read before claim") from exc
        if not isinstance(issue, dict) or issue.get("state", "open") != "open":
            raise QueueError("issue is no longer open")
        if _astra_labels(issue) != {_READY}:
            raise QueueError("issue is no longer exclusively ready")

        resolved = self._valid_task(ready.issue_number)
        if resolved is None:
            raise QueueError("signed task disappeared before claim")
        task, digest = resolved
        if digest != ready.task_digest or task != ready.task:
            raise QueueError("signed task changed before claim")

        claim_payload = {
            "issue_number": ready.issue_number,
            "task_digest": ready.task_digest,
            "task_id": ready.task.task_id,
            "worker_id": ready.task.worker_id,
        }
        claim_body = _CLAIM_PREFIX + canonical_json_v1(claim_payload).decode("utf-8")
        try:
            # Remove READY first: a crash after this point leaves a fail-closed claimed issue,
            # rather than allowing another worker to rediscover it as executable.
            self._api.replace_astra_labels(ready.issue_number, {_CLAIMED})
            self._api.post_issue_comment(ready.issue_number, claim_body)
        except Exception as exc:
            raise QueueError("issue claim could not be completed") from exc
