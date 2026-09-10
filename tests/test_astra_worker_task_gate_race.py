from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from astra_worker.protocol import encode_signed_envelope, hmac_sha256_hex
from astra_worker.task_gate import TaskGate


TASK_KEY = b"t" * 32
BASE_SHA = "a" * 40


def task_payload(*, expires_at: str = "2026-09-09T03:30:00Z") -> dict:
    return {
        "schema_version": "astra.task.v1",
        "task_id": "race-task-001",
        "worker_id": "scorp-windows-01",
        "repository_id": "cbi-primary",
        "base_ref": "cbi-v6-3-demand-expansion",
        "base_commit_sha": BASE_SHA,
        "issued_at": "2026-09-09T03:00:00Z",
        "expires_at": expires_at,
        "nonce": "race-nonce-001",
        "operations": [{"kind": "write_text", "path": "probe.txt", "content": "ok\n", "expect_absent": True}],
        "acceptance": {"max_changed_files": 1, "max_diff_bytes": 4096},
    }


def stale_event(payload: dict) -> dict:
    return {
        "repository": {"full_name": "Scorp96/customs-buyer-intelligence-ledger"},
        "issue": {
            "number": 32,
            "user": {"login": "Scorp96"},
            "body": json.dumps(payload, separators=(",", ":")),
            "labels": [{"name": "astra-task/proposed"}],
        },
    }


class RefPolicy:
    def allows_base_ref(self, ref: str) -> bool:
        return ref == "cbi-v6-3-demand-expansion"


class RaceApi:
    def __init__(self, signed_task: str) -> None:
        self.labels = {"astra-task/claimed"}
        self.signed_task = signed_task
        self.replacements: list[set[str]] = []

    def resolve_branch_head(self, repository: str, ref: str) -> str:
        return BASE_SHA

    def list_issue_comments(self, issue_number: int) -> list[dict]:
        return [{"user": {"login": "github-actions[bot]"}, "body": self.signed_task}]

    def get_issue(self, issue_number: int) -> dict:
        return {
            "number": issue_number,
            "state": "open",
            "labels": [{"name": label} for label in sorted(self.labels)],
        }

    def post_issue_comment(self, issue_number: int, body: str) -> None:
        raise AssertionError("identical signed task must not be reposted")

    def replace_astra_labels(self, issue_number: int, labels: set[str]) -> None:
        self.replacements.append(set(labels))
        self.labels = set(labels)


def gate(api: RaceApi) -> TaskGate:
    return TaskGate(
        api=api,
        repository="Scorp96/customs-buyer-intelligence-ledger",
        allowed_proposers={"Scorp96"},
        task_key=TASK_KEY,
        worker_id="scorp-windows-01",
        repository_id="cbi-primary",
        ref_policy=RefPolicy(),
        now=lambda: datetime(2026, 9, 9, 3, 10, tzinfo=timezone.utc),
    )


class StaleSignerRaceTests(unittest.TestCase):
    def test_late_identical_signer_cannot_downgrade_claimed_back_to_ready(self) -> None:
        payload = task_payload()
        signed = encode_signed_envelope("task", payload, hmac_sha256_hex(TASK_KEY, payload))
        api = RaceApi(signed)

        result = gate(api).process(stale_event(payload))

        self.assertEqual(result.status, "READY")
        self.assertEqual(api.labels, {"astra-task/claimed"})
        self.assertEqual(api.replacements, [])

    def test_late_invalid_signer_cannot_downgrade_claimed_to_rejected(self) -> None:
        payload = task_payload(expires_at="2026-09-09T03:05:00Z")
        signed = encode_signed_envelope("task", payload, hmac_sha256_hex(TASK_KEY, payload))
        api = RaceApi(signed)

        result = gate(api).process(stale_event(payload))

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(api.labels, {"astra-task/claimed"})
        self.assertEqual(api.replacements, [])


if __name__ == "__main__":
    unittest.main()
