from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, Protocol

from .github_api import GitHubApiError, GitHubIssueClient
from .models import TaskEnvelope, TaskValidationError
from .protocol import (
    ProtocolError,
    decode_signed_envelope,
    encode_signed_envelope,
    hmac_sha256_hex,
    parse_strict_json,
    verify_hmac_sha256,
)


class TaskGateError(RuntimeError):
    """Raised when the trusted task-signing gate cannot establish authorization."""


class RefPolicy(Protocol):
    def allows_base_ref(self, ref: str) -> bool: ...


@dataclass(frozen=True)
class GateResult:
    status: str
    issue_number: int | None
    reason: str


@dataclass(frozen=True)
class _EnvironmentRefPolicy:
    exact: frozenset[str]
    prefixes: tuple[str, ...]

    def allows_base_ref(self, ref: str) -> bool:
        if ref.lower() in {"main", "master", "production"}:
            return False
        return ref in self.exact or any(ref.startswith(prefix) for prefix in self.prefixes)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TaskGateError("timestamp is not UTC")
    return parsed


class TaskGate:
    def __init__(
        self,
        *,
        api: Any,
        repository: str,
        allowed_proposers: set[str],
        task_key: bytes,
        worker_id: str,
        repository_id: str,
        ref_policy: RefPolicy,
        max_task_age_seconds: int = 1800,
        max_task_payload_bytes: int = 49152,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not repository or not worker_id or not repository_id:
            raise TaskGateError("repository, worker_id, and repository_id are required")
        if not allowed_proposers or any(not isinstance(item, str) or not item for item in allowed_proposers):
            raise TaskGateError("allowed_proposers must be non-empty")
        if not isinstance(task_key, bytes) or len(task_key) < 32:
            raise TaskGateError("task HMAC key must be at least 32 bytes")
        if max_task_age_seconds <= 0 or max_task_payload_bytes <= 0:
            raise TaskGateError("task age and payload limits must be positive")
        self.api = api
        self.repository = repository
        self.allowed_proposers = {item.casefold() for item in allowed_proposers}
        self.task_key = task_key
        self.worker_id = worker_id
        self.repository_id = repository_id
        self.ref_policy = ref_policy
        self.max_task_age_seconds = int(max_task_age_seconds)
        self.max_task_payload_bytes = int(max_task_payload_bytes)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _reject(self, issue_number: int | None, reason: str) -> GateResult:
        if issue_number is not None:
            try:
                self.api.replace_astra_labels(issue_number, {"astra-task/rejected"})
            except Exception:
                # The security decision remains rejection even if GitHub cannot persist the label.
                pass
        return GateResult(status="REJECTED", issue_number=issue_number, reason=reason)

    @staticmethod
    def _issue_number(event: Any) -> int | None:
        if not isinstance(event, dict):
            return None
        issue = event.get("issue")
        number = issue.get("number") if isinstance(issue, dict) else None
        return number if isinstance(number, int) and not isinstance(number, bool) and number > 0 else None

    def _existing_valid_task_comments(self, issue_number: int) -> list[tuple[dict[str, Any], str]]:
        valid: list[tuple[dict[str, Any], str]] = []
        for comment in self.api.list_issue_comments(issue_number):
            if not isinstance(comment, dict):
                continue
            body = comment.get("body")
            author = comment.get("user")
            login = author.get("login") if isinstance(author, dict) else None
            if not isinstance(body, str) or not body.startswith("ASTRA_TASK_V1 "):
                continue
            if not isinstance(login, str) or login.casefold() != "github-actions[bot]":
                continue
            try:
                payload, signature = decode_signed_envelope(body, "task")
                verify_hmac_sha256(self.task_key, payload, signature)
            except ProtocolError:
                continue
            valid.append((payload, signature))
        return valid

    def process(self, event: dict[str, Any]) -> GateResult:
        issue_number = self._issue_number(event)
        try:
            if not isinstance(event, dict):
                raise TaskGateError("event must be an object")
            repository = event.get("repository")
            if not isinstance(repository, dict) or repository.get("full_name") != self.repository:
                raise TaskGateError("event repository mismatch")
            issue = event.get("issue")
            if not isinstance(issue, dict) or issue_number is None:
                raise TaskGateError("event issue is invalid")

            user = issue.get("user")
            proposer = user.get("login") if isinstance(user, dict) else None
            if not isinstance(proposer, str) or proposer.casefold() not in self.allowed_proposers:
                raise TaskGateError("issue proposer is not authorized")

            raw_labels = issue.get("labels", [])
            if not isinstance(raw_labels, list):
                raise TaskGateError("issue labels are invalid")
            labels = {
                item.get("name")
                for item in raw_labels
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            if "astra-task/proposed" not in labels:
                raise TaskGateError("issue is not proposed for ASTRA signing")

            body = issue.get("body")
            if not isinstance(body, str) or len(body.encode("utf-8")) > self.max_task_payload_bytes:
                raise TaskGateError("task body is missing or oversized")
            payload = parse_strict_json(body)
            if not isinstance(payload, dict):
                raise TaskGateError("task body must contain one JSON object")
            task = TaskEnvelope.from_mapping(payload)
            if task.worker_id != self.worker_id:
                raise TaskGateError("worker_id mismatch")
            if task.repository_id != self.repository_id:
                raise TaskGateError("repository_id mismatch")
            if not self.ref_policy.allows_base_ref(task.base_ref):
                raise TaskGateError("base_ref is not allowed")

            issued = _utc(task.issued_at)
            expires = _utc(task.expires_at)
            now = self.now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise TaskGateError("gate clock must be timezone-aware")
            now = now.astimezone(timezone.utc)
            age = (expires - issued).total_seconds()
            if age <= 0 or age > self.max_task_age_seconds:
                raise TaskGateError("task TTL exceeds policy")
            if now < issued or now >= expires:
                raise TaskGateError("task is not currently valid")

            resolved = self.api.resolve_branch_head(self.repository, task.base_ref)
            if resolved.casefold() != task.base_commit_sha.casefold():
                raise TaskGateError("base_ref does not resolve to signed base_commit_sha")

            expected_signature = hmac_sha256_hex(self.task_key, payload)
            existing = self._existing_valid_task_comments(issue_number)
            if len(existing) > 1:
                raise TaskGateError("multiple valid signed task comments are ambiguous")
            if existing:
                existing_payload, existing_signature = existing[0]
                if existing_payload != payload or existing_signature.casefold() != expected_signature.casefold():
                    raise TaskGateError("existing signed task conflicts with current proposal")
            else:
                comment = encode_signed_envelope("task", payload, expected_signature)
                self.api.post_issue_comment(issue_number, comment)

            self.api.replace_astra_labels(issue_number, {"astra-task/ready"})
            return GateResult(status="READY", issue_number=issue_number, reason="signed task ready")
        except (TaskGateError, TaskValidationError, ProtocolError, GitHubApiError, ValueError, TypeError):
            return self._reject(issue_number, "task signing gate rejected the proposal")


def _csv_set(raw: str, field: str, *, allow_empty: bool = False) -> set[str]:
    values = {item.strip() for item in raw.split(",") if item.strip()}
    if not values and not allow_empty:
        raise TaskGateError(f"{field} must not be empty")
    return values


def _key_from_environment(raw: str) -> bytes:
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise TaskGateError("ASTRA_TASK_HMAC_KEY_B64 is invalid") from exc
    if len(key) < 32:
        raise TaskGateError("ASTRA task HMAC key must be at least 32 bytes")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ASTRA trusted GitHub task signing gate")
    parser.add_argument("--event", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        event = parse_strict_json(args.event.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise TaskGateError("GitHub event must be an object")
        repository = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GITHUB_TOKEN"]
        allowed_proposers = _csv_set(os.environ["ASTRA_ALLOWED_PROPOSERS"], "allowed proposers")
        worker_id = os.environ["ASTRA_WORKER_ID"]
        repository_id = os.environ["ASTRA_REPOSITORY_ID"]
        exact = frozenset(
            _csv_set(os.environ.get("ASTRA_ALLOWED_BASE_REFS_EXACT", ""), "exact refs", allow_empty=True)
        )
        prefixes = tuple(
            sorted(
                _csv_set(
                    os.environ.get("ASTRA_ALLOWED_BASE_REF_PREFIXES", ""),
                    "ref prefixes",
                    allow_empty=True,
                )
            )
        )
        if not exact and not prefixes:
            raise TaskGateError("at least one base-ref rule is required")
        policy = _EnvironmentRefPolicy(exact=exact, prefixes=prefixes)
        key = _key_from_environment(os.environ["ASTRA_TASK_HMAC_KEY_B64"])
        max_age = int(os.environ.get("ASTRA_MAX_TASK_AGE_SECONDS", "1800"))
        api = GitHubIssueClient(repository, token)
        result = TaskGate(
            api=api,
            repository=repository,
            allowed_proposers=allowed_proposers,
            task_key=key,
            worker_id=worker_id,
            repository_id=repository_id,
            ref_policy=policy,
            max_task_age_seconds=max_age,
        ).process(event)
    except (OSError, KeyError, ValueError, ProtocolError, TaskGateError, GitHubApiError):
        return 2
    return 0 if result.status == "READY" else 3
