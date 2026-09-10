from __future__ import annotations

import re
from typing import Any

from .product_profiles import get_product_profile
from .render_r2_pvc_acceptance_v63 import (
    MUTATION_EVENT_TYPES,
    PERSISTENCE_PROBE_SCHEMA,
    PVC_ACCEPTANCE_SCHEMA,
)


PVC_ACCEPTANCE_VALIDATION_SCHEMA = (
    "cbi.render-r2-pvc-acceptance-validation.v6.3"
)
_DEPLOYMENT_IDENTITY_SCHEMA = "cbi.remote-deployment-identity.v6.3"
_OBJECT_STATE_SCHEMA_V2 = "cbi.object-store-state.v2"
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SENSITIVE_KEY_MARKERS = (
    "idempotency_key",
    "bearer_token",
    "secret_access_key",
    "access_key_id",
    "authorization",
    "credential",
    "password",
    "api_key",
    "private_key",
    "client_secret",
)


def _normalized_key(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_")


def _sensitive_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            child_path = f"{path}.{key}"
            if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
                found.append(child_path)
            found.extend(_sensitive_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_sensitive_paths(child, f"{path}[{index}]"))
    elif isinstance(value, tuple):
        for index, child in enumerate(value):
            found.extend(_sensitive_paths(child, f"{path}[{index}]"))
    return found


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _valid_nonnegative_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _append(blockers: list[str], value: str) -> None:
    if value not in blockers:
        blockers.append(value)


def _validate_health(
    blockers: list[str],
    health: Any,
    *,
    label: str,
    require_v2: bool = True,
) -> tuple[str, dict[str, Any]]:
    row = _mapping(health)
    identity = _mapping(row.get("deployment_identity"))
    git_sha = str(identity.get("git_sha") or "").strip().lower()
    if _GIT_SHA_RE.fullmatch(git_sha) is None:
        _append(blockers, f"DEPLOYMENT_GIT_SHA_INVALID:{label}")
    if identity.get("schema") != _DEPLOYMENT_IDENTITY_SCHEMA:
        _append(blockers, f"DEPLOYMENT_IDENTITY_SCHEMA_INVALID:{label}")
    if identity.get("git_sha_source") != "RENDER_GIT_COMMIT":
        _append(blockers, f"DEPLOYMENT_GIT_SHA_SOURCE_INVALID:{label}")
    if identity.get("acceptance_pin_required") is not True:
        _append(blockers, f"DEPLOYMENT_SHA_PIN_NOT_REQUIRED:{label}")
    if str(identity.get("object_store_mode") or "").lower() != "r2":
        _append(blockers, f"R2_OBJECT_STORE_MODE_INVALID:{label}")
    object_state_schema = identity.get("object_state_schema")
    if require_v2:
        if object_state_schema != _OBJECT_STATE_SCHEMA_V2:
            _append(blockers, f"R2_OBJECT_STATE_SCHEMA_INVALID:{label}")
    elif object_state_schema != _OBJECT_STATE_SCHEMA_V2:
        restore_source = str(identity.get("restore_source") or "").strip()
        if object_state_schema is not None or restore_source != "migration_v1":
            _append(blockers, f"R2_OBJECT_STATE_SCHEMA_INVALID:{label}")
    generation = identity.get("object_state_generation")
    if not _valid_nonnegative_int(generation):
        persistence = _mapping(row.get("object_store_persistence"))
        generation = persistence.get("generation")
    if not _valid_nonnegative_int(generation):
        _append(blockers, f"R2_GENERATION_INVALID:{label}")
    if str(row.get("status") or "").lower() != "ok":
        _append(blockers, f"REMOTE_HEALTH_NOT_OK:{label}")
    return git_sha, identity


def _validate_profile(blockers: list[str], receipt: dict[str, Any]) -> None:
    expected = get_product_profile("PVC")
    observed = _mapping(receipt.get("product_profile"))
    if observed.get("profile_id") != "PVC":
        _append(blockers, "PVC_PROFILE_ID_INVALID")
    if str(observed.get("profile_version") or "") != str(
        expected["profile_version"]
    ):
        _append(blockers, "PVC_PROFILE_VERSION_INVALID")
    if str(observed.get("profile_sha256") or "").lower() != str(
        expected["profile_sha256"]
    ).lower():
        _append(blockers, "PVC_PROFILE_SHA256_INVALID")


def _validate_replacement(
    blockers: list[str],
    receipt: dict[str, Any],
    before_identity: dict[str, Any],
    after_identity: dict[str, Any],
) -> int | None:
    replacement = _mapping(receipt.get("replacement"))
    before_instance = str(replacement.get("instance_before") or "").strip()
    after_instance = str(replacement.get("instance_after") or "").strip()
    restored_generation = replacement.get("restored_generation")
    restore_source = str(replacement.get("restore_source") or "").strip()
    if (
        not before_instance
        or not after_instance
        or before_instance == after_instance
        or not _valid_nonnegative_int(restored_generation)
        or restore_source != "object_state_v2"
    ):
        _append(blockers, "R2_RESTORE_LINEAGE_INVALID")
        return None

    evidence_before = _mapping(receipt.get("evidence_before"))
    source_generation = evidence_before.get("generation")
    if not _valid_nonnegative_int(source_generation):
        _append(blockers, "R2_RESTORE_LINEAGE_SOURCE_GENERATION_INVALID")
    elif restored_generation != source_generation:
        _append(blockers, "R2_RESTORE_LINEAGE_GENERATION_MISMATCH")

    after_restore = after_identity.get("restore_generation")
    if after_restore is not None and after_restore != restored_generation:
        _append(blockers, "R2_RESTORE_LINEAGE_HEALTH_MISMATCH")
    after_source = after_identity.get("restore_source")
    if after_source is not None and str(after_source) != "object_state_v2":
        _append(blockers, "R2_RESTORE_LINEAGE_HEALTH_SOURCE_INVALID")

    before_generation = before_identity.get("object_state_generation")
    if (
        _valid_nonnegative_int(before_generation)
        and _valid_nonnegative_int(restored_generation)
        and restored_generation < 0
    ):
        _append(blockers, "R2_RESTORE_LINEAGE_GENERATION_INVALID")
    return int(restored_generation)


def _mutation_exact(
    blockers: list[str],
    receipt: dict[str, Any],
    tool: str,
) -> bool:
    expectations = _mapping(receipt.get("mutation_expectations"))
    expected = _mapping(expectations.get(tool))
    expected_event = str(expected.get("event_type") or "")
    expected_sha = str(expected.get("request_sha256") or "").lower()
    if expected_event != MUTATION_EVENT_TYPES[tool]:
        _append(blockers, f"EXPECTED_EVENT_TYPE_INVALID:{tool}")
    if _SHA256_RE.fullmatch(expected_sha) is None:
        _append(blockers, f"EXACT_REQUEST_HASH_EXPECTATION_INVALID:{tool}")

    evidence_before = _mapping(receipt.get("evidence_before"))
    evidence_after = _mapping(receipt.get("evidence_after"))
    if evidence_before.get("schema") != PERSISTENCE_PROBE_SCHEMA:
        _append(blockers, "R2_EVIDENCE_BEFORE_SCHEMA_INVALID")
    if evidence_after.get("schema") != PERSISTENCE_PROBE_SCHEMA:
        _append(blockers, "R2_EVIDENCE_AFTER_SCHEMA_INVALID")

    event_before = _mapping(_mapping(evidence_before.get("events")).get(tool))
    event_after = _mapping(_mapping(evidence_after.get("events")).get(tool))
    wal_before = _mapping(_mapping(evidence_before.get("wal")).get(tool))
    wal_after = _mapping(_mapping(evidence_after.get("wal")).get(tool))

    exact = True
    for phase, event in (("before", event_before), ("after", event_after)):
        if event.get("count") != 1:
            _append(blockers, f"DUPLICATE_BUSINESS_EVENT:{tool}:{phase}")
            exact = False
        if str(event.get("event_type") or "") != MUTATION_EVENT_TYPES[tool]:
            _append(blockers, f"EVENT_TYPE_MISMATCH:{tool}:{phase}")
            exact = False
        if str(event.get("request_sha256") or "").lower() != expected_sha:
            _append(blockers, f"EXACT_REQUEST_HASH_MISMATCH:{tool}:{phase}:event")
            exact = False

    for phase, wal in (("before", wal_before), ("after", wal_after)):
        if str(wal.get("status") or "").upper() != "COMMITTED":
            _append(blockers, f"WAL_NOT_COMMITTED:{tool}:{phase}")
            exact = False
        if str(wal.get("request_sha256") or "").lower() != expected_sha:
            _append(blockers, f"EXACT_REQUEST_HASH_MISMATCH:{tool}:{phase}:wal")
            exact = False

    for phase, event, wal in (
        ("before", event_before, wal_before),
        ("after", event_after, wal_after),
    ):
        event_correlation = str(event.get("correlation_id") or "").strip()
        wal_correlation = str(wal.get("correlation_id") or "").strip()
        if not event_correlation or event_correlation != wal_correlation:
            _append(blockers, f"EXACT_CORRELATION_MISMATCH:{tool}:{phase}")
            exact = False

    if str(event_before.get("correlation_id") or "") != str(
        event_after.get("correlation_id") or ""
    ):
        _append(blockers, f"EXACT_CORRELATION_CHANGED_AFTER_RESTORE:{tool}")
        exact = False
    if str(event_before.get("request_sha256") or "").lower() != str(
        event_after.get("request_sha256") or ""
    ).lower():
        _append(blockers, f"EXACT_REQUEST_HASH_CHANGED_AFTER_RESTORE:{tool}")
        exact = False
    if event_before.get("seq") != event_after.get("seq"):
        _append(blockers, f"DUPLICATE_BUSINESS_EVENT_SEQ_CHANGED:{tool}")
        exact = False

    replay = _mapping(_mapping(receipt.get("replay_responses")).get(tool))
    replay_meta = _mapping(replay.get("mutation_meta"))
    if replay_meta.get("replayed") is not True:
        _append(blockers, f"IDEMPOTENT_REPLAY_NOT_PROVEN:{tool}")
        exact = False
    return exact


def validate_v63_render_r2_pvc_acceptance(receipt: Any) -> dict[str, Any]:
    blockers: list[str] = []
    sensitive = _sensitive_paths(receipt)
    for path in sensitive:
        _append(blockers, f"SENSITIVE_FIELD_EXPOSED:{path}")

    row = _mapping(receipt)
    if row.get("schema") != PVC_ACCEPTANCE_SCHEMA:
        _append(blockers, "PVC_ACCEPTANCE_SCHEMA_INVALID")
    if row.get("production_ready") is not False:
        _append(blockers, "PRODUCTION_READY_MUST_REMAIN_FALSE")

    _validate_profile(blockers, row)
    before_sha, before_identity = _validate_health(
        blockers, row.get("health_before"), label="before", require_v2=False
    )
    after_sha, after_identity = _validate_health(
        blockers, row.get("health_after"), label="after"
    )
    if before_sha and after_sha and before_sha != after_sha:
        _append(blockers, "DEPLOYMENT_GIT_SHA_CHANGED_AFTER_RESTORE")

    if before_identity.get("object_state_schema") != _OBJECT_STATE_SCHEMA_V2:
        evidence_before = _mapping(row.get("evidence_before"))
        if evidence_before.get("archive_format") != "object_state_v2":
            _append(blockers, "R2_EVIDENCE_BEFORE_ARCHIVE_FORMAT_INVALID")

    _validate_replacement(blockers, row, before_identity, after_identity)

    planning = _mapping(row.get("planning"))
    if planning.get("tool") != "plan_candidate_expansion":
        _append(blockers, "PVC_DEMAND_EXPANSION_PLANNING_MISSING")
    if planning.get("product_profile_id") != "PVC":
        _append(blockers, "PVC_DEMAND_EXPANSION_PROFILE_INVALID")

    verified = 0
    for tool in MUTATION_EVENT_TYPES:
        if _mutation_exact(blockers, row, tool):
            verified += 1

    status = "VERIFIED" if not blockers and verified == len(MUTATION_EVENT_TYPES) else "BLOCKED"
    return {
        "schema": PVC_ACCEPTANCE_VALIDATION_SCHEMA,
        "status": status,
        "blockers": sorted(blockers),
        "verified_mutation_count": verified,
        "production_ready": False,
    }
