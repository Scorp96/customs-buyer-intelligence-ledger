#!/usr/bin/env python3
"""Strict queue-correlation recovery for the final v6.1 MCP entrypoint.

Queue mutations receive an adapter-derived durable queue ID before the WAL
PREPARED intent is written. Recovery therefore requires both the exact derived
ID and its append-only QUEUED event. A same-content mutation from another
idempotency key cannot be mistaken for the crashed request.

Provider-plan, closure, sync, migration and other families without equivalent
request correlation remain fail-closed.
"""

from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_production as _production  # noqa: E402
from unified_runtime.core import digest as _core_digest  # noqa: E402


_v61 = _production._v61
_BASE_PREPARE_RESOURCE_SNAPSHOT = _v61._prepare_resource_snapshot
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared

_PENDING_QUEUE_PROOF = "WAL_DERIVED_PENDING_ID_AND_QUEUED_EVENT"
_HOST_QUEUE_PROOF = "WAL_DERIVED_HOST_ID_AND_QUEUED_EVENT"
_PENDING_GENERATED_FLAG = "_adapter_generated_pending_journal_id"
_HOST_GENERATED_FLAG = "_adapter_generated_host_bundle_queue_id"


def _derived_suffix(tool_name: str, key: str) -> str:
    return hashlib.sha256(f"{tool_name}:{key}".encode("utf-8")).hexdigest()[:12]


def _adapt_queue_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    args = copy.deepcopy(arguments)
    key = str(args.get("idempotency_key") or "").strip()
    if tool_name == "queue_pending_receipt":
        explicit = bool(str(args.get("journal_id") or "").strip())
        generated = bool(key) and not explicit
        if generated:
            args["journal_id"] = f"PEND-00000000T000000Z-{_derived_suffix(tool_name, key)}"
        args[_PENDING_GENERATED_FLAG] = generated
    elif tool_name == "queue_host_bundle":
        explicit = bool(str(args.get("bundle_queue_id") or "").strip())
        generated = bool(key) and not explicit
        if generated:
            args["bundle_queue_id"] = f"HOSTQ-00000000T000000Z-{_derived_suffix(tool_name, key)}"
        args[_HOST_GENERATED_FLAG] = generated
    return args


def _prepare_resource_snapshot(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "queue_pending_receipt":
        generated = args.get(_PENDING_GENERATED_FLAG) is True
        journal_id = str(args.get("journal_id") or "").strip()
        if not generated or not journal_id:
            return {
                "kind": "PENDING_RECEIPT_QUEUE_STRICT",
                "adapter_generated_id": False,
            }
        journal = _v61._server.RUNTIME.pending_journal
        try:
            event_count = len(journal.events.read())
            existed = journal.path(journal_id).is_file()
        except Exception:
            return {
                "kind": "PENDING_RECEIPT_QUEUE_STRICT",
                "adapter_generated_id": False,
            }
        return {
            "kind": "PENDING_RECEIPT_QUEUE_STRICT",
            "adapter_generated_id": True,
            "journal_id": journal_id,
            "entry_existed_before": existed,
            "queue_event_count_before": event_count,
        }

    if tool_name == "queue_host_bundle":
        generated = args.get(_HOST_GENERATED_FLAG) is True
        queue_id = str(args.get("bundle_queue_id") or "").strip()
        if not generated or not queue_id:
            return {
                "kind": "HOST_BUNDLE_QUEUE_STRICT",
                "adapter_generated_id": False,
            }
        queue = _v61._server.RUNTIME._v6_queue()
        try:
            event_count = len(queue.events.read())
            existed = queue._path(queue_id).is_file()
        except Exception:
            return {
                "kind": "HOST_BUNDLE_QUEUE_STRICT",
                "adapter_generated_id": False,
            }
        return {
            "kind": "HOST_BUNDLE_QUEUE_STRICT",
            "adapter_generated_id": True,
            "bundle_queue_id": queue_id,
            "entry_existed_before": existed,
            "queue_event_count_before": event_count,
        }

    return _BASE_PREPARE_RESOURCE_SNAPSHOT(tool_name, args)


def _matching_events_after(
    events: list[dict[str, Any]],
    before_count: int,
    event_type: str,
    id_field: str,
    expected_id: str,
    request_sha256: str,
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if int(event.get("seq") or 0) > before_count
        and event.get("event_type") == event_type
        and str((event.get("payload") or {}).get(id_field) or "") == expected_id
        and str((event.get("payload") or {}).get("request_sha256") or "") == request_sha256
    ]


def _reconcile_pending_queue(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    snapshot = stored.get("resource_snapshot_before")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("kind") != "PENDING_RECEIPT_QUEUE_STRICT"
        or snapshot.get("adapter_generated_id") is not True
        or snapshot.get("entry_existed_before") is not False
        or args.get(_PENDING_GENERATED_FLAG) is not True
    ):
        return None
    journal_id = str(args.get("journal_id") or "").strip()
    if not journal_id or str(snapshot.get("journal_id") or "") != journal_id:
        return None
    target_tool = str(args.get("target_tool") or "").strip()
    payload = args.get("payload")
    if not target_tool or not isinstance(payload, dict):
        return None
    pending_hash = _core_digest({"target_tool": target_tool, "payload": payload})
    journal = _v61._server.RUNTIME.pending_journal
    try:
        envelope = journal.load(journal_id)
        event_count_before = int(snapshot.get("queue_event_count_before") or 0)
        events = journal.events.read()
    except Exception:
        return None
    if (
        str(envelope.get("journal_id") or "") != journal_id
        or str(envelope.get("target_tool") or "") != target_tool
        or envelope.get("payload") != payload
        or str(envelope.get("request_sha256") or "") != pending_hash
    ):
        return None
    queued_events = _matching_events_after(
        events,
        event_count_before,
        "PENDING_RECEIPT_QUEUED",
        "journal_id",
        journal_id,
        pending_hash,
    )
    if len(queued_events) != 1:
        return None
    raw_result = {
        **envelope,
        "queued": True,
        "deduplicated": False,
        "path": str(journal.path(journal_id)),
    }
    return _production._finish_reconciliation(
        "queue_pending_receipt",
        stored,
        request_hash,
        path,
        raw_result,
        0,
        _PENDING_QUEUE_PROOF,
    )


def _reconcile_host_queue(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    snapshot = stored.get("resource_snapshot_before")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("kind") != "HOST_BUNDLE_QUEUE_STRICT"
        or snapshot.get("adapter_generated_id") is not True
        or snapshot.get("entry_existed_before") is not False
        or args.get(_HOST_GENERATED_FLAG) is not True
    ):
        return None
    queue_id = str(args.get("bundle_queue_id") or "").strip()
    if not queue_id or str(snapshot.get("bundle_queue_id") or "") != queue_id:
        return None
    payload = args.get("payload")
    if not isinstance(payload, dict):
        return None
    payload_hash = _core_digest(payload)
    queue = _v61._server.RUNTIME._v6_queue()
    try:
        envelope = queue.load(queue_id)
        event_count_before = int(snapshot.get("queue_event_count_before") or 0)
        events = queue.events.read()
    except Exception:
        return None
    if (
        str(envelope.get("bundle_queue_id") or "") != queue_id
        or envelope.get("payload") != payload
        or str(envelope.get("request_sha256") or "") != payload_hash
    ):
        return None
    queued_events = _matching_events_after(
        events,
        event_count_before,
        "HOST_BUNDLE_QUEUED",
        "bundle_queue_id",
        queue_id,
        payload_hash,
    )
    if len(queued_events) != 1:
        return None
    raw_result = {
        "bundle_queue_id": queue_id,
        "request_sha256": payload_hash,
        "status": "PENDING",
        "queued": True,
        "deduplicated": False,
        "path": str(queue._path(queue_id)),
    }
    return _production._finish_reconciliation(
        "queue_host_bundle",
        stored,
        request_hash,
        path,
        raw_result,
        0,
        _HOST_QUEUE_PROOF,
    )


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "queue_pending_receipt":
        return _reconcile_pending_queue(args, stored, request_hash, path)
    if tool_name == "queue_host_bundle":
        # Do not fall back to the older request-hash-only host recovery. The
        # strict correlation proof above is the production authority now.
        return _reconcile_host_queue(args, stored, request_hash, path)
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _queue_pending_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    args = _adapt_queue_arguments("queue_pending_receipt", arguments)
    return _v61._invoke_mutation(
        "queue_pending_receipt",
        _v61._ORIGINAL_HANDLERS["queue_pending_receipt"],
        args,
    )


def _queue_host_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    args = _adapt_queue_arguments("queue_host_bundle", arguments)
    return _v61._invoke_mutation(
        "queue_host_bundle",
        _v61._ORIGINAL_HANDLERS["queue_host_bundle"],
        args,
    )


_v61._prepare_resource_snapshot = _prepare_resource_snapshot
_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("queue_pending_receipt")
_v61._server.TOOL_HANDLERS["queue_pending_receipt"] = _queue_pending_handler
_v61._server.TOOL_HANDLERS["queue_host_bundle"] = _queue_host_handler


def main() -> int:
    return _production.main()


if __name__ == "__main__":
    raise SystemExit(main())
