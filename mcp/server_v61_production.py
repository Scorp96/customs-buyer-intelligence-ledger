#!/usr/bin/env python3
"""Final production v6.1 MCP entrypoint with append-only receipt recovery.

The lower production entry layers remain regression-stable. This overlay adds
mechanically proven reconciliation for mutation families whose durable Runtime
events contain enough identity and result material to reconstruct the original
response without re-executing the side effect.

It also closes two mutation-surface gaps: provider-plan creation and closure
issuance mutate durable investigation state and therefore receive the same
write-ahead idempotency envelope as every other production mutation. Families
without an exact proof remain fail-closed in PREPARED state.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_entry as _entry  # noqa: E402


_v61 = _entry._v61
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared

_EXECUTION_PROOF = "ATTEMPT_EXECUTION_CONTENT_HASH_AND_EVENT_SEQ"
_PROVIDER_PROOF = "PROVIDER_RECEIPT_CALL_CONTENT_HASH_AND_EVENT_SEQ"
_CRM_PROOF = "CRM_WRITEBACK_TRANSACTION_HASH_AND_EVENT_SEQ"

# These handlers write durable state even though the earlier adapter inventory
# omitted them. Protect them immediately; until family-specific recovery is
# proven, a crash after PREPARED remains fail-closed rather than re-executed.
_ADDITIONAL_MUTATING_TOOLS = {
    "plan_provider_calls",
    "evaluate_investigation_closure",
}


def _events_after(
    investigation_id: str,
    stored: dict[str, Any],
    event_type: str,
) -> list[dict[str, Any]]:
    try:
        before = int(stored.get("state_version_before") or 0)
        events = _v61._server.RUNTIME.store.read(investigation_id)
    except Exception:
        return []
    return [
        event
        for event in events
        if int(event.get("seq") or 0) > before
        and event.get("event_type") == event_type
    ]


def _finish_reconciliation(
    tool_name: str,
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
    raw_result: dict[str, Any],
    event_seq: int,
    proof: str,
) -> dict[str, Any]:
    result = {
        **raw_result,
        "mutation_meta": _v61._reconciled_meta(
            tool_name,
            stored,
            request_hash,
            event_seq,
            proof,
        ),
    }
    _v61._commit_receipt(path, stored, result, event_seq)
    return result


def _reconcile_execution_receipt(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    attempt = args.get("attempt")
    if not investigation_id or not isinstance(attempt, dict):
        return None
    attempt_id = str(attempt.get("attempt_id") or "").strip()
    execution_id = str(attempt.get("execution_id") or "").strip()
    content_sha256 = str(attempt.get("content_sha256") or "").strip().lower()
    if not attempt_id or not execution_id or not content_sha256:
        return None

    matches: list[dict[str, Any]] = []
    for event in _events_after(investigation_id, stored, "EXECUTION_RECEIPT_APPENDED"):
        payload = event.get("payload")
        persisted = payload.get("attempt") if isinstance(payload, dict) else None
        if not isinstance(persisted, dict):
            continue
        if (
            str(persisted.get("attempt_id") or "") == attempt_id
            and str(persisted.get("execution_id") or "") == execution_id
            and str(persisted.get("investigation_id") or "") == investigation_id
            and str(persisted.get("content_sha256") or "").lower() == content_sha256
        ):
            matches.append(event)
    if len(matches) != 1:
        return None

    event = matches[0]
    payload = event["payload"]
    raw_result = {
        "accepted": True,
        "attempt_id": attempt_id,
        "evidence_count": len(payload.get("evidence") or []),
        "pivots_generated": len(payload.get("pivots_generated") or []),
        "pivots_consumed": len(payload.get("pivots_consumed") or []),
        "append_only": True,
    }
    return _finish_reconciliation(
        "append_execution_receipt",
        stored,
        request_hash,
        path,
        raw_result,
        int(event["seq"]),
        _EXECUTION_PROOF,
    )


def _reconcile_provider_receipt(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    receipt = args.get("receipt")
    if not investigation_id or not isinstance(receipt, dict):
        return None
    provider_receipt_id = str(receipt.get("provider_receipt_id") or "").strip()
    tool_call_id = str(receipt.get("tool_call_id") or "").strip()
    planned_call_id = str(receipt.get("planned_call_id") or "").strip()
    content_sha256 = str(receipt.get("content_sha256") or "").strip().lower()
    if not provider_receipt_id or not tool_call_id or not planned_call_id or not content_sha256:
        return None

    matches: list[dict[str, Any]] = []
    for event in _events_after(investigation_id, stored, "PROVIDER_RECEIPT_APPENDED"):
        payload = event.get("payload")
        persisted = payload.get("receipt") if isinstance(payload, dict) else None
        if not isinstance(persisted, dict):
            continue
        if (
            str(persisted.get("provider_receipt_id") or "") == provider_receipt_id
            and str(persisted.get("tool_call_id") or "") == tool_call_id
            and str(persisted.get("planned_call_id") or "") == planned_call_id
            and str(persisted.get("investigation_id") or "") == investigation_id
            and str(persisted.get("content_sha256") or "").lower() == content_sha256
        ):
            matches.append(event)
    if len(matches) != 1:
        return None

    event = matches[0]
    payload = event["payload"]
    persisted = payload["receipt"]
    contacts = persisted.get("contacts_returned") or []
    raw_result = {
        "accepted": True,
        "provider_receipt_id": provider_receipt_id,
        "provider": persisted.get("provider"),
        "requested_capability": persisted.get("requested_capability"),
        "result": persisted.get("result"),
        "evidence_count": len(payload.get("evidence") or []),
        "contacts_returned": len(contacts),
        "route_eligible_contacts": sum(
            1 for item in contacts
            if isinstance(item, dict) and item.get("route_eligible") is True
        ),
        "pivots_generated": len(payload.get("pivots_generated") or []),
        "pivots_consumed": len(payload.get("pivots_consumed") or []),
        "closes_public_source_families": False,
        "append_only": True,
    }
    return _finish_reconciliation(
        "append_provider_receipt",
        stored,
        request_hash,
        path,
        raw_result,
        int(event["seq"]),
        _PROVIDER_PROOF,
    )


def _reconcile_crm_writeback_receipt(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    receipt = args.get("receipt")
    if not investigation_id or not isinstance(receipt, dict):
        return None
    writeback_id = str(receipt.get("writeback_id") or "").strip()
    transaction_id = str(receipt.get("transaction_id") or "").strip()
    workbook_hash = str(receipt.get("workbook_sha256_after") or "").strip().lower()
    audit_hash = str(receipt.get("audit_artifact_sha256") or "").strip().lower()
    if not writeback_id or not transaction_id or not workbook_hash or not audit_hash:
        return None

    matches: list[dict[str, Any]] = []
    for event in _events_after(investigation_id, stored, "CRM_WRITEBACK_RECEIPT_APPENDED"):
        payload = event.get("payload")
        persisted = payload.get("receipt") if isinstance(payload, dict) else None
        if not isinstance(persisted, dict):
            continue
        if (
            str(persisted.get("writeback_id") or "") == writeback_id
            and str(persisted.get("transaction_id") or "") == transaction_id
            and str(persisted.get("investigation_id") or "") == investigation_id
            and str(persisted.get("workbook_sha256_after") or "").lower() == workbook_hash
            and str(persisted.get("audit_artifact_sha256") or "").lower() == audit_hash
        ):
            matches.append(event)
    if len(matches) != 1:
        return None

    event = matches[0]
    persisted = event["payload"]["receipt"]
    raw_result = {
        "accepted": True,
        "writeback_id": persisted["writeback_id"],
        "transaction_id": persisted["transaction_id"],
        "status": persisted["status"],
        "crm_sync_complete": True,
        "target_workbook_path": persisted["target_workbook_path"],
        "workbook_sha256_after": persisted["workbook_sha256_after"],
        "receipt_sha256": persisted["receipt_sha256"],
        "append_only": True,
        "runtime_mutated_workbook": False,
        "validated_external_writer": "ARTIFACT_TOOL",
    }
    return _finish_reconciliation(
        "append_crm_writeback_receipt",
        stored,
        request_hash,
        path,
        raw_result,
        int(event["seq"]),
        _CRM_PROOF,
    )


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "append_execution_receipt":
        return _reconcile_execution_receipt(args, stored, request_hash, path)
    if tool_name == "append_provider_receipt":
        return _reconcile_provider_receipt(args, stored, request_hash, path)
    if tool_name == "append_crm_writeback_receipt":
        return _reconcile_crm_writeback_receipt(args, stored, request_hash, path)
    return _BASE_RECONCILE_PREPARED(
        tool_name,
        args,
        stored,
        request_hash,
        path,
    )


_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.update({
    "append_execution_receipt",
    "append_provider_receipt",
    "append_crm_writeback_receipt",
})

# Wrap the two previously omitted durable mutators. hardened_tool_descriptors()
# reads _MUTATING_TOOLS dynamically, so tools/list now also advertises the
# required idempotency key and optional optimistic state-version guard.
_v61._MUTATING_TOOLS.update(_ADDITIONAL_MUTATING_TOOLS)
for _tool_name in sorted(_ADDITIONAL_MUTATING_TOOLS):
    _v61._server.TOOL_HANDLERS[_tool_name] = _v61._wrap_handler(
        _tool_name,
        _v61._ORIGINAL_HANDLERS[_tool_name],
    )


def main() -> int:
    return _entry.main()


if __name__ == "__main__":
    raise SystemExit(main())
