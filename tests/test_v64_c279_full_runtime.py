from __future__ import annotations

import json
import os
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
from unittest.mock import patch


_DIAGNOSTIC_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_EMAIL_CANDIDATE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_CANDIDATE_RE = re.compile(r"^\+?[0-9][0-9\s().-]{5,}$")
_WEB_CANDIDATE_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
_MISSING = object()
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


class V64C279FullRuntimeRegression(unittest.TestCase):
    def test_c279_canonical_route_can_prepare_outreach_full_runtime(self):
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
                rank = {
                    "BLOCKED": 0,
                    "IDENTITY_ONLY": 1,
                    "COMPANY_ROUTE_READY": 2,
                    "NAMED_ROUTE_READY": 3,
                    "FOLLOW_UP_READY": 4,
                    "SEND_READY": 5,
                }
                actual_readiness = str(readiness.get("outreach_readiness") or readiness.get("readiness"))
                self.assertGreaterEqual(rank.get(actual_readiness, -1), rank["COMPANY_ROUTE_READY"])
                routes = [row for row in (readiness.get("canonical_route_view") or []) if isinstance(row, dict)]
                self.assertTrue(routes)

                named_ids = set(
                    dict(bridge.get("named_route") or {}).get("observation_ids") or []
                )
                route = next(
                    (row for row in routes if str(row.get("observation_id") or "") in named_ids),
                    routes[0],
                )
                closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
                self.assertTrue(closure.get("closed"))
                self.assertTrue(closure.get("closure_id"))

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
                prepared = runtime.prepare_outreach({
                    "investigation_id": investigation_id,
                    "closure_id": closure["closure_id"],
                    "route": route,
                    "history_digest": start.get("history_digest"),
                    "authority_digest": start.get("authority_digest"),
                    "subject": "PVC sheet sourcing contact",
                    "body": body,
                    "stage": "FIRST_TOUCH",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=15)
                    ).isoformat().replace("+00:00", "Z"),
                })
                self.assertTrue(prepared.get("prepared"), prepared)
                self.assertEqual(prepared.get("block_reasons") or [], [])
                self.assertFalse(prepared.get("sends_message"))


if __name__ == "__main__":
    unittest.main()
