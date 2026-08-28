#!/usr/bin/env python3
"""Synthetic, isolated v6.1 performance and scalability acceptance runner.

Smoke profile exercises the specification's normal 100-Evidence timing gates.
Full profile defaults to the specified large-state target: 10k Evidence, 1k
Pivots, 500 Peers and 5k canonical accounts. Explicit smaller counts exist only
for structural regression of the full code path. No live customer data, CRM
workbook, or outreach state is touched.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from unified_runtime import NETWORK_BRANCHES_V6, UnifiedRuntime


TARGETS = {
    "bundle_100_seconds": 5.0,
    "state_query_seconds": 0.5,
    "resume_seconds": 3.0,
}

FULL_TARGETS = {
    "evidence": 10000,
    "pivots": 1000,
    "peers": 500,
    "canonical_accounts": 5000,
}


def observation(index: int, *, pivot: bool = False) -> dict[str, Any]:
    claim = "trade.import_activity" if index % 2 else "product.fit"
    row: dict[str, Any] = {
        "observation_id": f"OBS-LOAD-{index:06d}",
        "claim_key": claim,
        "result": "POSITIVE",
        "owner_type": "ACCOUNT",
        "owner_id": "C-LOAD-SYNTH",
        "value": {
            "fixture_index": index,
            "shipment_count": index + 1 if claim == "trade.import_activity" else None,
        },
        "source": {
            "source_family": "synthetic_load",
            "source_type": "OFFICIAL",
            "reference_type": "PUBLIC_URL",
            "url": f"https://load-{index}.invalid/evidence",
            "locator": f"https://load-{index}.invalid/evidence#row",
            "raw_excerpt": f"Synthetic load evidence row {index}",
            "authority_level": "A1_OFFICIAL_PRIMARY",
            "freshness": "CURRENT_CONFIRMED",
            "observed_at": "2026-08-28T00:00:00Z",
        },
        "boundary": "Synthetic load fixture only; no live-company fact is asserted.",
        "search_cost": 0.0,
    }
    if pivot:
        row["pivots"] = [
            {
                "pivot_id": f"PIV-LOAD-{index:06d}",
                "type": "LOAD_ALIAS",
                "value": f"Synthetic Pivot {index}",
                "materiality": "OPTIONAL",
                "estimated_eiv": 0.01,
            }
        ]
    return row


def peer_discovery_observation(index: int) -> dict[str, Any]:
    branch = NETWORK_BRANCHES_V6[index % len(NETWORK_BRANCHES_V6)]
    return {
        "observation_id": f"OBS-PEER-DISC-{index:05d}",
        "evidence_id": f"EVD-PEER-DISC-{index:05d}",
        "claim_key": "relationship.supply_chain",
        "result": "POSITIVE",
        "owner_type": "ACCOUNT",
        "owner_id": "C-LOAD-SYNTH",
        "network_branch": branch,
        "value": {"peer_candidate": f"Synthetic Peer {index}"},
        "source": {
            "source_family": "synthetic_peer_discovery",
            "source_type": "OFFICIAL",
            "reference_type": "PUBLIC_URL",
            "url": f"https://peer-discovery-{index}.invalid/relationship",
            "locator": f"https://peer-discovery-{index}.invalid/relationship#row",
            "raw_excerpt": f"Synthetic peer relationship evidence {index}",
            "authority_level": "A1_OFFICIAL_PRIMARY",
            "freshness": "CURRENT_CONFIRMED",
            "observed_at": "2026-08-28T00:00:00Z",
        },
        "boundary": "Synthetic peer-discovery load fixture only.",
        "search_cost": 0.0,
    }


def start_runtime(root: Path) -> tuple[UnifiedRuntime, str]:
    runtime = UnifiedRuntime(root)
    started = runtime.start_investigation({
        "account": {
            "account_id": "C-LOAD-SYNTH",
            "country": "Synthetic",
            "name": "Synthetic Load Buyer",
        },
        "mode": "EXHAUSTIVE",
        "history": {"events": []},
        "budget_units": 100000.0,
    })
    return runtime, started["investigation_id"]


def append_batches(
    runtime: UnifiedRuntime,
    investigation_id: str,
    rows: list[dict[str, Any]],
    *,
    prefix: str,
) -> None:
    for offset in range(0, len(rows), 1000):
        batch = rows[offset : offset + 1000]
        result = runtime.compile_and_append_research_bundle({
            "investigation_id": investigation_id,
            "bundle": {
                "bundle_id": f"BUNDLE-{prefix}-{offset // 1000:04d}",
                "observations": batch,
            },
        })
        if result["rejected_count"]:
            raise RuntimeError(
                f"{prefix} batch {offset // 1000} rejected {result['rejected_count']} rows: {result['outcomes']}"
            )


def run_smoke(root: Path, enforce_targets: bool) -> dict[str, Any]:
    runtime, investigation_id = start_runtime(root)
    rows = [observation(index) for index in range(100)]

    started = time.perf_counter()
    append_batches(runtime, investigation_id, rows, prefix="SMOKE")
    bundle_seconds = time.perf_counter() - started

    started = time.perf_counter()
    account_state = runtime.get_account_state({"investigation_id": investigation_id})
    query_seconds = time.perf_counter() - started

    recreated = UnifiedRuntime(root)
    started = time.perf_counter()
    resumed = recreated.resume_investigation({"investigation_id": investigation_id})
    resume_seconds = time.perf_counter() - started

    metrics = {
        "bundle_100_seconds": round(bundle_seconds, 6),
        "state_query_seconds": round(query_seconds, 6),
        "resume_seconds": round(resume_seconds, 6),
    }
    target_results = {
        key: metrics[key] < threshold for key, threshold in TARGETS.items()
    }
    passed = (
        account_state["investigation_id"] == investigation_id
        and resumed["investigation_id"] == investigation_id
        and resumed["durable"] is True
        and (all(target_results.values()) if enforce_targets else True)
    )
    return {
        "profile": "smoke",
        "passed": passed,
        "evidence_count": 100,
        "metrics": metrics,
        "targets": TARGETS,
        "target_results": target_results,
        "enforce_targets": enforce_targets,
    }


def run_full(
    root: Path,
    canonical_accounts: int = FULL_TARGETS["canonical_accounts"],
    *,
    total_evidence: int = FULL_TARGETS["evidence"],
    pivot_count: int = FULL_TARGETS["pivots"],
    peer_count: int = FULL_TARGETS["peers"],
) -> dict[str, Any]:
    if canonical_accounts < 0:
        raise ValueError("canonical_accounts must be non-negative")
    if total_evidence < 1:
        raise ValueError("total_evidence must be positive")
    if peer_count < 0 or peer_count > total_evidence:
        raise ValueError("peer_count must be between 0 and total_evidence")
    remaining = total_evidence - peer_count
    if pivot_count < 0 or pivot_count > remaining:
        raise ValueError("pivot_count must be between 0 and total_evidence - peer_count")

    runtime, investigation_id = start_runtime(root)
    peer_rows = [peer_discovery_observation(index) for index in range(peer_count)]
    if peer_rows:
        append_batches(runtime, investigation_id, peer_rows, prefix="PEER-DISCOVERY")
    for index, row in enumerate(peer_rows):
        runtime.append_peer_discovery({
            "investigation_id": investigation_id,
            "peer": {
                "peer_id": f"PEER-LOAD-{index:05d}",
                "name": f"Synthetic Peer {index}",
                "country": "Synthetic",
                "network_branch": row["network_branch"],
                "discovered_from_owner_id": "C-LOAD-SYNTH",
                "discovered_by_observation_id": row["observation_id"],
                "relationship_evidence_ids": [row["evidence_id"]],
            },
        })

    rows = [
        observation(peer_count + index, pivot=index < pivot_count)
        for index in range(remaining)
    ]
    started = time.perf_counter()
    if rows:
        append_batches(runtime, investigation_id, rows, prefix="LARGE")
    append_seconds = time.perf_counter() - started

    account_started = time.perf_counter()
    for index in range(canonical_accounts):
        runtime.resolve_or_create_account({
            "candidate": {
                "name": f"Synthetic Canonical Account {index}",
                "country": "Synthetic",
            },
            "create_if_missing": True,
        })
    account_seconds = time.perf_counter() - account_started

    recreated = UnifiedRuntime(root)
    load_started = time.perf_counter()
    internal = recreated._v6_state(investigation_id)  # acceptance-only structural count
    load_seconds = time.perf_counter() - load_started
    query_started = time.perf_counter()
    public_state = recreated.get_investigation_state({"investigation_id": investigation_id})
    query_seconds = time.perf_counter() - query_started
    resume_started = time.perf_counter()
    resumed = recreated.resume_investigation({"investigation_id": investigation_id})
    resume_seconds = time.perf_counter() - resume_started

    counts = {
        "evidence": len(internal["observations"]),
        "pivots": len(internal["pivots"]),
        "peers": len(internal["peers"]),
        "canonical_accounts_requested": canonical_accounts,
    }
    expected = {
        "evidence": total_evidence,
        "pivots": pivot_count,
        "peers": peer_count,
        "canonical_accounts": canonical_accounts,
    }
    passed = (
        counts["evidence"] == total_evidence
        and counts["pivots"] == pivot_count
        and counts["peers"] == peer_count
        and public_state["observation_count"] == total_evidence
        and public_state["peer_count"] == peer_count
        and resumed["durable"] is True
    )
    return {
        "profile": "full" if expected == FULL_TARGETS else "full-reduced-structural",
        "passed": passed,
        "counts": counts,
        "expected_counts": expected,
        "metrics": {
            "append_non_peer_evidence_seconds": round(append_seconds, 6),
            "canonical_account_creation_seconds": round(account_seconds, 6),
            "large_state_load_seconds": round(load_seconds, 6),
            "large_public_state_query_seconds": round(query_seconds, 6),
            "large_resume_seconds": round(resume_seconds, 6),
        },
        "spec_full_targets": FULL_TARGETS,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated CBI v6.1 load acceptance.")
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--enforce-targets", action="store_true")
    parser.add_argument(
        "--canonical-accounts",
        type=int,
        default=FULL_TARGETS["canonical_accounts"],
        help="Full-profile canonical-account count; default matches v6 target.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="cbi-v61-load-") as temp:
        root = Path(temp) / "sessions"
        result = (
            run_smoke(root, args.enforce_targets)
            if args.profile == "smoke"
            else run_full(root, args.canonical_accounts)
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
