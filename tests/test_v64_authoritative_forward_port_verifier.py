from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_v64_authoritative_forward_port.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("v64_authoritative_forward_port", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("verifier module spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V64AuthoritativeForwardPortVerifierTests(unittest.TestCase):
    def _bridge(self, investigation_id: str = "INV-TEST") -> dict:
        return {
            "schema": "cbi.v64-c279-authoritative-regression-bridge.v1",
            "investigation_id": investigation_id,
            "durable_state": {
                "last_safe_seq": 2,
                "last_safe_event_hash": "b" * 64,
            },
            "pre_patch": {
                "outreach_readiness": "IDENTITY_ONLY",
                "block_reasons": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            },
            "post_patch_expectation": {
                "minimum_outreach_readiness": "COMPANY_ROUTE_READY",
                "prepare_outreach_succeeds": True,
                "sends_message": False,
            },
        }

    def _source_root(self, root: Path, bridge: dict, *, hash_value: str | None = None) -> Path:
        source = root / "runtime"
        sessions = source / "sessions"
        sessions.mkdir(parents=True)
        event_hash = hash_value or bridge["durable_state"]["last_safe_event_hash"]
        session = sessions / f"{bridge['investigation_id']}.jsonl"
        rows = [
            {"seq": 1, "event_hash": "a" * 64},
            {"seq": 2, "event_hash": event_hash},
        ]
        session.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return source

    def test_semantic_forward_port_does_not_replay_stale_stream_b_patch(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("CBI_v64_backup_retention_payload_ownership_wave2_4.patch", text)
        self.assertNotIn('"git", "am"', text)
        self.assertNotIn("--apply-patches", text)

    def test_bridge_schema_and_expectations_fail_closed(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bridge.json"
            bad = self._bridge()
            bad["schema"] = "wrong"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "C279_BRIDGE_SCHEMA_INVALID"):
                verifier.load_c279_bridge(path)

            bad = self._bridge()
            bad["post_patch_expectation"]["sends_message"] = True
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "C279_BRIDGE_EXPECTATION_INVALID"):
                verifier.load_c279_bridge(path)

    def test_source_tail_is_bound_to_private_bridge(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bridge = self._bridge()
            bridge_path = root / "bridge.json"
            bridge_path.write_text(json.dumps(bridge), encoding="utf-8")
            source = self._source_root(root, bridge)
            loaded = verifier.load_c279_bridge(bridge_path)
            summary = verifier.verify_c279_source_tail(source, loaded)
            self.assertEqual(summary["session_sha256"], verifier._sha256_file(source / "sessions" / "INV-TEST.jsonl"))
            self.assertEqual(summary["bridge_sha256"], verifier._sha256_file(bridge_path))
            self.assertNotIn("source_root", summary)
            self.assertNotIn("investigation_id", summary)

    def test_source_tail_mismatch_blocks(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bridge = self._bridge()
            source = self._source_root(root, bridge, hash_value="c" * 64)
            bridge_path = root / "bridge.json"
            bridge_path.write_text(json.dumps(bridge), encoding="utf-8")
            loaded = verifier.load_c279_bridge(bridge_path)
            with self.assertRaisesRegex(verifier.VerificationError, "C279_SOURCE_EVENT_HASH_MISMATCH"):
                verifier.verify_c279_source_tail(source, loaded)

    def test_c279_gate_requires_readiness_prepare_and_isolation(self):
        verifier = load_verifier()
        path = verifier.require_c279_integration_test(ROOT)
        text = path.read_text(encoding="utf-8")
        self.assertIn("TemporaryDirectory", text)
        self.assertIn("copytree", text)
        self.assertIn("evaluate_outreach_readiness", text)
        self.assertIn("prepare_outreach", text)
        self.assertIn("sends_message", text)

    def test_verification_command_contract_and_private_env_scope(self):
        verifier = load_verifier()
        commands = verifier.build_verification_commands("PYTHON")
        names = [row["name"] for row in commands]
        self.assertEqual(
            names,
            [
                "canonical-route-prepare",
                "c279-full-runtime",
                "mro-owner",
                "v6-protocol",
                "v61-protocol",
                "full-unittest-suite",
            ],
        )
        c279 = next(row for row in commands if row["name"] == "c279-full-runtime")
        self.assertTrue(c279["private_c279_env"])
        for row in commands:
            if row["name"] != "c279-full-runtime":
                self.assertFalse(row["private_c279_env"], row)
        full = next(row for row in commands if row["name"] == "full-unittest-suite")
        self.assertIn("test_*.py", full["argv"])

    def test_remote_refs_must_be_distinct_origin_refs(self):
        verifier = load_verifier()
        self.assertEqual(
            verifier.validate_remote_refs("origin/source", "origin/production"),
            {"source_ref": "origin/source", "production_ref": "origin/production"},
        )
        for source, production in [
            ("source", "origin/prod"),
            ("origin/source", "prod"),
            ("origin/source", "origin/source"),
            ("origin/../source", "origin/prod"),
        ]:
            with self.assertRaises(verifier.VerificationError):
                verifier.validate_remote_refs(source, production)

    def test_report_never_persists_private_paths_or_raw_bridge_values(self):
        verifier = load_verifier()
        report = verifier.build_public_report(
            checkout={"branch": "feature", "head": "d" * 40, "source_sha": "e" * 40, "production_sha": "f" * 40},
            source_binding={"bridge_sha256": "1" * 64, "session_sha256": "2" * 64},
            gate_results=[{"name": "c279-full-runtime", "returncode": 0}],
            verified=True,
        )
        encoded = json.dumps(report, sort_keys=True)
        self.assertNotIn("INV-", encoded)
        self.assertNotIn("source_root", encoded)
        self.assertNotIn("bridge_path", encoded)
        self.assertTrue(report["verified"])


if __name__ == "__main__":
    unittest.main()
