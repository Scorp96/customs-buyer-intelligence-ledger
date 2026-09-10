from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest

from astra_worker.config import RepositoryBinding
from astra_worker.github_api import GitHubApiError, GitHubIssueClient
from astra_worker.protocol import (
    canonical_json_v1,
    decode_signed_envelope,
    encode_signed_envelope,
    hmac_sha256_hex,
    verify_hmac_sha256,
)
from astra_worker.receipt_gate import ReceiptGate, ReceiptGateError
from astra_worker.task_gate import TaskGate


BASE_SHA = "a" * 40
TASK_KEY = b"t" * 32
RECEIPT_KEY = b"r" * 32


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


def signed_task_body(payload: dict, *, key: bytes = TASK_KEY) -> str:
    return encode_signed_envelope("task", payload, hmac_sha256_hex(key, payload))


def patch_chunk_body(
    task_id: str,
    *,
    index: int,
    total: int,
    text: str,
    patch_sha256: str,
) -> str:
    payload = {
        "schema_version": "astra.patch-chunk.v1",
        "task_id": task_id,
        "index": index,
        "total": total,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "patch_sha256": patch_sha256,
    }
    return "ASTRA_PATCH_CHUNK_V1 " + canonical_json_v1(payload).decode("utf-8")


def valid_receipt_mapping(
    task: dict,
    *,
    chunks: tuple[str, ...] = ("abc", "def"),
    status: str = "APPLY_READY",
    observed_final_hashes: dict[str, str | None] | None = None,
) -> dict:
    patch = "".join(chunks).encode("utf-8")
    final_hashes = observed_final_hashes or {
        "example.txt": hashlib.sha256(b"hello\n").hexdigest()
    }
    return {
        "schema_version": "astra.receipt.v1",
        "task_id": task["task_id"],
        "worker_id": task["worker_id"],
        "repository_id": task["repository_id"],
        "base_ref": task["base_ref"],
        "base_commit_sha": task["base_commit_sha"],
        "status": status,
        "evidence": {
            "changed_paths": ["example.txt"],
            "observed_final_hashes": final_hashes,
            "diff_bytes": len(patch),
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "patch_chunk_sha256": [
                hashlib.sha256(chunk.encode("utf-8")).hexdigest() for chunk in chunks
            ],
            "cleanup_success": True,
            "execution": {"success": True, "applied": True, "steps": []},
        },
    }


def signed_receipt_body(payload: dict, *, key: bytes = RECEIPT_KEY) -> str:
    return encode_signed_envelope("receipt", payload, hmac_sha256_hex(key, payload))


def receipt_event(body: str) -> dict:
    return {
        "repository": {"full_name": "Scorp96/customs-buyer-intelligence-ledger"},
        "issue": {"number": 42},
        "comment": {"body": body, "user": {"login": "worker-runtime"}},
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

    def get_issue(self, issue_number: int) -> dict:
        return {
            "number": issue_number,
            "state": "open",
            "labels": [{"name": label} for label in sorted(self.labels)],
        }

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


class ReceiptGateTests(unittest.TestCase):
    def _api_for_receipt(
        self,
        *,
        task: dict | None = None,
        chunks: tuple[str, ...] = ("abc", "def"),
        receipt: dict | None = None,
        receipt_key: bytes = RECEIPT_KEY,
        chunk_order: tuple[int, ...] | None = None,
        extra_receipts: tuple[str, ...] = (),
    ) -> tuple[FakeGitHub, str]:
        task = task or valid_task_mapping()
        receipt = receipt or valid_receipt_mapping(task, chunks=chunks)
        patch = "".join(chunks).encode("utf-8")
        patch_sha = hashlib.sha256(patch).hexdigest()
        order = chunk_order or tuple(range(1, len(chunks) + 1))
        comments: list[dict] = [
            {"user": {"login": "github-actions[bot]"}, "body": signed_task_body(task)}
        ]
        for index in order:
            comments.append(
                {
                    "user": {"login": "worker-runtime"},
                    "body": patch_chunk_body(
                        task["task_id"],
                        index=index,
                        total=len(chunks),
                        text=chunks[index - 1],
                        patch_sha256=patch_sha,
                    ),
                }
            )
        body = signed_receipt_body(receipt, key=receipt_key)
        comments.extend(
            {"user": {"login": "worker-runtime"}, "body": item} for item in extra_receipts
        )
        comments.append({"user": {"login": "worker-runtime"}, "body": body})
        api = FakeGitHub(existing_comments=comments)
        api.labels = {"astra-task/claimed"}
        return api, body

    def _gate(self, api: FakeGitHub) -> ReceiptGate:
        return ReceiptGate(
            api=api,
            repository="Scorp96/customs-buyer-intelligence-ledger",
            task_key=TASK_KEY,
            receipt_key=RECEIPT_KEY,
        )

    def test_invalid_receipt_hmac_never_sets_result_verified(self) -> None:
        api, body = self._api_for_receipt(receipt_key=b"x" * 32)
        with self.assertRaises(ReceiptGateError):
            self._gate(api).process(receipt_event(body))
        self.assertEqual(api.labels, {"astra-task/claimed"})
        self.assertNotIn("astra-task/result-verified", api.labels)

    def test_missing_or_reordered_chunk_is_rejected(self) -> None:
        task = valid_task_mapping()
        receipt = valid_receipt_mapping(task, chunks=("abc", "def"))
        api, body = self._api_for_receipt(
            task=task,
            chunks=("abc", "def"),
            receipt=receipt,
            chunk_order=(2, 1),
        )
        with self.assertRaises(ReceiptGateError):
            self._gate(api).process(receipt_event(body))
        self.assertEqual(api.labels, {"astra-task/claimed"})

        api2, body2 = self._api_for_receipt(
            task=task,
            chunks=("abc", "def"),
            receipt=receipt,
            chunk_order=(1,),
        )
        with self.assertRaises(ReceiptGateError):
            self._gate(api2).process(receipt_event(body2))
        self.assertEqual(api2.labels, {"astra-task/claimed"})

    def test_duplicate_conflicting_terminal_receipt_is_rejected(self) -> None:
        task = valid_task_mapping()
        first = valid_receipt_mapping(task)
        duplicate = signed_receipt_body(first)
        api, body = self._api_for_receipt(task=task, receipt=first, extra_receipts=(duplicate,))
        with self.assertRaises(ReceiptGateError):
            self._gate(api).process(receipt_event(body))
        self.assertEqual(api.labels, {"astra-task/claimed"})

        conflicting = valid_receipt_mapping(task, status="QUARANTINED")
        api2, body2 = self._api_for_receipt(
            task=task,
            receipt=first,
            extra_receipts=(signed_receipt_body(conflicting),),
        )
        with self.assertRaises(ReceiptGateError):
            self._gate(api2).process(receipt_event(body2))
        self.assertEqual(api2.labels, {"astra-task/claimed"})

    def test_task_receipt_identity_and_signed_final_hashes_are_reverified(self) -> None:
        task = valid_task_mapping()
        wrong_identity = valid_receipt_mapping(task)
        wrong_identity["base_commit_sha"] = "b" * 40
        api, body = self._api_for_receipt(task=task, receipt=wrong_identity)
        with self.assertRaises(ReceiptGateError):
            self._gate(api).process(receipt_event(body))

        wrong_hash = valid_receipt_mapping(
            task,
            observed_final_hashes={"example.txt": hashlib.sha256(b"evil\n").hexdigest()},
        )
        api2, body2 = self._api_for_receipt(task=task, receipt=wrong_hash)
        with self.assertRaises(ReceiptGateError):
            self._gate(api2).process(receipt_event(body2))
        self.assertNotIn("astra-task/result-verified", api2.labels)

    def test_valid_apply_ready_receipt_sets_verified_and_completed(self) -> None:
        api, body = self._api_for_receipt()
        result = self._gate(api).process(receipt_event(body))
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(
            api.labels,
            {"astra-task/result-verified", "astra-task/completed"},
        )


class GitHubClientSurfaceTests(unittest.TestCase):
    def test_client_does_not_expose_source_write_or_pr_write_methods(self) -> None:
        client_methods = {name for name in dir(GitHubIssueClient) if not name.startswith("_")}
        self.assertTrue(
            {
                "get_issue",
                "list_open_issues_by_label",
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

    def test_comment_listing_paginates_beyond_first_hundred(self) -> None:
        client = GitHubIssueClient("Scorp96/customs-buyer-intelligence-ledger", "token-value")
        calls: list[str] = []

        def fake_request(method: str, path: str, payload=None):
            self.assertEqual(method, "GET")
            self.assertIsNone(payload)
            calls.append(path)
            if "page=2" in path:
                return [{"id": 101}]
            return [{"id": index} for index in range(1, 101)]

        client._request = fake_request  # type: ignore[method-assign]
        comments = client.list_issue_comments(42)
        self.assertEqual(len(comments), 101)
        self.assertTrue(any("page=2" in path for path in calls))

    def test_comment_listing_fails_closed_at_pagination_cap(self) -> None:
        client = GitHubIssueClient("Scorp96/customs-buyer-intelligence-ledger", "token-value")
        calls: list[str] = []

        def fake_request(method: str, path: str, payload=None):
            self.assertEqual(method, "GET")
            calls.append(path)
            return [{"id": index} for index in range(100)]

        client._request = fake_request  # type: ignore[method-assign]
        with self.assertRaises(GitHubApiError):
            client.list_issue_comments(42)
        self.assertGreaterEqual(len(calls), 2)


class WorkflowContractTests(unittest.TestCase):
    def test_signer_workflow_has_minimal_permissions_and_no_pull_request_target(self) -> None:
        workflow = Path(".github/workflows/astra-task-sign.yml").read_text(encoding="utf-8")
        self.assertIn("issues: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("scripts/astra_task_gate.py", workflow)

    def test_receipt_workflow_has_minimal_permissions_and_comment_only_trigger(self) -> None:
        workflow = Path(".github/workflows/astra-receipt-verify.yml").read_text(encoding="utf-8")
        self.assertIn("issue_comment:", workflow)
        self.assertIn("types: [created]", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("scripts/astra_receipt_gate.py", workflow)
        self.assertIn("ASTRA_TASK_HMAC_KEY", workflow)
        self.assertIn("ASTRA_RECEIPT_HMAC_KEY", workflow)


if __name__ == "__main__":
    unittest.main()
