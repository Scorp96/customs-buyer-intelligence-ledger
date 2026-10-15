"""Isolated, fail-closed session/WAL receipt-ownership adapter.

NOT connected to production. A verified SessionStore snapshot, externally
pinned tail, exact source-task owner, and trusted WAL COMMITTED proof are ALL
mandatory. User flags and receipt URLs alone cannot authorize completion.
"""
from __future__ import annotations
from typing import Any, Callable
from .core import SessionStore

_WALProof = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], bool]

def make_host_wal_receipt_verifier(
    *,
    session_store: SessionStore,
    investigation_id: str,
    account_id: str,
    expected_last_seq: int,
    expected_last_event_hash: str,
    wal_commit_verifier: _WALProof | None,
) -> Callable[[dict[str, Any], dict[str, Any]], bool]:
    """Construct read-only host-only verifier with independently pinned inputs.

    Caller must supply a trusted WAL reader verifying COMMITTED status, exact
    request/result identity and correlation. No live WAL authority is wired.
    """
    def verify(task: dict[str, Any], receipt: dict[str, Any]) -> bool:
        if not callable(wal_commit_verifier):
            return False
        if not isinstance(task, dict) or not isinstance(receipt, dict):
            return False
        if (
            not isinstance(expected_last_seq, int) or isinstance(expected_last_seq, bool)
            or expected_last_seq <= 0
            or not isinstance(expected_last_event_hash, str)
            or len(expected_last_event_hash) != 64
            or any(c not in "0123456789abcdef" for c in expected_last_event_hash)
            or not investigation_id or not account_id
        ):
            return False
        try:
            events = session_store.read(investigation_id)
        except Exception:
            return False
        if (
            len(events) != expected_last_seq
            or events[-1].get("event_hash") != expected_last_event_hash
            or events[0].get("event_type") != "INVESTIGATION_STARTED"
            or (events[0].get("payload") or {}).get("account", {}).get("account_id") != account_id
        ):
            return False
        seq, h = receipt.get("event_seq"), receipt.get("event_hash")
        if (
            not isinstance(seq, int) or isinstance(seq, bool)
            or seq <= 1 or seq > len(events)
            or not isinstance(h, str) or len(h) != 64
        ):
            return False
        event = events[seq - 1]
        if event.get("event_hash") != h or event.get("event_type") != "EXECUTION_RECEIPT_APPENDED":
            return False
        payload = event.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("attempt"), dict):
            return False
        attempt = payload["attempt"]
        if (
            attempt.get("investigation_id") != investigation_id
            or attempt.get("owner_id") != account_id
            or receipt.get("investigation_id") != investigation_id
            or receipt.get("account_id") != account_id
        ):
            return False
        for name in ("attempt_id", "execution_id", "completed_at", "result",
                     "content_sha256", "raw_result_locator"):
            if not isinstance(attempt.get(name), str) or not attempt[name]:
                return False
            if receipt.get(name) != attempt[name]:
                return False
        if attempt.get("result") == "BLOCKED":
            return False
        is_source = "call_id" in task
        mandatory = (
            ("call_id", "branch_group", "branch", "source_family", "query")
            if is_source else
            ("task_id", "opportunity_id", "route_target", "source_family", "company_name")
        )
        for field in mandatory:
            value = task.get(field)
            if not isinstance(value, str) or not value.strip():
                return False
            if attempt.get(field) != value or receipt.get(field) != value:
                return False
        if receipt.get("result") == "POSITIVE":
            refs = payload.get("evidence")
            evidence_ids = attempt.get("evidence_ids")
            if not isinstance(refs, list) or not isinstance(evidence_ids, list) or not evidence_ids:
                return False
            if {x.get("evidence_id") for x in refs if isinstance(x, dict)} != set(evidence_ids):
                return False
            claimed = receipt.get("evidence_ids") if is_source else receipt.get("route_evidence_ids")
            if not isinstance(claimed, list) or set(claimed) != set(evidence_ids):
                return False
        if receipt.get("result") == "NEGATIVE_EXHAUSTED":
            if attempt.get("evidence_ids") not in ([], None) or attempt.get("blocked_reason"):
                return False
        if receipt.get("result") == "NOT_APPLICABLE_JUSTIFIED":
            reason = receipt.get("not_applicable_reason") or receipt.get("justification")
            if not isinstance(reason, str) or not reason.strip():
                return False
            if attempt.get("blocked_reason") != reason:
                return False
        try:
            return wal_commit_verifier(event, attempt, task) is True
        except Exception:
            return False
    return verify
