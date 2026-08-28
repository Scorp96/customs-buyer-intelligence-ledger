#!/usr/bin/env python3
"""Cold-process acceptance checks for the production v6.1 MCP adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SERVER = Path(__file__).with_name("server_v61.py")


def rpc(process: subprocess.Popen[str], request_id: int, method: str, params: dict | None = None) -> dict:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, ensure_ascii=True) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise RuntimeError(f"MCP adapter ended unexpectedly: {stderr}")
    return json.loads(line)


def tool(process: subprocess.Popen[str], request_id: int, name: str, arguments: dict) -> dict:
    response = rpc(process, request_id, "tools/call", {"name": name, "arguments": arguments})
    if "error" in response:
        raise RuntimeError(f"{name}: {response['error']['message']}")
    return response["result"]["structuredContent"]


def expect_error(process: subprocess.Popen[str], request_id: int, name: str, arguments: dict, fragment: str) -> None:
    response = rpc(process, request_id, "tools/call", {"name": name, "arguments": arguments})
    if "error" not in response:
        raise AssertionError(f"{name}: expected error containing {fragment!r}")
    message = str(response["error"].get("message") or "")
    if fragment not in message:
        raise AssertionError(f"{name}: error {message!r} did not contain {fragment!r}")


def main() -> int:
    passed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cbi-v61-adapter-") as temp:
        root = Path(temp)
        environment = dict(os.environ)
        environment.update({
            "CBI_SESSION_ROOT": str(root / "sessions"),
            "CBI_HOST_PENDING_ROOT": str(root / "host-pending"),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        try:
            initialized = rpc(process, 1, "initialize", {"protocolVersion": "2025-06-18"})["result"]
            assert initialized["serverInfo"]["version"] == "6.1.0"
            listed = rpc(process, 2, "tools/list")["result"]["tools"]
            tools = {row["name"]: row for row in listed}
            start_schema = tools["start_investigation"]["inputSchema"]
            closure = start_schema["properties"]["network_policy"]["properties"]["closure_strategy"]
            assert closure["const"] == "DECISION_SATURATION"
            objective_props = tools["submit_research_objective"]["inputSchema"]["properties"]
            assert "idempotency_key" in objective_props
            assert "expected_state_version" in objective_props
            passed.extend(["initialize_v61_adapter", "decision_saturation_public_contract", "mutation_guards_discoverable"])

            start_args = {
                "account": {"account_id": "C-ADAPTER-SYNTH", "country": "Synthetic", "name": "Synthetic Adapter Buyer"},
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
                "network_policy": {"closure_strategy": "DECISION_SATURATION"},
                "idempotency_key": "start-adapter-0001",
            }
            started = tool(process, 3, "start_investigation", start_args)
            investigation_id = started["investigation_id"]
            assert started["completion_policy"] == "DECISION_SATURATION"
            assert started["mutation_meta"]["replayed"] is False
            replayed = tool(process, 4, "start_investigation", start_args)
            assert replayed["investigation_id"] == investigation_id
            assert replayed["mutation_meta"]["replayed"] is True
            passed.extend(["start_decision_saturation", "durable_idempotent_start_replay"])

            resumed = tool(process, 5, "resume_investigation", {"investigation_id": investigation_id})
            current_version = int(resumed["last_safe_seq"])
            objective_args = {
                "investigation_id": investigation_id,
                "expected_state_version": current_version,
                "idempotency_key": "objective-adapter-0001",
                "objective": {
                    "claim_key": "identity.legal_entity",
                    "query_or_navigation": "Verify the synthetic legal entity fixture",
                    "source_family": "synthetic_official",
                },
            }
            objective = tool(process, 6, "submit_research_objective", objective_args)
            assert objective["mutation_meta"]["state_version_before"] == current_version
            assert objective["mutation_meta"]["state_version_after"] > current_version
            objective_replay = tool(process, 7, "submit_research_objective", objective_args)
            assert objective_replay["mutation_meta"]["replayed"] is True
            passed.extend(["optimistic_state_version_success", "idempotent_replay_precedes_stale_retry_check"])

            stale_args = {
                "investigation_id": investigation_id,
                "expected_state_version": current_version,
                "idempotency_key": "objective-adapter-0002",
                "objective": {
                    "claim_key": "product.fit",
                    "query_or_navigation": "Verify synthetic product fit",
                    "source_family": "synthetic_official",
                },
            }
            expect_error(process, 8, "submit_research_objective", stale_args, "STATE_VERSION_CONFLICT")
            passed.append("stale_writer_rejected")

            conflicting_replay = dict(start_args)
            conflicting_replay["account"] = {"account_id": "C-ADAPTER-OTHER", "country": "Synthetic", "name": "Other Synthetic Buyer"}
            expect_error(process, 9, "start_investigation", conflicting_replay, "IDEMPOTENCY_KEY_CONFLICT")
            passed.append("idempotency_key_request_conflict_rejected")

            legacy_start = dict(start_args)
            legacy_start["idempotency_key"] = "start-adapter-legacy"
            legacy_start["network_policy"] = {"closure_strategy": "QUEUE_PIVOT_SATURATION"}
            expect_error(process, 10, "start_investigation", legacy_start, "must be DECISION_SATURATION")
            passed.append("legacy_queue_closure_rejected_on_production_adapter")
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    print(json.dumps({"runtime_version": "6.1.0", "passed": len(passed), "tests": passed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
