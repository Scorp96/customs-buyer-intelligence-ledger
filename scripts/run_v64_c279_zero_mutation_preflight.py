#!/usr/bin/env python3
"""Fail-closed, zero-production-mutation C279 preflight."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.render_r2_acceptance_client_v63 import (
    RenderR2AcceptanceClient,
    RenderR2AcceptanceClientConfig,
    RenderR2AcceptanceClientError,
)


SCHEMA = "cbi.v64-c279-zero-mutation-preflight.v1"
TARGET_ACCOUNT_ID = "C279"
READ_ONLY_TOOLS = frozenset(
    {
        "get_portfolio_queue",
        "get_investigation_health",
        "get_investigation_state",
        "evaluate_outreach_readiness",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PreflightError(RuntimeError):
    pass


def _fail(code: str) -> None:
    raise PreflightError(str(code))


def _read_only_call(client: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in READ_ONLY_TOOLS:
        _fail("PREFLIGHT_MUTATION_TOOL_FORBIDDEN")
    result = client.call_tool(name, arguments)
    if not isinstance(result, dict):
        _fail("PREFLIGHT_REMOTE_RESULT_INVALID")
    return result


def _tail(value: dict[str, Any]) -> tuple[int, str]:
    try:
        seq = int(value.get("last_safe_seq"))
    except (TypeError, ValueError):
        _fail("C279_TAIL_INVALID")
    event_hash = str(value.get("last_safe_event_hash") or "").strip().lower()
    if seq < 1 or _SHA256_RE.fullmatch(event_hash) is None:
        _fail("C279_TAIL_INVALID")
    return seq, event_hash


def run_preflight(client: Any) -> dict[str, Any]:
    remote_health = client.read_health()
    if not isinstance(remote_health, dict):
        _fail("REMOTE_HEALTH_INVALID")
    client.initialize()

    portfolio = _read_only_call(client, "get_portfolio_queue", {"limit": 1000})
    rows = portfolio.get("queue")
    if not isinstance(rows, list):
        _fail("PORTFOLIO_QUEUE_INVALID")
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("account_id") or "").strip() == TARGET_ACCOUNT_ID
    ]
    if len(matches) != 1:
        _fail("C279_TARGET_NOT_UNIQUE")
    investigation_id = str(matches[0].get("investigation_id") or "").strip()
    if not investigation_id:
        _fail("C279_INVESTIGATION_ID_MISSING")

    investigation_health = _read_only_call(
        client,
        "get_investigation_health",
        {"investigation_id": investigation_id},
    )
    if (
        investigation_health.get("status") != "READY"
        or investigation_health.get("read_only") is not False
    ):
        _fail("C279_INVESTIGATION_NOT_READY")
    health_seq, health_hash = _tail(investigation_health)

    state = _read_only_call(
        client,
        "get_investigation_state",
        {"investigation_id": investigation_id},
    )
    state_seq, state_hash = _tail(state)
    if (
        str(state.get("investigation_id") or "") != investigation_id
        or str(state.get("account_id") or "") != TARGET_ACCOUNT_ID
        or (state_seq, state_hash) != (health_seq, health_hash)
    ):
        _fail("C279_TAIL_MISMATCH")

    claims = state.get("claims")
    company_route = claims.get("contact.company_route") if isinstance(claims, dict) else None
    if not isinstance(company_route, dict) or company_route.get("state") != "SUPPORTED":
        _fail("C279_PREPATCH_BASELINE_MISMATCH")

    readiness = _read_only_call(
        client,
        "evaluate_outreach_readiness",
        {"investigation_id": investigation_id},
    )
    blockers = readiness.get("block_reasons")
    if (
        str(readiness.get("investigation_id") or "") != investigation_id
        or readiness.get("outreach_readiness") != "IDENTITY_ONLY"
        or not isinstance(blockers, list)
        or "VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED" not in blockers
        or readiness.get("sends_message") is not False
    ):
        _fail("C279_PREPATCH_BASELINE_MISMATCH")

    identity = remote_health.get("deployment_identity")
    deployed_sha = str(identity.get("git_sha") or "").strip().lower() if isinstance(identity, dict) else ""
    return {
        "schema": SCHEMA,
        "status": "VERIFIED",
        "verified": True,
        "production_mutation_performed": False,
        "account_id": TARGET_ACCOUNT_ID,
        "investigation_id": investigation_id,
        "last_safe_seq": health_seq,
        "last_safe_event_hash": health_hash,
        "pre_patch_outreach_readiness": "IDENTITY_ONLY",
        "deployment_git_sha": deployed_sha,
    }


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run zero-mutation C279 production preflight")
    parser.add_argument("--expected-production-sha", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output)
    base_url = str(os.environ.get("CBI_V63_ACCEPTANCE_BASE_URL") or "").strip()
    bearer = str(os.environ.get("CBI_V63_ACCEPTANCE_BEARER_TOKEN") or "").strip()
    try:
        client = RenderR2AcceptanceClient(
            RenderR2AcceptanceClientConfig(
                base_url=base_url,
                bearer_token=bearer,
                expected_git_sha=args.expected_production_sha,
                timeout_seconds=30.0,
            )
        )
        receipt = run_preflight(client)
        _write_receipt(output, receipt)
        print("C279_ZERO_MUTATION_PREFLIGHT=VERIFIED")
        return 0
    except (PreflightError, RenderR2AcceptanceClientError) as exc:
        error_code = str(exc).split(":", 1)[0].strip() or "PREFLIGHT_FAILED"
        receipt = {
            "schema": SCHEMA,
            "status": "BLOCKED",
            "verified": False,
            "production_mutation_performed": False,
            "error_code": error_code,
        }
        try:
            _write_receipt(output, receipt)
        except OSError:
            pass
        print(f"C279 zero-mutation preflight blocked: {error_code}", file=sys.stderr)
        return 2
    except OSError:
        print("C279 zero-mutation preflight blocked: PREFLIGHT_OUTPUT_WRITE_FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
