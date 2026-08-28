#!/usr/bin/env python3
"""Synthetic, isolated v6.1 performance and scalability acceptance runner.

Profiles are deliberately distinct:

* ``smoke`` exercises the specification's normal 100-Evidence timing gates.
* ``full`` exercises one large Investigation at 10k Evidence / 1k Pivots /
  500 Peers plus 5k canonical accounts.
* ``scale`` exercises the separate production scalability target: 5k canonical
  accounts, 1k simultaneous production investigations, 100k Evidence records,
  100k preserved Source Attempts and 20k Peers.

The scale profile is a state-scalability acceptance, not a claim that 120k
single-record fsync mutations can be executed within an unstated throughput
SLO. Every Evidence record is compiled through the real v6 Evidence Compiler.
For each Investigation, at least one Source Attempt and one Peer are also
validated through their real Runtime APIs. Remaining high-cardinality Attempt
and Peer events use the Runtime's own ``SessionStore.append_many`` primitive to
build the same durable event payloads under the same append-only hash chain,
then a cold Runtime reload validates aggregate counts and the production
Portfolio view. This preserves the distinction between API semantic coverage
and durable-state scalability.

All profiles use temporary isolated state. No live customer data, CRM workbook,
or outreach state is touched.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime import NETWORK_BRANCHES_V6, UnifiedRuntime
from unified_runtime.resilience import digest, iso_utc


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

SCALE_TARGETS = {
    "canonical_accounts": 5000,
    "simultaneous_investigations": 1000,
    "evidence_records": 100000,
    "source_attempts": 100000,
    "peers": 20000,
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


def _partition(total: int, buckets: int, index: int) -> int:
    base, remainder = divmod(total, buckets)
    return base + (1 if index < remainder else 0)


def _scale_account_id(index: int) -> str:
    return f"C-SCALE-{index:05d}"


def _scale_observation(
    investigation_index: int,
    row_index: int,
    account_id: str,
    *,
    peer_evidence: bool,
) -> dict[str, Any]:
    observation_id = f"OBS-SCALE-{investigation_index:04d}-{row_index:04d}"
    evidence_id = f"EVD-SCALE-{investigation_index:04d}-{row_index:04d}"
    if peer_evidence:
        branch = NETWORK_BRANCHES_V6[row_index % len(NETWORK_BRANCHES_V6)]
        claim = "relationship.supply_chain"
        value = {"peer_candidate": f"Scale Peer {investigation_index}-{row_index}"}
        source_family = "scale_peer_discovery"
    else:
        branch = ""
        claim = "trade.import_activity" if row_index % 2 else "product.fit"
        value = {
            "fixture_index": row_index,
            "shipment_count": row_index + 1 if claim == "trade.import_activity" else None,
        }
        source_family = "scale_evidence"
    source_url = f"https://scale-{investigation_index}-{row_index}.invalid/evidence"
    row: dict[str, Any] = {
        "observation_id": observation_id,
        "evidence_id": evidence_id,
        "claim_key": claim,
        "result": "POSITIVE",
        "owner_type": "ACCOUNT",
        "owner_id": account_id,
        "value": value,
        "source": {
            "source_family": source_family,
            "source_type": source_family,
            "reference_type": "PUBLIC_URL",
            "url": source_url,
            "locator": f"{source_url}#row",
            "raw_excerpt": f"Isolated scale acceptance evidence {investigation_index}/{row_index}",
            "authority_level": "A1_OFFICIAL_PRIMARY",
            "freshness": "CURRENT_CONFIRMED",
            "observed_at": "2026-08-28T00:00:00Z",
        },
        "boundary": "Synthetic isolated scalability fixture; no live-company fact is asserted.",
        "search_cost": 0.0,
    }
    if branch:
        row["network_branch"] = branch
    return row


def _scale_attempt(investigation_id: str, account_id: str, investigation_index: int, attempt_index: int) -> dict[str, Any]:
    material = f"scale-attempt:{investigation_index}:{attempt_index}".encode("utf-8")
    content_sha256 = hashlib.sha256(material).hexdigest()
    timestamp = "2026-08-28T00:00:00Z"
    return {
        "attempt_id": f"ATT-SCALE-{investigation_index:04d}-{attempt_index:04d}",
        "investigation_id": investigation_id,
        "owner_type": "ACCOUNT",
        "owner_id": account_id,
        "module_or_branch": "company_profile",
        "source_family": "official_home",
        "query": f"Scale acceptance query {investigation_index}/{attempt_index}",
        "started_at": timestamp,
        "completed_at": timestamp,
        "checked_at": timestamp,
        "tool_or_operator": "SYNTHETIC_SCALE_ACCEPTANCE",
        "execution_id": f"EXEC-SCALE-{investigation_index:04d}-{attempt_index:04d}",
        "result": "NEGATIVE",
        "result_count": 0,
        "raw_result_locator": f"https://scale-attempt-{investigation_index}-{attempt_index}.invalid/no-result",
        "content_sha256": content_sha256,
        "evidence_ids": [],
        "pivots_generated": [],
        "blocked_reason": "",
        "discovered_peer_ids": [],
        "relationship_evidence_ids": {},
    }


def _scale_attempt_event(attempt: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (
        "EXECUTION_RECEIPT_APPENDED",
        {
            "attempt": attempt,
            "evidence": [],
            "pivots_generated": [],
            "pivots_consumed": [],
            "manual_visual_items_resolved": [],
        },
    )


def _scale_peer_payload(
    investigation_id: str,
    account_id: str,
    investigation_index: int,
    peer_index: int,
) -> dict[str, Any]:
    name = f"Scale Peer {investigation_index}-{peer_index}"
    country = "ScaleLab"
    identity_key = digest({"name": name.casefold(), "country": country.casefold(), "tax_id": ""})
    return {
        "schema": "cbi.peer.v6.1",
        "peer_id": f"PEER-SCALE-{investigation_index:04d}-{peer_index:04d}",
        "investigation_id": investigation_id,
        "name": name,
        "country": country,
        "tax_id": "",
        "network_branch": NETWORK_BRANCHES_V6[peer_index % len(NETWORK_BRANCHES_V6)],
        "discovered_from_owner_id": account_id,
        "discovered_by_observation_id": f"OBS-SCALE-{investigation_index:04d}-{peer_index:04d}",
        "relationship_evidence_ids": [f"EVD-SCALE-{investigation_index:04d}-{peer_index:04d}"],
        "identity_key": identity_key,
        "stage": "DISCOVERED",
        "discovered_at": iso_utc(),
    }


def _start_scale_investigation(runtime: UnifiedRuntime, index: int) -> tuple[str, str]:
    account_id = _scale_account_id(index)
    started = runtime.start_investigation({
        "account": {
            "account_id": account_id,
            "country": "ScaleLab",
            "name": f"Scale Acceptance Buyer {index}",
        },
        "mode": "EXHAUSTIVE",
        "history": {"events": []},
        "input": {
            "synthetic": True,
            "portfolio_environment": "PRODUCTION",
            "portfolio_lifecycle": "ACTIVE",
            "investigation_scope": "SCALE_ACCEPTANCE",
        },
        "budget_units": 1000000.0,
        "resume_existing": False,
    })
    return started["investigation_id"], account_id


def run_scale(
    root: Path,
    *,
    canonical_accounts: int = SCALE_TARGETS["canonical_accounts"],
    simultaneous_investigations: int = SCALE_TARGETS["simultaneous_investigations"],
    evidence_records: int = SCALE_TARGETS["evidence_records"],
    source_attempts: int = SCALE_TARGETS["source_attempts"],
    peers: int = SCALE_TARGETS["peers"],
) -> dict[str, Any]:
    if simultaneous_investigations < 1:
        raise ValueError("simultaneous_investigations must be positive")
    if canonical_accounts < simultaneous_investigations:
        raise ValueError("canonical_accounts must be >= simultaneous_investigations")
    if evidence_records < simultaneous_investigations:
        raise ValueError("evidence_records must provide at least one Evidence record per investigation")
    if source_attempts < simultaneous_investigations:
        raise ValueError("source_attempts must provide at least one formal API sample per investigation")
    if peers < simultaneous_investigations:
        raise ValueError("peers must provide at least one formal API sample per investigation")
    if peers > evidence_records:
        raise ValueError("peers cannot exceed Evidence records because each Peer needs relationship Evidence")

    runtime = UnifiedRuntime(root)
    investigation_ids: list[str] = []
    generation_started = time.perf_counter()
    formal_attempt_samples = 0
    formal_peer_samples = 0

    for investigation_index in range(simultaneous_investigations):
        investigation_id, account_id = _start_scale_investigation(runtime, investigation_index)
        investigation_ids.append(investigation_id)
        evidence_count = _partition(evidence_records, simultaneous_investigations, investigation_index)
        attempt_count = _partition(source_attempts, simultaneous_investigations, investigation_index)
        peer_count = _partition(peers, simultaneous_investigations, investigation_index)
        if peer_count > evidence_count:
            raise ValueError(
                f"investigation {investigation_index}: peer partition exceeds Evidence partition"
            )

        rows = [
            _scale_observation(
                investigation_index,
                row_index,
                account_id,
                peer_evidence=row_index < peer_count,
            )
            for row_index in range(evidence_count)
        ]
        append_batches(
            runtime,
            investigation_id,
            rows,
            prefix=f"SCALE-{investigation_index:04d}",
        )

        first_attempt = _scale_attempt(investigation_id, account_id, investigation_index, 0)
        formal_attempt = runtime.append_execution_receipt({
            "investigation_id": investigation_id,
            "attempt": first_attempt,
            "evidence": [],
            "pivots": [],
            "pivots_consumed": [],
            "manual_visual_items_resolved": [],
        })
        if formal_attempt.get("accepted") is not True:
            raise RuntimeError(f"formal Source Attempt sample was rejected for investigation {investigation_index}")
        formal_attempt_samples += 1

        first_peer = _scale_peer_payload(investigation_id, account_id, investigation_index, 0)
        formal_peer = runtime.append_peer_discovery({
            "investigation_id": investigation_id,
            "peer": {
                "peer_id": first_peer["peer_id"],
                "name": first_peer["name"],
                "country": first_peer["country"],
                "network_branch": first_peer["network_branch"],
                "discovered_from_owner_id": account_id,
                "discovered_by_observation_id": first_peer["discovered_by_observation_id"],
                "relationship_evidence_ids": first_peer["relationship_evidence_ids"],
            },
        })
        if formal_peer.get("accepted") is not True:
            raise RuntimeError(f"formal Peer sample was rejected for investigation {investigation_index}")
        formal_peer_samples += 1

        bulk_rows: list[tuple[str, dict[str, Any]]] = []
        for attempt_index in range(1, attempt_count):
            bulk_rows.append(
                _scale_attempt_event(
                    _scale_attempt(
                        investigation_id,
                        account_id,
                        investigation_index,
                        attempt_index,
                    )
                )
            )
        for peer_index in range(1, peer_count):
            bulk_rows.append(
                (
                    "V6_PEER_DISCOVERED",
                    _scale_peer_payload(
                        investigation_id,
                        account_id,
                        investigation_index,
                        peer_index,
                    ),
                )
            )
        if bulk_rows:
            runtime.store.append_many(investigation_id, bulk_rows)

    for index in range(simultaneous_investigations, canonical_accounts):
        account_id = _scale_account_id(index)
        runtime.resolve_or_create_account({
            "candidate": {
                "account_id": account_id,
                "name": f"Scale Acceptance Canonical Account {index}",
                "country": "ScaleLab",
            },
            "requested_account_id": account_id,
            "create_if_missing": True,
        })
    generation_seconds = time.perf_counter() - generation_started

    recreated = UnifiedRuntime(root)
    aggregate_started = time.perf_counter()
    aggregate = {
        "simultaneous_investigations": len(investigation_ids),
        "evidence_records": 0,
        "source_attempts": 0,
        "peers": 0,
    }
    for investigation_id in investigation_ids:
        events = recreated.store.read(investigation_id)
        for event in events:
            if event["event_type"] == "V6_OBSERVATION_COMPILED":
                observation_row = event.get("payload", {}).get("observation", {})
                if observation_row.get("evidence_id"):
                    aggregate["evidence_records"] += 1
            elif event["event_type"] == "EXECUTION_RECEIPT_APPENDED":
                aggregate["source_attempts"] += 1
            elif event["event_type"] == "V6_PEER_DISCOVERED":
                aggregate["peers"] += 1
    aggregate_seconds = time.perf_counter() - aggregate_started

    canonical_started = time.perf_counter()
    canonical_count = len(recreated.canonical_registry.entries())
    canonical_query_seconds = time.perf_counter() - canonical_started

    portfolio_started = time.perf_counter()
    portfolio = recreated.get_portfolio_queue({"limit": 1000})
    portfolio_seconds = time.perf_counter() - portfolio_started

    sample_started = time.perf_counter()
    sample_indices = sorted({0, simultaneous_investigations // 2, simultaneous_investigations - 1})
    samples: list[dict[str, Any]] = []
    for index in sample_indices:
        investigation_id = investigation_ids[index]
        v6_state = recreated._v6_state(investigation_id)
        compatibility_state = recreated._state(investigation_id)
        samples.append({
            "investigation_id": investigation_id,
            "v6_observations": len(v6_state["observations"]),
            "v6_peers": len(v6_state["peers"]),
            "source_attempts": len(compatibility_state["attempts"]),
            "last_safe_seq": v6_state["events"][-1]["seq"],
        })
    sample_validation_seconds = time.perf_counter() - sample_started

    counts = {
        "canonical_accounts": canonical_count,
        **aggregate,
        "portfolio_active_investigations": portfolio["active_count"],
        "portfolio_total_scanned": portfolio["total_scanned"],
        "portfolio_superseded": portfolio["superseded_count"],
        "portfolio_quarantined": portfolio["quarantined_count"],
    }
    expected = {
        "canonical_accounts": canonical_accounts,
        "simultaneous_investigations": simultaneous_investigations,
        "evidence_records": evidence_records,
        "source_attempts": source_attempts,
        "peers": peers,
    }
    passed = (
        canonical_count == canonical_accounts
        and aggregate["simultaneous_investigations"] == simultaneous_investigations
        and aggregate["evidence_records"] == evidence_records
        and aggregate["source_attempts"] == source_attempts
        and aggregate["peers"] == peers
        and portfolio["active_count"] == simultaneous_investigations
        and portfolio["total_scanned"] == simultaneous_investigations
        and portfolio["superseded_count"] == 0
        and portfolio["quarantined_count"] == 0
        and formal_attempt_samples == simultaneous_investigations
        and formal_peer_samples == simultaneous_investigations
    )
    exact_target = expected == SCALE_TARGETS
    return {
        "profile": "scale" if exact_target else "scale-reduced-structural",
        "passed": passed,
        "counts": counts,
        "expected_counts": expected,
        "formal_api_samples": {
            "evidence_compiler_investigations": simultaneous_investigations,
            "source_attempt_api_samples": formal_attempt_samples,
            "peer_discovery_api_samples": formal_peer_samples,
        },
        "samples": samples,
        "metrics": {
            "generation_seconds": round(generation_seconds, 6),
            "cold_hash_chain_aggregate_seconds": round(aggregate_seconds, 6),
            "canonical_registry_query_seconds": round(canonical_query_seconds, 6),
            "portfolio_query_seconds": round(portfolio_seconds, 6),
            "sample_state_reconstruction_seconds": round(sample_validation_seconds, 6),
        },
        "spec_scale_targets": SCALE_TARGETS,
        "acceptance_boundary": {
            "proves_durable_state_scalability": True,
            "proves_single_record_mutation_throughput_slo": False,
            "all_evidence_compiled_by_formal_v6_compiler": True,
            "source_attempt_and_peer_bulk_events_use_session_store_append_many": True,
            "cold_reload_validates_hash_chains": True,
            "portfolio_active_count_uses_public_runtime_view": True,
        },
    }


def parse_args() -> Any:
    import argparse

    parser = argparse.ArgumentParser(description="Run isolated CBI v6.1 load acceptance.")
    parser.add_argument("--profile", choices=["smoke", "full", "scale"], default="smoke")
    parser.add_argument("--enforce-targets", action="store_true")
    parser.add_argument(
        "--canonical-accounts",
        type=int,
        default=None,
        help="Override canonical-account count for full/scale profiles.",
    )
    parser.add_argument("--scale-investigations", type=int, default=SCALE_TARGETS["simultaneous_investigations"])
    parser.add_argument("--scale-evidence", type=int, default=SCALE_TARGETS["evidence_records"])
    parser.add_argument("--scale-attempts", type=int, default=SCALE_TARGETS["source_attempts"])
    parser.add_argument("--scale-peers", type=int, default=SCALE_TARGETS["peers"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="cbi-v61-load-") as temp:
        root = Path(temp) / "sessions"
        if args.profile == "smoke":
            result = run_smoke(root, args.enforce_targets)
        elif args.profile == "full":
            result = run_full(
                root,
                FULL_TARGETS["canonical_accounts"] if args.canonical_accounts is None else args.canonical_accounts,
            )
        else:
            result = run_scale(
                root,
                canonical_accounts=(
                    SCALE_TARGETS["canonical_accounts"]
                    if args.canonical_accounts is None
                    else args.canonical_accounts
                ),
                simultaneous_investigations=args.scale_investigations,
                evidence_records=args.scale_evidence,
                source_attempts=args.scale_attempts,
                peers=args.scale_peers,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
