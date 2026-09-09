from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Any

from .compiler import CompilerError, intended_final_hashes
from .github_api import GitHubApiError, GitHubIssueClient
from .models import ReceiptEnvelope, TaskEnvelope
from .protocol import (
    ProtocolError,
    canonical_json_v1,
    decode_signed_envelope,
    parse_strict_json,
    verify_hmac_sha256,
)


class ReceiptGateError(RuntimeError):
    """Raised when a worker result cannot be proven from signed GitHub evidence."""


@dataclass(frozen=True)
class ReceiptGateResult:
    status: str
    issue_number: int
    task_id: str
    receipt_status: str


_TASK_PREFIX = "ASTRA_TASK_V1 "
_RECEIPT_PREFIX = "ASTRA_RECEIPT_V1 "
_PATCH_PREFIX = "ASTRA_PATCH_CHUNK_V1 "
_BOT_LOGIN = "github-actions[bot]"
_CLAIMED = "astra-task/claimed"
_RESULT_VERIFIED = "astra-task/result-verified"
_COMPLETED = "astra-task/completed"
_FAILED = "astra-task/failed"
_REJECTED = "astra-task/rejected"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_PATCH_CHUNK_BYTES = 48 * 1024
_PATCH_KEYS = {
    "schema_version",
    "task_id",
    "index",
    "total",
    "text",
    "sha256",
    "patch_sha256",
}


def _labels(issue: dict[str, Any]) -> set[str]:
    raw = issue.get("labels", [])
    if not isinstance(raw, list):
        raise ReceiptGateError("issue labels have an unexpected shape")
    result: set[str] = set()
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str) or not name:
            raise ReceiptGateError("issue label is malformed")
        result.add(name)
    return result


def _astra_labels(issue: dict[str, Any]) -> set[str]:
    return {label for label in _labels(issue) if label.startswith("astra-task/")}


def _comment_body(comment: dict[str, Any]) -> str:
    body = comment.get("body")
    return body if isinstance(body, str) else ""


def _comment_author(comment: dict[str, Any]) -> str:
    user = comment.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    return login if isinstance(login, str) else ""


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReceiptGateError(f"{field} must be lowercase SHA-256 hex")
    return value


def _strict_patch_chunk(body: str) -> dict[str, Any]:
    if not body.startswith(_PATCH_PREFIX):
        raise ReceiptGateError("patch chunk prefix is invalid")
    try:
        value = parse_strict_json(body[len(_PATCH_PREFIX) :])
    except ProtocolError as exc:
        raise ReceiptGateError("patch chunk JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != _PATCH_KEYS:
        raise ReceiptGateError("patch chunk shape is invalid")
    if value["schema_version"] != "astra.patch-chunk.v1":
        raise ReceiptGateError("patch chunk schema version is unsupported")
    if not isinstance(value["task_id"], str) or not value["task_id"]:
        raise ReceiptGateError("patch chunk task_id is invalid")
    for field in ("index", "total"):
        item = value[field]
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ReceiptGateError(f"patch chunk {field} must be positive")
    if not isinstance(value["text"], str):
        raise ReceiptGateError("patch chunk text must be text")
    raw = value["text"].encode("utf-8")
    if len(raw) > _MAX_PATCH_CHUNK_BYTES:
        raise ReceiptGateError("patch chunk exceeds 48 KiB")
    declared = _require_sha256(value["sha256"], "patch chunk sha256")
    _require_sha256(value["patch_sha256"], "patch chunk complete patch SHA-256")
    if hashlib.sha256(raw).hexdigest() != declared:
        raise ReceiptGateError("patch chunk SHA-256 mismatch")
    return value


class ReceiptGate:
    def __init__(
        self,
        *,
        api: Any,
        repository: str,
        task_key: bytes,
        receipt_key: bytes,
    ) -> None:
        if not isinstance(repository, str) or not repository:
            raise ReceiptGateError("repository must be non-empty")
        for name, key in (("task", task_key), ("receipt", receipt_key)):
            if not isinstance(key, bytes) or not key:
                raise ReceiptGateError(f"{name} HMAC key must be non-empty bytes")
        if task_key == receipt_key:
            raise ReceiptGateError("task and receipt HMAC keys must be independent")
        self._api = api
        self._repository = repository
        self._task_key = task_key
        self._receipt_key = receipt_key

    def _signed_task(self, comments: list[dict[str, Any]]) -> TaskEnvelope:
        valid: list[TaskEnvelope] = []
        for comment in comments:
            if _comment_author(comment) != _BOT_LOGIN:
                continue
            body = _comment_body(comment)
            if not body.startswith(_TASK_PREFIX):
                continue
            try:
                payload, signature = decode_signed_envelope(body, "task")
                verify_hmac_sha256(self._task_key, payload, signature)
                valid.append(TaskEnvelope.from_mapping(payload))
            except (ProtocolError, ValueError):
                continue
        if len(valid) != 1:
            raise ReceiptGateError("issue must contain exactly one valid signed task")
        return valid[0]

    def _event_receipt(self, body: str) -> ReceiptEnvelope:
        if not body.startswith(_RECEIPT_PREFIX):
            raise ReceiptGateError("event comment is not a receipt")
        try:
            payload, signature = decode_signed_envelope(body, "receipt")
            verify_hmac_sha256(self._receipt_key, payload, signature)
            return ReceiptEnvelope.from_mapping(payload)
        except (ProtocolError, ValueError) as exc:
            raise ReceiptGateError("event receipt HMAC or schema is invalid") from exc

    def _single_valid_receipt(
        self,
        comments: list[dict[str, Any]],
        event_receipt: ReceiptEnvelope,
    ) -> ReceiptEnvelope:
        valid: list[tuple[ReceiptEnvelope, bytes]] = []
        for comment in comments:
            body = _comment_body(comment)
            if not body.startswith(_RECEIPT_PREFIX):
                continue
            try:
                payload, signature = decode_signed_envelope(body, "receipt")
                verify_hmac_sha256(self._receipt_key, payload, signature)
                receipt = ReceiptEnvelope.from_mapping(payload)
            except (ProtocolError, ValueError):
                continue
            valid.append((receipt, canonical_json_v1(payload)))
        if len(valid) != 1:
            raise ReceiptGateError("issue must contain exactly one valid terminal receipt")
        receipt, canonical = valid[0]
        if canonical != canonical_json_v1(asdict(event_receipt)):
            raise ReceiptGateError("event receipt is not the issue's unique valid terminal receipt")
        return receipt

    def _verify_identity(self, task: TaskEnvelope, receipt: ReceiptEnvelope) -> None:
        fields = (
            "task_id",
            "worker_id",
            "repository_id",
            "base_ref",
            "base_commit_sha",
        )
        for field in fields:
            if getattr(task, field) != getattr(receipt, field):
                raise ReceiptGateError(f"task/receipt {field} mismatch")

    def _verify_final_hashes(self, task: TaskEnvelope, receipt: ReceiptEnvelope) -> dict[str, Any]:
        evidence = receipt.evidence
        if not isinstance(evidence, dict):
            raise ReceiptGateError("receipt evidence must be an object")
        observed = evidence.get("observed_final_hashes")
        if not isinstance(observed, dict):
            raise ReceiptGateError("receipt observed_final_hashes must be an object")
        try:
            intended = intended_final_hashes(task)
        except CompilerError as exc:
            raise ReceiptGateError("signed task cannot be compiled into final hash authority") from exc
        if observed != intended:
            raise ReceiptGateError("receipt final hashes do not match signed task authority")
        changed_paths = evidence.get("changed_paths")
        if not isinstance(changed_paths, list) or any(not isinstance(item, str) for item in changed_paths):
            raise ReceiptGateError("receipt changed_paths are invalid")
        changed_identity = [path.casefold() for path in changed_paths]
        if len(set(changed_identity)) != len(changed_identity):
            raise ReceiptGateError("receipt changed_paths contain duplicates or case collisions")
        intended_identity = {path.casefold() for path in intended}
        if any(path.casefold() not in intended_identity for path in changed_paths):
            raise ReceiptGateError("receipt changed_paths exceed signed mutation authority")
        return evidence

    def _verify_patch(
        self,
        task: TaskEnvelope,
        receipt: ReceiptEnvelope,
        comments: list[dict[str, Any]],
        evidence: dict[str, Any],
    ) -> None:
        patch_sha = _require_sha256(evidence.get("patch_sha256"), "receipt patch_sha256")
        chunk_hashes = evidence.get("patch_chunk_sha256")
        if not isinstance(chunk_hashes, list) or any(
            not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None for item in chunk_hashes
        ):
            raise ReceiptGateError("receipt patch_chunk_sha256 is invalid")
        diff_bytes = evidence.get("diff_bytes")
        if isinstance(diff_bytes, bool) or not isinstance(diff_bytes, int) or diff_bytes < 0:
            raise ReceiptGateError("receipt diff_bytes is invalid")

        chunks: list[dict[str, Any]] = []
        for comment in comments:
            body = _comment_body(comment)
            if not body.startswith(_PATCH_PREFIX):
                continue
            chunk = _strict_patch_chunk(body)
            if chunk["task_id"] != task.task_id:
                raise ReceiptGateError("issue contains patch chunk for a different task")
            chunks.append(chunk)

        if len(chunks) != len(chunk_hashes):
            raise ReceiptGateError("patch chunk count does not match receipt")
        expected_total = len(chunks)
        reconstructed: list[str] = []
        for expected_index, (chunk, expected_hash) in enumerate(zip(chunks, chunk_hashes), start=1):
            if chunk["index"] != expected_index or chunk["total"] != expected_total:
                raise ReceiptGateError("patch chunks are missing, duplicated, or reordered")
            if chunk["sha256"] != expected_hash:
                raise ReceiptGateError("ordered patch chunk hash does not match receipt")
            if chunk["patch_sha256"] != patch_sha:
                raise ReceiptGateError("patch chunk complete-patch binding is inconsistent")
            reconstructed.append(chunk["text"])
        raw = "".join(reconstructed).encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != patch_sha:
            raise ReceiptGateError("ordered patch chunks do not reconstruct the receipt patch")
        if len(raw) != diff_bytes:
            raise ReceiptGateError("reconstructed patch byte count does not match receipt")

    def _verify_execution_and_cleanup(self, receipt: ReceiptEnvelope, evidence: dict[str, Any]) -> None:
        cleanup = evidence.get("cleanup_success")
        if not isinstance(cleanup, bool):
            raise ReceiptGateError("receipt cleanup_success is invalid")
        execution = evidence.get("execution")
        if not isinstance(execution, dict):
            raise ReceiptGateError("receipt execution evidence is invalid")
        success = execution.get("success")
        applied = execution.get("applied")
        steps = execution.get("steps")
        if not isinstance(success, bool) or not isinstance(applied, bool) or not isinstance(steps, list):
            raise ReceiptGateError("receipt execution evidence shape is invalid")
        if receipt.status == "APPLY_READY" and (not cleanup or not success or not applied):
            raise ReceiptGateError("APPLY_READY requires successful apply evidence and cleanup")

    def process(self, event: dict[str, Any]) -> ReceiptGateResult:
        if not isinstance(event, dict):
            raise ReceiptGateError("GitHub event must be an object")
        repository = event.get("repository")
        full_name = repository.get("full_name") if isinstance(repository, dict) else None
        if full_name != self._repository:
            raise ReceiptGateError("event repository does not match configured repository")
        issue_event = event.get("issue")
        issue_number = issue_event.get("number") if isinstance(issue_event, dict) else None
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
            raise ReceiptGateError("event issue number is invalid")
        comment = event.get("comment")
        body = comment.get("body") if isinstance(comment, dict) else None
        if not isinstance(body, str):
            raise ReceiptGateError("event comment body is invalid")
        event_receipt = self._event_receipt(body)

        try:
            issue = self._api.get_issue(issue_number)
            comments = self._api.list_issue_comments(issue_number)
        except Exception as exc:
            raise ReceiptGateError("issue state could not be re-read") from exc
        if not isinstance(issue, dict) or issue.get("state", "open") != "open":
            raise ReceiptGateError("receipt issue is not open")
        if _astra_labels(issue) != {_CLAIMED}:
            raise ReceiptGateError("receipt issue is not exclusively claimed")
        if not isinstance(comments, list) or any(not isinstance(item, dict) for item in comments):
            raise ReceiptGateError("issue comments have an unexpected shape")

        task = self._signed_task(comments)
        receipt = self._single_valid_receipt(comments, event_receipt)
        self._verify_identity(task, receipt)
        evidence = self._verify_final_hashes(task, receipt)
        self._verify_patch(task, receipt, comments, evidence)
        self._verify_execution_and_cleanup(receipt, evidence)

        if receipt.status == "APPLY_READY":
            terminal = _COMPLETED
        elif receipt.status in {"NOT_APPLY_READY", "QUARANTINED"}:
            terminal = _FAILED
        elif receipt.status == "REJECTED":
            terminal = _REJECTED
        else:  # ReceiptEnvelope already validates this; retain fail-closed defense in depth.
            raise ReceiptGateError("receipt status is unsupported")
        try:
            self._api.replace_astra_labels(issue_number, {_RESULT_VERIFIED, terminal})
        except Exception as exc:
            raise ReceiptGateError("verified receipt labels could not be persisted") from exc
        return ReceiptGateResult(
            status="VERIFIED",
            issue_number=issue_number,
            task_id=task.task_id,
            receipt_status=receipt.status,
        )


def _key_from_environment(raw: str, name: str) -> bytes:
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise ReceiptGateError(f"{name} is invalid") from exc
    if len(key) < 32:
        raise ReceiptGateError(f"{name} must decode to at least 32 bytes")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ASTRA GitHub worker receipt verification gate")
    parser.add_argument("--event", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        event = parse_strict_json(args.event.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise ReceiptGateError("GitHub event must be an object")
        repository = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GITHUB_TOKEN"]
        task_key = _key_from_environment(
            os.environ["ASTRA_TASK_HMAC_KEY_B64"], "ASTRA_TASK_HMAC_KEY_B64"
        )
        receipt_key = _key_from_environment(
            os.environ["ASTRA_RECEIPT_HMAC_KEY_B64"], "ASTRA_RECEIPT_HMAC_KEY_B64"
        )
        api = GitHubIssueClient(repository, token)
        ReceiptGate(
            api=api,
            repository=repository,
            task_key=task_key,
            receipt_key=receipt_key,
        ).process(event)
    except (
        OSError,
        KeyError,
        ValueError,
        ProtocolError,
        ReceiptGateError,
        GitHubApiError,
    ):
        return 2
    return 0