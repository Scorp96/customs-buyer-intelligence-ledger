from __future__ import annotations

import copy
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import production_source_snapshot_v63
from .exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from .exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from .product_profiles import get_product_profile
from .recovery_semantics_v63 import (
    canonical_v63_wal_request_sha256,
    snapshot_sha256,
)


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CANDIDATE_TOOL = "append_candidate_discovery"
_CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"
_OPPORTUNITY_TOOL = "create_product_opportunity"
_OPPORTUNITY_EVENT = "V63_PRODUCT_OPPORTUNITY_CREATED"
_ANCHOR_TOOL = "promote_opportunity_anchor"
_ANCHOR_EVENT = "V63_OPPORTUNITY_ANCHOR_PROMOTED"


@dataclass(frozen=True)
class ExactCheckoutAcceptanceConfig:
    repo_root: Path
    expected_git_sha: str
    output_dir: Path


def _checkout_git_sha(repo_root: Path) -> str:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise RuntimeError("CHECKOUT_ROOT_NOT_FOUND")
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("CHECKOUT_GIT_SHA_UNAVAILABLE") from exc
    sha = str(completed.stdout or "").strip().lower()
    if completed.returncode != 0 or not _GIT_SHA_RE.fullmatch(sha):
        raise RuntimeError("CHECKOUT_GIT_SHA_UNAVAILABLE")
    return sha


def _assert_expected_git_sha(config: ExactCheckoutAcceptanceConfig) -> str:
    expected = str(config.expected_git_sha or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(expected):
        raise RuntimeError("EXPECTED_GIT_SHA_INVALID")
    actual = _checkout_git_sha(config.repo_root)
    if actual != expected:
        raise RuntimeError(f"GIT_SHA_MISMATCH expected={expected} actual={actual}")
    return actual


def _build_ready_source_snapshot(repo_root: Path) -> dict[str, Any]:
    snapshot = production_source_snapshot_v63.build_v63_production_source_snapshot(
        Path(repo_root).resolve()
    )
    if not isinstance(snapshot, dict):
        raise RuntimeError("SOURCE_SNAPSHOT_NOT_READY: invalid snapshot result")
    snapshot_sha = str(snapshot.get("snapshot_sha256") or "").strip().lower()
    if (
        snapshot.get("status") != "READY"
        or snapshot.get("source_pins_complete") is not True
        or not _SHA256_RE.fullmatch(snapshot_sha)
    ):
        blockers = ",".join(str(item) for item in snapshot.get("blockers") or [])
        detail = f":{blockers}" if blockers else ""
        raise RuntimeError(f"SOURCE_SNAPSHOT_NOT_READY{detail}")
    return snapshot


def _assert_source_snapshot_unchanged(
    repo_root: Path,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise RuntimeError("SOURCE_SNAPSHOT_DRIFT: invalid original snapshot")
    snapshot_sha = str(snapshot.get("snapshot_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(snapshot_sha):
        raise RuntimeError("SOURCE_SNAPSHOT_DRIFT: invalid original snapshot sha")
    validation = production_source_snapshot_v63.validate_v63_production_source_snapshot(
        Path(repo_root).resolve(),
        snapshot,
    )
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        details: list[str] = []
        if isinstance(validation, dict):
            details.extend(str(item) for item in validation.get("blockers") or [])
            details.extend(
                f"DRIFTED:{item}" for item in validation.get("drifted_files") or []
            )
            details.extend(
                f"MISSING:{item}" for item in validation.get("missing_files") or []
            )
            if validation.get("entrypoint_changed") is True:
                details.append("ENTRYPOINT_CHANGED")
        detail = ":" + ",".join(details) if details else ""
        raise RuntimeError(f"SOURCE_SNAPSHOT_DRIFT{detail}")
    return validation


def _without_idempotency_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_idempotency_keys(item)
            for key, item in value.items()
            if str(key).casefold() != "idempotency_key"
        }
    if isinstance(value, list):
        return [_without_idempotency_keys(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_without_idempotency_keys(item) for item in value)
    return copy.deepcopy(value)


def _candidate_success_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "candidate": {
            "candidate_id": "CAND-V63-EXACT-001",
            "discovered_from_anchor_id": "ANCHOR-V63-SYNTH-001",
            "branch_group": "TRADE_GRAPH",
            "branch": "same_product_hs_application_buyer",
            "company_name": "Synthetic Exact Candidate Buyer",
            "product_profile_id": "PVC",
        },
        "idempotency_key": "v63-exact-candidate-success-0001",
    }


def _opportunity_success_arguments(investigation_id: str) -> dict[str, Any]:
    profile = get_product_profile("PVC")
    account_id = "C-V63-EXACT-OPPORTUNITY"
    return {
        "investigation_id": investigation_id,
        "canonical_resolution": {
            "canonical_status": "CONFIRMED",
            "canonical_account_id": account_id,
            "resolver_authority": "PRIMARY_LEGAL_NAME_COUNTRY",
            "resolver_is_existing_production_authority": True,
            "ambiguous": False,
            "address_only_match": False,
            "alias_only_match": False,
            "tax_conflict": False,
            "country_conflict": False,
        },
        "opportunity": {
            "opportunity_id": "OPP-V63-EXACT-001",
            "account_id": account_id,
            "product_profile_id": profile["profile_id"],
            "product_profile_version": profile["profile_version"],
            "product_profile_sha256": profile["profile_sha256"],
            "application_ids": ["CABINETRY"],
            "buyer_archetype_ids": ["CABINET_MANUFACTURER"],
            "market_cell_ids": ["SYNTHETIC-EXACT-CELL"],
        },
        "idempotency_key": "v63-exact-opportunity-success-0001",
    }


def _anchor_success_arguments(investigation_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "opportunity_id": "OPP-V63-EXACT-ANCHOR-001",
        "promotion_reason": "Synthetic exact B+ material novelty promotion",
        "anchor_eligibility": {
            "anchor_eligible": True,
            "commercial_value_grade": "B+",
            "canonical_status": "CONFIRMED",
            "commercial_evidence_bound": True,
            "material_novelty_signals": ["STRONG_CURRENT_PROCUREMENT"],
            "contact_readiness_is_gate": False,
            "blockers": [],
        },
        "cycle_dedup_complete": True,
        "idempotency_key": "v63-exact-anchor-success-0001",
    }


def _start_synthetic_investigation(
    harness: ExactCheckoutMcpHarness,
    request_id: int,
    *,
    account_id: str,
    name: str,
    idempotency_key: str,
) -> str:
    started = harness.tool(
        request_id,
        "start_investigation",
        {
            "account": {
                "account_id": account_id,
                "country": "Synthetic",
                "name": name,
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": idempotency_key,
        },
    )
    investigation_id = str(started.get("investigation_id") or "").strip()
    if not investigation_id:
        raise RuntimeError("SYNTHETIC_INVESTIGATION_ID_MISSING")
    return investigation_id


def _run_candidate_success_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()
    harness = ExactCheckoutMcpHarness(root, persistence)
    harness.start()
    try:
        investigation_id = _start_synthetic_investigation(
            harness,
            2,
            account_id="C-V63-EXACT-CANDIDATE",
            name="Synthetic v6.3 Exact Candidate Buyer",
            idempotency_key="v63-exact-candidate-start-0001",
        )
        arguments = _candidate_success_arguments(investigation_id)
        raw_response = harness.tool(3, _CANDIDATE_TOOL, arguments)
    finally:
        harness.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    evidence = reader.normalize_mutation_evidence(investigation_id, _CANDIDATE_TOOL)
    events = evidence.get("events") or []
    wal_records = evidence.get("wal_records") or []
    expected_request_sha = canonical_v63_wal_request_sha256(
        _CANDIDATE_TOOL, arguments
    )

    event = events[0] if len(events) == 1 else {}
    wal = wal_records[0] if len(wal_records) == 1 else {}
    event_correlation = str(event.get("correlation_id") or "").strip()
    wal_correlation = str(wal.get("correlation_id") or "").strip()
    exact_correlation_proven = bool(
        len(events) == 1
        and len(wal_records) == 1
        and event.get("event_type") == _CANDIDATE_EVENT
        and wal.get("status") == "COMMITTED"
        and event_correlation
        and event_correlation == wal_correlation
    )
    exact_request_hash_proven = bool(
        len(events) == 1
        and len(wal_records) == 1
        and event.get("request_sha256") == expected_request_sha
        and wal.get("request_sha256") == expected_request_sha
    )
    if not exact_correlation_proven:
        raise RuntimeError("CANDIDATE_SUCCESS_EXACT_CORRELATION_NOT_PROVEN")
    if not exact_request_hash_proven:
        raise RuntimeError("CANDIDATE_SUCCESS_EXACT_REQUEST_HASH_NOT_PROVEN")

    response = _without_idempotency_keys(raw_response)
    if not isinstance(response, dict) or response.get("status") != "DISCOVERED":
        raise RuntimeError("CANDIDATE_SUCCESS_RESPONSE_INVALID")

    return {
        "scenario": "candidate_success",
        "tool": _CANDIDATE_TOOL,
        "investigation_id": investigation_id,
        "response": response,
        "evidence": evidence,
        "exact_correlation_proven": exact_correlation_proven,
        "exact_request_hash_proven": exact_request_hash_proven,
    }


def _run_opportunity_success_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()
    harness = ExactCheckoutMcpHarness(root, persistence)
    harness.start()
    try:
        investigation_id = _start_synthetic_investigation(
            harness,
            2,
            account_id="C-V63-EXACT-OPPORTUNITY",
            name="Synthetic v6.3 Exact Opportunity Buyer",
            idempotency_key="v63-exact-opportunity-start-0001",
        )
        arguments = _opportunity_success_arguments(investigation_id)
        raw_response = harness.tool(3, _OPPORTUNITY_TOOL, arguments)
    finally:
        harness.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    evidence = reader.normalize_mutation_evidence(investigation_id, _OPPORTUNITY_TOOL)
    events = evidence.get("events") or []
    wal_records = evidence.get("wal_records") or []
    expected_request_sha = canonical_v63_wal_request_sha256(
        _OPPORTUNITY_TOOL, arguments
    )

    event = events[0] if len(events) == 1 else {}
    wal = wal_records[0] if len(wal_records) == 1 else {}
    event_correlation = str(event.get("correlation_id") or "").strip()
    wal_correlation = str(wal.get("correlation_id") or "").strip()
    exact_correlation_proven = bool(
        len(events) == 1
        and len(wal_records) == 1
        and event.get("event_type") == _OPPORTUNITY_EVENT
        and wal.get("status") == "COMMITTED"
        and event_correlation
        and event_correlation == wal_correlation
    )
    exact_request_hash_proven = bool(
        len(events) == 1
        and len(wal_records) == 1
        and event.get("request_sha256") == expected_request_sha
        and wal.get("request_sha256") == expected_request_sha
    )

    response = _without_idempotency_keys(raw_response)
    business_response = copy.deepcopy(response)
    if isinstance(business_response, dict):
        business_response.pop("mutation_meta", None)
    result_snapshot = event.get("result_snapshot") if isinstance(event, dict) else None
    result_snapshot_sha = (
        str(event.get("result_snapshot_sha256") or "").lower()
        if isinstance(event, dict)
        else ""
    )
    exact_result_snapshot_proven = bool(
        isinstance(result_snapshot, dict)
        and result_snapshot == business_response
        and _SHA256_RE.fullmatch(result_snapshot_sha)
        and snapshot_sha256(result_snapshot) == result_snapshot_sha
    )

    if not exact_correlation_proven:
        raise RuntimeError("OPPORTUNITY_SUCCESS_EXACT_CORRELATION_NOT_PROVEN")
    if not exact_request_hash_proven:
        raise RuntimeError("OPPORTUNITY_SUCCESS_EXACT_REQUEST_HASH_NOT_PROVEN")
    if not exact_result_snapshot_proven:
        raise RuntimeError("OPPORTUNITY_SUCCESS_EXACT_RESULT_SNAPSHOT_NOT_PROVEN")
    if not isinstance(response, dict) or response.get("status") != "CREATED":
        raise RuntimeError("OPPORTUNITY_SUCCESS_RESPONSE_INVALID")

    return {
        "scenario": "opportunity_success",
        "tool": _OPPORTUNITY_TOOL,
        "investigation_id": investigation_id,
        "response": response,
        "evidence": evidence,
        "durable_result_snapshot": copy.deepcopy(result_snapshot),
        "exact_correlation_proven": exact_correlation_proven,
        "exact_request_hash_proven": exact_request_hash_proven,
        "exact_result_snapshot_proven": exact_result_snapshot_proven,
    }


def _run_anchor_success_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()
    harness = ExactCheckoutMcpHarness(root, persistence)
    harness.start()
    try:
        investigation_id = _start_synthetic_investigation(
            harness,
            2,
            account_id="C-V63-EXACT-ANCHOR",
            name="Synthetic v6.3 Exact Anchor Buyer",
            idempotency_key="v63-exact-anchor-start-0001",
        )
        arguments = _anchor_success_arguments(investigation_id)
        raw_response = harness.tool(3, _ANCHOR_TOOL, arguments)
    finally:
        harness.stop()

    reader = ExactCheckoutPersistenceReader(persistence)
    evidence = reader.normalize_mutation_evidence(investigation_id, _ANCHOR_TOOL)
    events = evidence.get("events") or []
    wal_records = evidence.get("wal_records") or []
    expected_request_sha = canonical_v63_wal_request_sha256(_ANCHOR_TOOL, arguments)

    event = events[0] if len(events) == 1 else {}
    wal = wal_records[0] if len(wal_records) == 1 else {}
    event_correlation = str(event.get("correlation_id") or "").strip()
    wal_correlation = str(wal.get("correlation_id") or "").strip()
    exact_correlation_proven = bool(
        len(events) == 1
        and len(wal_records) == 1
        and event.get("event_type") == _ANCHOR_EVENT
        and wal.get("status") == "COMMITTED"
        and event_correlation
        and event_correlation == wal_correlation
    )
    exact_request_hash_proven = bool(
        len(events) == 1
        and len(wal_records) == 1
        and event.get("request_sha256") == expected_request_sha
        and wal.get("request_sha256") == expected_request_sha
    )

    durable_matches: list[dict[str, Any]] = []
    for raw_event in reader.read_session_events(investigation_id):
        correlation = raw_event.get("mutation_correlation")
        if (
            raw_event.get("event_type") == _ANCHOR_EVENT
            and isinstance(correlation, dict)
            and correlation.get("tool") == _ANCHOR_TOOL
            and correlation.get("correlation_id") == event_correlation
        ):
            durable_matches.append(raw_event)
    durable_event = durable_matches[0] if len(durable_matches) == 1 else {}
    payload = durable_event.get("payload") if isinstance(durable_event, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    eligibility = _without_idempotency_keys(payload.get("anchor_eligibility_snapshot"))
    cycle = _without_idempotency_keys(payload.get("cycle_dedup_snapshot"))

    response = _without_idempotency_keys(raw_response)
    exact_anchor_snapshots_proven = bool(
        len(durable_matches) == 1
        and isinstance(eligibility, dict)
        and eligibility == arguments["anchor_eligibility"]
        and eligibility.get("anchor_eligible") is True
        and isinstance(cycle, dict)
        and cycle == {"cycle_dedup_complete": True}
        and isinstance(response, dict)
        and response.get("anchor_eligibility_snapshot") == eligibility
        and response.get("cycle_dedup_snapshot") == cycle
    )

    if not exact_correlation_proven:
        raise RuntimeError("ANCHOR_SUCCESS_EXACT_CORRELATION_NOT_PROVEN")
    if not exact_request_hash_proven:
        raise RuntimeError("ANCHOR_SUCCESS_EXACT_REQUEST_HASH_NOT_PROVEN")
    if not exact_anchor_snapshots_proven:
        raise RuntimeError("ANCHOR_SUCCESS_EXACT_SNAPSHOTS_NOT_PROVEN")
    if not isinstance(response, dict) or response.get("status") != "PROMOTED":
        raise RuntimeError("ANCHOR_SUCCESS_RESPONSE_INVALID")

    return {
        "scenario": "anchor_success",
        "tool": _ANCHOR_TOOL,
        "investigation_id": investigation_id,
        "response": response,
        "evidence": evidence,
        "durable_anchor_snapshots": {
            "anchor_eligibility_snapshot": copy.deepcopy(eligibility),
            "cycle_dedup_snapshot": copy.deepcopy(cycle),
        },
        "exact_correlation_proven": exact_correlation_proven,
        "exact_request_hash_proven": exact_request_hash_proven,
        "exact_anchor_snapshots_proven": exact_anchor_snapshots_proven,
    }


def run_v63_exact_checkout_live_acceptance(
    config: ExactCheckoutAcceptanceConfig,
) -> dict[str, Any]:
    if not isinstance(config, ExactCheckoutAcceptanceConfig):
        raise TypeError("config must be ExactCheckoutAcceptanceConfig")
    _assert_expected_git_sha(config)
    _build_ready_source_snapshot(config.repo_root)
    raise RuntimeError("ACCEPTANCE_EXECUTION_NOT_IMPLEMENTED")
