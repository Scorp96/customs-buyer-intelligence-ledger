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
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CANDIDATE_TOOL = "append_candidate_discovery"
_CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"


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
            "product_profile_id": "PVC_FOAM_BOARD",
        },
        "idempotency_key": "v63-exact-candidate-success-0001",
    }


def _run_candidate_success_scenario(
    repo_root: Path,
    persistence_root: Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    persistence = Path(persistence_root).resolve()
    harness = ExactCheckoutMcpHarness(root, persistence)
    harness.start()
    try:
        started = harness.tool(
            2,
            "start_investigation",
            {
                "account": {
                    "account_id": "C-V63-EXACT-CANDIDATE",
                    "country": "Synthetic",
                    "name": "Synthetic v6.3 Exact Candidate Buyer",
                },
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
                "network_policy": {"closure_strategy": "DECISION_SATURATION"},
                "idempotency_key": "v63-exact-candidate-start-0001",
            },
        )
        investigation_id = str(started.get("investigation_id") or "").strip()
        if not investigation_id:
            raise RuntimeError("CANDIDATE_SUCCESS_INVESTIGATION_ID_MISSING")
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


def run_v63_exact_checkout_live_acceptance(
    config: ExactCheckoutAcceptanceConfig,
) -> dict[str, Any]:
    if not isinstance(config, ExactCheckoutAcceptanceConfig):
        raise TypeError("config must be ExactCheckoutAcceptanceConfig")
    _assert_expected_git_sha(config)
    _build_ready_source_snapshot(config.repo_root)
    raise RuntimeError("ACCEPTANCE_EXECUTION_NOT_IMPLEMENTED")
