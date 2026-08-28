#!/usr/bin/env python3
"""v6.1 production MCP adapter over the stable compatibility server.

The large compatibility server remains readable and regression-stable.  This
adapter hardens the public v6 surface without silently rewriting historical v5
semantics: Decision Saturation is the only production closure strategy, and
mutation calls can use durable idempotency plus optimistic state-version checks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server as _server  # noqa: E402
from unified_runtime import ValidationError  # noqa: E402
from unified_runtime.resilience import exclusive_file_lock  # noqa: E402


_MUTATING_TOOLS = {
    "resolve_or_create_account",
    "start_investigation",
    "submit_research_objective",
    "compile_and_append_research_bundle",
    "append_information_record",
    "append_execution_receipt",
    "append_provider_receipt",
    "append_peer_receipt",
    "append_peer_discovery",
    "evaluate_peer",
    "promote_anchor",
    "close_pivot",
    "append_crm_writeback_receipt",
    "queue_pending_receipt",
    "sync_pending_receipts",
    "queue_host_bundle",
    "sync_pending_research_bundles",
    "sync_pending_bundles",
    "prepare_outreach",
    "render_outreach_action_card",
    "migrate_v5_4_1_to_v6",
}

_LEGACY_COMPATIBILITY_TOOLS = {
    "append_execution_receipt",
    "append_provider_receipt",
    "append_peer_receipt",
    "evaluate_commercial_readiness",
}

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
_ORIGINAL_TOOL_DESCRIPTORS = _server.tool_descriptors
_ORIGINAL_HANDLERS = dict(_server.TOOL_HANDLERS)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _journal_root() -> Path:
    root = _server.RUNTIME.store.root.parent / "mcp-idempotency-v61"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_version(arguments: dict[str, Any]) -> int:
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    if not investigation_id:
        return 0
    try:
        events = _server.RUNTIME.store.read(investigation_id)
    except Exception:
        return 0
    return int(events[-1]["seq"]) if events else 0


def _idempotency_path(tool_name: str, key: str) -> Path:
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]+", "-", tool_name)
    safe_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return _journal_root() / f"{safe_tool}-{safe_key}.json"


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    payload = (_canonical(value) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _normalize_start_contract(arguments: dict[str, Any]) -> dict[str, Any]:
    args = copy.deepcopy(arguments)
    policy = args.get("network_policy")
    if isinstance(policy, dict):
        strategy = str(policy.get("closure_strategy") or "").strip().upper()
        if strategy and strategy != "DECISION_SATURATION":
            raise ValidationError("network_policy.closure_strategy must be DECISION_SATURATION on the v6.1 production surface")
        policy.pop("closure_strategy", None)
    return args


def _invoke_mutation(tool_name: str, handler: Callable[[dict[str, Any]], dict[str, Any]], arguments: dict[str, Any]) -> dict[str, Any]:
    args = copy.deepcopy(arguments)
    if tool_name == "start_investigation":
        args = _normalize_start_contract(args)

    expected = args.pop("expected_state_version", None)
    before = _state_version(args)
    if expected is not None:
        try:
            expected_int = int(expected)
        except (TypeError, ValueError) as exc:
            raise ValidationError("expected_state_version must be an integer") from exc
        if expected_int != before:
            raise ValidationError(f"STATE_VERSION_CONFLICT expected={expected_int} current={before}")

    key = str(args.get("idempotency_key") or "").strip()
    if key and not _KEY_RE.fullmatch(key):
        raise ValidationError("idempotency_key must be 8-160 characters using letters, digits, dot, underscore, colon or hyphen")

    request_for_hash = copy.deepcopy(args)
    request_for_hash.pop("idempotency_key", None)
    request_hash = _digest({"tool": tool_name, "arguments": request_for_hash})

    def execute() -> dict[str, Any]:
        result = handler(args)
        after = _state_version(args)
        return {
            **result,
            "mutation_meta": {
                "schema": "cbi.mutation-meta.v6.1",
                "tool": tool_name,
                "idempotency_key": key or None,
                "request_sha256": request_hash,
                "state_version_before": before,
                "state_version_after": after,
                "replayed": False,
            },
        }

    if not key:
        return execute()

    path = _idempotency_path(tool_name, key)
    lock = path.with_suffix(".lock")
    with exclusive_file_lock(lock, timeout_seconds=60.0):
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored.get("request_sha256") != request_hash:
                raise ValidationError("IDEMPOTENCY_KEY_CONFLICT: key already committed with different request content")
            result = copy.deepcopy(stored["result"])
            result.setdefault("mutation_meta", {})["replayed"] = True
            return result
        result = execute()
        _atomic_json_write(path, {
            "schema": "cbi.mutation-receipt.v6.1",
            "tool": tool_name,
            "idempotency_key": key,
            "request_sha256": request_hash,
            "result_sha256": _digest(result),
            "result": result,
        })
        return result


def _wrap_handler(tool_name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def wrapped(arguments: dict[str, Any]) -> dict[str, Any]:
        return _invoke_mutation(tool_name, handler, arguments)

    return wrapped


def hardened_tool_descriptors() -> list[dict[str, Any]]:
    tools = _ORIGINAL_TOOL_DESCRIPTORS()
    for tool in tools:
        name = tool.get("name")
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            continue
        properties = schema.setdefault("properties", {})
        if name == "start_investigation":
            network = properties.get("network_policy")
            if isinstance(network, dict):
                closure = network.get("properties", {}).get("closure_strategy")
                if isinstance(closure, dict):
                    closure.clear()
                    closure.update({
                        "type": "string",
                        "const": "DECISION_SATURATION",
                        "description": "Production v6 closure policy. Legacy queue saturation is compatibility history only.",
                    })
        if name in _MUTATING_TOOLS:
            properties.setdefault("idempotency_key", {
                "type": "string",
                "minLength": 8,
                "maxLength": 160,
                "description": "Durable replay key. Strongly recommended during the compatibility transition; future v6 production schemas will require it.",
            })
            properties.setdefault("expected_state_version", {
                "type": "integer",
                "minimum": 0,
                "description": "Optional optimistic-concurrency guard; stale writers fail with STATE_VERSION_CONFLICT.",
            })
        if name in _LEGACY_COMPATIBILITY_TOOLS:
            tool["description"] = "[LEGACY_COMPATIBILITY_ONLY] " + str(tool.get("description") or "")
    return tools


# Patch only the adapter-facing descriptor/handler tables.  The original module
# remains importable for compatibility regression tests and migration tooling.
_server.tool_descriptors = hardened_tool_descriptors
for _name in _MUTATING_TOOLS:
    if _name in _ORIGINAL_HANDLERS:
        _server.TOOL_HANDLERS[_name] = _wrap_handler(_name, _ORIGINAL_HANDLERS[_name])


def main() -> int:
    return _server.main()


if __name__ == "__main__":
    raise SystemExit(main())
