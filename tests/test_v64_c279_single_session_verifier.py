from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from unified_runtime import UnifiedRuntime
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG
from scripts.verify_v64_c279_single_session import main, verify_single_session


ROOT = Path(__file__).resolve().parents[1]


def _observation(claim_key: str, index: int) -> dict:
    value: object = {"fixture": claim_key}
    if claim_key == "contact.named_route":
        value = {
            "channel": "EMAIL",
            "value": "buyer@example.invalid",
            "person_name": "Synthetic Decision Maker",
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "masked": False,
            "guessed": False,
        }
    elif claim_key == "contact.company_route":
        value = {
            "channel": "EMAIL",
            "value": "info@example.invalid",
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "masked": False,
            "guessed": False,
        }
    return {
        "claim_key": claim_key,
        "result": "POSITIVE",
        "owner_type": "ACCOUNT",
        "owner_id": "C-SINGLE-SESSION",
        "value": value,
        "source": {
            "source_family": "synthetic_single_session",
            "source_type": "OFFICIAL",
            "reference_type": "PUBLIC_URL",
            "url": f"https://example.invalid/single/{index}",
            "locator": f"https://example.invalid/single/{index}#fact",
            "raw_excerpt": f"Synthetic single-session fixture {index}",
            "authority_level": "A1_OFFICIAL_PRIMARY",
            "freshness": "CURRENT",
            "observed_at": "2026-09-05T00:00:00Z",
        },
        "boundary": "Synthetic test fixture only.",
    }


def _build_fixture(runtime: UnifiedRuntime) -> tuple[str, dict]:
    started = runtime.start_investigation({
        "account": {
            "account_id": "C-SINGLE-SESSION",
            "country": "Synthetic",
            "name": "Single Session Buyer",
        },
        "mode": "EXHAUSTIVE",
        "history": {"events": []},
        "priority_grade": "A",
    })
    investigation_id = started["investigation_id"]
    runtime.compile_and_append_research_bundle({
        "investigation_id": investigation_id,
        "bundle": {
            "bundle_id": "BUNDLE-SINGLE-SESSION",
            "observations": [
                _observation(claim_key, index)
                for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG)
            ],
        },
    })
    state = runtime.get_investigation_state({"investigation_id": investigation_id})
    bridge = {
        "investigation_id": investigation_id,
        "durable_state": {
            "last_safe_seq": state["last_safe_seq"],
            "last_safe_event_hash": state["last_safe_event_hash"],
        },
    }
    return investigation_id, bridge


def _run_cli(argv: list[str]) -> tuple[int, dict]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        return_code = main(argv)
    return return_code, json.loads(output.getvalue())


class V64C279SingleSessionVerifierTests(unittest.TestCase):
    def test_one_jsonl_is_sufficient_for_full_isolated_outreach_proof(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-single-test-") as temp:
            source_sessions = Path(temp) / "source" / "sessions"
            runtime = UnifiedRuntime(source_sessions)
            investigation_id, bridge = _build_fixture(runtime)
            source_jsonl = runtime.store.path(investigation_id)
            before = source_jsonl.read_bytes()

            receipt = verify_single_session(bridge=bridge, source_jsonl=source_jsonl)

            self.assertEqual(receipt["status"], "PASS")
            self.assertTrue(receipt["tail_match"])
            self.assertTrue(receipt["closure_closed"])
            self.assertTrue(receipt["prepared"])
            self.assertFalse(receipt["sends_message"])
            self.assertTrue(receipt["source_unchanged"])
            self.assertEqual(source_jsonl.read_bytes(), before)

    def test_direct_cli_help_runs_from_repository_root(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_v64_c279_single_session.py"),
                "--help",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--bridge", completed.stdout)
        self.assertIn("--source-session", completed.stdout)

    def test_cli_emits_only_sanitized_receipt_fields(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-single-cli-") as temp:
            root = Path(temp)
            runtime = UnifiedRuntime(root / "source" / "sessions")
            investigation_id, bridge = _build_fixture(runtime)
            source_jsonl = runtime.store.path(investigation_id)
            bridge_path = root / "bridge.json"
            bridge_path.write_text(json.dumps(bridge), encoding="utf-8")

            return_code, receipt = _run_cli([
                "--bridge", str(bridge_path),
                "--source-session", str(source_jsonl),
            ])

            self.assertEqual(return_code, 0)
            self.assertEqual(set(receipt), {
                "schema",
                "status",
                "tail_match",
                "outreach_readiness",
                "closure_closed",
                "prepared",
                "sends_message",
                "source_unchanged",
            })
            self.assertEqual(receipt["schema"], "cbi.v64-c279-single-session-proof.v1")
            serialized = json.dumps(receipt, sort_keys=True)
            self.assertNotIn(investigation_id, serialized)
            self.assertNotIn(str(source_jsonl), serialized)
            self.assertNotIn("buyer@example.invalid", serialized)
            self.assertNotIn("info@example.invalid", serialized)

    def test_cli_tail_mismatch_fails_closed_with_sanitized_blocker(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-single-cli-mismatch-") as temp:
            root = Path(temp)
            runtime = UnifiedRuntime(root / "source" / "sessions")
            investigation_id, bridge = _build_fixture(runtime)
            source_jsonl = runtime.store.path(investigation_id)
            bridge["durable_state"]["last_safe_event_hash"] = "0" * 64
            bridge_path = root / "bridge.json"
            bridge_path.write_text(json.dumps(bridge), encoding="utf-8")

            return_code, receipt = _run_cli([
                "--bridge", str(bridge_path),
                "--source-session", str(source_jsonl),
            ])

            self.assertEqual(return_code, 2)
            self.assertEqual(receipt, {
                "schema": "cbi.v64-c279-single-session-proof.v1",
                "status": "BLOCKED",
                "blocker": "AUTHORITATIVE_TAIL_MISMATCH",
            })
            serialized = json.dumps(receipt, sort_keys=True)
            self.assertNotIn(investigation_id, serialized)
            self.assertNotIn(str(source_jsonl), serialized)

    def test_cli_rejects_non_jsonl_source_without_opening_private_content(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-single-cli-suffix-") as temp:
            root = Path(temp)
            bridge_path = root / "bridge.json"
            bridge_path.write_text(json.dumps({
                "investigation_id": "INV-PRIVATE-SENTINEL",
                "durable_state": {
                    "last_safe_seq": 1,
                    "last_safe_event_hash": "1" * 64,
                },
            }), encoding="utf-8")
            source_path = root / "private-session.txt"
            source_path.write_text("PRIVATE-SENTINEL-CONTENT", encoding="utf-8")

            return_code, receipt = _run_cli([
                "--bridge", str(bridge_path),
                "--source-session", str(source_path),
            ])

            self.assertEqual(return_code, 2)
            self.assertEqual(receipt, {
                "schema": "cbi.v64-c279-single-session-proof.v1",
                "status": "BLOCKED",
                "blocker": "SOURCE_SESSION_JSONL_REQUIRED",
            })
            self.assertNotIn("PRIVATE-SENTINEL-CONTENT", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
