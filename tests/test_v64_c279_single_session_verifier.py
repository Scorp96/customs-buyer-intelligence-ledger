from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from unified_runtime import UnifiedRuntime
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG
from scripts.verify_v64_c279_single_session import verify_single_session


def _observation(claim_key: str, index: int) -> dict:
    value: object = {"fixture": claim_key}
    if claim_key == "contact.company_route":
        value = {
            "channel": "EMAIL",
            "value": "buyer@example.invalid",
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


if __name__ == "__main__":
    unittest.main()
