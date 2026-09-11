#!/usr/bin/env python3
"""Pure validation/normalization for Social + Global Radar candidate intake.

This module deliberately performs no Runtime construction, MCP mutation, CRM write,
or outreach action. It only validates an upstream candidate bundle and returns a
normalized copy plus a deterministic content fingerprint.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any


SCHEMA_VERSION = "cbi.social-radar-candidate.v1"
ALLOWED_STAGES = {"SOCIAL", "GLOBAL_RADAR", "SOCIAL_AND_RADAR"}
ALLOWED_PLATFORMS = {
    "INSTAGRAM",
    "TIKTOK",
    "WEB",
    "B2B",
    "INDUSTRY_MEDIA",
    "SEARCH_TREND",
}
ALLOWED_ENTITY_TYPES = {"COMPANY", "PERSON", "CREATOR", "UNKNOWN"}
ALLOWED_SOURCE_GRADES = {"REJECT", "C", "B", "B+", "A-CANDIDATE", "A+-CANDIDATE"}
ALLOWED_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT_RESEARCH"}
FORBIDDEN_FINAL_AUTHORITY_FIELDS = {
    "final_grade",
    "cbi_grade",
    "commercial_value",
    "research_confidence",
    "outreach_readiness",
    "decision_saturation",
}


class SocialRadarIntakeError(ValueError):
    """Fail-closed validation error for an upstream candidate bundle."""


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SocialRadarIntakeError(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise SocialRadarIntakeError(f"{field} must be an array")
    return value


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SocialRadarIntakeError(f"{field} must be a string")
    text = value.strip()
    if not text and not allow_empty:
        raise SocialRadarIntakeError(f"{field} must not be empty")
    return text


def _confidence(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SocialRadarIntakeError(f"{field} must be numeric")
    number = float(value)
    if number < 0.0 or number > 1.0:
        raise SocialRadarIntakeError(f"{field} must be between 0 and 1")
    return number


def _score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SocialRadarIntakeError(f"{field} must be numeric")
    number = float(value)
    if number < 0.0 or number > 100.0:
        raise SocialRadarIntakeError(f"{field} must be between 0 and 100")
    return number


def _datetime(value: Any, field: str) -> str:
    text = _text(value, field)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise SocialRadarIntakeError(f"{field} must be an ISO-8601 date-time") from exc
    if parsed.tzinfo is None:
        raise SocialRadarIntakeError(f"{field} must be timezone-aware")
    return text


def _platform(value: Any, field: str) -> str:
    platform = _text(value, field).upper()
    if platform not in ALLOWED_PLATFORMS:
        raise SocialRadarIntakeError(f"{field} has unsupported platform {platform}")
    return platform


def _canonical_bytes(bundle: dict[str, Any]) -> bytes:
    material = copy.deepcopy(bundle)
    material.pop("candidate_fingerprint", None)
    return json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def candidate_fingerprint(bundle: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 over canonical JSON key ordering."""

    if not isinstance(bundle, dict):
        raise SocialRadarIntakeError("candidate bundle must be an object")
    return hashlib.sha256(_canonical_bytes(bundle)).hexdigest()


def _validate_identity(bundle: dict[str, Any]) -> None:
    identity = _mapping(bundle.get("canonical_identity"), "canonical_identity")
    identity["display_name"] = _text(identity.get("display_name"), "canonical_identity.display_name")
    identity["normalized_name"] = _text(identity.get("normalized_name"), "canonical_identity.normalized_name")
    entity_type = _text(identity.get("entity_type"), "canonical_identity.entity_type").upper()
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise SocialRadarIntakeError("canonical_identity.entity_type is unsupported")
    identity["entity_type"] = entity_type
    identity["confidence"] = _confidence(identity.get("confidence"), "canonical_identity.confidence")


def _validate_profiles(bundle: dict[str, Any]) -> None:
    profiles = _list(bundle.get("profiles"), "profiles")
    for index, raw in enumerate(profiles):
        profile = _mapping(raw, f"profiles[{index}]")
        profile["platform"] = _platform(profile.get("platform"), f"profiles[{index}].platform")
        profile["profile_id"] = _text(
            profile.get("profile_id", ""), f"profiles[{index}].profile_id", allow_empty=True
        )
        profile["url"] = _text(profile.get("url"), f"profiles[{index}].url")


def _validate_evidence(bundle: dict[str, Any]) -> set[str]:
    evidence_rows = _list(bundle.get("evidence"), "evidence")
    if not evidence_rows:
        raise SocialRadarIntakeError("at least one item of direct evidence is required")
    evidence_ids: set[str] = set()
    for index, raw in enumerate(evidence_rows):
        row = _mapping(raw, f"evidence[{index}]")
        evidence_id = _text(row.get("evidence_id"), f"evidence[{index}].evidence_id")
        if evidence_id in evidence_ids:
            raise SocialRadarIntakeError(f"duplicate evidence_id {evidence_id}")
        evidence_ids.add(evidence_id)
        row["evidence_id"] = evidence_id
        row["evidence_type"] = _text(row.get("evidence_type"), f"evidence[{index}].evidence_type")
        if "value" not in row:
            raise SocialRadarIntakeError(f"evidence[{index}].value is required")
        row["source_url"] = _text(row.get("source_url"), f"evidence[{index}].source_url")
        row["source_platform"] = _platform(
            row.get("source_platform"), f"evidence[{index}].source_platform"
        )
        row["observed_at"] = _datetime(row.get("observed_at"), f"evidence[{index}].observed_at")
        row["confidence"] = _confidence(row.get("confidence"), f"evidence[{index}].confidence")
    return evidence_ids


def _validate_inferences(bundle: dict[str, Any], evidence_ids: set[str]) -> None:
    rows = _list(bundle.get("inferences"), "inferences")
    inference_ids: set[str] = set()
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"inferences[{index}]")
        inference_id = _text(row.get("inference_id"), f"inferences[{index}].inference_id")
        if inference_id in inference_ids:
            raise SocialRadarIntakeError(f"duplicate inference_id {inference_id}")
        inference_ids.add(inference_id)
        row["inference_id"] = inference_id
        row["claim"] = _text(row.get("claim"), f"inferences[{index}].claim")
        row["confidence"] = _confidence(row.get("confidence"), f"inferences[{index}].confidence")
        basis = _list(row.get("basis_evidence_ids"), f"inferences[{index}].basis_evidence_ids")
        if not basis:
            raise SocialRadarIntakeError(f"inferences[{index}] must reference direct evidence")
        normalized_basis = [_text(item, f"inferences[{index}].basis_evidence_ids") for item in basis]
        unknown = sorted(set(normalized_basis) - evidence_ids)
        if unknown:
            raise SocialRadarIntakeError(
                f"inferences[{index}] references unknown evidence: {', '.join(unknown)}"
            )
        row["basis_evidence_ids"] = normalized_basis
        row["reason_code"] = _text(row.get("reason_code"), f"inferences[{index}].reason_code")


def _validate_routes(bundle: dict[str, Any]) -> None:
    rows = _list(bundle.get("routes"), "routes")
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"routes[{index}]")
        for field in ("route_type", "route_value", "source", "purpose", "validation_status"):
            row[field] = _text(row.get(field), f"routes[{index}].{field}")
        row["confidence"] = _confidence(row.get("confidence"), f"routes[{index}].confidence")


def _validate_discovery(bundle: dict[str, Any]) -> None:
    discovery = _mapping(bundle.get("discovery"), "discovery")
    for field in ("market", "language", "keyword", "semantic_cluster"):
        discovery[field] = _text(discovery.get(field), f"discovery.{field}")
    discovery["source_platform"] = _platform(discovery.get("source_platform"), "discovery.source_platform")
    graph_depth = discovery.get("graph_depth")
    if graph_depth is not None:
        if isinstance(graph_depth, bool) or not isinstance(graph_depth, int) or graph_depth < 0:
            raise SocialRadarIntakeError("discovery.graph_depth must be a non-negative integer or null")
    if "trend_window" in discovery and discovery["trend_window"] is not None:
        discovery["trend_window"] = _text(discovery["trend_window"], "discovery.trend_window")


def _validate_source_score(bundle: dict[str, Any]) -> None:
    source_score = _mapping(bundle.get("source_score"), "source_score")
    forbidden = sorted(FORBIDDEN_FINAL_AUTHORITY_FIELDS.intersection(source_score))
    if forbidden:
        raise SocialRadarIntakeError(
            "source bundle may not assert final CBI grade/authority fields: " + ", ".join(forbidden)
        )
    grade = _text(source_score.get("grade"), "source_score.grade").upper()
    if grade in {"A", "A+"}:
        raise SocialRadarIntakeError("source bundle may not assert final CBI grade A/A+")
    if grade not in ALLOWED_SOURCE_GRADES:
        raise SocialRadarIntakeError(f"source_score.grade is unsupported: {grade}")
    source_score["grade"] = grade
    source_score["score"] = _score(source_score.get("score"), "source_score.score")
    components = _mapping(source_score.get("components"), "source_score.components")
    for name, value in list(components.items()):
        components[name] = _score(value, f"source_score.components.{name}")


def validate_and_normalize_social_radar_candidate(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate an upstream bundle and return a normalized deep copy.

    The result is safe to hand to later CBI research orchestration, but this
    function itself performs no durable or external side effect.
    """

    if not isinstance(bundle, dict):
        raise SocialRadarIntakeError("candidate bundle must be an object")
    normalized = copy.deepcopy(bundle)

    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise SocialRadarIntakeError(f"schema_version must equal {SCHEMA_VERSION}")
    normalized["candidate_id"] = _text(normalized.get("candidate_id"), "candidate_id")
    normalized["observed_at"] = _datetime(normalized.get("observed_at"), "observed_at")

    stage = _text(normalized.get("source_stage"), "source_stage").upper()
    if stage not in ALLOWED_STAGES:
        raise SocialRadarIntakeError(f"unsupported source_stage {stage}")
    normalized["source_stage"] = stage

    _validate_identity(normalized)
    _validate_profiles(normalized)
    evidence_ids = _validate_evidence(normalized)
    _validate_inferences(normalized, evidence_ids)
    _validate_routes(normalized)
    _validate_discovery(normalized)
    _validate_source_score(normalized)

    priority = _text(normalized.get("recommended_cbi_priority"), "recommended_cbi_priority").upper()
    if priority not in ALLOWED_PRIORITIES:
        raise SocialRadarIntakeError(f"unsupported recommended_cbi_priority {priority}")
    normalized["recommended_cbi_priority"] = priority

    if stage == "SOCIAL":
        social_platforms = {p.get("platform") for p in normalized["profiles"]}
        if not social_platforms.intersection({"INSTAGRAM", "TIKTOK"}):
            raise SocialRadarIntakeError("SOCIAL bundle requires an Instagram or TikTok profile")

    normalized["candidate_fingerprint"] = candidate_fingerprint(normalized)
    return normalized
