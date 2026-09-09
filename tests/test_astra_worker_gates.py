from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from astra_worker.config import RepositoryBinding
from astra_worker.github_api import GitHubApiError, GitHubIssueClient
from astra_worker.protocol import (
    decode_signed_envelope,
    encode_signed_envelope,
    hmac_sha256_hex,
    verify_hmac_sha256,
)
from astra_worker.task_gate import TaskGate


BASE_SHA = "a" * 40
TASK_KEY = b"t" * 32


def binding() -> RepositoryBinding:
    return RepositoryBinding.from_mapping(
        "cbi-primary",
        {
            "github_repository": "Scorp96/customs-buyer-intelligence-ledger",
            "expected_origin": "https://github.com/Scorp96/customs-buyer-intelligence-ledger",
            "mirror_root": "D:/ASTRAWorker/repos/cbi-primary.git",
            "allowed_base_refs_exact": ["cbi-v6-3-demand-expansion"],
            "allowed_base_ref_prefixes": ["astra-"],
            "ephemeral_branch_prefix": "astra-worker/",
        },
    )


def valid_task_mapping(**overrides) -> dict:
    payload = {
        "schema_version": "astra.task.v1",
        "task_id": "task-gate-001",
        "worker_id": "scorp-windows-01",
        "repository_id": "cbi-primary",
        "base_ref": "cbi-v6-3-demand-expansion",
        "base_commit_sha": BASE_SHA,
        "issued_at": "2026-09-09T03:00:00Z",
        "expires_at": "2026-09-09T03:30:00Z",
        "nonce": "nonce-gate-001",
        "operations": [
            {
                "kind": "write_text",
                "path": "example.txt",
                "content": "hello\n",
                "expect_absent": True,
            }
        ],
        "acceptance": {"max_changed_files": 5, "max_diff_bytes": 4096},
    }
    payload.update(overrides)
    return payload


def issue_event(payload: dict | str, *, proposer: str = "Scorp96", labels=None) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return {
        "repository": {"full_name": "Scorp96/customs-buyer-intelligence-ledger"},
        "issue": {
            "number": 42,
            "user": {"login": proposer},
            "body": body,
            "labels": [{"name": item} for item in (labels or ["astra-task/proposed"])],
        },
    }


class FakeGitHub:
    def __init__(self, *, ref_sha: str = BASE_SHA, existing_comments=None) -> None:
        self.ref_sha = ref_sha
        self.comments: list[tuple[int, str]] = []
        self.existing_comments = list(existing_comments or [])
        self.labels: set[str] = {"astra-task/proposed"}
        self.resolve_calls: list[tuple[str, str]] = []

    def resolve_branch_head(self, repository: str, ref: str) -> str:
        self.resolve_calls.append((repository, ref))
        return self.ref_sha

    def list_issue_comments(self, issue_number: int) -> list[dict]:
        return list(self.existing_comments)

    def post_issue_comment(self, issue_number: int, body: str) -> None:
        self.comments.append((issue_number, body))
        self.existing_comments.append({"user": {"login": "github-actions[bot]"}, "body": body})

    def replace_astra_labels(self, issue_number: int, labels: set[str]) -> None:
        self.labels = set(labels)


def make_gate(api: FakeGitHub, **overrides) -> TaskGate:
    kwargs = {
        "api": api,
        "repository": "Scorp96/customs-buyer-intelligence-ledger",
        "allowed_proposers": {"Scorp96"},
        "task_key": TASK_KEY,
        "worker_id": "scorp-windows-01",
        "repository_id": "cbi-primary",
        "ref_policy": binding(),
        "max_task_age_seconds": 1800,
        "now": lambda: datetime(2026, 9, 9, 3, 10, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return TaskGate(**kwargs)


class TaskGateTests(unittest.TestCase):
    def test_valid_proposal_is_bound_signed_and_promoted_ready(self) -> None:
        api = FakeGitHub()
        result = make_gate(api).process(issue_event(valid_task_mapping()))
        self.assertEqual(result.status, "READY")
        self.assertEqual(
            api.resolve_calls,
            [("Scorp96/customs-buyer-intelligence-ledger", "cbi-v6-3-demand-expansion")],
        )
        self.assertEqual(api.labels, {"astra-task/ready"})
        self.assertEqual(len(api.comments), 1)
        payload, signature = decode_signed_envelope(api.comments[0][1], "task")
        verify_hmac_sha256(TASK_KEY, payload, signature)
        self.assertEqual(payload["base_commit_sha"], BASE_SHA)

    def test_retry_reuses_identical_valid_signed_comment_without_posting_duplicate(self) -> None:
        payload = valid_task_mapping()
        signature = hmac_sha256_hex(TASK_KEY, payload)
        existing = encode_signed_envelope("task", payload, signature)
        api = FakeGitHub(
            existing_comments=[{"user": {"login": "github-actions[bot]"}, "body": existing}]
        )
        result = make_gate(api).process(issue_event(payload))
        self.assertEqual(result.status, "READY")
        self.assertEqual(api.comments, [])
        self.assertEqual(api.labels, {"astra-task/ready"})

    def test_conflicting_preexisting_valid_signed_task_fails_closed(self) -> None:
        other = valid_task_mapping(task_id="other-task", nonce="other-nonce")
        existing = encode_signed_envelope("task", other, hmac_sha256_hex(TASK_KEY, other))
        api = FakeGitHub(
            existing_comments=[{"user": {"login": "github-actions[bot]"}, "body": existing}]
        )
        result = make_gate(api).process(issue_event(valid_task_mapping()))
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(api.comments, [])
        self.assertEqual(api.labels, {"astra-task/rejected"})

    def test_unauthorized_proposer_never_gets_ready(self) -> None:
        api = FakeGitHub()
        result = make_gate(api).process(issue_event(valid_task_mapping(), proposer="mallory"))
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(api.labels, {"astra-task/rejected"})
        self.assertEqual(api.comments, [])
        self.assertEqual(api.resolve_calls, [])

    def test_base_ref_sha_mismatch_is_rejected(self) -> None:
        api = FakeGitHub(ref_sha="1" * 40)
        result = make_gate(api).process(issue_event(valid_task_mapping(base_commit_sha="2" * 40)))
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(api.labels, {"astra-task/rejected"})
        self.assertEqual(api.comments, [])

    def test_wrong_repository_worker_repo_id_or_disallowed_ref_is_rejected(self) -> None:
        cases = []
        wrong_repo_event = issue_event(valid_task_mapping())
        wrong_repo_event["repository"]["full_name"] = "Scorp96/other"
        cases.append(wrong_repo_event)
        cases.append(issue_event(valid_task_mapping(worker_id="other-worker")))
        cases.append(issue_event(valid_task_mapping(repository_id="other-repo")))
        cases.append(issue_event(valid_task_mapping(base_ref="main")))
        for event in cases:
            with self.subTest(event=event):
                api = FakeGitHub()
                result = make_gate(api).process(event)
                self.assertEqual(result.status, "REJECTED")
                self.assertNotIn("astra-task/ready", api.labels)

    def test_missing_proposed_label_or_expired_or_too_long_ttl_is_rejected(self) -> None:
        events = [
            issue_event(valid_task_mapping(), labels=["bug"]),
            issue_event(valid_task_mapping(expires_at="2026-09-09T03:05:00Z")),
            issue_event(valid_task_mapping(expires_at="2026-09-09T04:00:00Z")),
        ]
        for event in events:
            api = FakeGitHub()
            result = make_gate(api).process(event)
            self.assertEqual(result.status, "REJECTED")
            self.assertEqual(api.comments, [])

    def test_duplicate_key_json_is_rejected_before_signing(self) -> None:
        raw = json.dumps(valid_task_mapping())
        raw = raw.replace(
            '"task_id": "task-gate-001",',
            '"task_id": "task-gate-001", "task_id": "evil",',
            1,
        )
        api = FakeGitHub()
        result = make_gate(api).process(issue_event(raw))
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(api.comments, [])


class GitHubClientSurfaceTests(unittest.TestCase):
    def test_client_does_not_expose_source_write_or_pr_write_methods(self) -> None:
        client_methods = {name for name in dir(GitHubIssueClient) if not name.startswith("_")}
        self.assertTrue(
            {
                "get_issue",
                "list_issue_comments",
                "post_issue_comment",
                "replace_astra_labels",
                "resolve_branch_head",
            }.issubset(client_methods)
        )
        self.assertFalse(
            {
                "create_file",
                "update_file",
                "delete_file",
                "create_pull_request",
                "merge_pull_request",
            }.intersection(client_methods)
        )

    def test_api_error_never_includes_bearer_token(self) -> None:
        token = "ghp_super_secret_token_value"
        client = GitHubIssueClient("Scorp96/customs-buyer-intelligence-ledger", token)
        error = client._safe_error(
            "request failed",
            RuntimeError(f"header Authorization: Bearer {token}"),
        )
        self.assertIsInstance(error, GitHubApiError)
        self.assertNotIn(token, str(error))


class WorkflowContractTests(unittest.TestCase):
    def test_signer_workflow_has_minimal_permissions_and_no_pull_request_target(self) -> None:
        workflow = Path(".github/workflows/astra-task-sign.yml").read_text(encoding="utf-8")
        self.assertIn("issues: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("scripts/astra_task_gate.py", workflow)


if __name__ == "__main__":
    unittest.main()
