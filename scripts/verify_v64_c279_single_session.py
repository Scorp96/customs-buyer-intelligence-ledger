#!/usr/bin/env python3
"""Isolated single-session verifier for the CBI v6.4 C279 release gate.

This module never mutates the supplied source JSONL. It copies exactly one
committed session into a temporary root, runs the current Runtime only against
that copy, and returns sanitized proof fields.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_runtime import UnifiedRuntime


SAFE_FIRST_TOUCH_BODY = (
    "Hello, I’m contacting your company from XingHuai New Materials. We manufacture PVC foam board "
    "and related rigid panel materials for distribution, cabinetry, interior fabrication, signage and "
    "general sheet applications. I would like to understand whether your purchasing team is open to "
    "evaluating an additional qualified supply source. We can provide a concise product overview and "
    "then prepare technical information only against requirements that your team confirms. Could you "
    "please direct this message to the colleague responsible for purchasing or sourcing sheet materials? "
    "If this category is not relevant, no further action is needed. Best regards, Mark Zhou"
)


def verify_single_session(*, bridge: dict, source_jsonl: Path) -> dict[str, object]:
    """Verify one committed session by operating only on an isolated copy."""

    investigation_id = str(bridge["investigation_id"])
    expected = dict(bridge["durable_state"])
    source_jsonl = Path(source_jsonl)
    if source_jsonl.name != f"{investigation_id}.jsonl":
        raise AssertionError("source session filename does not match bridge")

    source_before = source_jsonl.read_bytes()
    with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-single-") as temp:
        sessions = Path(temp) / "sessions"
        sessions.mkdir(parents=True)
        isolated_jsonl = sessions / source_jsonl.name
        isolated_jsonl.write_bytes(source_before)

        runtime = UnifiedRuntime(sessions)
        state = runtime.get_investigation_state({"investigation_id": investigation_id})
        tail_match = (
            state["last_safe_seq"] == int(expected["last_safe_seq"])
            and state["last_safe_event_hash"] == str(expected["last_safe_event_hash"])
        )
        if not tail_match:
            raise AssertionError("authoritative tail commitment mismatch")

        readiness = runtime.evaluate_outreach_readiness({"investigation_id": investigation_id})
        routes = [
            row
            for row in readiness.get("canonical_route_view", [])
            if isinstance(row, dict)
        ]
        if not routes:
            raise AssertionError("canonical route unavailable")

        closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
        if not closure.get("closed"):
            raise AssertionError("investigation did not close on isolated copy")

        start = runtime._v6_state(investigation_id)["start"]
        prepared = runtime.prepare_outreach({
            "investigation_id": investigation_id,
            "closure_id": closure["closure_id"],
            "route": routes[0],
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
            raise AssertionError(
                "synthetic prepare_outreach blocked: "
                + ",".join(str(item) for item in prepared.get("block_reasons", []))
            )

    source_after = source_jsonl.read_bytes()
    return {
        "status": "PASS",
        "tail_match": True,
        "outreach_readiness": (
            readiness.get("outreach_readiness") or readiness.get("readiness")
        ),
        "closure_closed": bool(closure.get("closed")),
        "prepared": bool(prepared.get("prepared")),
        "sends_message": bool(prepared.get("sends_message")),
        "source_unchanged": source_before == source_after,
    }
