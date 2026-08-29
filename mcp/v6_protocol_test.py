#!/usr/bin/env python3
"""Cold-process MCP coverage for every v6-native tool route."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SERVER = Path(__file__).with_name("server.py")
CLAIMS = (
    "identity.legal_entity",
    "identity.ultimate_buyer",
    "product.fit",
    "trade.import_activity",
    "company.operating_status",
    "commercial.procurement_need",
    "relationship.supply_chain",
    "buying_group.decision_chain",
    "contact.company_route",
    "contact.named_route",
    "outreach.route_safety",
)
BRANCHES = (
    "REGIONAL_PEERS",
    "INDUSTRY_PEERS",
    "SCALE_PEERS",
    "SAME_SUPPLIER_BUYERS",
    "SAME_PRODUCT_HS_APPLICATION_BUYERS",
    "COMPETING_SUPPLIERS_AND_SUBSTITUTES",
)


def rpc(process: subprocess.Popen[str], request_id: int, method: str, params: dict | None = None) -> dict:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, ensure_ascii=True) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("MCP server ended unexpectedly")
    return json.loads(line)


def tool(process: subprocess.Popen[str], request_id: int, name: str, arguments: dict) -> dict:
    response = rpc(process, request_id, "tools/call", {"name": name, "arguments": arguments})
    if "error" in response:
        raise RuntimeError(f"{name}: {response['error']['message']}")
    return response["result"]["structuredContent"]


def expect_invalid(process: subprocess.Popen[str], request_id: int, name: str) -> None:
    response = rpc(process, request_id, "tools/call", {"name": name, "arguments": {}})
    if "error" not in response:
        raise AssertionError(f"{name}: empty invalid input was accepted")


def main() -> int:
    passed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cbi-v6-mcp-") as temp:
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
            assert len(listed) == 42
            passed.extend(["initialize_v6", "tools_list_42"])

            started = tool(process, 3, "start_investigation", {
                "account": {"account_id": "C-MCP-V6-SYNTH", "country": "Synthetic", "name": "Synthetic MCP v6 Buyer"},
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
                "priority_grade": "A",
            })
            investigation_id = started["investigation_id"]
            passed.append("start_investigation_v6")

            observations = []
            for index, claim in enumerate(CLAIMS):
                value: object = {"fixture": claim}
                if claim == "contact.named_route":
                    value = {
                        "channel": "EMAIL", "value": "buyer@example.invalid", "person_name": "Synthetic Person",
                        "verified": True, "current": True, "owned_by_account": True, "masked": False, "guessed": False,
                    }
                elif claim == "contact.company_route":
                    value = {
                        "channel": "EMAIL", "value": "info@example.invalid",
                        "verified": True, "current": True, "owned_by_account": True, "masked": False, "guessed": False,
                    }
                row = {
                    "claim_key": claim,
                    "result": "POSITIVE",
                    "value": value,
                    "source": {
                        "source_family": "synthetic_official",
                        "source_type": "OFFICIAL",
                        "reference_type": "PUBLIC_URL",
                        "url": f"https://example.invalid/mcp-v6/{index}",
                        "locator": f"https://example.invalid/mcp-v6/{index}#record",
                        "raw_excerpt": f"Synthetic MCP v6 evidence {index}",
                        "authority_level": "A1_OFFICIAL_PRIMARY",
                        "freshness": "CURRENT",
                        "observed_at": "2026-08-28T00:00:00Z",
                    },
                    "boundary": "Synthetic protocol fixture only.",
                }
                if claim == "relationship.supply_chain":
                    row["network_branch"] = "INDUSTRY_PEERS"
                    row["pivots"] = [{
                        "type": "ALIAS", "value": "Synthetic Alias", "materiality": "MATERIAL", "estimated_eiv": 2.0,
                    }]
                observations.append(row)
            compiled = tool(process, 4, "compile_and_append_research_bundle", {
                "investigation_id": investigation_id,
                "bundle": {"bundle_id": "BUNDLE-MCP-V6", "observations": observations},
            })
            assert compiled["accepted_count"] == len(CLAIMS)
            passed.append("compile_bundle_v6")

            calls = [
                ("get_runtime_contract", {}),
                ("get_runtime_health", {"investigation_id": investigation_id}),
                ("get_investigation_health", {"investigation_id": investigation_id}),
                ("resume_investigation", {"investigation_id": investigation_id}),
                ("get_claims", {"investigation_id": investigation_id}),
                ("get_account_state", {"investigation_id": investigation_id}),
                ("get_investigation_state", {"investigation_id": investigation_id}),
                ("get_next_research_objectives", {"investigation_id": investigation_id, "limit": 10}),
                ("get_portfolio_queue", {"limit": 10}),
                ("get_material_pivots", {"investigation_id": investigation_id}),
                ("evaluate_commercial_value", {"investigation_id": investigation_id}),
                ("evaluate_research_confidence", {"investigation_id": investigation_id}),
                ("evaluate_outreach_readiness", {"investigation_id": investigation_id}),
                ("evaluate_decision_saturation", {"investigation_id": investigation_id}),
                ("prepare_crm_writeback", {
                    "investigation_id": investigation_id,
                    "target_workbook_path": str(root / "synthetic-production.xlsx"),
                    "records": [],
                }),
            ]
            request_id = 10
            for name, arguments in calls:
                tool(process, request_id, name, arguments)
                passed.append(name)
                request_id += 1

            objective = tool(process, 30, "submit_research_objective", {
                "investigation_id": investigation_id,
                "objective": {
                    "claim_key": "relationship.supply_chain",
                    "query_or_navigation": "Synthetic Alias official relationship",
                    "source_family": "synthetic_official",
                },
            })
            pivot = tool(process, 31, "get_material_pivots", {"investigation_id": investigation_id})["material_pivots"][0]
            tool(process, 32, "close_pivot", {
                "investigation_id": investigation_id,
                "pivot_id": pivot["pivot_id"],
                "status": "CONSUMED",
                "reason": "Consumed in a later protocol-test objective.",
                "consumed_by_objective_id": objective["objective_id"],
            })
            passed.extend(["submit_research_objective", "close_pivot"])

            relationship = compiled["outcomes"][CLAIMS.index("relationship.supply_chain")]
            peer = tool(process, 33, "append_peer_discovery", {
                "investigation_id": investigation_id,
                "peer": {
                    "name": "Synthetic MCP Peer",
                    "country": "Synthetic",
                    "network_branch": "INDUSTRY_PEERS",
                    "discovered_by_observation_id": relationship["observation_id"],
                    "relationship_evidence_ids": [relationship["evidence_id"]],
                },
            })
            peer_fact_claims = ["identity.legal_entity", "product.fit", "trade.import_activity"]
            peer_facts = tool(process, 331, "compile_and_append_research_bundle", {
                "investigation_id": investigation_id,
                "bundle": {
                    "bundle_id": "BUNDLE-MCP-PEER-FACTS",
                    "observations": [
                        {
                            "claim_key": claim,
                            "owner_type": "PEER",
                            "owner_id": peer["peer_id"],
                            "result": "POSITIVE",
                            "value": {"fixture": claim},
                            "source": {
                                "source_family": "synthetic_peer_official",
                                "source_type": "OFFICIAL",
                                "reference_type": "PUBLIC_URL",
                                "url": f"https://peer-evidence.invalid/mcp-v61/{index}",
                                "locator": f"https://peer-evidence.invalid/mcp-v61/{index}#fact",
                                "raw_excerpt": f"Synthetic Peer fact {claim}",
                                "authority_level": "B1_OFFICIAL_COMPANY",
                                "freshness": "CURRENT",
                                "observed_at": "2026-08-28T00:00:00Z",
                            },
                            "boundary": "Synthetic Peer fact protocol fixture only.",
                        }
                        for index, claim in enumerate(peer_fact_claims)
                    ],
                },
            })
            evaluated = tool(process, 34, "evaluate_peer", {
                "investigation_id": investigation_id,
                "peer_id": peer["peer_id"],
                "assessment": {
                    "entity_verified": True, "product_fit_verified": True, "business_or_trade_verified": True,
                    "relationship_verified": True, "commercial_novelty": True, "canonical_new": True,
                    "fact_evidence_ids": {
                        "entity_verified": [peer_facts["outcomes"][0]["evidence_id"]],
                        "product_fit_verified": [peer_facts["outcomes"][1]["evidence_id"]],
                        "business_or_trade_verified": [peer_facts["outcomes"][2]["evidence_id"]],
                        "relationship_verified": [relationship["evidence_id"]],
                        "commercial_novelty": [
                            peer_facts["outcomes"][1]["evidence_id"],
                            peer_facts["outcomes"][2]["evidence_id"],
                        ],
                    },
                    "commercial_novelty_basis": (
                        "Independent Peer product and trade Evidence supports a distinct protocol-test anchor decision."
                    ),
                },
            })
            assert evaluated["stage"] == "ANCHOR_ELIGIBLE"
            tool(process, 35, "promote_anchor", {
                "investigation_id": investigation_id,
                "peer_id": peer["peer_id"],
                "promotion_reason": "Synthetic protocol fixture.",
            })
            branch_compiled = tool(process, 351, "compile_and_append_research_bundle", {
                "investigation_id": investigation_id,
                "bundle": {
                    "bundle_id": "BUNDLE-MCP-PEER-BRANCHES",
                    "observations": [
                        {
                            "claim_key": "relationship.supply_chain",
                            "owner_type": "PEER",
                            "owner_id": peer["peer_id"],
                            "network_branch": branch,
                            "result": "POSITIVE",
                            "value": {"fixture": branch},
                            "source": {
                                "source_family": "synthetic_network",
                                "source_type": "OFFICIAL",
                                "reference_type": "PUBLIC_URL",
                                "url": f"https://example.invalid/mcp-v6/peer/{index}",
                                "locator": f"https://example.invalid/mcp-v6/peer/{index}#branch",
                                "raw_excerpt": f"Synthetic Peer branch {branch}",
                                "authority_level": "B1_OFFICIAL_COMPANY",
                                "freshness": "CURRENT",
                                "observed_at": "2026-08-28T00:00:00Z",
                            },
                            "boundary": "Synthetic Peer branch protocol fixture only.",
                        }
                        for index, branch in enumerate(BRANCHES)
                    ],
                },
            })
            tool(process, 36, "evaluate_peer", {
                "investigation_id": investigation_id,
                "peer_id": peer["peer_id"],
                "assessment": {
                    "full_audit_complete": True,
                    "network_branch_states": {
                        branch: {
                            "status": "SATURATED",
                            "decision_basis": "Synthetic Peer-owned branch Evidence compiled in the protocol test.",
                            "evidence_ids": [branch_compiled["outcomes"][index]["evidence_id"]],
                            "max_remaining_eiv": 0.0,
                        }
                        for index, branch in enumerate(BRANCHES)
                    },
                },
            })
            passed.extend(["append_peer_discovery", "evaluate_peer", "promote_anchor"])

            closure = tool(process, 37, "evaluate_investigation_closure", {"investigation_id": investigation_id})
            assert closure["closed"] is True
            passed.append("evaluate_investigation_closure_v6")

            host_payload = {
                "investigation_id": investigation_id,
                "bundle": {
                    "bundle_id": "BUNDLE-MCP-HOST-QUEUE",
                    "observations": [{
                        **observations[2],
                        "source": {**observations[2]["source"], "url": "https://example.invalid/mcp-v6/host", "locator": "https://example.invalid/mcp-v6/host#record", "raw_excerpt": "Host queue fixture"},
                    }],
                },
            }
            queued = tool(process, 38, "queue_host_bundle", {"payload": host_payload})
            assert queued["queued"] is True
            tool(process, 39, "sync_pending_research_bundles", {"investigation_id": investigation_id, "dry_run": True})
            synced = tool(process, 40, "sync_pending_bundles", {"investigation_id": investigation_id})
            assert synced["processed"] == 1
            passed.extend(["queue_host_bundle", "sync_pending_research_bundles", "sync_pending_bundles"])

            migration = tool(process, 41, "migrate_v5_4_1_to_v6", {"target_root": str(root / "migration-target")})
            assert migration["verified"] is True and migration["switched"] is False
            passed.append("migrate_v5_4_1_to_v6")

            required_v6 = [
                "get_investigation_health", "resume_investigation", "submit_research_objective",
                "compile_and_append_research_bundle", "get_claims", "get_account_state",
                "get_investigation_state", "get_next_research_objectives", "append_peer_discovery",
                "evaluate_peer", "promote_anchor", "get_material_pivots", "close_pivot",
                "prepare_crm_writeback", "evaluate_commercial_value", "evaluate_research_confidence",
                "evaluate_outreach_readiness", "evaluate_decision_saturation", "queue_host_bundle",
                "migrate_v5_4_1_to_v6",
            ]
            for offset, name in enumerate(required_v6, 100):
                expect_invalid(process, offset, name)
            passed.append("v6_required_tools_reject_empty_input")
        finally:
            if process.stdin:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
    print(json.dumps({"runtime_version": "6.1.0", "passed": len(passed), "tests": passed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
