from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_peer_pivot_recovery.py"


class V61PeerPivotWalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-peer-pivot-wal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.host_root = self.root / "host-pending"
        self.processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._cleanup)
        self.runtime = UnifiedRuntime(self.session_root)
        self.start = self.runtime.start_investigation({
            "account": {
                "account_id": "C-PEER-PIVOT-WAL",
                "country": "Synthetic",
                "name": "Synthetic Peer Pivot WAL Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "A",
        })
        self.investigation_id = self.start["investigation_id"]

    def _env(self, crash_after_handler: str = "") -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.host_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if crash_after_handler:
            env["CBI_V61_TEST_CRASH_AFTER_HANDLER"] = crash_after_handler
        else:
            env.pop("CBI_V61_TEST_CRASH_AFTER_HANDLER", None)
        return env

    def _spawn(self, crash_after_handler: str = "") -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._env(crash_after_handler),
        )
        self.processes.append(process)
        self._rpc(process, 1, "initialize", {"protocolVersion": "2025-06-18"})
        return process

    @staticmethod
    def _rpc(
        process: subprocess.Popen[str],
        request_id: int,
        method: str,
        params: dict | None = None,
    ) -> dict:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }, ensure_ascii=True) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"server ended before response: {stderr}")
        return json.loads(line)

    def _tool(
        self,
        process: subprocess.Popen[str],
        request_id: int,
        name: str,
        arguments: dict,
    ) -> dict:
        response = self._rpc(
            process,
            request_id,
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if "error" in response:
            raise AssertionError(response["error"])
        return response["result"]["structuredContent"]

    @staticmethod
    def _crash_call(
        process: subprocess.Popen[str],
        request_id: int,
        name: str,
        arguments: dict,
    ) -> None:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, ensure_ascii=True) + "\n")
        process.stdin.flush()
        if process.stdout.readline() != "":
            raise AssertionError("crash-injected mutation unexpectedly returned")
        process.wait(timeout=10)
        if process.returncode != 91:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"unexpected crash code {process.returncode}: {stderr}")
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def _cleanup(self) -> None:
        for process in self.processes:
            self._stop(process)

    def _events(self) -> list[dict]:
        path = self.session_root / f"{self.investigation_id}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _observation(
        self,
        claim_key: str,
        suffix: str,
        *,
        owner_type: str = "ACCOUNT",
        owner_id: str = "C-PEER-PIVOT-WAL",
        network_branch: str = "",
        relationship_to_account: str = "",
        pivots: list[dict] | None = None,
    ) -> dict:
        row = {
            "claim_key": claim_key,
            "result": "POSITIVE",
            "owner_type": owner_type,
            "owner_id": owner_id,
            "value": {"fixture": suffix},
            "network_branch": network_branch,
            "source": {
                "source_family": "synthetic_official",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": f"https://evidence.example.invalid/{suffix}",
                "locator": f"https://evidence.example.invalid/{suffix}#fact",
                "raw_excerpt": f"Synthetic peer/pivot WAL fixture {suffix}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT",
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": "Synthetic WAL fixture only.",
            "pivots": pivots or [],
        }
        if relationship_to_account:
            row["relationship_to_account"] = relationship_to_account
        return row

    def _compile(self, rows: list[dict], bundle_id: str) -> dict:
        return self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": bundle_id, "observations": rows},
        })

    def _peer_discovery_args(self) -> tuple[dict, dict]:
        bundle = self._compile([
            self._observation(
                "relationship.supply_chain",
                "peer-discovery",
                network_branch="INDUSTRY_PEERS",
                relationship_to_account="INDUSTRY_PEER",
            )
        ], "BUNDLE-PEER-WAL-DISCOVERY")
        outcome = bundle["outcomes"][0]
        peer = {
            "name": "Synthetic WAL Peer",
            "country": "Synthetic",
            "network_branch": "INDUSTRY_PEERS",
            "discovered_by_observation_id": outcome["observation_id"],
            "relationship_evidence_ids": [outcome["evidence_id"]],
        }
        return peer, outcome

    def _discover_directly(self) -> tuple[dict, dict]:
        peer, outcome = self._peer_discovery_args()
        result = self.runtime.append_peer_discovery({
            "investigation_id": self.investigation_id,
            "peer": peer,
        })
        return result, outcome

    def _eligible_peer(self) -> tuple[dict, dict]:
        peer, discovery = self._discover_directly()
        peer_id = peer["peer_id"]
        bundle = self._compile([
            self._observation(
                "identity.legal_entity",
                "peer-entity",
                owner_type="PEER",
                owner_id=peer_id,
            ),
            self._observation(
                "product.fit",
                "peer-product",
                owner_type="PEER",
                owner_id=peer_id,
            ),
            self._observation(
                "trade.import_activity",
                "peer-trade",
                owner_type="PEER",
                owner_id=peer_id,
            ),
        ], "BUNDLE-PEER-WAL-FACTS")
        evidence = {
            "entity_verified": [bundle["outcomes"][0]["evidence_id"]],
            "product_fit_verified": [bundle["outcomes"][1]["evidence_id"]],
            "business_or_trade_verified": [bundle["outcomes"][2]["evidence_id"]],
            "relationship_verified": [discovery["evidence_id"]],
            "commercial_novelty": [
                bundle["outcomes"][1]["evidence_id"],
                bundle["outcomes"][2]["evidence_id"],
            ],
        }
        assessment = {
            "entity_verified": True,
            "product_fit_verified": True,
            "business_or_trade_verified": True,
            "relationship_verified": True,
            "commercial_novelty": True,
            "canonical_new": True,
            "fact_evidence_ids": evidence,
            "commercial_novelty_basis": (
                "Independent synthetic product and trade evidence supports a distinct anchor candidate."
            ),
        }
        return peer, assessment

    def test_contract_exposes_peer_pivot_recovery(self) -> None:
        process = self._spawn()
        contract = self._tool(process, 2, "get_runtime_contract", {})
        wal = contract["production_adapter_mutation_wal"]
        recovery = wal["peer_pivot_lifecycle_recovery"]
        expected = {
            "append_peer_discovery",
            "evaluate_peer",
            "promote_anchor",
            "close_pivot",
        }
        self.assertEqual(set(recovery["tools"]), expected)
        self.assertTrue(recovery["requires_exact_event_correlation"])
        self.assertFalse(recovery["reexecutes_side_effect"])
        self.assertTrue(expected.issubset(set(wal["automatic_reconciliation_tools"])))
        health = self._tool(process, 3, "get_runtime_health", {})
        self.assertEqual(health["peer_pivot_lifecycle_recovery"]["status"], "ENABLED")

    def test_peer_discovery_crash_recovers_exact_event_without_duplicate(self) -> None:
        peer, _ = self._peer_discovery_args()
        arguments = {
            "investigation_id": self.investigation_id,
            "peer": peer,
            "idempotency_key": "peer-discovery-crash-0001",
        }
        crashing = self._spawn("append_peer_discovery")
        self._crash_call(crashing, 2, "append_peer_discovery", arguments)
        events = [e for e in self._events() if e["event_type"] == "V6_PEER_DISCOVERED"]
        self.assertEqual(len(events), 1)
        process = self._spawn()
        recovered = self._tool(process, 3, "append_peer_discovery", arguments)
        self.assertEqual(recovered["peer_id"], events[0]["payload"]["peer_id"])
        self.assertEqual(recovered["stage"], "DISCOVERED")
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        replayed = self._tool(process, 4, "append_peer_discovery", arguments)
        self.assertTrue(replayed["mutation_meta"]["replayed"])
        self.assertEqual(
            sum(e["event_type"] == "V6_PEER_DISCOVERED" for e in self._events()),
            1,
        )

    def test_peer_evaluation_crash_recovers_exact_stage_without_duplicate(self) -> None:
        peer, assessment = self._eligible_peer()
        arguments = {
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": assessment,
            "idempotency_key": "peer-evaluation-crash-0001",
        }
        crashing = self._spawn("evaluate_peer")
        self._crash_call(crashing, 2, "evaluate_peer", arguments)
        events = [e for e in self._events() if e["event_type"] == "V6_PEER_EVALUATED"]
        self.assertEqual(len(events), 1)
        process = self._spawn()
        recovered = self._tool(process, 3, "evaluate_peer", arguments)
        self.assertEqual(recovered["peer_id"], peer["peer_id"])
        self.assertEqual(recovered["stage"], events[0]["payload"]["stage"])
        self.assertEqual(recovered["stage"], "ANCHOR_ELIGIBLE")
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            sum(e["event_type"] == "V6_PEER_EVALUATED" for e in self._events()),
            1,
        )

    def test_anchor_promotion_crash_recovers_exact_event_without_duplicate(self) -> None:
        peer, assessment = self._eligible_peer()
        evaluated = self.runtime.evaluate_peer({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": assessment,
        })
        self.assertEqual(evaluated["stage"], "ANCHOR_ELIGIBLE")
        arguments = {
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "promotion_reason": "Synthetic WAL promotion fixture.",
            "idempotency_key": "anchor-promotion-crash-0001",
        }
        crashing = self._spawn("promote_anchor")
        self._crash_call(crashing, 2, "promote_anchor", arguments)
        events = [e for e in self._events() if e["event_type"] == "V6_ANCHOR_PROMOTED"]
        self.assertEqual(len(events), 1)
        process = self._spawn()
        recovered = self._tool(process, 3, "promote_anchor", arguments)
        self.assertEqual(recovered["stage"], "PROMOTED_ANCHOR")
        self.assertEqual(recovered["promotion_reason"], arguments["promotion_reason"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            sum(e["event_type"] == "V6_ANCHOR_PROMOTED" for e in self._events()),
            1,
        )

    def test_pivot_close_crash_recovers_exact_terminal_event_without_duplicate(self) -> None:
        bundle = self._compile([
            self._observation(
                "identity.legal_entity",
                "pivot-source",
                pivots=[{
                    "type": "ALIAS",
                    "value": "Synthetic WAL Alias",
                    "materiality": "MATERIAL",
                    "estimated_eiv": 9.0,
                }],
            )
        ], "BUNDLE-PIVOT-WAL")
        self.assertEqual(bundle["rejected_count"], 0)
        pivot = self.runtime.get_material_pivots({
            "investigation_id": self.investigation_id,
        })["material_pivots"][0]
        objective = self.runtime.submit_research_objective({
            "investigation_id": self.investigation_id,
            "objective": {
                "claim_key": "identity.legal_entity",
                "query_or_navigation": "Synthetic WAL Alias official registry",
                "source_family": "official_registry",
            },
        })
        arguments = {
            "investigation_id": self.investigation_id,
            "pivot_id": pivot["pivot_id"],
            "status": "CONSUMED",
            "reason": "Consumed by the exact later synthetic objective.",
            "consumed_by_objective_id": objective["objective_id"],
            "idempotency_key": "pivot-close-crash-0001",
        }
        crashing = self._spawn("close_pivot")
        self._crash_call(crashing, 2, "close_pivot", arguments)
        events = [e for e in self._events() if e["event_type"] == "V6_PIVOT_CLOSED"]
        self.assertEqual(len(events), 1)
        process = self._spawn()
        recovered = self._tool(process, 3, "close_pivot", arguments)
        self.assertEqual(recovered["pivot_id"], pivot["pivot_id"])
        self.assertEqual(recovered["status"], "CONSUMED")
        self.assertEqual(recovered["consumed_by_objective_id"], objective["objective_id"])
        self.assertTrue(recovered["mutation_meta"]["reconciled_after_crash"])
        self.assertEqual(
            sum(e["event_type"] == "V6_PIVOT_CLOSED" for e in self._events()),
            1,
        )


if __name__ == "__main__":
    unittest.main()
