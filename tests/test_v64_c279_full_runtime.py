from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
from unittest.mock import patch

from scripts.discover_v64_positive_route_candidate import (
    _named_lane_bound,
    route_is_fully_qualified,
)


_DIAGNOSTIC_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_EMAIL_CANDIDATE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_CANDIDATE_RE = re.compile(r"^\+?[0-9][0-9\s().-]{5,}$")
_WEB_CANDIDATE_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
_MISSING = object()
_C279_INTEGRATED_BASE_SHA = "17f4fe160c0908a602224eab95d172ba4eb753c6"
_C279_EXACT_DELTA_PATHS = frozenset({
    ".github/workflows/cbi-v64-c279-authoritative-isolated.yml",
    ".github/workflows/cbi-v64-positive-route-authoritative-isolated.yml",
    ".github/workflows/cbi-v64-positive-route-discovery.yml",
    "scripts/capture_v64_c279_single_session.py",
    "scripts/discover_v64_positive_route_candidate.py",
    "tests/test_v61_research_orchestration_hardening.py",
    "tests/test_v64_c279_capture.py",
    "tests/test_v64_c279_full_runtime.py",
    "tests/test_v64_positive_route_discovery.py",
    "unified_runtime/research_orchestration_hardening.py",
})
_SHAPE_PATHS = (
    "value",
    "value.channel",
    "value.kind",
    "value.value",
    "value.verified",
    "value.masked",
    "value.guessed",
    "value.channel_proof",
    "value.email",
    "value.phone",
    "value.whatsapp",
    "value.zalo",
    "value.social",
    "value.form",
    "value.contact",
    "value.contact.email",
    "value.contact.phone",
    "value.contact.whatsapp",
    "value.contact.zalo",
    "value.contact.social",
    "value.contact.form",
    "contact",
    "contact.email",
    "contact.phone",
    "contact.whatsapp",
    "contact.zalo",
    "contact.social",
    "contact.form",
    "contact_info",
    "contact_info.email",
    "contact_info.phone",
    "contact_info.whatsapp",
    "contact_info.zalo",
    "contact_info.social",
    "contact_info.form",
    "source",
    "source.freshness",
)
_CANDIDATE_PATH_TYPES = (
    ("value.value", "GENERIC"),
    ("value.email", "EMAIL"),
    ("value.phone", "PHONE"),
    ("value.whatsapp", "WHATSAPP"),
    ("value.zalo", "WHATSAPP"),
    ("value.social", "SOCIAL"),
    ("value.form", "FORM"),
    ("value.contact.email", "EMAIL"),
    ("value.contact.phone", "PHONE"),
    ("value.contact.whatsapp", "WHATSAPP"),
    ("value.contact.zalo", "WHATSAPP"),
    ("value.contact.social", "SOCIAL"),
    ("value.contact.form", "FORM"),
    ("contact.email", "EMAIL"),
    ("contact.phone", "PHONE"),
    ("contact.whatsapp", "WHATSAPP"),
    ("contact.zalo", "WHATSAPP"),
    ("contact.social", "SOCIAL"),
    ("contact.form", "FORM"),
    ("contact_info.email", "EMAIL"),
    ("contact_info.phone", "PHONE"),
    ("contact_info.whatsapp", "WHATSAPP"),
    ("contact_info.zalo", "WHATSAPP"),
    ("contact_info.social", "SOCIAL"),
    ("contact_info.form", "FORM"),
)


def _diagnostic_codes(values: object) -> list[str]:
    codes: list[str] = []
    for value in values if isinstance(values, list) else []:
        code = str(value or "").strip().upper()
        if not _DIAGNOSTIC_CODE_RE.fullmatch(code):
            raise ValueError("ROUTE_PROJECTION_DIAGNOSTIC_CODE_INVALID")
        codes.append(code)
    return sorted(set(codes))


def _diagnostic_optional_code(value: object) -> str | None:
    code = str(value or "").strip().upper()
    if not code:
        return None
    if not _DIAGNOSTIC_CODE_RE.fullmatch(code):
        raise ValueError("ROUTE_PROJECTION_DIAGNOSTIC_CODE_INVALID")
    return code


def _diagnostic_ids(values: object) -> list[str]:
    identifiers: list[str] = []
    for value in values if isinstance(values, list) else []:
        identifier = str(value or "").strip()
        if not identifier:
            raise ValueError("ROUTE_PROJECTION_DIAGNOSTIC_ID_INVALID")
        identifiers.append(identifier)
    return sorted(set(identifiers))


def _fixed_path_value(value: object, path: str) -> object:
    current = value
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _shape_classification(value: object) -> str:
    if value is _MISSING:
        return "MISSING"
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, str):
        return "STRING"
    if isinstance(value, dict):
        return "OBJECT"
    if isinstance(value, list):
        return "ARRAY"
    if isinstance(value, (int, float)):
        return "NUMBER"
    return "OTHER"


def _recognizable_candidate(value: object, expected_type: str) -> tuple[str, bool]:
    if not isinstance(value, str):
        return expected_type, False
    if expected_type == "GENERIC":
        if _EMAIL_CANDIDATE_RE.fullmatch(value):
            return "EMAIL", True
        if _PHONE_CANDIDATE_RE.fullmatch(value):
            return "PHONE", True
        return "GENERIC", False
    if expected_type == "EMAIL":
        return expected_type, _EMAIL_CANDIDATE_RE.fullmatch(value) is not None
    if expected_type in {"PHONE", "WHATSAPP"}:
        return expected_type, _PHONE_CANDIDATE_RE.fullmatch(value) is not None
    if expected_type in {"SOCIAL", "FORM"}:
        return expected_type, _WEB_CANDIDATE_RE.fullmatch(value) is not None
    raise ValueError("ROUTE_SCHEMA_SHAPE_PATH_INVALID")


def _sanitize_route_schema_shape_diagnostics(
    route_projection: object,
    state: object,
) -> dict[str, object]:
    projection = dict(route_projection) if isinstance(route_projection, dict) else {}
    runtime_state = dict(state) if isinstance(state, dict) else {}
    if projection.get("contains_route_values") is not False:
        raise ValueError("ROUTE_PROJECTION_CONTAINS_VALUES")

    start = runtime_state.get("start")
    account = start.get("account") if isinstance(start, dict) else None
    account_id = str(account.get("account_id") or "") if isinstance(account, dict) else ""
    observations = runtime_state.get("observations")
    observation_map = observations if isinstance(observations, dict) else {}
    shape_rows: list[dict[str, object]] = []
    for observation_id in _diagnostic_ids(projection.get("claim_observation_ids")):
        observation = observation_map.get(observation_id)
        if not isinstance(observation, dict):
            shape_rows.append({
                "observation_id": observation_id,
                "observation_available": False,
                "field_path_classifications": [],
                "candidate_pattern_counts": {"EMAIL": 0, "PHONE": 0, "WHATSAPP": 0, "SOCIAL": 0, "FORM": 0},
                "candidate_bindings": [],
            })
            continue

        source = observation.get("source")
        freshness = str(source.get("freshness") or "").strip().upper() if isinstance(source, dict) else ""
        account_bound = (
            observation.get("owner_type") == "ACCOUNT"
            and str(observation.get("owner_id") or "") == account_id
        )
        evidence_bound = bool(str(observation.get("evidence_id") or "").strip())
        strong_direct_freshness = freshness in {"CURRENT", "CURRENT_CONFIRMED"}
        field_paths = [
            {"path": path, "classification": _shape_classification(_fixed_path_value(observation, path))}
            for path in _SHAPE_PATHS
        ]
        counts = {"EMAIL": 0, "PHONE": 0, "WHATSAPP": 0, "SOCIAL": 0, "FORM": 0}
        candidates: list[dict[str, object]] = []
        for path, expected_type in _CANDIDATE_PATH_TYPES:
            candidate_type, recognizable = _recognizable_candidate(
                _fixed_path_value(observation, path), expected_type
            )
            if recognizable and candidate_type in counts:
                counts[candidate_type] += 1
            candidates.append({
                "path": path,
                "candidate_type": candidate_type,
                "recognizable": recognizable,
                "bound_to_account": account_bound,
                "bound_to_evidence": evidence_bound,
                "strong_direct_freshness": strong_direct_freshness,
            })
        shape_rows.append({
            "observation_id": observation_id,
            "observation_available": True,
            "field_path_classifications": field_paths,
            "candidate_pattern_counts": counts,
            "candidate_bindings": candidates,
        })
    return {
        "schema": "cbi.v64-c279-route-schema-shape-diagnostic.v1",
        "contains_route_values": False,
        "observations": shape_rows,
    }


def _sanitize_route_projection_diagnostics(
    route_projection: object,
    outreach: object,
) -> dict[str, object]:
    projection = dict(route_projection) if isinstance(route_projection, dict) else {}
    readiness_view = dict(outreach) if isinstance(outreach, dict) else {}
    if projection.get("contains_route_values") is not False:
        raise ValueError("ROUTE_PROJECTION_CONTAINS_VALUES")

    observations: list[dict[str, object]] = []
    for row in projection.get("observations") if isinstance(projection.get("observations"), list) else []:
        if not isinstance(row, dict):
            raise ValueError("ROUTE_PROJECTION_DIAGNOSTIC_ROW_INVALID")
        evidence_id = str(row.get("evidence_id") or "").strip() or None
        observations.append({
            "observation_id": _diagnostic_ids([row.get("observation_id")])[0],
            "evidence_id": evidence_id,
            "freshness": _diagnostic_optional_code(row.get("freshness")),
            "rejection_reasons": _diagnostic_codes(row.get("rejection_reasons")),
        })

    routes = readiness_view.get("canonical_route_view")
    route_rows = routes if isinstance(routes, list) else []
    route_evidence_ids: list[str] = []
    route_source_types = _diagnostic_codes(readiness_view.get("canonical_route_sources"))
    if not route_source_types:
        route_source_types = _diagnostic_codes([
            row.get("route_source") for row in route_rows if isinstance(row, dict)
        ])
    for row in route_rows:
        if isinstance(row, dict):
            route_evidence_ids.extend(_diagnostic_ids(row.get("evidence_ids")))

    return {
        "route_projection_diagnostics": {
            "status": _diagnostic_optional_code(projection.get("status")),
            "claim_state": _diagnostic_optional_code(projection.get("claim_state")),
            "claim_observation_ids": _diagnostic_ids(projection.get("claim_observation_ids")),
            "claim_evidence_ids": _diagnostic_ids(projection.get("claim_evidence_ids")),
            "observations": observations,
            "contains_route_values": False,
            "mutates_history": bool(projection.get("mutates_history")),
        },
        "readiness": _diagnostic_optional_code(
            readiness_view.get("outreach_readiness") or readiness_view.get("readiness") or "UNKNOWN"
        ),
        "block_reason_codes": _diagnostic_codes(readiness_view.get("block_reasons")),
        "canonical_route_count": len(route_rows),
        "canonical_route_source_types": route_source_types,
        "canonical_route_observation_ids": _diagnostic_ids(
            readiness_view.get("valid_company_route_observation_ids")
        ),
        "canonical_route_information_ids": _diagnostic_ids(
            readiness_view.get("valid_information_route_ids")
        ),
        "canonical_route_evidence_ids": sorted(set(route_evidence_ids)),
    }


def _write_route_projection_diagnostics(path_value: str, diagnostics: dict[str, object]) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(diagnostics, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


_ACCEPTANCE_CASE_KINDS = frozenset({"NEGATIVE_SAFETY", "POSITIVE_ROUTE"})
_READINESS_RANK = {
    "BLOCKED": 0,
    "IDENTITY_ONLY": 1,
    "COMPANY_ROUTE_READY": 2,
    "NAMED_ROUTE_READY": 3,
    "FOLLOW_UP_READY": 4,
    "SEND_READY": 5,
}
_RECOGNIZED_ROUTE_CHANNELS = frozenset({"EMAIL", "PHONE", "WHATSAPP", "ZALO", "SOCIAL", "FORM"})
_C279_REQUIRED_REJECTION_CODES = frozenset({
    "ROUTE_NOT_VERIFIED", "ROUTE_VALUE_REQUIRED", "UNSUPPORTED_ROUTE_CHANNEL",
})
_POSITIVE_DRAFT_ONLY_BODY = (
    "Hello, I’m contacting your company from XingHuai New Materials. We manufacture PVC foam board and related "
    "rigid panel materials for distribution, cabinetry, interior fabrication, signage, and sheet applications. I would "
    "like to understand whether your purchasing team is open to evaluating an additional qualified supply source. We "
    "can provide a concise product overview, technical specifications, and samples only when your team confirms what "
    "is relevant. Please let me know the best colleague for purchasing or sourcing rigid sheet materials, and whether "
    "an introductory discussion would be useful. If this category is not relevant, no further action is needed. Thank "
    "you for your time and consideration. Best regards, Mark Zhou."
)


def _acceptance_reason_codes(values: object) -> list[str]:
    return _diagnostic_codes(values)


def _positive_route_precondition(routes: object, account_id: object) -> dict[str, int]:
    """Count safety properties without returning route rows or values.

    `route_is_fully_qualified` is the single-row safety authority. This
    aggregate keeps the diagnostic counters but never combines facts from
    different rows.
    """
    exact_account_id = str(account_id or "").strip()
    recognized = 0
    current_verified_account_owned = 0
    evidence_bound = 0
    fully_qualified = 0
    named_qualified = 0
    for route in routes if isinstance(routes, list) else []:
        if not isinstance(route, dict):
            continue
        channel = str(route.get("channel") or route.get("kind") or "").strip().upper()
        if channel not in _RECOGNIZED_ROUTE_CHANNELS:
            continue
        value = route.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        recognized += 1
        account_owned = bool(exact_account_id) and (
            route.get("owned_by_account") is True
            and str(route.get("owner_entity_id") or "").strip() == exact_account_id
        )
        current_verified = route.get("current") is True and route.get("verified") is True
        if not (account_owned and current_verified):
            continue
        current_verified_account_owned += 1
        evidence_ids = {
            str(item).strip()
            for item in (route.get("evidence_ids") if isinstance(route.get("evidence_ids"), list) else [])
            if str(item).strip()
        }
        if not evidence_ids:
            continue
        evidence_bound += 1
        if not route_is_fully_qualified(route, exact_account_id):
            continue
        fully_qualified += 1
        if route_is_fully_qualified(route, exact_account_id, require_named_person=True):
            named_qualified += 1
    return {
        "recognized_route_count": recognized,
        "current_verified_account_owned_count": current_verified_account_owned,
        "evidence_bound_count": evidence_bound,
        "fully_qualified_route_count": fully_qualified,
        "named_qualified_route_count": named_qualified,
    }


def _is_eligible_named_route(route: object, account_id: object, readiness: object) -> bool:
    """Require one fully qualified row plus its exact named lane binding."""
    return (
        route_is_fully_qualified(route, account_id, require_named_person=True)
        and _named_lane_bound(route, readiness)
    )


def _isolated_positive_closure_gate(closure: object) -> dict[str, object]:
    """Return a fixed, non-identifying gate for an isolated draft-only probe.

    A captured source may contain no closure.  The only permitted evaluation is
    in the disposable runtime copy, and it must never invent an id or authorize
    a draft merely because a route is usable.  Do not include the closure id in
    this result: it is an ephemeral runtime input, not a receipt field.
    """
    view = dict(closure) if isinstance(closure, dict) else {}
    dimensions = dict(view.get("state_dimensions") or {})
    eligible = (
        view.get("closed") is True
        and str(view.get("status") or "").strip().upper() == "COMPLETE_POSITIVE"
        and bool(str(view.get("closure_id") or "").strip())
        and dimensions.get("outreach_prerequisites_complete") is True
    )
    return {
        "closure_evaluated": isinstance(closure, dict),
        "closure_eligible": eligible,
        "reason_codes": [] if eligible else ["POSITIVE_ROUTE_CLOSURE_NOT_OUTREACH_ELIGIBLE"],
    }


def _evaluate_acceptance_case(facts: object) -> dict[str, object]:
    """Validate a typed acceptance case without returning values or route rows."""
    view = dict(facts) if isinstance(facts, dict) else {}
    case_kind = str(view.get("case_kind") or "").strip().upper()
    readiness = str(view.get("readiness") or "").strip().upper()
    reasons: list[str] = []
    if case_kind not in _ACCEPTANCE_CASE_KINDS:
        reasons.append("ACCEPTANCE_CASE_KIND_INVALID")
    if readiness not in _READINESS_RANK:
        reasons.append("ACCEPTANCE_CASE_READINESS_INVALID")

    counts: dict[str, int] = {}
    for key in ("canonical_route_count", "account_route_count", "effective_route_count"):
        value = view.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            reasons.append("ACCEPTANCE_CASE_ROUTE_COUNT_INVALID")
            counts[key] = -1
        else:
            counts[key] = value

    prepared = view.get("prepare_outreach")
    prepared_view = dict(prepared) if isinstance(prepared, dict) else None
    sends_message = prepared_view.get("sends_message") if prepared_view is not None else False
    if sends_message is not False:
        reasons.append("SENDS_MESSAGE_MUST_BE_FALSE")

    if case_kind == "NEGATIVE_SAFETY":
        if readiness != "IDENTITY_ONLY" or any(counts.get(key) != 0 for key in counts):
            reasons.append("NEGATIVE_CASE_RECLASSIFICATION_REQUIRED")
        blockers = set(_acceptance_reason_codes(view.get("block_reason_codes")))
        if not blockers:
            reasons.append("NEGATIVE_ROUTE_BLOCKERS_REQUIRED")
        rejection_codes = set(_acceptance_reason_codes(view.get("observation_rejection_codes")))
        if not _C279_REQUIRED_REJECTION_CODES <= rejection_codes:
            reasons.append("NEGATIVE_ROUTE_REJECTION_CODES_REQUIRED")
        if prepared_view is None or prepared_view.get("prepared") is not False:
            reasons.append("NEGATIVE_PREPARE_OUTREACH_MUST_BE_REJECTED")

    if case_kind == "POSITIVE_ROUTE":
        precondition = dict(view.get("positive_route_precondition") or {})
        for key in (
            "recognized_route_count",
            "current_verified_account_owned_count",
            "evidence_bound_count",
            "fully_qualified_route_count",
            "named_qualified_route_count",
        ):
            value = precondition.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                reasons.append("POSITIVE_ROUTE_" + key.removesuffix("_count").upper() + "_REQUIRED")
        if _READINESS_RANK.get(readiness, -1) < _READINESS_RANK["COMPANY_ROUTE_READY"]:
            reasons.append("POSITIVE_ROUTE_READINESS_REQUIRED")
        if any(counts.get(key, -1) < 1 for key in counts):
            reasons.append("POSITIVE_ROUTE_CANONICAL_ACCOUNT_EFFECTIVE_ROUTE_REQUIRED")
        named_route_binding_count = view.get("named_route_binding_count")
        if isinstance(named_route_binding_count, bool) or not isinstance(named_route_binding_count, int) or named_route_binding_count < 1:
            reasons.append("POSITIVE_ROUTE_NAMED_ROUTE_BINDING_REQUIRED")
        closure_gate = dict(view.get("isolated_closure_gate") or {})
        if closure_gate.get("closure_eligible") is not True:
            reasons.append("POSITIVE_ROUTE_CLOSURE_NOT_OUTREACH_ELIGIBLE")
        # A positive case must not even attempt draft preparation until every
        # selected route precondition has independently passed.
        precondition_failures = [code for code in reasons if code.startswith("POSITIVE_ROUTE_")]
        if precondition_failures and prepared_view is not None:
            reasons.append("POSITIVE_ROUTE_PREPARE_ATTEMPTED_BEFORE_PRECONDITION")
        elif not precondition_failures and (prepared_view is None or prepared_view.get("prepared") is not True):
            reasons.append("POSITIVE_ROUTE_PREPARE_OUTREACH_REQUIRED")

    safe_reasons = _acceptance_reason_codes(reasons)
    return {
        "schema": "cbi.v64-authoritative-acceptance-case.v1",
        "case_kind": case_kind if case_kind in _ACCEPTANCE_CASE_KINDS else "INVALID",
        "status": "ACCEPTANCE_CASE_VERIFIED" if not safe_reasons else "INVALID_ACCEPTANCE_CASE",
        "reason_codes": safe_reasons,
        "sends_message": False,
    }


class V64C279RouteProjectionDiagnosticsTests(unittest.TestCase):
    def test_sanitized_projection_keeps_only_allowlisted_non_route_fields(self):
        route_value = "private-route@example.invalid"
        diagnostics = {
            "status": "SUPPORTED_CLAIM_WITHOUT_CANONICAL_ROUTE",
            "claim_state": "SUPPORTED",
            "claim_observation_ids": ["OBS-C279-1"],
            "claim_evidence_ids": ["EVD-C279-1"],
            "observations": [{
                "observation_id": "OBS-C279-1",
                "evidence_id": "EVD-C279-1",
                "freshness": "CURRENT_CONFIRMED",
                "rejection_reasons": ["ROUTE_NOT_VERIFIED"],
                "value": route_value,
            }],
            "contains_route_values": False,
            "mutates_history": False,
        }
        outreach = {
            "outreach_readiness": "IDENTITY_ONLY",
            "block_reasons": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            "canonical_route_view": [{
                "value": route_value,
                "observation_id": "OBS-C279-1",
                "evidence_ids": ["EVD-C279-1"],
                "route_source": "COMPILED_OBSERVATION",
            }],
            "canonical_route_sources": ["COMPILED_OBSERVATION"],
            "valid_company_route_observation_ids": ["OBS-C279-1"],
            "valid_information_route_ids": [],
        }

        result = _sanitize_route_projection_diagnostics(diagnostics, outreach)

        self.assertEqual(set(result), {
            "route_projection_diagnostics",
            "readiness",
            "block_reason_codes",
            "canonical_route_count",
            "canonical_route_source_types",
            "canonical_route_observation_ids",
            "canonical_route_information_ids",
            "canonical_route_evidence_ids",
        })
        self.assertFalse(result["route_projection_diagnostics"]["contains_route_values"])
        self.assertEqual(result["readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_count"], 1)
        self.assertEqual(result["canonical_route_source_types"], ["COMPILED_OBSERVATION"])
        self.assertEqual(result["canonical_route_observation_ids"], ["OBS-C279-1"])
        self.assertEqual(result["canonical_route_evidence_ids"], ["EVD-C279-1"])
        self.assertNotIn(route_value, json.dumps(result, sort_keys=True))

    def test_sanitized_projection_fails_closed_when_runtime_does_not_guarantee_no_values(self):
        with self.assertRaisesRegex(ValueError, "ROUTE_PROJECTION_CONTAINS_VALUES"):
            _sanitize_route_projection_diagnostics(
                {"contains_route_values": True},
                {"outreach_readiness": "IDENTITY_ONLY"},
            )

    def test_schema_shape_diagnostics_classify_only_fixed_legacy_slots_without_values(self):
        private_values = {
            "email": "private.route@example.invalid",
            "phone": "+15550101999",
            "whatsapp": "+15550101888",
            "social": "https://social.example.invalid/private-profile",
            "form": "https://example.invalid/private-contact-form",
            "token": "do-not-emit-token",
            "url": "https://example.invalid/private-source",
        }
        projection = {
            "contains_route_values": False,
            "claim_observation_ids": ["OBS-C279-SHAPE"],
        }
        state = {
            "start": {"account": {"account_id": "ACCOUNT-C279"}},
            "observations": {
                "OBS-C279-SHAPE": {
                    "owner_type": "ACCOUNT",
                    "owner_id": "ACCOUNT-C279",
                    "evidence_id": "EVD-C279-SHAPE",
                    "source": {"freshness": "CURRENT_CONFIRMED", "url": private_values["url"]},
                    "value": {
                        "channel": "EMAIL",
                        "value": private_values["email"],
                        "contact": {
                            "phone": private_values["phone"],
                            "whatsapp": private_values["whatsapp"],
                            "unexpected": private_values["token"],
                        },
                    },
                    "contact": {
                        "social": private_values["social"],
                        "form": private_values["form"],
                        "unexpected": private_values["token"],
                    },
                    "contact_info": {"email": private_values["email"]},
                    "unexpected_top_level": private_values["token"],
                }
            },
        }

        result = _sanitize_route_schema_shape_diagnostics(projection, state)

        self.assertEqual(set(result), {"schema", "contains_route_values", "observations"})
        self.assertFalse(result["contains_route_values"])
        row = result["observations"][0]
        self.assertEqual(set(row), {
            "observation_id", "observation_available", "field_path_classifications",
            "candidate_pattern_counts", "candidate_bindings",
        })
        self.assertEqual(row["candidate_pattern_counts"], {
            "EMAIL": 2,
            "PHONE": 1,
            "WHATSAPP": 1,
            "SOCIAL": 1,
            "FORM": 1,
        })
        bindings = {item["path"]: item for item in row["candidate_bindings"]}
        self.assertEqual(bindings["value.value"]["candidate_type"], "EMAIL")
        self.assertTrue(bindings["value.value"]["recognizable"])
        self.assertTrue(bindings["value.contact.phone"]["bound_to_account"])
        self.assertTrue(bindings["value.contact.phone"]["bound_to_evidence"])
        self.assertTrue(bindings["value.contact.phone"]["strong_direct_freshness"])
        classifications = {item["path"]: item["classification"] for item in row["field_path_classifications"]}
        self.assertEqual(set(classifications), set(_SHAPE_PATHS))
        self.assertEqual(classifications["value.contact.phone"], "STRING")
        self.assertEqual(classifications["contact.form"], "STRING")
        self.assertEqual(
            {item["path"] for item in row["candidate_bindings"]},
            {path for path, _candidate_type in _CANDIDATE_PATH_TYPES},
        )
        self.assertNotIn("unexpected_top_level", json.dumps(result, sort_keys=True))
        serialized = json.dumps(result, sort_keys=True)
        for value in private_values.values():
            self.assertNotIn(value, serialized)


class V64C279AcceptanceMatrixTests(unittest.TestCase):
    def test_authoritative_workflow_allowlist_matches_exact_candidate_delta(self):
        root = Path(__file__).resolve().parents[1]
        workflow = root / ".github/workflows/cbi-v64-c279-authoritative-isolated.yml"
        text = workflow.read_text(encoding="utf-8")
        match = re.search(r"allowed = \{(?P<body>.*?)\n\s*\}", text, flags=re.DOTALL)
        self.assertIsNotNone(match)
        declared = frozenset(re.findall(r'"([^"\n]+)"', match.group("body")))
        self.assertEqual(declared, _C279_EXACT_DELTA_PATHS)

        # Exact history is available in the isolated worktree and in the
        # dedicated workflow (fetch-depth 2). Release CI may be intentionally
        # shallow, so the fixed declaration remains a non-skipped assertion.
        present = subprocess.run(
            ["git", "cat-file", "-e", f"{_C279_INTEGRATED_BASE_SHA}^{{commit}}"],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode == 0
        if present:
            changed = frozenset(subprocess.check_output(
                ["git", "diff", "--name-only", _C279_INTEGRATED_BASE_SHA, "HEAD"],
                cwd=root,
                text=True,
            ).splitlines())
            self.assertEqual(changed, _C279_EXACT_DELTA_PATHS)

    def test_positive_isolated_first_touch_body_matches_runtime_80_to_110_word_gate(self):
        from unified_runtime.v6 import _word_count

        self.assertGreaterEqual(_word_count(_POSITIVE_DRAFT_ONLY_BODY), 80)
        self.assertLessEqual(_word_count(_POSITIVE_DRAFT_ONLY_BODY), 110)

    def test_negative_safety_case_requires_identity_only_zero_routes_and_rejected_prepare(self):
        result = _evaluate_acceptance_case({
            "case_kind": "NEGATIVE_SAFETY",
            "readiness": "IDENTITY_ONLY",
            "canonical_route_count": 0,
            "account_route_count": 0,
            "effective_route_count": 0,
            "block_reason_codes": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            "observation_rejection_codes": [
                "ROUTE_NOT_VERIFIED", "ROUTE_VALUE_REQUIRED", "UNSUPPORTED_ROUTE_CHANNEL",
            ],
            "prepare_outreach": {"prepared": False, "sends_message": False},
        })

        self.assertEqual(result["status"], "ACCEPTANCE_CASE_VERIFIED")
        self.assertEqual(result["case_kind"], "NEGATIVE_SAFETY")

    def test_negative_safety_case_with_a_route_fails_reclassification_gate(self):
        result = _evaluate_acceptance_case({
            "case_kind": "NEGATIVE_SAFETY",
            "readiness": "COMPANY_ROUTE_READY",
            "canonical_route_count": 1,
            "account_route_count": 1,
            "effective_route_count": 1,
            "block_reason_codes": [],
            "observation_rejection_codes": [],
            "prepare_outreach": {"prepared": False, "sends_message": False},
        })

        self.assertEqual(result["status"], "INVALID_ACCEPTANCE_CASE")
        self.assertIn("NEGATIVE_CASE_RECLASSIFICATION_REQUIRED", result["reason_codes"])

    def test_positive_route_case_requires_recognized_current_verified_account_evidence_route(self):
        result = _evaluate_acceptance_case({
            "case_kind": "POSITIVE_ROUTE",
            "readiness": "COMPANY_ROUTE_READY",
            "canonical_route_count": 1,
            "account_route_count": 1,
            "effective_route_count": 1,
            "positive_route_precondition": {
                "recognized_route_count": 1,
                "current_verified_account_owned_count": 1,
                "evidence_bound_count": 1,
                "fully_qualified_route_count": 1,
                "named_qualified_route_count": 1,
            },
            "isolated_closure_gate": {"closure_eligible": True},
            "named_route_binding_count": 1,
            "prepare_outreach": {"prepared": True, "sends_message": False},
        })

        self.assertEqual(result["status"], "ACCEPTANCE_CASE_VERIFIED")
        self.assertEqual(result["case_kind"], "POSITIVE_ROUTE")

    def test_positive_route_precondition_counts_only_exact_current_verified_evidence_bound_rows(self):
        counts = _positive_route_precondition([
            {
                "channel": "EMAIL", "owner_entity_id": "ACCOUNT-1", "owned_by_account": True,
                "current": True, "verified": True, "evidence_ids": ["EVD-1"],
                "observation_id": "OBS-1", "named_person": "Private Name", "value": "never-serialize@example.invalid",
                "route_source": "COMPILED_OBSERVATION", "route_scope": "BUYER_DIRECT",
            },
            {
                "channel": "EMAIL", "owner_entity_id": "ACCOUNT-OTHER", "owned_by_account": True,
                "current": True, "verified": True, "evidence_ids": ["EVD-2"],
                "observation_id": "OBS-2", "value": "other@example.invalid",
            },
            {
                "channel": "PHONE", "owner_entity_id": "ACCOUNT-1", "owned_by_account": True,
                "current": False, "verified": True, "evidence_ids": ["EVD-3"],
                "observation_id": "OBS-3", "value": "+15550101999",
            },
            {
                "channel": "UNSUPPORTED", "owner_entity_id": "ACCOUNT-1", "owned_by_account": True,
                "current": True, "verified": True, "evidence_ids": ["EVD-4"],
                "observation_id": "OBS-4", "value": "do-not-count",
            },
        ], "ACCOUNT-1")

        self.assertEqual(counts, {
            "recognized_route_count": 3,
            "current_verified_account_owned_count": 1,
            "evidence_bound_count": 1,
            "fully_qualified_route_count": 1,
            "named_qualified_route_count": 1,
        })
        self.assertNotIn("never-serialize@example.invalid", json.dumps(counts, sort_keys=True))

    def test_positive_route_precondition_requires_every_eligibility_gate_on_one_row(self):
        valid_email = {
            "kind": "EMAIL",
            "value": "private.email@example.invalid",
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "owner_entity_id": "ACCOUNT-1",
            "masked": False,
            "guessed": False,
            "evidence_ids": ["EVD-EMAIL"],
            "observation_id": "OBS-EMAIL",
            "named_person": "Private Name",
            "route_source": "COMPILED_OBSERVATION",
            "route_scope": "BUYER_DIRECT",
        }
        valid_whatsapp = {
            "kind": "WHATSAPP",
            "value": "+15550101999",
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "owner_entity_id": "ACCOUNT-1",
            "masked": False,
            "guessed": False,
            "evidence_ids": ["EVD-WHATSAPP"],
            "information_id": "INF-WHATSAPP",
            "channel_proof": True,
            "named_person": "Private Name",
            "route_source": "INFORMATION_HISTORY",
            "route_scope": "BUYER_DIRECT",
        }
        invalid_rows = {
            "blank_value": {**valid_email, "value": "   "},
            "masked": {**valid_email, "masked": True},
            "guessed": {**valid_email, "guessed": True},
            "owned_flag_false": {**valid_email, "owned_by_account": False},
            "owner_mismatch": {**valid_email, "owner_entity_id": "ACCOUNT-OTHER"},
            "missing_evidence": {**valid_email, "evidence_ids": []},
            "missing_canonical_identifier": {
                **valid_email, "observation_id": "", "information_id": "",
            },
            "whatsapp_without_proof": {**valid_whatsapp, "channel_proof": False},
            "zalo_without_proof": {**valid_whatsapp, "kind": "ZALO", "channel_proof": False},
        }
        for name, row in invalid_rows.items():
            with self.subTest(name=name):
                counts = _positive_route_precondition([row], "ACCOUNT-1")
                self.assertEqual(counts["fully_qualified_route_count"], 0)

        counts = _positive_route_precondition([valid_email, valid_whatsapp], "ACCOUNT-1")
        self.assertEqual(counts["fully_qualified_route_count"], 2)
        self.assertEqual(counts["named_qualified_route_count"], 2)
        serialized = json.dumps(counts, sort_keys=True)
        self.assertNotIn(valid_email["value"], serialized)
        self.assertNotIn(valid_whatsapp["value"], serialized)

    def test_positive_route_precondition_rejects_blank_account_and_supplier_scope(self):
        valid = {
            "kind": "EMAIL", "value": "named@example.invalid", "verified": True,
            "current": True, "owned_by_account": True, "owner_entity_id": "ACCOUNT-1",
            "masked": False, "guessed": False, "evidence_ids": ["EVD-1"],
            "observation_id": "OBS-1", "named_person": "Private Name",
            "route_scope": "BUYER_DIRECT",
        }
        for name, account_id, row in (
            ("blank_account", "", {**valid, "owner_entity_id": ""}),
            ("supplier_scope", "ACCOUNT-1", {**valid, "route_scope": "SUPPLIER_DIRECT"}),
        ):
            with self.subTest(name=name):
                counts = _positive_route_precondition([row], account_id)
                self.assertEqual(counts["fully_qualified_route_count"], 0)
                self.assertEqual(counts["named_qualified_route_count"], 0)

    def test_mixed_lane_ids_are_not_named_bindings_and_do_not_prepare(self):
        readiness = {
            "valid_named_route_observation_ids": ["OBS-COMPILED"],
            "valid_information_route_ids": ["INFO-HISTORY"],
        }
        base = {
            "kind": "EMAIL", "value": "named@example.invalid", "verified": True,
            "current": True, "owned_by_account": True, "owner_entity_id": "ACCOUNT-1",
            "masked": False, "guessed": False, "evidence_ids": ["EVD-1"],
            "named_person": "Private Name", "route_scope": "BUYER_DIRECT",
        }
        mixed_rows = [
            {
                **base, "route_source": "COMPILED_OBSERVATION",
                "observation_id": "OBS-COMPILED", "information_id": "INFO-MIXED-COMPILED",
            },
            {
                **base, "route_source": "INFORMATION_HISTORY",
                "observation_id": "OBS-MIXED-HISTORY", "information_id": "INFO-HISTORY",
            },
        ]
        for row in mixed_rows:
            self.assertFalse(_is_eligible_named_route(row, "ACCOUNT-1", readiness))

        eligible = [
            row for row in mixed_rows
            if _is_eligible_named_route(row, "ACCOUNT-1", readiness)
        ]
        prepare_calls: list[dict[str, object]] = []

        def prepare_outreach(arguments):
            prepare_calls.append(dict(arguments))
            raise AssertionError("prepare_outreach must not run without a bound named route")

        if eligible:
            prepare_outreach({"route": eligible[0]})
        self.assertEqual(len(eligible), 0)
        self.assertEqual(prepare_calls, [])

    def test_positive_route_without_evidence_bound_route_fails_before_prepare(self):
        result = _evaluate_acceptance_case({
            "case_kind": "POSITIVE_ROUTE",
            "readiness": "COMPANY_ROUTE_READY",
            "canonical_route_count": 1,
            "account_route_count": 1,
            "effective_route_count": 1,
            "positive_route_precondition": {
                "recognized_route_count": 1,
                "current_verified_account_owned_count": 1,
                "evidence_bound_count": 0,
                "fully_qualified_route_count": 0,
                "named_qualified_route_count": 0,
            },
            "prepare_outreach": None,
        })

        self.assertEqual(result["status"], "INVALID_ACCEPTANCE_CASE")
        self.assertIn("POSITIVE_ROUTE_EVIDENCE_BOUND_REQUIRED", result["reason_codes"])

    def test_positive_route_requires_a_single_fully_qualified_route_before_prepare(self):
        result = _evaluate_acceptance_case({
            "case_kind": "POSITIVE_ROUTE",
            "readiness": "COMPANY_ROUTE_READY",
            "canonical_route_count": 2,
            "account_route_count": 2,
            "effective_route_count": 2,
            "positive_route_precondition": {
                "recognized_route_count": 2,
                "current_verified_account_owned_count": 1,
                "evidence_bound_count": 1,
                "fully_qualified_route_count": 0,
                "named_qualified_route_count": 0,
            },
            "prepare_outreach": None,
        })

        self.assertEqual(result["status"], "INVALID_ACCEPTANCE_CASE")
        self.assertIn("POSITIVE_ROUTE_FULLY_QUALIFIED_ROUTE_REQUIRED", result["reason_codes"])

    def test_positive_isolated_closure_gate_never_authorizes_prepare_without_a_real_eligible_closure(self):
        blocked = _isolated_positive_closure_gate({
            "closed": False,
            "status": "BLOCKED",
            "closure_id": None,
            "state_dimensions": {"outreach_prerequisites_complete": False},
        })
        self.assertEqual(blocked, {
            "closure_evaluated": True,
            "closure_eligible": False,
            "reason_codes": ["POSITIVE_ROUTE_CLOSURE_NOT_OUTREACH_ELIGIBLE"],
        })

        eligible = _isolated_positive_closure_gate({
            "closed": True,
            "status": "COMPLETE_POSITIVE",
            "closure_id": "CLOS-private-id-not-emitted",
            "state_dimensions": {"outreach_prerequisites_complete": True},
        })
        self.assertEqual(eligible, {
            "closure_evaluated": True,
            "closure_eligible": True,
            "reason_codes": [],
        })
        self.assertNotIn("CLOS-private-id-not-emitted", json.dumps(eligible, sort_keys=True))


class V64C279FullRuntimeRegression(unittest.TestCase):
    def test_positive_route_authoritative_case_full_runtime(self):
        """Run a selected positive case only in a disposable decrypted copy.

        This test is intentionally environment-gated: its bridge is created
        only after an exact-tail ciphertext capture.  It never receives a live
        Runtime object and never writes the source snapshot.
        """
        bridge_path = os.environ.get("CBI_V64_POSITIVE_BRIDGE_EVIDENCE")
        source_root_value = os.environ.get("CBI_V64_POSITIVE_SOURCE_RUNTIME_ROOT")
        if not bridge_path or not source_root_value:
            self.skipTest("private authoritative positive bridge/runtime root not supplied")

        bridge = json.loads(Path(bridge_path).read_text(encoding="utf-8"))
        source_root = Path(source_root_value).expanduser().resolve()
        investigation_id = str(bridge["investigation_id"])
        durable = dict(bridge.get("durable_state") or {})
        expected_seq = int(durable["last_safe_seq"])
        expected_hash = str(durable["last_safe_event_hash"])
        acceptance_case = dict(bridge.get("acceptance_case") or {})
        self.assertEqual(
            acceptance_case,
            {
                "schema": "cbi.v64-authoritative-acceptance-case.v1",
                "case_kind": "POSITIVE_ROUTE",
                "sends_message": False,
            },
        )

        with tempfile.TemporaryDirectory(prefix="cbi-v64-positive-route-") as temp_dir:
            isolated_root = Path(temp_dir) / "runtime"
            shutil.copytree(source_root, isolated_root)
            sessions_root = isolated_root / "sessions"
            self.assertTrue((sessions_root / f"{investigation_id}.jsonl").is_file())
            runtime_env = {"CBI_SESSION_ROOT": str(sessions_root)}
            for env_name, relative in (("CBI_CANONICAL_ROOT", "canonical"), ("CBI_PENDING_ROOT", "pending")):
                candidate = isolated_root / relative
                if candidate.exists():
                    runtime_env[env_name] = str(candidate)

            with patch.dict(os.environ, runtime_env, clear=False):
                from unified_runtime import UnifiedRuntime

                runtime = UnifiedRuntime(sessions_root)
                state = runtime.get_investigation_state({"investigation_id": investigation_id})
                self.assertEqual(state["last_safe_seq"], expected_seq)
                self.assertEqual(state["last_safe_event_hash"], expected_hash)
                account_state = runtime.get_account_state({"investigation_id": investigation_id})
                readiness = dict(account_state.get("outreach_readiness") or {})
                diagnostics = _sanitize_route_projection_diagnostics(
                    account_state.get("route_projection_diagnostics"), readiness
                )
                routes = [row for row in (readiness.get("canonical_route_view") or []) if isinstance(row, dict)]
                start = runtime._v6_state(investigation_id)["start"]
                account_id = str((start.get("account") or {}).get("account_id") or "")
                precondition = _positive_route_precondition(routes, account_id)

                # This call may issue a closure event, but exclusively inside the
                # temporary runtime.  It must not be emulated from route facts.
                closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
                closure_gate = _isolated_positive_closure_gate(closure)
                prepared: dict[str, object] | None = None
                valid_named_observations = {
                    str(item).strip()
                    for item in (readiness.get("valid_named_route_observation_ids") or [])
                    if str(item).strip()
                }
                valid_information_routes = {
                    str(item).strip()
                    for item in (readiness.get("valid_information_route_ids") or [])
                    if str(item).strip()
                }
                named_lane_readiness = {
                    "valid_named_route_observation_ids": valid_named_observations,
                    "valid_information_route_ids": valid_information_routes,
                }
                eligible_named_routes = [
                    row for row in routes
                    if _is_eligible_named_route(row, account_id, named_lane_readiness)
                ]
                if eligible_named_routes and closure_gate["closure_eligible"]:
                    # Use the canonical row only within this isolated process;
                    # no row/value is placed in diagnostics, receipt, or logs.
                    route = eligible_named_routes[0]
                    prepared = runtime.prepare_outreach({
                        "investigation_id": investigation_id,
                        "closure_id": closure["closure_id"],
                        "route": route,
                        "history_digest": start.get("history_digest"),
                        "authority_digest": start.get("authority_digest"),
                        "subject": "PVC sheet sourcing contact",
                        "body": _POSITIVE_DRAFT_ONLY_BODY,
                        "stage": "FIRST_TOUCH",
                        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
                    })
                acceptance = _evaluate_acceptance_case({
                    "case_kind": "POSITIVE_ROUTE",
                    "readiness": diagnostics["readiness"],
                    "canonical_route_count": diagnostics["canonical_route_count"],
                    "account_route_count": len([row for row in account_state.get("routes") or [] if isinstance(row, dict)]),
                    "effective_route_count": len(readiness.get("valid_company_route_observation_ids") or [])
                    + len(readiness.get("valid_information_route_ids") or []),
                    "positive_route_precondition": precondition,
                    "named_route_binding_count": len(eligible_named_routes),
                    "isolated_closure_gate": closure_gate,
                    "prepare_outreach": None if prepared is None else {
                        "prepared": prepared.get("prepared") is True,
                        "sends_message": prepared.get("sends_message") is True,
                    },
                })
                diagnostics["positive_route_precondition"] = precondition
                diagnostics["isolated_closure_gate"] = closure_gate
                diagnostics["acceptance_case"] = acceptance
                diagnostics_path = str(os.environ.get("CBI_V64_POSITIVE_ROUTE_DIAGNOSTICS") or "").strip()
                if diagnostics_path:
                    _write_route_projection_diagnostics(diagnostics_path, diagnostics)
                self.assertFalse(acceptance["sends_message"], acceptance)

    def test_c279_negative_safety_authoritative_case_full_runtime(self):
        bridge_path = os.environ.get("CBI_V64_C279_BRIDGE_EVIDENCE")
        source_root_value = os.environ.get("CBI_V64_C279_SOURCE_RUNTIME_ROOT")
        if not bridge_path or not source_root_value:
            self.skipTest("private authoritative C279 bridge/runtime root not supplied")

        bridge = json.loads(Path(bridge_path).read_text(encoding="utf-8"))
        source_root = Path(source_root_value).expanduser().resolve()
        investigation_id = str(bridge["investigation_id"])
        durable = dict(bridge.get("durable_state") or {})
        expected_seq = int(durable["last_safe_seq"])
        expected_hash = str(durable["last_safe_event_hash"])

        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-") as temp_dir:
            isolated_root = Path(temp_dir) / "runtime"
            shutil.copytree(source_root, isolated_root)
            sessions_root = isolated_root / "sessions"
            self.assertTrue((sessions_root / f"{investigation_id}.jsonl").is_file())

            runtime_env = {"CBI_SESSION_ROOT": str(sessions_root)}
            for env_name, relative in (
                ("CBI_CANONICAL_ROOT", "canonical"),
                ("CBI_PENDING_ROOT", "pending"),
            ):
                candidate = isolated_root / relative
                if candidate.exists():
                    runtime_env[env_name] = str(candidate)

            with patch.dict(os.environ, runtime_env, clear=False):
                from unified_runtime import UnifiedRuntime

                runtime = UnifiedRuntime(sessions_root)
                state = runtime.get_investigation_state({"investigation_id": investigation_id})
                self.assertEqual(state["last_safe_seq"], expected_seq)
                self.assertEqual(state["last_safe_event_hash"], expected_hash)

                account_state = runtime.get_account_state({"investigation_id": investigation_id})
                readiness = dict(account_state.get("outreach_readiness") or {})
                diagnostics = _sanitize_route_projection_diagnostics(
                    account_state.get("route_projection_diagnostics"),
                    readiness,
                )
                diagnostics["route_schema_shape_diagnostics"] = _sanitize_route_schema_shape_diagnostics(
                    account_state.get("route_projection_diagnostics"),
                    runtime._v6_state(investigation_id),
                )
                diagnostics_path = str(os.environ.get("CBI_V64_C279_ROUTE_PROJECTION_DIAGNOSTICS") or "").strip()
                if diagnostics_path:
                    _write_route_projection_diagnostics(diagnostics_path, diagnostics)
                routes = [row for row in (readiness.get("canonical_route_view") or []) if isinstance(row, dict)]
                start = runtime._v6_state(investigation_id)["start"]
                body = (
                    "Hello, I’m contacting your company from XingHuai New Materials. We manufacture PVC foam board "
                    "and related rigid panel materials for distribution, cabinetry, interior fabrication, signage and "
                    "general sheet applications. I would like to understand whether your purchasing team is open to "
                    "evaluating an additional qualified supply source. We can provide a concise product overview and "
                    "then prepare technical information only against requirements that your team confirms. Could you "
                    "please direct this message to the colleague responsible for purchasing or sourcing sheet materials? "
                    "If this category is not relevant, no further action is needed. Best regards, Mark Zhou"
                )
                acceptance_case = dict(bridge.get("acceptance_case") or {})
                self.assertEqual(
                    set(acceptance_case),
                    {"schema", "case_kind", "required_observation_rejection_codes", "sends_message"},
                )
                self.assertEqual(acceptance_case.get("schema"), "cbi.v64-authoritative-acceptance-case.v1")
                self.assertEqual(acceptance_case.get("case_kind"), "NEGATIVE_SAFETY")
                self.assertFalse(acceptance_case.get("sends_message"))
                self.assertEqual(
                    set(_acceptance_reason_codes(acceptance_case.get("required_observation_rejection_codes"))),
                    _C279_REQUIRED_REJECTION_CODES,
                )
                rejection_codes = sorted({
                    code
                    for row in diagnostics["route_projection_diagnostics"]["observations"]
                    for code in row["rejection_reasons"]
                })
                # This request is intentionally malformed/noncanonical and is run
                # solely against the disposable copy. It is a rejection probe, not
                # a contact attempt and cannot append an outreach preparation.
                prepared = runtime.prepare_outreach({
                    "investigation_id": investigation_id,
                    "closure_id": "NEGATIVE_SAFETY_REJECTED",
                    "route": {
                        "kind": "EMAIL",
                        "value": "no-route@example.invalid",
                        "verified": False,
                        "current": False,
                        "owned_by_account": False,
                        "owner_entity_id": "",
                        "evidence_ids": [],
                    },
                    "history_digest": start.get("history_digest"),
                    "authority_digest": start.get("authority_digest"),
                    "subject": "PVC sheet sourcing contact",
                    "body": body,
                    "stage": "FIRST_TOUCH",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=15)
                    ).isoformat().replace("+00:00", "Z"),
                })
                acceptance = _evaluate_acceptance_case({
                    "case_kind": acceptance_case.get("case_kind"),
                    "readiness": diagnostics["readiness"],
                    "canonical_route_count": diagnostics["canonical_route_count"],
                    "account_route_count": len([row for row in account_state.get("routes") or [] if isinstance(row, dict)]),
                    "effective_route_count": len(readiness.get("valid_company_route_observation_ids") or [])
                    + len(readiness.get("valid_information_route_ids") or []),
                    "block_reason_codes": diagnostics["block_reason_codes"],
                    "observation_rejection_codes": rejection_codes,
                    "prepare_outreach": {
                        "prepared": bool(prepared.get("prepared")),
                        "sends_message": bool(prepared.get("sends_message", False)),
                    },
                })
                diagnostics["acceptance_case"] = acceptance
                if diagnostics_path:
                    Path(diagnostics_path).unlink(missing_ok=True)
                    _write_route_projection_diagnostics(diagnostics_path, diagnostics)
                self.assertEqual(acceptance["status"], "ACCEPTANCE_CASE_VERIFIED", acceptance)
                self.assertFalse(prepared.get("prepared"), prepared)
                self.assertFalse(prepared.get("sends_message", False), prepared)


if __name__ == "__main__":
    unittest.main()
