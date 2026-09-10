#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.discover_v64_positive_route_candidate import _mcp, sanitize_health

BASE_URL = "https://cbi-v61-preview.onrender.com"
PRODUCTION_SHA = "6b0fc38466b6e96e228ae081651789a929455bbe"
CANDIDATE_SHA = "7222fa19c1bace68b0ad4c44a707298966bf15e1"
INVESTIGATION_ID = "INV-20260909T022542Z-a0294bced6ca"
TAIL_SEQ = 25
TAIL_HASH = "bca8826e3e041b3604d31c27754f54429a213a24cfc0849b0a7f9aae1593580d"


def health(bearer: str, serial: int) -> dict[str, object]:
    with urllib.request.urlopen(BASE_URL + "/healthz", timeout=60) as response:
        public = json.load(response)
    runtime = _mcp(BASE_URL, bearer, serial, "get_runtime_health", {})
    return sanitize_health(public, runtime)


def main() -> int:
    bearer = os.environ.get("CBI_V64_DISCOVERY_BEARER", "").strip()
    if not bearer:
        raise SystemExit("POSITIVE_ACCEPTANCE_BEARER_MISSING")
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    root = runner_temp / "cbi-v64-final-positive"
    artifact = root / "artifact"
    source_root = root / "source-runtime"
    session_dir = source_root / "sessions"
    artifact.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = artifact / "positive-authoritative-receipt.json"
    bridge_path = root / "bridge.json"
    diagnostics_path = root / "diagnostics.json"
    test_log_path = root / "test-output.txt"
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    source_sha = ""
    failure_stage = "BEFORE_HEALTH"
    reason_codes: list[str] = []
    diagnostics: dict[str, object] = {}
    test_outcome = "not_run"
    verified = False
    try:
        before = health(bearer, 1)
        assert before["status"] == "ok"
        assert before["git_sha"] == PRODUCTION_SHA
        assert before["runtime_ready"] is True
        assert before["wal_prepared_count"] == 0
        assert before["wal_invalid_count"] == 0
        assert before["wal_reconciliation_required"] is False

        failure_stage = "EXACT_SESSION_CAPTURE"
        captured = _mcp(
            BASE_URL,
            bearer,
            2,
            "capture_authoritative_source_evidence",
            {
                "operation": "EXACT_SESSION_CAPTURE",
                "investigation_id": INVESTIGATION_ID,
                "expected_last_safe_seq": TAIL_SEQ,
                "expected_last_safe_event_hash": TAIL_HASH,
                "acknowledge_private_state": True,
            },
        )
        assert isinstance(captured, dict)
        assert captured.get("schema") == "cbi.v64-authoritative-single-session-capture.v1"
        assert captured.get("investigation_id") == INVESTIGATION_ID
        assert captured.get("last_safe_seq") == TAIL_SEQ
        assert captured.get("last_safe_event_hash") == TAIL_HASH
        assert captured.get("source_stable_through_capture") is True
        assert captured.get("production_write_performed") is False
        payload = base64.b64decode(str(captured.get("payload_base64") or ""), validate=True)
        source_sha = hashlib.sha256(payload).hexdigest()
        assert source_sha == captured.get("payload_sha256")
        session_path = session_dir / f"{INVESTIGATION_ID}.jsonl"
        session_path.write_bytes(payload)

        bridge = {
            "schema": "cbi.v64-positive-route-authoritative-bridge.v1",
            "investigation_id": INVESTIGATION_ID,
            "durable_state": {
                "last_safe_seq": TAIL_SEQ,
                "last_safe_event_hash": TAIL_HASH,
            },
            "acceptance_case": {
                "schema": "cbi.v64-authoritative-acceptance-case.v1",
                "case_kind": "POSITIVE_ROUTE",
                "sends_message": False,
            },
        }
        bridge_path.write_text(json.dumps(bridge, sort_keys=True), encoding="utf-8")

        failure_stage = "ISOLATED_FULL_RUNTIME"
        env = dict(os.environ)
        env["CBI_V64_POSITIVE_BRIDGE_EVIDENCE"] = str(bridge_path)
        env["CBI_V64_POSITIVE_SOURCE_RUNTIME_ROOT"] = str(source_root)
        env["CBI_V64_POSITIVE_ROUTE_DIAGNOSTICS"] = str(diagnostics_path)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_v64_c279_full_runtime.V64C279FullRuntimeRegression.test_positive_route_authoritative_case_full_runtime",
                "-v",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=300,
        )
        test_log_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
        test_outcome = "success" if completed.returncode == 0 else "failure"
        assert completed.returncode == 0
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        acceptance = diagnostics.get("acceptance_case") or {}
        assert isinstance(acceptance, dict)
        assert acceptance.get("case_kind") == "POSITIVE_ROUTE"
        assert acceptance.get("status") == "ACCEPTANCE_CASE_VERIFIED"
        assert acceptance.get("sends_message") is False
        precondition = diagnostics.get("positive_route_precondition") or {}
        assert isinstance(precondition, dict)
        assert int(precondition.get("fully_qualified_route_count") or 0) >= 1
        assert int(precondition.get("named_qualified_route_count") or 0) >= 1
        closure_gate = diagnostics.get("isolated_closure_gate") or {}
        assert isinstance(closure_gate, dict) and closure_gate.get("closure_eligible") is True
        route_diag = diagnostics.get("route_projection_diagnostics") or {}
        assert isinstance(route_diag, dict) and route_diag.get("contains_route_values") is False
        assert hashlib.sha256(session_path.read_bytes()).hexdigest() == source_sha

        failure_stage = "AFTER_HEALTH"
        after = health(bearer, 3)
        assert after == before
        verified = True
        failure_stage = ""
    except Exception as exc:
        code = type(exc).__name__.upper()
        reason_codes = ["POSITIVE_AUTHORITATIVE_" + code]
        try:
            after = health(bearer, 99)
        except Exception:
            after = {}
    finally:
        if source_root.exists():
            shutil.rmtree(source_root)
        for path in (bridge_path, diagnostics_path, test_log_path):
            path.unlink(missing_ok=True)

    receipt = {
        "schema": "cbi.v64-final-positive-authoritative.v1",
        "verified": verified,
        "candidate_runtime_sha": CANDIDATE_SHA,
        "production_source_sha": PRODUCTION_SHA,
        "investigation_id": INVESTIGATION_ID,
        "last_safe_seq": TAIL_SEQ,
        "last_safe_event_hash": TAIL_HASH,
        "source_snapshot_sha256": source_sha,
        "full_runtime_outcome": test_outcome,
        "source_runtime_mutation_detected": False,
        "plaintext_artifact_retained": False,
        "sends_message": False,
        "failure_stage": failure_stage or None,
        "reason_codes": reason_codes,
        "production_before": before,
        "production_after": after,
        "diagnostics": diagnostics,
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("POSITIVE_AUTHORITATIVE_VERIFIED=" + ("true" if verified else "false"))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
