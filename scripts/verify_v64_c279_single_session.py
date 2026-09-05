#!/usr/bin/env python3
"""Isolated single-session verifier for the CBI v6.4 C279 release gate.

This module never mutates the supplied source JSONL. It copies exactly one
committed session into a temporary root, runs the current Runtime only against
that copy, and emits only sanitized proof fields.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from unified_runtime import UnifiedRuntime


PROOF_SCHEMA = "cbi.v64-c279-single-session-proof.v1"

SAFE_FIRST_TOUCH_BODY = (
    "Hello, I’m contacting your company from XingHuai New Materials. We manufacture PVC foam board "
    "and related rigid panel materials for distribution, cabinetry, interior fabrication, signage and "
    "general sheet applications. I would like to understand whether your purchasing team is open to "
    "evaluating an additional qualified supply source. We can provide a concise product overview and "
    "then prepare technical information only against requirements that your team confirms. Could you "
    "please direct this message to the colleague responsible for purchasing or sourcing sheet materials? "
    "If this category is not relevant, no further action is needed. Best regards, Mark Zhou"
)


class VerificationError(RuntimeError):
    """Fail-closed verification error carrying only a stable sanitized code."""


def _require_bridge_shape(bridge: object) -> tuple[str, dict[str, object]]:
    if not isinstance(bridge, dict):
        raise VerificationError("BRIDGE_EVIDENCE_INVALID")
    investigation_id = str(bridge.get("investigation_id") or "").strip()
    durable = bridge.get("durable_state")
    if not investigation_id or not isinstance(durable, dict):
        raise VerificationError("BRIDGE_EVIDENCE_INVALID")
    try:
        last_safe_seq = int(durable["last_safe_seq"])
        last_safe_hash = str(durable["last_safe_event_hash"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError("BRIDGE_EVIDENCE_INVALID") from exc
    if last_safe_seq < 0 or len(last_safe_hash) != 64:
        raise VerificationError("BRIDGE_EVIDENCE_INVALID")
    if any(ch not in "0123456789abcdefABCDEF" for ch in last_safe_hash):
        raise VerificationError("BRIDGE_EVIDENCE_INVALID")
    return investigation_id, {
        "last_safe_seq": last_safe_seq,
        "last_safe_event_hash": last_safe_hash,
    }


def _select_route(bridge: dict, routes: list[dict]) -> dict:
    named_ids = {
        str(item)
        for item in dict(bridge.get("named_route") or {}).get("observation_ids", [])
        if str(item).strip()
    }
    if named_ids:
        named = next(
            (
                row
                for row in routes
                if str(row.get("observation_id") or "") in named_ids
            ),
            None,
        )
        if named is not None:
            return named
    return routes[0]


def verify_single_session(*, bridge: dict, source_jsonl: Path) -> dict[str, object]:
    """Verify one committed session by operating only on an isolated copy."""

    investigation_id, expected = _require_bridge_shape(bridge)
    source_jsonl = Path(source_jsonl)
    if source_jsonl.suffix.lower() != ".jsonl":
        raise VerificationError("SOURCE_SESSION_JSONL_REQUIRED")
    if not source_jsonl.is_file():
        raise VerificationError("SOURCE_SESSION_REQUIRED")
    if source_jsonl.name != f"{investigation_id}.jsonl":
        raise VerificationError("SOURCE_SESSION_FILENAME_MISMATCH")

    source_before = source_jsonl.read_bytes()
    pending_error: Exception | None = None
    readiness: dict = {}
    closure: dict = {}
    prepared: dict = {}
    try:
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-single-") as temp:
            sessions = Path(temp) / "sessions"
            sessions.mkdir(parents=True)
            isolated_jsonl = sessions / source_jsonl.name
            isolated_jsonl.write_bytes(source_before)

            runtime = UnifiedRuntime(sessions)
            state = runtime.get_investigation_state({"investigation_id": investigation_id})
            tail_match = (
                state["last_safe_seq"] == expected["last_safe_seq"]
                and state["last_safe_event_hash"] == expected["last_safe_event_hash"]
            )
            if not tail_match:
                raise VerificationError("AUTHORITATIVE_TAIL_MISMATCH")

            readiness = runtime.evaluate_outreach_readiness({"investigation_id": investigation_id})
            routes = [
                row
                for row in readiness.get("canonical_route_view", [])
                if isinstance(row, dict)
            ]
            if not routes:
                raise VerificationError("CANONICAL_ROUTE_UNAVAILABLE")
            route = _select_route(bridge, routes)

            closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
            if not closure.get("closed") or not closure.get("closure_id"):
                raise VerificationError("ISOLATED_CLOSURE_REQUIRED")

            start = runtime._v6_state(investigation_id)["start"]
            prepared = runtime.prepare_outreach({
                "investigation_id": investigation_id,
                "closure_id": closure["closure_id"],
                "route": route,
                "history_digest": start.get("history_digest"),
                "authority_digest": start.get("authority_digest"),
                "subject": "PVC sheet sourcing contact",
                "body": SAFE_FIRST_TOUCH_BODY,
                "stage": "FIRST_TOUCH",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=15)
                ).isoformat().replace("+00:00", "Z"),
            })
            if not prepared.get("prepared"):
                raise VerificationError("ISOLATED_PREPARE_OUTREACH_BLOCKED")
    except Exception as exc:
        pending_error = exc

    source_after = source_jsonl.read_bytes()
    if source_after != source_before:
        raise VerificationError("SOURCE_SESSION_MUTATED")
    if pending_error is not None:
        raise pending_error
    if bool(prepared.get("sends_message")):
        raise VerificationError("SEND_SIDE_EFFECT_FORBIDDEN")

    return {
        "schema": PROOF_SCHEMA,
        "status": "PASS",
        "tail_match": True,
        "outreach_readiness": (
            readiness.get("outreach_readiness") or readiness.get("readiness")
        ),
        "closure_closed": bool(closure.get("closed")),
        "prepared": bool(prepared.get("prepared")),
        "sends_message": False,
        "source_unchanged": True,
    }


def _blocked(blocker: str) -> dict[str, str]:
    return {
        "schema": PROOF_SCHEMA,
        "status": "BLOCKED",
        "blocker": blocker,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the CBI v6.4 C279 verifier against one isolated session JSONL."
    )
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--source-session", required=True)
    args = parser.parse_args(argv)

    source_jsonl = Path(args.source_session).expanduser()
    if source_jsonl.suffix.lower() != ".jsonl":
        print(json.dumps(_blocked("SOURCE_SESSION_JSONL_REQUIRED"), sort_keys=True))
        return 2

    try:
        bridge_path = Path(args.bridge).expanduser()
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
        receipt = verify_single_session(bridge=bridge, source_jsonl=source_jsonl)
    except VerificationError as exc:
        blocker = str(exc) if str(exc) else "VERIFICATION_FAILED"
        print(json.dumps(_blocked(blocker), sort_keys=True))
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        print(json.dumps(_blocked("BRIDGE_EVIDENCE_INVALID"), sort_keys=True))
        return 2
    except Exception:
        print(json.dumps(_blocked("VERIFICATION_FAILED"), sort_keys=True))
        return 2

    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
