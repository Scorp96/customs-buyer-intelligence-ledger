from __future__ import annotations

import hashlib
import unittest

from astra_worker.protocol import (
    canonical_json_v1,
    encode_signed_envelope,
    hmac_sha256_hex,
    parse_strict_json,
)
from astra_worker.queue import QueueError, TaskQueue


TASK_KEY = b"t" * 32
WORKER_ID = "scorp-windows-01"


def task_payload(**overrides) -> dict:
    payload = {
        "schema_version": "astra.task.v1",
        "task_id": "task-queue-001",
        "worker_id": WORKER_ID,
        "repository_id": "cbi-primary",
        "base_ref": "cbi-v6-3-demand-expansion",
        "base_commit_sha": "a" * 40,
        "issued_at": "2026-09-09T03:00:00Z",
        "expires_at": "2026-09-09T03:30:00Z",
        "nonce": "nonce-queue-001",
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


def signed_task_comment(payload: dict, *, key: bytes = TASK_KEY) -> dict:
    return {
        "user": {"login": "github-actions[bot]"},
        "body": encode_signed_envelope("task", payload, hmac_sha256_hex(key, payload)),
    }


def issue(number: int, *, labels: list[str]) -> dict:
    return {
        "number": number,
        "state": "open",
        "labels": [{"name": label} for label in labels],
    }


class FakeQueueApi:
    def __init__(self, issues: list[dict], comments: dict[int, list[dict]]) -> None:
        self.issues = list(issues)
        self.comments = {number: list(values) for number, values in comments.items()}
        self.list_labels: list[str] = []
        self.replaced: list[tuple[int, set[str]]] = []
        self.posted: list[tuple[int, str]] = []

    def list_open_issues_by_label(self, label: str) -> list[dict]:
        self.list_labels.append(label)
        return list(self.issues)

    def get_issue(self, issue_number: int) -> dict:
        for item in self.issues:
            if item.get("number") == issue_number:
                return item
        raise AssertionError("unknown issue")

    def list_issue_comments(self, issue_number: int) -> list[dict]:
        return list(self.comments.get(issue_number, []))

    def replace_astra_labels(self, issue_number: int, labels: set[str]) -> None:
        self.replaced.append((issue_number, set(labels)))
        for item in self.issues:
            if item.get("number") == issue_number:
                non_astra = [
                    label
                    for label in item.get("labels", [])
                    if isinstance(label, dict)
                    and isinstance(label.get("name"), str)
                    and not label["name"].startswith("astra-task/")
                ]
                item["labels"] = non_astra + [{"name": label} for label in sorted(labels)]

    def post_issue_comment(self, issue_number: int, body: str) -> None:
        self.posted.append((issue_number, body))
        self.comments.setdefault(issue_number, []).append(
            {"user": {"login": "worker-runtime"}, "body": body}
        )


class TaskQueueTests(unittest.TestCase):
    def test_unsigned_ready_issue_is_not_returned(self) -> None:
        api = FakeQueueApi(
            [issue(1, labels=["astra-task/ready"])],
            {1: [{"user": {"login": "Scorp96"}, "body": "unsigned"}]},
        )
        queue = TaskQueue(api=api, task_key=TASK_KEY)
        self.assertEqual(queue.find_ready(WORKER_ID), [])
        self.assertEqual(api.list_labels, ["astra-task/ready"])

    def test_two_conflicting_valid_signed_tasks_fail_closed(self) -> None:
        first = task_payload()
        second = task_payload(task_id="task-queue-002", nonce="nonce-queue-002")
        api = FakeQueueApi(
            [issue(2, labels=["astra-task/ready"])],
            {2: [signed_task_comment(first), signed_task_comment(second)]},
        )
        queue = TaskQueue(api=api, task_key=TASK_KEY)
        with self.assertRaises(QueueError):
            queue.find_ready(WORKER_ID)

    def test_wrong_worker_or_conflicting_lifecycle_is_not_executable(self) -> None:
        wrong_worker = task_payload(worker_id="other-worker")
        api = FakeQueueApi(
            [
                issue(3, labels=["astra-task/ready"]),
                issue(4, labels=["astra-task/ready", "astra-task/claimed"]),
            ],
            {
                3: [signed_task_comment(wrong_worker)],
                4: [signed_task_comment(task_payload(task_id="task-queue-004", nonce="nonce-queue-004"))],
            },
        )
        queue = TaskQueue(api=api, task_key=TASK_KEY)
        self.assertEqual(queue.find_ready(WORKER_ID), [])

    def test_valid_ready_task_is_selected_and_claim_comment_binds_task_digest(self) -> None:
        payload = task_payload()
        api = FakeQueueApi(
            [issue(5, labels=["bug", "astra-task/ready"])],
            {5: [signed_task_comment(payload)]},
        )
        queue = TaskQueue(api=api, task_key=TASK_KEY)
        ready = queue.find_ready(WORKER_ID)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].issue_number, 5)
        self.assertEqual(ready[0].task.task_id, payload["task_id"])
        expected_digest = hashlib.sha256(canonical_json_v1(payload)).hexdigest()
        self.assertEqual(ready[0].task_digest, expected_digest)

        queue.claim(ready[0])
        self.assertEqual(api.replaced, [(5, {"astra-task/claimed"})])
        self.assertEqual(len(api.posted), 1)
        prefix = "ASTRA_CLAIM_V1 "
        self.assertTrue(api.posted[0][1].startswith(prefix))
        claim = parse_strict_json(api.posted[0][1][len(prefix) :])
        self.assertEqual(
            claim,
            {
                "issue_number": 5,
                "task_digest": expected_digest,
                "task_id": payload["task_id"],
                "worker_id": WORKER_ID,
            },
        )
        self.assertNotIn("nonce-queue-001", api.posted[0][1])

    def test_claim_revalidates_ready_state_before_mutating(self) -> None:
        payload = task_payload()
        api = FakeQueueApi(
            [issue(6, labels=["astra-task/ready"])],
            {6: [signed_task_comment(payload)]},
        )
        queue = TaskQueue(api=api, task_key=TASK_KEY)
        ready = queue.find_ready(WORKER_ID)[0]
        api.issues[0]["labels"] = [{"name": "astra-task/claimed"}]
        with self.assertRaises(QueueError):
            queue.claim(ready)
        self.assertEqual(api.replaced, [])
        self.assertEqual(api.posted, [])


if __name__ == "__main__":
    unittest.main()
