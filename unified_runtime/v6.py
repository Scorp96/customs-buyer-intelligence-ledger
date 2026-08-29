"""Customs Buyer Intelligence v6 production-governance overlay.

The v5 runtime remains the compatibility adapter.  This module provides the
v6 claim-driven state machine, evidence compiler, decision-saturation engine,
peer lifecycle, portfolio scheduler, durable host queue and copy migration.
It intentionally performs no web search and never sends outreach.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from .core import (
    CONCRETE_CLAIM_PATTERNS,
    INTERNATIONAL_PHONE_RE,
    MASKED_CONTACT_RE,
    URL_RE,
    _word_count,
)
from .errors import ValidationError
from .resilience import HashChainLog, canonical_json, digest, exclusive_file_lock, iso_utc


V6_RUNTIME_VERSION = "6.1.0"
V6_BUILD_ID = "CBI-V6.1-INDEPENDENT-AUDIT-EVIDENCE-ATOMICITY-V1"

V6_CBI_MCP_TOOL_NAMES = (
    "get_runtime_contract", "get_runtime_health", "get_investigation_health",
    "resolve_or_create_account", "start_investigation", "resume_investigation",
    "submit_research_objective", "compile_and_append_research_bundle", "get_claims",
    "get_account_state", "get_investigation_state", "get_next_research_objectives",
    "get_portfolio_queue", "append_information_record", "get_information_history",
    "plan_public_source_calls", "plan_provider_calls", "append_execution_receipt",
    "append_provider_receipt", "append_peer_receipt", "append_peer_discovery",
    "evaluate_peer", "promote_anchor", "get_material_pivots", "close_pivot",
    "append_crm_writeback_receipt", "prepare_crm_writeback",
    "evaluate_commercial_readiness", "evaluate_commercial_value",
    "evaluate_research_confidence", "evaluate_outreach_readiness",
    "evaluate_decision_saturation", "evaluate_investigation_closure",
    "prepare_outreach", "render_outreach_action_card", "queue_pending_receipt",
    "get_pending_journal_status", "sync_pending_receipts", "queue_host_bundle",
    "sync_pending_bundles", "sync_pending_research_bundles", "migrate_v5_4_1_to_v6",
)

CLAIM_STATES = (
    "UNSEEN",
    "SEARCHING",
    "SUPPORTED",
    "STRONGLY_SUPPORTED",
    "CONFLICTED",
    "REFUTED",
    "NEGATIVE_EXHAUSTED",
    "BLOCKED",
    "NOT_APPLICABLE",
    "STALE",
)

COMMERCIAL_VALUE_GRADES = ("A+", "A", "A-", "B+", "B", "B-", "C", "D", "NQ")
RESEARCH_CONFIDENCE_GRADES = ("R0", "R1", "R2", "R3", "R4", "R5")
OUTREACH_READINESS_STATES = (
    "BLOCKED",
    "IDENTITY_ONLY",
    "COMPANY_ROUTE_READY",
    "NAMED_ROUTE_READY",
    "FOLLOW_UP_READY",
    "SEND_READY",
)
PEER_STAGES = (
    "DISCOVERED",
    "QUALIFIED",
    "ANCHOR_ELIGIBLE",
    "PROMOTED_ANCHOR",
    "FULLY_AUDITED",
)
NETWORK_BRANCHES_V6 = (
    "REGIONAL_PEERS",
    "INDUSTRY_PEERS",
    "SCALE_PEERS",
    "SAME_SUPPLIER_BUYERS",
    "SAME_PRODUCT_HS_APPLICATION_BUYERS",
    "COMPETING_SUPPLIERS_AND_SUBSTITUTES",
)

AUTHORITY_LEVELS = (
    "A1_OFFICIAL_PRIMARY",
    "A2_REGULATORY_OR_GOVERNMENT",
    "B1_OFFICIAL_COMPANY",
    "B2_REPUTABLE_INDUSTRY_OR_DIRECTORY",
    "C1_PUBLIC_PROFESSIONAL_OR_SOCIAL",
    "C2_SECONDARY_PUBLIC",
    "D1_USER_SUPPLIED_UNVERIFIED",
    "D2_DERIVED_OR_INFERRED",
)
FRESHNESS_LEVELS = ("LIVE", "CURRENT", "RECENT", "HISTORICAL", "STALE", "UNKNOWN")
OBSERVATION_RESULTS = (
    "POSITIVE",
    "NEGATIVE",
    "NEGATIVE_EXHAUSTED",
    "BLOCKED",
    "NOT_APPLICABLE",
    "REFUTED",
    "CONFLICT",
)
REFERENCE_TYPES = (
    "PUBLIC_URL",
    "LOCAL_ARTIFACT",
    "USER_INPUT",
    "LEGACY_CRM",
    "PROVIDER_RECEIPT",
    "DERIVED_CALCULATION",
)

DEFAULT_CLAIM_CATALOG: dict[str, dict[str, Any]] = {
    "identity.legal_entity": {"critical": True, "commercial_weight": 10, "decision_impact": 1.0, "allow_not_applicable": False},
    "identity.ultimate_buyer": {"critical": True, "commercial_weight": 10, "decision_impact": 1.0, "allow_not_applicable": False},
    "product.fit": {"critical": True, "commercial_weight": 20, "decision_impact": 1.0, "allow_not_applicable": False},
    "trade.import_activity": {"critical": True, "commercial_weight": 20, "decision_impact": 0.95, "allow_not_applicable": False},
    "company.operating_status": {"critical": True, "commercial_weight": 10, "decision_impact": 0.9, "allow_not_applicable": False},
    "commercial.procurement_need": {"critical": True, "commercial_weight": 15, "decision_impact": 0.9, "allow_not_applicable": False},
    "relationship.supply_chain": {"critical": False, "commercial_weight": 10, "decision_impact": 0.75, "allow_not_applicable": True},
    "buying_group.decision_chain": {"critical": False, "commercial_weight": 5, "decision_impact": 0.7, "allow_not_applicable": False},
    "contact.company_route": {"critical": False, "commercial_weight": 0, "decision_impact": 0.55, "allow_not_applicable": False},
    "contact.named_route": {"critical": False, "commercial_weight": 0, "decision_impact": 0.6, "allow_not_applicable": False},
    "outreach.route_safety": {"critical": False, "commercial_weight": 0, "decision_impact": 0.65, "allow_not_applicable": True},
}

SEARCH_PLAYBOOK: dict[str, tuple[str, ...]] = {
    "identity": ("official_registry", "tax_registry", "official_site", "maps", "legal_notices"),
    "product": ("official_products", "catalog_pdf", "project_pages", "trade_descriptions", "industry_directories"),
    "trade": ("customs_rows", "shipment_history", "supplier_links", "port_or_logistics_context"),
    "company": ("official_site", "maps", "registries", "news", "jobs", "associations"),
    "buying_group": ("official_team", "linkedin_people", "press", "registries", "conference_or_association"),
    "contact": ("official_contact", "footer_mobile", "public_social", "maps", "directories", "public_reverse_lookup"),
    "network": NETWORK_BRANCHES_V6,
}

BUDGET_BY_GRADE = {"A+": 100.0, "A": 60.0, "A-": 40.0, "B+": 20.0, "B": 10.0, "B-": 8.0, "C": 5.0, "D": 3.0, "NQ": 0.0}
OUTREACH_STAGE_RANK = {
    "FIRST_TOUCH": 0, "FOLLOW_UP_1": 1, "FOLLOW_UP_2": 2, "MEETING": 3,
    "SAMPLE": 4, "QUOTE": 5, "PI": 6, "ORDER": 7, "PAYMENT": 8,
    "NEGOTIATION": 9, "CLOSED_WON": 10, "CLOSED_LOST": 10,
}
V6_OPERATIONAL_EVENTS = {
    "V6_OBSERVATION_COMPILED", "V6_RESEARCH_OBJECTIVE_SUBMITTED", "V6_PIVOT_CLOSED",
    "V6_PEER_DISCOVERED", "V6_PEER_EVALUATED", "V6_ANCHOR_PROMOTED",
    "INFORMATION_RECORD_APPENDED", "EXECUTION_RECEIPT_APPENDED", "PROVIDER_PLAN_CREATED",
    "PROVIDER_RECEIPT_APPENDED", "PEER_RECEIPT_APPENDED", "ANCHOR_EXPANSION_CLOSED",
    "CRM_WRITEBACK_RECEIPT_APPENDED",
}

MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
MAX_RESEARCH_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_HOST_QUEUE_PAYLOAD_BYTES = 32 * 1024 * 1024
PEER_STAGE_RANK = {stage: index for index, stage in enumerate(PEER_STAGES)}

_URL_RE = re.compile(r"^https?://\S+$", flags=re.I)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,159}$")
_SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|cookie)(?=$|[_-])"
    r"|^(?:apikey|accesstoken|refreshtoken|clientsecret)$",
    re.I,
)
_SECRET_VALUE_RE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|bearer\s+[A-Za-z0-9._~+/-]{12,})", re.I)
_SECRET_QUERY_RE = re.compile(
    r"(?:[?&]|\b)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|cookie)=[^&#\s]+",
    re.I,
)
_SELF_PROOF_RE = re.compile(r"^(?:AUDIT_QUERY:|MANUAL_ASSERTION:|VALIDATOR_NEGATIVE:|SELF_PROOF:)", re.I)
_BLOCKED_AS_NA_RE = re.compile(
    r"(?:\b(?:401|403|407|429)\b|login|sign[ -]?in|paywall|captcha|blocked|timeout|rate[ -]?limit|anti[ -]?bot|反爬|登录|付费墙|验证码|访问受限)",
    re.I,
)
_COMMON_TWO_LABEL_PUBLIC_SUFFIXES = {
    "co.uk", "com.au", "com.br", "com.cn", "com.hk", "com.mx", "com.my",
    "com.ph", "com.sg", "com.tr", "com.tw", "com.vn", "co.id", "co.jp",
    "co.kr", "co.nz", "co.th", "co.za",
}


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field}: object required")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field}: array required")
    return value


def _nonempty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field}: non-empty value required")
    return text


def _safe_id(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValidationError(f"{field}: invalid identifier")
    return text


def _parse_time(value: Any, field: str) -> datetime:
    text = _nonempty(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field}: ISO-8601 timestamp required") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field}: timezone required")
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _valid_hash(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValidationError(f"{field}: SHA-256 required")
    return text


def _walk_no_secrets(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                raise ValidationError(f"{path}.{key}: provider credential fields must never be persisted")
            _walk_no_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_no_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if _SECRET_VALUE_RE.search(value) or _SECRET_QUERY_RE.search(value):
            raise ValidationError(f"{path}: value resembles a credential and cannot be persisted")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValidationError(f"{path}: non-finite numbers are not valid durable data")


def _encoded_size(value: Any, field: str) -> int:
    try:
        return len(canonical_json(value).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field}: JSON-compatible finite data required") from exc


def _independent_source_key(source: dict[str, Any]) -> str:
    reference_type = str(source.get("reference_type") or "")
    if reference_type == "PUBLIC_URL":
        host = (urlsplit(str(source.get("url") or source.get("locator") or "")).hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]
        labels = [label for label in host.split(".") if label]
        if len(labels) >= 3 and ".".join(labels[-2:]) in _COMMON_TWO_LABEL_PUBLIC_SUFFIXES:
            controller = ".".join(labels[-3:])
        elif len(labels) >= 2:
            controller = ".".join(labels[-2:])
        else:
            controller = host
        return f"PUBLIC_URL:{controller}"
    return f"{reference_type}:{str(source.get('locator') or '').casefold()}"


def _serialized_v6_mutation(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(self: Any, arguments: dict[str, Any]) -> Any:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        lock = self.store.root / f".{investigation_id}.v6-mutation.lock"
        with exclusive_file_lock(lock, timeout_seconds=60.0):
            return method(self, arguments)

    return wrapped


def _stable_id(prefix: str, value: Any, size: int = 16) -> str:
    return f"{prefix}-{digest(value)[:size]}"


def _grade_for_score(score: float) -> str:
    if score >= 92:
        return "A+"
    if score >= 84:
        return "A"
    if score >= 76:
        return "A-"
    if score >= 68:
        return "B+"
    if score >= 58:
        return "B"
    if score >= 48:
        return "B-"
    if score >= 35:
        return "C"
    if score > 0:
        return "D"
    return "NQ"


class HostBundleQueue:
    """Process-independent, append-only host queue used when MCP is unavailable."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = HashChainLog(root / "queue-events.jsonl")

    def _path(self, bundle_queue_id: str) -> Path:
        if not re.fullmatch(r"HOSTQ-[0-9TZ-]+-[0-9a-f]{12}", bundle_queue_id):
            raise ValidationError("bundle_queue_id: invalid")
        return self.root / f"{bundle_queue_id}.json"

    def queue(self, payload: dict[str, Any], queue_id: str = "") -> dict[str, Any]:
        _walk_no_secrets(payload)
        if _encoded_size(payload, "payload") > MAX_HOST_QUEUE_PAYLOAD_BYTES:
            raise ValidationError("payload exceeds the 32 MiB durable host-queue limit")
        _nonempty(payload.get("investigation_id"), "payload.investigation_id")
        _require_object(payload.get("bundle"), "payload.bundle")
        request_hash = digest(payload)
        with exclusive_file_lock(self.root / "host-queue-write.lock"):
            for row in self.entries():
                if row["request_sha256"] == request_hash:
                    return {**row, "queued": False, "deduplicated": True}
            queue_id = queue_id.strip() or f"HOSTQ-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
            envelope = {
                "schema": "cbi.host-pending-bundle.v6.1",
                "bundle_queue_id": queue_id,
                "queued_at": iso_utc(),
                "request_sha256": request_hash,
                "payload": payload,
            }
            path = self._path(queue_id)
            try:
                descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor, (canonical_json(envelope) + "\n").encode("utf-8"))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except FileExistsError as exc:
                raise ValidationError("bundle_queue_id collision") from exc
            self.events.append("HOST_BUNDLE_QUEUED", {
                "bundle_queue_id": queue_id,
                "request_sha256": request_hash,
                "status": "PENDING",
            })
            return {
                "bundle_queue_id": queue_id,
                "request_sha256": request_hash,
                "status": "PENDING",
                "queued": True,
                "deduplicated": False,
                "path": str(path),
            }

    def entries(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in self.events.read():
            payload = event["payload"]
            queue_id = payload.get("bundle_queue_id")
            if queue_id:
                latest[queue_id] = {**payload, "recorded_at": event["recorded_at"]}
        rows: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("HOSTQ-*.json")):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError(f"{path.name}: corrupt host queue envelope") from exc
            if digest(envelope.get("payload")) != envelope.get("request_sha256"):
                raise ValidationError(f"{path.name}: host queue hash mismatch")
            status = latest.get(envelope["bundle_queue_id"], {})
            rows.append({
                "bundle_queue_id": envelope["bundle_queue_id"],
                "request_sha256": envelope["request_sha256"],
                "investigation_id": envelope["payload"].get("investigation_id"),
                "status": status.get("status", "PENDING"),
                "recorded_at": status.get("recorded_at", envelope["queued_at"]),
                "path": str(path),
            })
        return rows

    def load(self, queue_id: str) -> dict[str, Any]:
        envelope = json.loads(self._path(queue_id).read_text(encoding="utf-8"))
        if digest(envelope.get("payload")) != envelope.get("request_sha256"):
            raise ValidationError("host queue envelope hash mismatch")
        return envelope

    def record(self, queue_id: str, request_hash: str, status: str, result: Any = None, error: str = "") -> None:
        self.events.append("HOST_BUNDLE_SYNC_RESULT", {
            "bundle_queue_id": queue_id,
            "request_sha256": request_hash,
            "status": status,
            "result_sha256": digest(result or {}),
            "error": error,
        })


class V6RuntimeMixin:
    """Mixin layered before the v5.4 compatibility runtime."""

    def _v6_queue(self) -> HostBundleQueue:
        configured = os.environ.get("CBI_HOST_PENDING_ROOT")
        root = Path(configured) if configured else self.store.root.parent / "host-pending-v6"
        return HostBundleQueue(root)

    def _v6_events(self, investigation_id: str) -> list[dict[str, Any]]:
        return self.store.read(_nonempty(investigation_id, "investigation_id"))

    def _ensure_v6(self, investigation_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        init_lock = self.store.root / f".{investigation_id}.v6-init.lock"
        with exclusive_file_lock(init_lock, timeout_seconds=30.0):
            events = self._v6_events(investigation_id)
            existing = next((event["payload"] for event in events if event["event_type"] == "V6_RUNTIME_INITIALIZED"), None)
            if existing:
                return existing
            catalog = {key: dict(value) for key, value in DEFAULT_CLAIM_CATALOG.items()}
            extra = options.get("claim_catalog") or {}
            if not isinstance(extra, dict):
                raise ValidationError("claim_catalog: object required")
            for key, config in extra.items():
                claim_key = _safe_id(key, "claim_catalog key")
                row = _require_object(config, f"claim_catalog.{claim_key}")
                catalog[claim_key] = {
                    "critical": row.get("critical") is True,
                    "commercial_weight": max(0.0, float(row.get("commercial_weight", 0))),
                    "decision_impact": min(1.0, max(0.0, float(row.get("decision_impact", 0.5)))),
                    "allow_not_applicable": row.get("allow_not_applicable") is True,
                }
            grade = str(options.get("priority_grade") or "B").upper()
            if grade not in BUDGET_BY_GRADE:
                raise ValidationError("priority_grade invalid")
            payload = {
                "schema": "cbi.investigation-extension.v6.1",
                "state_version": 2,
                "runtime_version": V6_RUNTIME_VERSION,
                "build_id": V6_BUILD_ID,
                "investigation_id": investigation_id,
                "claim_catalog": catalog,
                "search_playbook": {key: list(value) for key, value in SEARCH_PLAYBOOK.items()},
                "network_branches": list(NETWORK_BRANCHES_V6),
                "priority_grade": grade,
                "budget_units": float(options.get("budget_units", BUDGET_BY_GRADE[grade])),
                "decision_saturation_threshold": float(options.get("decision_saturation_threshold", 0.12)),
                "completion_policy": "DECISION_SATURATION",
                "source_profile_semantics": "SEARCH_PLAYBOOK_NOT_MANDATORY_CHECKLIST",
                "created_at": iso_utc(),
            }
            _walk_no_secrets(payload, "v6_initialization")
            self.store.append(investigation_id, "V6_RUNTIME_INITIALIZED", payload)
            return payload

    def _v6_state(self, investigation_id: str) -> dict[str, Any]:
        events = self._v6_events(investigation_id)
        start = events[0]["payload"]
        extension = next((event["payload"] for event in events if event["event_type"] == "V6_RUNTIME_INITIALIZED"), None)
        if extension is None:
            extension = {
                "schema": "cbi.investigation-extension.v6.1",
                "state_version": 0,
                "runtime_version": V6_RUNTIME_VERSION,
                "build_id": V6_BUILD_ID,
                "investigation_id": investigation_id,
                "claim_catalog": {key: dict(value) for key, value in DEFAULT_CLAIM_CATALOG.items()},
                "search_playbook": {key: list(value) for key, value in SEARCH_PLAYBOOK.items()},
                "network_branches": list(NETWORK_BRANCHES_V6),
                "priority_grade": "B",
                "budget_units": BUDGET_BY_GRADE["B"],
                "decision_saturation_threshold": 0.12,
                "completion_policy": "DECISION_SATURATION",
                "source_profile_semantics": "SEARCH_PLAYBOOK_NOT_MANDATORY_CHECKLIST",
                "legacy_adapter_read_only": True,
            }
        state: dict[str, Any] = {
            "events": events,
            "start": start,
            "extension": extension,
            "observations": {},
            "observation_hashes": {},
            "bundles": {},
            "objectives": {},
            "pivots": {},
            "peers": {},
            "closures": {},
            "cost_used": 0.0,
        }
        for event in events[1:]:
            payload = event["payload"]
            kind = event["event_type"]
            if kind == "V6_OBSERVATION_COMPILED":
                observation = {**payload["observation"], "_event_seq": event["seq"]}
                state["observations"][observation["observation_id"]] = observation
                state["observation_hashes"][observation["source_observation_hash"]] = observation["observation_id"]
                state["cost_used"] += float(observation.get("search_cost", 1.0))
                for pivot in observation.get("pivots", []):
                    state["pivots"][pivot["pivot_id"]] = {**pivot, "_generated_seq": event["seq"]}
            elif kind == "V6_RESEARCH_BUNDLE_COMPILED":
                state["bundles"][payload["bundle_id"]] = dict(payload)
            elif kind == "V6_RESEARCH_OBJECTIVE_SUBMITTED":
                state["objectives"][payload["objective_id"]] = {**payload, "_event_seq": event["seq"]}
            elif kind == "V6_PIVOT_CLOSED":
                if payload["pivot_id"] in state["pivots"]:
                    state["pivots"][payload["pivot_id"]].update(payload)
            elif kind == "V6_PEER_DISCOVERED":
                state["peers"][payload["peer_id"]] = {**payload, "_discovery_seq": event["seq"]}
            elif kind in {"V6_PEER_EVALUATED", "V6_ANCHOR_PROMOTED"}:
                peer = state["peers"].setdefault(payload["peer_id"], {"peer_id": payload["peer_id"]})
                peer.update(payload)
                peer["_last_lifecycle_seq"] = event["seq"]
                if kind == "V6_ANCHOR_PROMOTED":
                    peer["_promotion_seq"] = event["seq"]
            elif kind == "CLOSURE_ISSUED":
                # Schema-less Closure rows belong to the v5 compatibility
                # engine and remain historical lineage only.  They must never
                # become fresh v6 research/outreach authority.
                if str(payload.get("schema") or "").startswith("cbi.closure.v6"):
                    state["closures"][payload["closure_id"]] = {**payload, "seq": event["seq"]}
            elif kind == "OUTREACH_PREPARED":
                closure = state["closures"].get(payload.get("closure_id"))
                if closure:
                    closure["used"] = True
        return state

    def start_investigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        _walk_no_secrets(args, "arguments")
        # Session reuse is a read-then-create operation in the compatibility
        # adapter.  Serialize starts so concurrent identical requests cannot
        # create parallel investigations before either becomes visible.
        with exclusive_file_lock(self.store.root / ".v6-start.lock", timeout_seconds=60.0):
            result = super().start_investigation(arguments)
            extension = self._ensure_v6(result["investigation_id"], args)
        return {
            **result,
            "schema": "cbi.investigation.v6.1",
            "runtime_version": V6_RUNTIME_VERSION,
            "build_id": V6_BUILD_ID,
            "claim_catalog": extension["claim_catalog"],
            "search_playbook": extension["search_playbook"],
            "completion_policy": "DECISION_SATURATION",
            "budget": {"priority_grade": extension["priority_grade"], "allocated_units": extension["budget_units"]},
        }

    def resume_investigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        return {
            "schema": "cbi.investigation-state.v6.1",
            "investigation_id": investigation_id,
            "status": "RESUMED",
            "durable": True,
            "last_safe_seq": state["events"][-1]["seq"],
            "last_safe_event_hash": state["events"][-1]["event_hash"],
            "observations": len(state["observations"]),
            "objectives": len(state["objectives"]),
            "open_material_pivots": len(self._material_pivots(state)),
            "transport_session_is_state_owner": False,
        }

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract.update({
            "runtime_version": V6_RUNTIME_VERSION,
            "build_id": V6_BUILD_ID,
            "architecture": {
                "layers": ["HOST_RESEARCH_AGENT", "EVIDENCE_COMPILER", "GOVERNANCE_RUNTIME", "ARTIFACT_TOOL_TRANSACTION"],
                "sidecar": "PORTFOLIO_SCHEDULER_AND_BUDGET_CONTROLLER",
                "runtime_executes_web_search": False,
                "runtime_owns_durable_governance_state": True,
                "transport_session_owns_state": False,
            },
        })
        contract["schemas"] = {
            "investigation": "cbi.investigation.v6.1",
            "research_bundle": "cbi.research-bundle.v6.1",
            "compiled_observation": "cbi.compiled-observation.v6.1",
            "claim_view": "cbi.claim-view.v6.1",
            "host_pending_bundle": "cbi.host-pending-bundle.v6.1",
            "crm_writeback_receipt": "cbi.crm-writeback.v6.1",
        }
        contract["workflow_policy"]["answer_first"]["cbi_mcp_tools_forbidden"] = list(V6_CBI_MCP_TOOL_NAMES)
        contract["enums"].update({
            "claim_state": list(CLAIM_STATES),
            "commercial_value_grade": list(COMMERCIAL_VALUE_GRADES),
            "research_confidence": list(RESEARCH_CONFIDENCE_GRADES),
            "outreach_readiness": list(OUTREACH_READINESS_STATES),
            "peer_stage": list(PEER_STAGES),
            "authority_level": list(AUTHORITY_LEVELS),
            "freshness": list(FRESHNESS_LEVELS),
            "observation_result": list(OBSERVATION_RESULTS),
        })
        contract["claim_driven_research"] = {
            "claim_catalog": DEFAULT_CLAIM_CATALOG,
            "search_playbook": {key: list(value) for key, value in SEARCH_PLAYBOOK.items()},
            "source_profile_is_mandatory_checklist": False,
            "closure_strategy": "DECISION_SATURATION",
            "eiv_formula": "probability * decision_impact * evidence_quality_gain * commercial_weight / search_cost",
            "budget_exhaustion_closes_research": False,
            "positive_result_closes_research": False,
            "strong_support_requires_independent_controlling_sources": True,
            "critical_claim_not_applicable_default": False,
            "negative_exhaustion_declarations_bind_to_actual_attempts": True,
        }
        contract["commercial_dimensions"] = {
            "commercial_value_independent_of_contact_crm": True,
            "contact_or_crm_caps_commercial_value": False,
            "research_confidence_independent": True,
            "outreach_readiness_independent": True,
            "crm_state_independent": True,
            "legacy_grade_cap_is_not_v6_policy": True,
        }
        contract["peer_policy_v6"] = {
            "stages": list(PEER_STAGES),
            "branches": list(NETWORK_BRANCHES_V6),
            "contact_coverage_required_for_anchor_eligibility": False,
            "branch_closure": "CLAIM_AND_EIV_BASED",
            "positive_fact_evidence_binding_required": True,
            "peer_owned_evidence_must_follow_discovery": True,
            "lifecycle_is_monotonic": True,
            "undispositioned_peer_blocks_saturation": True,
            "canonical_new_is_registry_derived": True,
        }
        contract["durability_v6"] = {
            "session_log": "APPEND_ONLY_HASH_CHAIN_SERIALIZED_READ_WRITE_FSYNC",
            "host_queue_independent_of_runtime_transport": True,
            "resume_tool": "resume_investigation",
            "compiler_batch_size": {"minimum": 1, "maximum": 1000},
            "compiler_payload_bytes": {
                "maximum_observation": MAX_OBSERVATION_BYTES,
                "maximum_bundle": MAX_RESEARCH_BUNDLE_BYTES,
                "maximum_host_queue_payload": MAX_HOST_QUEUE_PAYLOAD_BYTES,
            },
            "partial_success": True,
            "idempotent_replay": True,
            "concurrent_identical_bundle_replay": "EXACTLY_ONCE",
            "dead_process_lock_recovery": True,
            "closure_and_outreach_atomic_tail_check": True,
        }
        contract["closure_invalidation_v6_1"] = {
            "expired_token_reusable": False,
            "operational_event_types": sorted(V6_OPERATIONAL_EVENTS),
        }
        contract["error_categories"] = [
            "VALIDATION_ERROR", "CONFLICT_ERROR", "TRANSPORT_ERROR", "PROVIDER_ERROR",
            "PERSISTENCE_ERROR", "INTEGRITY_ERROR", "QUARANTINED_READ_ONLY",
        ]
        return contract

    def get_runtime_health(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().get_runtime_health(arguments)
        try:
            queue_rows = self._v6_queue().entries()
            host_queue_error = None
        except ValidationError as exc:
            queue_rows = []
            host_queue_error = str(exc)
        errors = list(result.get("errors") or [])
        if host_queue_error:
            errors.append(host_queue_error)
        return {
            **result,
            "runtime_version": V6_RUNTIME_VERSION,
            "build_id": V6_BUILD_ID,
            "architecture_status": "READY" if not errors else "QUARANTINED_READ_ONLY",
            "host_pending_bundles": {
                status: sum(row["status"] == status for row in queue_rows)
                for status in {"PENDING", "SYNCED", "PARTIAL_SUCCESS", "FAILED_VALIDATION"}
            },
            "errors": errors,
        }

    @_serialized_v6_mutation
    def submit_research_objective(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        raw = _require_object(args.get("objective"), "objective")
        _walk_no_secrets(raw, "objective")
        if _encoded_size(raw, "objective") > 256 * 1024:
            raise ValidationError("objective exceeds the 256 KiB limit")
        claim_key = _nonempty(raw.get("claim_key"), "objective.claim_key")
        if claim_key not in state["extension"]["claim_catalog"]:
            raise ValidationError("objective.claim_key is not registered in the investigation claim catalog")
        objective_id = str(raw.get("objective_id") or _stable_id("OBJ", {"investigation_id": investigation_id, **raw})).strip()
        _safe_id(objective_id, "objective.objective_id")
        if objective_id in state["objectives"]:
            if digest(raw) == state["objectives"][objective_id].get("input_sha256"):
                return {"accepted": True, "deduplicated": True, "objective_id": objective_id}
            raise ValidationError("duplicate objective_id with different content")
        probability = min(1.0, max(0.0, float(raw.get("probability", 0.5))))
        decision_impact = min(1.0, max(0.0, float(raw.get("decision_impact", state["extension"]["claim_catalog"][claim_key]["decision_impact"]))))
        evidence_gain = min(1.0, max(0.0, float(raw.get("evidence_quality_gain", 0.6))))
        commercial_weight = max(0.0, float(raw.get("commercial_weight", max(1.0, state["extension"]["claim_catalog"][claim_key]["commercial_weight"]))))
        search_cost = max(0.01, float(raw.get("search_cost", 1.0)))
        eiv = probability * decision_impact * evidence_gain * commercial_weight / search_cost
        payload = {
            "schema": "cbi.research-objective.v6.1",
            "objective_id": objective_id,
            "investigation_id": investigation_id,
            "claim_key": claim_key,
            "query_or_navigation": _nonempty(raw.get("query_or_navigation"), "objective.query_or_navigation"),
            "source_family": _nonempty(raw.get("source_family"), "objective.source_family"),
            "network_branch": str(raw.get("network_branch") or ""),
            "probability": probability,
            "decision_impact": decision_impact,
            "evidence_quality_gain": evidence_gain,
            "commercial_weight": commercial_weight,
            "search_cost": search_cost,
            "eiv": round(eiv, 8),
            "status": "PLANNED",
            "input_sha256": digest(raw),
            "submitted_at": iso_utc(),
        }
        self.store.append(investigation_id, "V6_RESEARCH_OBJECTIVE_SUBMITTED", payload)
        return {"accepted": True, "deduplicated": False, **payload}

    def _normalize_source(self, raw: dict[str, Any], observation: dict[str, Any], index: int) -> dict[str, Any]:
        source = _require_object(raw, f"observations[{index}].source")
        reference_type = str(source.get("reference_type") or "PUBLIC_URL").upper()
        if reference_type not in REFERENCE_TYPES:
            raise ValidationError(f"observations[{index}].source.reference_type invalid")
        url = str(source.get("url") or "").strip()
        locator = _nonempty(source.get("locator") or url, f"observations[{index}].source.locator")
        if _SELF_PROOF_RE.search(locator):
            raise ValidationError(f"observations[{index}].source.locator is a self-authored proof string")
        if reference_type == "PUBLIC_URL" and not _URL_RE.fullmatch(url):
            raise ValidationError(f"observations[{index}].source.url requires a concrete HTTP(S) URL")
        if reference_type != "PUBLIC_URL" and url:
            raise ValidationError(f"observations[{index}].source.url must be empty for non-URL evidence")
        authority = str(source.get("authority_level") or "C2_SECONDARY_PUBLIC").upper()
        if authority not in AUTHORITY_LEVELS:
            raise ValidationError(f"observations[{index}].source.authority_level invalid")
        freshness = str(source.get("freshness") or "UNKNOWN").upper()
        if freshness not in FRESHNESS_LEVELS:
            raise ValidationError(f"observations[{index}].source.freshness invalid")
        supplied_hash = str(source.get("content_sha256") or "").strip()
        explicit_raw_content = source.get("raw_content")
        raw_material = explicit_raw_content
        if raw_material in (None, ""):
            raw_material = source.get("raw_excerpt")
        calculated_hash = ""
        if raw_material not in (None, ""):
            material = raw_material.encode("utf-8") if isinstance(raw_material, str) else canonical_json(raw_material).encode("utf-8")
            calculated_hash = hashlib.sha256(material).hexdigest()
        if supplied_hash:
            content_hash = _valid_hash(supplied_hash, f"observations[{index}].source.content_sha256")
            if explicit_raw_content not in (None, "") and calculated_hash and content_hash != calculated_hash:
                raise ValidationError(f"observations[{index}].source.content_sha256 does not match raw_content")
        elif calculated_hash:
            content_hash = calculated_hash
        else:
            raise ValidationError(f"observations[{index}].source requires content_sha256 or raw_content/raw_excerpt")
        excerpt = str(source.get("raw_excerpt") or "")[:2000]
        return {
            "source_family": _nonempty(source.get("source_family"), f"observations[{index}].source.source_family"),
            "source_type": _nonempty(source.get("source_type") or source.get("source_family"), f"observations[{index}].source.source_type"),
            "reference_type": reference_type,
            "url": url,
            "locator": locator,
            "content_sha256": content_hash,
            "authority_level": authority,
            "freshness": freshness,
            "observed_at": _format_time(_parse_time(source.get("observed_at"), f"observations[{index}].source.observed_at")),
            "raw_excerpt": excerpt,
            "raw_content_retained": False,
        }

    def _normalize_observation(
        self,
        investigation_id: str,
        bundle_id: str,
        index: int,
        raw: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        _walk_no_secrets(raw, f"observations[{index}]")
        result = str(raw.get("result") or "POSITIVE").upper()
        if result not in OBSERVATION_RESULTS:
            raise ValidationError(f"observations[{index}].result invalid")
        claim_key = _nonempty(raw.get("claim_key"), f"observations[{index}].claim_key")
        if claim_key not in state["extension"]["claim_catalog"]:
            raise ValidationError(f"observations[{index}].claim_key is not registered")
        owner_type = str(raw.get("owner_type") or "ACCOUNT").upper()
        if owner_type not in {"ACCOUNT", "PEER", "PERSON", "SUPPLIER", "PRODUCT"}:
            raise ValidationError(f"observations[{index}].owner_type invalid")
        account_id = state["start"]["account"]["account_id"]
        owner_id = _nonempty(raw.get("owner_id") or account_id, f"observations[{index}].owner_id")
        if owner_type == "ACCOUNT" and owner_id != account_id:
            raise ValidationError(f"observations[{index}]: ACCOUNT owner must match the investigation account")
        if owner_type == "PEER" and owner_id not in state["peers"]:
            raise ValidationError(f"observations[{index}]: PEER owner must be discovered before Peer-owned Evidence is compiled")
        source = self._normalize_source(_require_object(raw.get("source"), f"observations[{index}].source"), raw, index)
        if result == "NEGATIVE_EXHAUSTED":
            exhaustion = _require_object(raw.get("search_exhaustion"), f"observations[{index}].search_exhaustion")
            strategies = exhaustion.get("independent_queries") or []
            attempts = exhaustion.get("independent_attempts") or []
            if exhaustion.get("exhausted") is not True or not isinstance(strategies, list) or len({str(x).strip().casefold() for x in strategies if str(x).strip()}) < 2:
                raise ValidationError(f"observations[{index}]: NEGATIVE_EXHAUSTED requires at least two independent real query/navigation strategies")
            if not isinstance(attempts, list) or len(attempts) < 2:
                raise ValidationError(f"observations[{index}]: NEGATIVE_EXHAUSTED requires at least two independent raw proof receipts")
            proof_keys: set[tuple[str, str]] = set()
            actual_queries: set[str] = set()
            for attempt_index, attempt_raw in enumerate(attempts):
                attempt = _require_object(attempt_raw, f"observations[{index}].search_exhaustion.independent_attempts[{attempt_index}]")
                query = _nonempty(attempt.get("query_or_navigation"), f"observations[{index}].search_exhaustion.independent_attempts[{attempt_index}].query_or_navigation")
                locator = _nonempty(attempt.get("raw_result_locator"), f"observations[{index}].search_exhaustion.independent_attempts[{attempt_index}].raw_result_locator")
                if _SELF_PROOF_RE.search(locator):
                    raise ValidationError(f"observations[{index}]: negative exhaustion raw proof cannot be self-authored")
                if not (
                    _URL_RE.fullmatch(locator)
                    or Path(locator).is_absolute()
                    or locator.startswith(("artifact://", "snapshot://", "page-snapshot://"))
                ):
                    raise ValidationError(f"observations[{index}]: negative exhaustion requires a concrete URL or saved artifact locator")
                proof_hash = _valid_hash(attempt.get("content_sha256"), f"observations[{index}].search_exhaustion.independent_attempts[{attempt_index}].content_sha256")
                proof_keys.add((query.casefold(), f"{locator}|{proof_hash}"))
                actual_queries.add(" ".join(query.casefold().split()))
            if len(proof_keys) < 2 or len(actual_queries) < 2:
                raise ValidationError(f"observations[{index}]: negative exhaustion proofs must be independent")
            declared_queries = {" ".join(str(item).casefold().split()) for item in strategies if str(item).strip()}
            if any(
                not any(declared in actual or actual in declared for actual in actual_queries)
                for declared in declared_queries
            ):
                raise ValidationError(f"observations[{index}]: every declared exhaustion strategy must bind to a real attempt query/navigation")
        if result == "BLOCKED" and not str(raw.get("blocked_reason") or "").strip():
            raise ValidationError(f"observations[{index}].blocked_reason required")
        if result == "NOT_APPLICABLE":
            reason = str(raw.get("not_applicable_reason") or "").strip()
            claim_config = state["extension"]["claim_catalog"][claim_key]
            if claim_config.get("allow_not_applicable") is not True:
                raise ValidationError(f"observations[{index}]: claim does not permit NOT_APPLICABLE")
            if len(reason) < 20:
                raise ValidationError(f"observations[{index}].not_applicable_reason requires a specific justification")
            if _BLOCKED_AS_NA_RE.search(reason):
                raise ValidationError(f"observations[{index}]: access failure must be BLOCKED, not NOT_APPLICABLE")
        value = raw.get("value")
        observation_type = str(raw.get("observation_type") or "FACT").upper()
        network_branch = str(raw.get("network_branch") or "").upper()
        if network_branch and network_branch not in NETWORK_BRANCHES_V6:
            raise ValidationError(f"observations[{index}].network_branch invalid")
        material = {
            "owner_type": owner_type,
            "owner_id": owner_id,
            "observation_type": observation_type,
            "network_branch": network_branch,
            "module_or_branch": network_branch or claim_key.split(".", 1)[0],
            "claim_key": claim_key,
            "result": result,
            "value": value,
            "source": source,
            "relationship_to_account": str(raw.get("relationship_to_account") or "SELF"),
        }
        source_observation_hash = digest(material)
        observation_id = str(raw.get("observation_id") or _stable_id("OBS", source_observation_hash)).strip()
        _safe_id(observation_id, f"observations[{index}].observation_id")
        evidence_id = None
        if result in {"POSITIVE", "REFUTED", "CONFLICT"}:
            evidence_id = str(raw.get("evidence_id") or _stable_id("EVD", {"observation_id": observation_id, "source": source["content_sha256"]})).strip()
            _safe_id(evidence_id, f"observations[{index}].evidence_id")
        pivots: list[dict[str, Any]] = []
        for pivot_index, pivot_raw in enumerate(raw.get("pivots") or []):
            pivot = _require_object(pivot_raw, f"observations[{index}].pivots[{pivot_index}]")
            pivot_value = _nonempty(pivot.get("value"), f"observations[{index}].pivots[{pivot_index}].value")
            pivot_type = _nonempty(pivot.get("type"), f"observations[{index}].pivots[{pivot_index}].type").upper()
            materiality = str(pivot.get("materiality") or "OPTIONAL").upper()
            if materiality not in {"MATERIAL", "OPTIONAL"}:
                raise ValidationError(f"observations[{index}].pivots[{pivot_index}].materiality invalid")
            pivot_id = str(pivot.get("pivot_id") or _stable_id("PIV", {"observation_id": observation_id, "type": pivot_type, "value": pivot_value})).strip()
            pivots.append({
                "pivot_id": _safe_id(pivot_id, f"observations[{index}].pivots[{pivot_index}].pivot_id"),
                "pivot_type": pivot_type,
                "pivot_value": pivot_value,
                "materiality": materiality,
                "estimated_eiv": max(0.0, float(pivot.get("estimated_eiv", 0.0))),
                "generated_by_observation_id": observation_id,
                "generated_at": iso_utc(),
                "status": "OPEN",
            })
        return {
            "schema": "cbi.compiled-observation.v6.1",
            "observation_id": observation_id,
            "source_observation_hash": source_observation_hash,
            "bundle_id": bundle_id,
            "investigation_id": investigation_id,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "relationship_to_account": material["relationship_to_account"],
            "observation_type": observation_type,
            "network_branch": network_branch,
            "module_or_branch": network_branch or claim_key.split(".", 1)[0],
            "claim_key": claim_key,
            "result": result,
            "value": value,
            "source": source,
            "evidence_id": evidence_id,
            "boundary": _nonempty(raw.get("boundary") or "Only the stated observation is supported; no unstated ownership, recency or commercial conclusion is implied.", f"observations[{index}].boundary"),
            "conflicts_with": [str(item) for item in raw.get("conflicts_with") or []],
            "blocked_reason": str(raw.get("blocked_reason") or ""),
            "not_applicable_reason": str(raw.get("not_applicable_reason") or ""),
            "search_exhaustion": raw.get("search_exhaustion") or {},
            "pivots": pivots,
            "commercial_signals": raw.get("commercial_signals") or {},
            "search_cost": max(0.0, float(raw.get("search_cost", 1.0))),
            "compiled_at": iso_utc(),
        }

    @_serialized_v6_mutation
    def compile_and_append_research_bundle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        bundle = _require_object(args.get("bundle"), "bundle")
        _walk_no_secrets({key: value for key, value in bundle.items() if key != "observations"}, "bundle")
        try:
            bundle_size = len(json.dumps(
                bundle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=True,
            ).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("bundle: JSON-compatible data required") from exc
        if bundle_size > MAX_RESEARCH_BUNDLE_BYTES:
            raise ValidationError("bundle exceeds the 32 MiB compiler limit")
        observations = _require_list(bundle.get("observations"), "bundle.observations")
        if not 1 <= len(observations) <= 1000:
            raise ValidationError("bundle.observations must contain 1-1000 observations")
        input_material = json.dumps(
            {"investigation_id": investigation_id, "observations": observations},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
        ).encode("utf-8")
        input_sha256 = hashlib.sha256(input_material).hexdigest()
        bundle_id = str(bundle.get("bundle_id") or f"BUNDLE-{input_sha256[:16]}").strip()
        _safe_id(bundle_id, "bundle.bundle_id")
        prior = state["bundles"].get(bundle_id)
        if prior:
            if prior.get("input_sha256") != input_sha256:
                raise ValidationError("bundle_id replayed with different content")
            return {**prior, "idempotent_replay": True}
        outcomes: list[dict[str, Any]] = []
        accepted_ids: list[str] = []
        pending_rows: list[tuple[str, dict[str, Any]]] = []
        pending_hashes: dict[str, str] = {}
        pending_ids: set[str] = set()
        for index, item in enumerate(observations):
            try:
                raw = _require_object(item, f"bundle.observations[{index}]")
                if _encoded_size(raw, f"bundle.observations[{index}]") > MAX_OBSERVATION_BYTES:
                    raise ValidationError(f"bundle.observations[{index}] exceeds the 2 MiB observation limit")
                normalized = self._normalize_observation(investigation_id, bundle_id, index, raw, state)
                existing_id = state["observation_hashes"].get(normalized["source_observation_hash"]) or pending_hashes.get(normalized["source_observation_hash"])
                if existing_id:
                    outcomes.append({"index": index, "status": "DEDUPLICATED", "observation_id": existing_id})
                    accepted_ids.append(existing_id)
                    continue
                if normalized["observation_id"] in state["observations"] or normalized["observation_id"] in pending_ids:
                    raise ValidationError("duplicate observation_id with different content")
                pending_rows.append(("V6_OBSERVATION_COMPILED", {"observation": normalized}))
                pending_hashes[normalized["source_observation_hash"]] = normalized["observation_id"]
                pending_ids.add(normalized["observation_id"])
                outcomes.append({"index": index, "status": "ACCEPTED", "observation_id": normalized["observation_id"], "evidence_id": normalized["evidence_id"]})
                accepted_ids.append(normalized["observation_id"])
            except (ValidationError, TypeError, ValueError) as exc:
                outcomes.append({"index": index, "status": "REJECTED", "error_category": "VALIDATION_ERROR", "error": str(exc)})
        self.store.append_many(investigation_id, pending_rows)
        accepted = sum(row["status"] in {"ACCEPTED", "DEDUPLICATED"} for row in outcomes)
        rejected = len(outcomes) - accepted
        summary = {
            "schema": "cbi.research-bundle-result.v6.1",
            "bundle_id": bundle_id,
            "investigation_id": investigation_id,
            "input_sha256": input_sha256,
            "accepted_count": accepted,
            "rejected_count": rejected,
            "status": "ACCEPTED" if rejected == 0 else ("PARTIAL_SUCCESS" if accepted else "REJECTED"),
            "accepted_observation_ids": accepted_ids,
            "outcomes": outcomes,
            "compiled_at": iso_utc(),
        }
        self.store.append(investigation_id, "V6_RESEARCH_BUNDLE_COMPILED", summary)
        return {**summary, "idempotent_replay": False}

    def _claims_view(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        account_id = state["start"]["account"]["account_id"]
        for claim_key, config in state["extension"]["claim_catalog"].items():
            rows = [
                row for row in state["observations"].values()
                if row["claim_key"] == claim_key and row["owner_type"] == "ACCOUNT" and row["owner_id"] == account_id
            ]
            positive = [row for row in rows if row["result"] == "POSITIVE"]
            refuted = [row for row in rows if row["result"] == "REFUTED"]
            conflicts = [row for row in rows if row["result"] == "CONFLICT" or row.get("conflicts_with")]
            exhausted = [row for row in rows if row["result"] == "NEGATIVE_EXHAUSTED"]
            blocked = [row for row in rows if row["result"] == "BLOCKED"]
            not_applicable = [row for row in rows if row["result"] == "NOT_APPLICABLE"]
            searching = [row for row in rows if row["result"] == "NEGATIVE"]
            source_documents = {row["source"]["content_sha256"] for row in positive}
            independent_sources = {_independent_source_key(row["source"]) for row in positive}
            strong_authority = any(row["source"]["authority_level"].startswith(("A1_", "A2_", "B1_")) for row in positive)
            all_stale = bool(positive) and all(row["source"]["freshness"] in {"HISTORICAL", "STALE"} for row in positive)
            if conflicts or (positive and refuted):
                status = "CONFLICTED"
            elif all_stale:
                status = "STALE"
            elif len(independent_sources) >= 2 and strong_authority:
                status = "STRONGLY_SUPPORTED"
            elif positive:
                status = "SUPPORTED"
            elif refuted:
                status = "REFUTED"
            elif exhausted:
                status = "NEGATIVE_EXHAUSTED"
            elif blocked:
                status = "BLOCKED"
            elif not_applicable:
                status = "NOT_APPLICABLE"
            elif searching or any(row["claim_key"] == claim_key for row in state["objectives"].values()):
                status = "SEARCHING"
            else:
                status = "UNSEEN"
            output[claim_key] = {
                "claim_key": claim_key,
                "state": status,
                "critical": bool(config["critical"]),
                "decision_impact": float(config["decision_impact"]),
                "commercial_weight": float(config["commercial_weight"]),
                "observation_ids": [row["observation_id"] for row in rows],
                "evidence_ids": [row["evidence_id"] for row in rows if row.get("evidence_id")],
                "source_count": len({row["source"]["locator"] for row in rows}),
                "source_document_count": len(source_documents),
                "independent_source_count": len(independent_sources),
                "conflict_count": len(conflicts),
                "blocked_reasons": sorted({row["blocked_reason"] for row in blocked if row["blocked_reason"]}),
            }
        return output

    def get_claims(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        claims = self._claims_view(state)
        return {
            "schema": "cbi.claim-view.v6.1",
            "investigation_id": state["start"]["investigation_id"],
            "claims": claims,
            "counts": {status: sum(row["state"] == status for row in claims.values()) for status in CLAIM_STATES},
        }

    def _material_pivots(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            pivot for pivot in state["pivots"].values()
            if pivot.get("status") in {"OPEN", "BLOCKED"}
            and (pivot.get("materiality") == "MATERIAL" or float(pivot.get("estimated_eiv", 0)) >= state["extension"]["decision_saturation_threshold"])
        ]

    def get_material_pivots(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        pivots = self._material_pivots(state)
        return {"investigation_id": state["start"]["investigation_id"], "material_pivots": pivots, "count": len(pivots)}

    @_serialized_v6_mutation
    def close_pivot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        _walk_no_secrets(args, "arguments")
        pivot_id = _nonempty(args.get("pivot_id"), "pivot_id")
        pivot = state["pivots"].get(pivot_id)
        if not pivot:
            raise ValidationError("pivot not found")
        status = str(args.get("status") or "CONSUMED").upper()
        if status not in {"CONSUMED", "NOT_MATERIAL", "BLOCKED"}:
            raise ValidationError("status must be CONSUMED, NOT_MATERIAL or BLOCKED")
        reason = _nonempty(args.get("reason"), "reason")
        if pivot.get("status") in {"CONSUMED", "NOT_MATERIAL"}:
            if pivot.get("status") == status:
                return {"accepted": True, "deduplicated": True, **pivot}
            raise ValidationError("terminal Pivot state cannot regress or be rewritten")
        if status == "CONSUMED":
            objective_id = _nonempty(args.get("consumed_by_objective_id"), "consumed_by_objective_id")
            if objective_id not in state["objectives"]:
                raise ValidationError("consuming objective not found")
            objective = state["objectives"][objective_id]
            if int(objective.get("_event_seq", 0)) <= int(pivot.get("_generated_seq", 0)):
                raise ValidationError("Pivot consumption requires a later independent objective")
            pivot_value = str(pivot.get("pivot_value") or "").casefold()
            if pivot_value not in str(objective.get("query_or_navigation") or "").casefold():
                raise ValidationError("consuming objective must contain the Pivot value")
            max_remaining_eiv = 0.0
        elif status == "NOT_MATERIAL":
            if len(reason) < 20:
                raise ValidationError("NOT_MATERIAL requires a specific decision basis")
            try:
                max_remaining_eiv = float(args.get("max_remaining_eiv"))
            except (TypeError, ValueError) as exc:
                raise ValidationError("NOT_MATERIAL requires max_remaining_eiv") from exc
            if not math.isfinite(max_remaining_eiv) or max_remaining_eiv < 0:
                raise ValidationError("max_remaining_eiv must be a finite non-negative number")
            if max_remaining_eiv >= float(state["extension"]["decision_saturation_threshold"]):
                raise ValidationError("NOT_MATERIAL requires remaining EIV below the decision-saturation threshold")
            objective_id = ""
        else:
            objective_id = ""
            max_remaining_eiv = max(0.0, float(args.get("max_remaining_eiv", pivot.get("estimated_eiv", 0.0))))
        payload = {
            "pivot_id": pivot_id,
            "status": status,
            "reason": reason,
            "consumed_by_objective_id": objective_id,
            "max_remaining_eiv": max_remaining_eiv,
            "closed_at": iso_utc(),
        }
        self.store.append(investigation_id, "V6_PIVOT_CLOSED", payload)
        return {"accepted": True, **payload}

    def _objective_candidates(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        claims = self._claims_view(state)
        threshold = float(state["extension"]["decision_saturation_threshold"])
        candidates: list[dict[str, Any]] = []
        status_probability = {"UNSEEN": 0.65, "SEARCHING": 0.45, "BLOCKED": 0.2, "CONFLICTED": 0.7, "STALE": 0.55}
        for claim_key, claim in claims.items():
            if claim["state"] not in status_probability:
                continue
            probability = status_probability[claim["state"]]
            evidence_gain = 0.9 if claim["state"] in {"UNSEEN", "CONFLICTED"} else 0.65
            commercial_weight = max(1.0, claim["commercial_weight"])
            search_cost = 1.0 if claim["state"] != "BLOCKED" else 2.0
            eiv = probability * claim["decision_impact"] * evidence_gain * commercial_weight / search_cost
            family = claim_key.split(".", 1)[0]
            candidates.append({
                "candidate_type": "CLAIM",
                "claim_key": claim_key,
                "recommended_source_families": list(SEARCH_PLAYBOOK.get(family, SEARCH_PLAYBOOK.get("company", ()))),
                "probability": probability,
                "decision_impact": claim["decision_impact"],
                "evidence_quality_gain": evidence_gain,
                "commercial_weight": commercial_weight,
                "search_cost": search_cost,
                "eiv": round(eiv, 8),
                "material": claim["critical"] or eiv >= threshold,
            })
        for pivot in self._material_pivots(state):
            eiv = max(float(pivot.get("estimated_eiv", 0.0)), threshold)
            candidates.append({
                "candidate_type": "PIVOT",
                "pivot_id": pivot["pivot_id"],
                "pivot_type": pivot["pivot_type"],
                "pivot_value": pivot["pivot_value"],
                "eiv": round(eiv, 8),
                "material": True,
            })
        candidates.sort(key=lambda row: (-float(row["eiv"]), str(row.get("claim_key") or row.get("pivot_id"))))
        return candidates

    def get_next_research_objectives(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        limit = int(args.get("limit", 20))
        if not 1 <= limit <= 1000:
            raise ValidationError("limit must be 1-1000")
        remaining = max(0.0, float(state["extension"]["budget_units"]) - state["cost_used"])
        candidates = self._objective_candidates(state)
        status = "READY" if remaining > 0 else "PAUSED_RESOURCE_LIMIT"
        return {
            "investigation_id": state["start"]["investigation_id"],
            "status": status,
            "budget": {
                "priority_grade": state["extension"]["priority_grade"],
                "allocated_units": state["extension"]["budget_units"],
                "used_units": round(state["cost_used"], 4),
                "remaining_units": round(remaining, 4),
                "budget_exhaustion_closes_research": False,
            },
            "objectives": candidates[:limit] if remaining > 0 else [],
            "deferred_objectives": candidates if remaining <= 0 else candidates[limit:],
        }

    @_serialized_v6_mutation
    def append_peer_discovery(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        raw = _require_object(args.get("peer"), "peer")
        _walk_no_secrets(raw, "peer")
        branch = str(raw.get("network_branch") or "").upper()
        if branch not in NETWORK_BRANCHES_V6:
            raise ValidationError("peer.network_branch invalid")
        name = _nonempty(raw.get("name"), "peer.name")
        country = _nonempty(raw.get("country"), "peer.country")
        relationship_ids = [str(item) for item in raw.get("relationship_evidence_ids") or []]
        evidence_index = {
            row["evidence_id"]: row
            for row in state["observations"].values()
            if row.get("evidence_id")
        }
        if not relationship_ids or not set(relationship_ids) <= set(evidence_index):
            raise ValidationError("peer requires relationship Evidence compiled in this investigation")
        discovery_observation_id = _nonempty(raw.get("discovered_by_observation_id"), "peer.discovered_by_observation_id")
        discovery_observation = state["observations"].get(discovery_observation_id)
        if not discovery_observation or discovery_observation.get("result") != "POSITIVE":
            raise ValidationError("peer discovery observation must be a positive compiled observation")
        if discovery_observation.get("network_branch") != branch:
            raise ValidationError("peer relationship Evidence must come from the same Network Branch discovery observation")
        if discovery_observation.get("evidence_id") not in relationship_ids:
            raise ValidationError("peer relationship Evidence must include the discovery observation Evidence")
        for evidence_id in relationship_ids:
            relationship = evidence_index[evidence_id]
            if (
                relationship.get("result") != "POSITIVE"
                or relationship.get("claim_key") != "relationship.supply_chain"
                or relationship.get("network_branch") != branch
            ):
                raise ValidationError("all Peer relationship Evidence must be positive, relationship-bound, and from the discovery branch")
        identity_key = digest({"name": name.casefold(), "country": country.casefold(), "tax_id": str(raw.get("tax_id") or "").casefold()})
        existing = next((peer for peer in state["peers"].values() if peer.get("identity_key") == identity_key), None)
        if existing:
            return {"accepted": True, "deduplicated": True, "peer_id": existing["peer_id"], "stage": existing["stage"]}
        peer_id = str(raw.get("peer_id") or _stable_id("PEER", identity_key)).strip()
        payload = {
            "schema": "cbi.peer.v6.1",
            "peer_id": _safe_id(peer_id, "peer.peer_id"),
            "investigation_id": investigation_id,
            "name": name,
            "country": country,
            "tax_id": str(raw.get("tax_id") or ""),
            "network_branch": branch,
            "discovered_from_owner_id": _nonempty(raw.get("discovered_from_owner_id") or state["start"]["account"]["account_id"], "peer.discovered_from_owner_id"),
            "discovered_by_observation_id": discovery_observation_id,
            "relationship_evidence_ids": relationship_ids,
            "identity_key": identity_key,
            "stage": "DISCOVERED",
            "discovered_at": iso_utc(),
        }
        self.store.append(investigation_id, "V6_PEER_DISCOVERED", payload)
        return {"accepted": True, "deduplicated": False, **payload}

    @_serialized_v6_mutation
    def evaluate_peer(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        peer_id = _nonempty(args.get("peer_id"), "peer_id")
        peer = state["peers"].get(peer_id)
        if not peer:
            raise ValidationError("peer not found")
        assessment = _require_object(args.get("assessment"), "assessment")
        _walk_no_secrets(assessment, "assessment")
        fact_keys = (
            "entity_verified", "product_fit_verified", "business_or_trade_verified",
            "relationship_verified", "commercial_novelty",
        )
        prior_facts = peer.get("assessment") if isinstance(peer.get("assessment"), dict) else {}
        facts = {
            key: (assessment.get(key) is True if key in assessment else prior_facts.get(key) is True)
            for key in fact_keys
        }
        supplied_bindings = assessment.get("fact_evidence_ids")
        if supplied_bindings is None:
            supplied_bindings = peer.get("fact_evidence_ids") or {}
        bindings_raw = _require_object(supplied_bindings, "assessment.fact_evidence_ids")
        bindings: dict[str, list[str]] = {}
        for key in fact_keys:
            raw_ids = bindings_raw.get(key) or []
            if not isinstance(raw_ids, list):
                raise ValidationError(f"assessment.fact_evidence_ids.{key}: array required")
            bindings[key] = [str(item) for item in raw_ids]
        evidence_index = {
            row["evidence_id"]: row
            for row in state["observations"].values()
            if row.get("evidence_id")
        }
        expected_claims = {
            "entity_verified": {"identity.legal_entity"},
            "product_fit_verified": {"product.fit"},
            "business_or_trade_verified": {"trade.import_activity", "company.operating_status"},
            "commercial_novelty": {
                "product.fit", "trade.import_activity", "company.operating_status",
                "commercial.procurement_need", "relationship.supply_chain",
            },
        }
        for key, claims in expected_claims.items():
            if not facts[key]:
                continue
            if not bindings[key]:
                raise ValidationError(f"{key}: positive fact requires bound Peer-owned Evidence IDs")
            for evidence_id in bindings[key]:
                observation = evidence_index.get(evidence_id)
                if (
                    not observation
                    or observation.get("owner_type") != "PEER"
                    or observation.get("owner_id") != peer_id
                    or observation.get("result") != "POSITIVE"
                    or observation.get("claim_key") not in claims
                    or int(observation.get("_event_seq", 0)) <= int(peer.get("_discovery_seq", 0))
                ):
                    raise ValidationError(f"{key}: Evidence Owner, Claim, result, or Peer lifecycle binding mismatch")
        if facts["relationship_verified"]:
            if not bindings["relationship_verified"]:
                raise ValidationError("relationship_verified: discovery relationship Evidence is required")
            if not set(bindings["relationship_verified"]) <= set(peer.get("relationship_evidence_ids") or []):
                raise ValidationError("relationship_verified: Evidence must be the Peer discovery relationship Evidence")
        novelty_basis = str(
            assessment.get("commercial_novelty_basis")
            or peer.get("commercial_novelty_basis")
            or ""
        ).strip()
        if facts["commercial_novelty"] and len(novelty_basis) < 40:
            raise ValidationError("commercial_novelty requires a specific evidence-backed decision basis")

        canonical_result = self.canonical_registry.resolve({
            "name": peer.get("name"),
            "country": peer.get("country"),
            "tax_id": peer.get("tax_id"),
        })
        canonical_new = canonical_result["status"] == "NOT_FOUND"
        if "canonical_new" in assessment and (assessment.get("canonical_new") is True) != canonical_new:
            raise ValidationError("canonical_new is mechanically derived and does not match the canonical registry")
        facts["canonical_new"] = canonical_new
        if facts["entity_verified"] and facts["product_fit_verified"] and facts["business_or_trade_verified"]:
            stage = "QUALIFIED"
        else:
            stage = "DISCOVERED"
        if stage == "QUALIFIED" and facts["relationship_verified"] and facts["commercial_novelty"] and facts["canonical_new"]:
            stage = "ANCHOR_ELIGIBLE"
        if assessment.get("full_audit_complete") is True:
            if peer.get("stage") not in {"PROMOTED_ANCHOR", "FULLY_AUDITED"}:
                raise ValidationError("FULLY_AUDITED requires a previously promoted anchor")
            branch_states = _require_object(assessment.get("network_branch_states"), "assessment.network_branch_states")
            if set(branch_states) != set(NETWORK_BRANCHES_V6):
                raise ValidationError("full audit requires all six Network Branches")
            branch_evidence_index = {
                evidence_id: row
                for evidence_id, row in evidence_index.items()
                if row.get("owner_type") == "PEER" and row.get("owner_id") == peer_id
            }
            normalized_branches: dict[str, dict[str, Any]] = {}
            for branch, detail_raw in branch_states.items():
                detail = _require_object(detail_raw, f"assessment.network_branch_states.{branch}")
                status = str(detail.get("status") or "").upper()
                if status not in {"SATURATED", "NOT_MATERIAL"}:
                    raise ValidationError("each Network Branch must be SATURATED or NOT_MATERIAL")
                basis = _nonempty(detail.get("decision_basis"), f"assessment.network_branch_states.{branch}.decision_basis")
                evidence_ids = [str(item) for item in detail.get("evidence_ids") or []]
                if status == "SATURATED":
                    if not evidence_ids:
                        raise ValidationError(f"{branch}: SATURATED requires Peer-owned branch Evidence")
                    for evidence_id in evidence_ids:
                        observation = branch_evidence_index.get(evidence_id)
                        if (
                            not observation
                            or observation.get("network_branch") != branch
                            or observation.get("result") != "POSITIVE"
                            or int(observation.get("_event_seq", 0)) <= int(peer.get("_promotion_seq", 0))
                        ):
                            raise ValidationError(f"{branch}: branch Evidence Owner, branch, result, or lifecycle mismatch")
                try:
                    max_remaining_eiv = float(detail.get("max_remaining_eiv", 1.0))
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{branch}: max_remaining_eiv must be numeric") from exc
                if not math.isfinite(max_remaining_eiv) or max_remaining_eiv < 0:
                    raise ValidationError(f"{branch}: max_remaining_eiv must be finite and non-negative")
                if status == "NOT_MATERIAL" and max_remaining_eiv >= float(state["extension"]["decision_saturation_threshold"]):
                    raise ValidationError(f"{branch}: NOT_MATERIAL requires remaining EIV below threshold")
                normalized_branches[branch] = {
                    "status": status,
                    "decision_basis": basis,
                    "evidence_ids": evidence_ids,
                    "max_remaining_eiv": max_remaining_eiv,
                }
            stage = "FULLY_AUDITED"
        else:
            normalized_branches = peer.get("network_branch_states") or {}
        current_stage = str(peer.get("stage") or "DISCOVERED")
        if PEER_STAGE_RANK.get(current_stage, 0) > PEER_STAGE_RANK.get(stage, 0):
            stage = current_stage
        disposition = str(assessment.get("disposition") or peer.get("disposition") or "PENDING").upper()
        if disposition not in {"PENDING", "NOT_MATERIAL"}:
            raise ValidationError("assessment.disposition must be PENDING or NOT_MATERIAL")
        max_remaining_eiv = peer.get("max_remaining_eiv")
        decision_basis = str(assessment.get("decision_basis") or peer.get("decision_basis") or "").strip()
        if disposition == "NOT_MATERIAL":
            if stage in {"PROMOTED_ANCHOR", "FULLY_AUDITED"}:
                raise ValidationError("a promoted or fully audited anchor cannot be disposed as NOT_MATERIAL")
            if len(decision_basis) < 20:
                raise ValidationError("NOT_MATERIAL Peer disposition requires a specific decision basis")
            try:
                max_remaining_eiv = float(assessment.get("max_remaining_eiv"))
            except (TypeError, ValueError) as exc:
                raise ValidationError("NOT_MATERIAL Peer disposition requires max_remaining_eiv") from exc
            if not math.isfinite(max_remaining_eiv) or max_remaining_eiv < 0:
                raise ValidationError("Peer max_remaining_eiv must be finite and non-negative")
            if max_remaining_eiv >= float(state["extension"]["decision_saturation_threshold"]):
                raise ValidationError("NOT_MATERIAL Peer disposition requires remaining EIV below threshold")
        payload = {
            "peer_id": peer_id,
            "stage": stage,
            "assessment": facts,
            "fact_evidence_ids": bindings,
            "commercial_novelty_basis": novelty_basis,
            "canonical_resolution": canonical_result,
            "disposition": disposition,
            "decision_basis": decision_basis,
            "max_remaining_eiv": max_remaining_eiv,
            "contact_coverage": assessment.get("contact_coverage") or {},
            "contact_coverage_required_for_anchor_eligibility": False,
            "network_branch_states": normalized_branches,
            "evaluated_at": iso_utc(),
        }
        self.store.append(investigation_id, "V6_PEER_EVALUATED", payload)
        return {"accepted": True, **payload}

    @_serialized_v6_mutation
    def promote_anchor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        peer_id = _nonempty(args.get("peer_id"), "peer_id")
        _walk_no_secrets(args, "arguments")
        peer = state["peers"].get(peer_id)
        if not peer or peer.get("stage") != "ANCHOR_ELIGIBLE":
            raise ValidationError("peer must be ANCHOR_ELIGIBLE before promotion")
        if peer.get("disposition") == "NOT_MATERIAL":
            raise ValidationError("a Peer disposed as NOT_MATERIAL cannot be promoted")
        payload = {
            "peer_id": peer_id,
            "stage": "PROMOTED_ANCHOR",
            "promotion_reason": _nonempty(args.get("promotion_reason"), "promotion_reason"),
            "contact_coverage_required": False,
            "six_branch_research_required": True,
            "promoted_at": iso_utc(),
        }
        self.store.append(investigation_id, "V6_ANCHOR_PROMOTED", payload)
        return {"accepted": True, **payload}

    def evaluate_commercial_value(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        claims = self._claims_view(state)
        supported_factor = {
            "STRONGLY_SUPPORTED": 1.0,
            "SUPPORTED": 0.82,
            "CONFLICTED": 0.25,
            "STALE": 0.2,
            "REFUTED": 0.0,
            "NEGATIVE_EXHAUSTED": 0.0,
            "BLOCKED": 0.0,
            "NOT_APPLICABLE": 0.0,
            "SEARCHING": 0.0,
            "UNSEEN": 0.0,
        }
        weighted = sum(claim["commercial_weight"] * supported_factor[claim["state"]] for claim in claims.values())
        total = sum(claim["commercial_weight"] for claim in claims.values()) or 1.0
        score = round(100.0 * weighted / total, 2)
        grade = _grade_for_score(score)
        return {
            "schema": "cbi.commercial-value.v6.1",
            "investigation_id": state["start"]["investigation_id"],
            "commercial_value_grade": grade,
            "score": score,
            "basis": [{"claim_key": key, "claim_state": row["state"], "weight": row["commercial_weight"]} for key, row in claims.items() if row["commercial_weight"] > 0],
            "contact_or_crm_caps_grade": False,
            "conversion_guaranteed": False,
        }

    def evaluate_research_confidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        claims = self._claims_view(state)
        factors = {
            "STRONGLY_SUPPORTED": 1.0, "SUPPORTED": 0.72, "REFUTED": 0.82,
            "NEGATIVE_EXHAUSTED": 0.75, "NOT_APPLICABLE": 0.7, "STALE": 0.25,
            "CONFLICTED": 0.15, "BLOCKED": 0.05, "SEARCHING": 0.05, "UNSEEN": 0.0,
        }
        score = round(100 * sum(factors[row["state"]] * max(0.1, row["decision_impact"]) for row in claims.values()) / sum(max(0.1, row["decision_impact"]) for row in claims.values()), 2)
        grade = "R5" if score >= 85 else "R4" if score >= 70 else "R3" if score >= 50 else "R2" if score >= 30 else "R1" if score > 0 else "R0"
        return {
            "schema": "cbi.research-confidence.v6.1",
            "investigation_id": state["start"]["investigation_id"],
            "research_confidence": grade,
            "score": score,
            "conflicted_claims": [key for key, row in claims.items() if row["state"] == "CONFLICTED"],
            "blocked_claims": [key for key, row in claims.items() if row["state"] == "BLOCKED"],
        }

    def evaluate_outreach_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        account_id = state["start"]["account"]["account_id"]
        contacts = [
            row for row in state["observations"].values()
            if row["result"] == "POSITIVE" and row["claim_key"] in {"contact.company_route", "contact.named_route"}
            and row["owner_id"] == account_id and isinstance(row.get("value"), dict)
        ]
        valid = [
            row for row in contacts
            if row["value"].get("verified") is True
            and row["value"].get("current") is True
            and row["value"].get("owned_by_account") is True
            and row["value"].get("masked") is not True
            and row["value"].get("guessed") is not True
            and row["source"].get("freshness") in {"LIVE", "CURRENT", "RECENT"}
            and (
                str(row["value"].get("channel") or "").upper() != "EMAIL"
                or _EMAIL_RE.fullmatch(str(row["value"].get("value") or "")) is not None
            )
            and (
                str(row["value"].get("channel") or "").upper() not in {"WHATSAPP", "ZALO"}
                or row["value"].get("channel_proof") is True
            )
        ]
        named = [row for row in valid if row["claim_key"] == "contact.named_route" and str(row["value"].get("person_name") or "").strip()]
        prior_stage = str(state["start"].get("history_highest_stage") or "")
        unexpired_closure = any(
            not closure.get("used")
            and datetime.fromisoformat(str(closure["expires_at"]).replace("Z", "+00:00")) > datetime.now(timezone.utc)
            and not any(event["seq"] > closure["seq"] and event["event_type"] in V6_OPERATIONAL_EVENTS for event in state["events"])
            for closure in state["closures"].values()
        )
        if state["start"].get("opt_out"):
            readiness = "BLOCKED"
            reasons = ["ACCOUNT_OPTED_OUT"]
        elif unexpired_closure and named:
            readiness = "FOLLOW_UP_READY" if prior_stage else "SEND_READY"
            reasons = []
        elif named:
            readiness = "NAMED_ROUTE_READY"
            reasons = ["DECISION_SATURATION_CLOSURE_REQUIRED"]
        elif valid:
            readiness = "COMPANY_ROUTE_READY"
            reasons = ["NAMED_ROUTE_NOT_PROVEN"]
        elif self._claims_view(state)["identity.legal_entity"]["state"] in {"SUPPORTED", "STRONGLY_SUPPORTED"}:
            readiness = "IDENTITY_ONLY"
            reasons = ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"]
        else:
            readiness = "BLOCKED"
            reasons = ["IDENTITY_AND_ROUTE_NOT_READY"]
        return {
            "schema": "cbi.outreach-readiness.v6.1",
            "investigation_id": state["start"]["investigation_id"],
            "outreach_readiness": readiness,
            "valid_company_route_observation_ids": [row["observation_id"] for row in valid],
            "valid_named_route_observation_ids": [row["observation_id"] for row in named],
            "block_reasons": reasons,
            "crm_sync_required_for_readiness": False,
            "sends_message": False,
        }

    def evaluate_decision_saturation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        state = self._v6_state(_nonempty(args.get("investigation_id"), "investigation_id"))
        claims = self._claims_view(state)
        resolved = {"SUPPORTED", "STRONGLY_SUPPORTED", "REFUTED", "NEGATIVE_EXHAUSTED", "NOT_APPLICABLE"}
        unresolved_critical = [key for key, row in claims.items() if row["critical"] and row["state"] not in resolved]
        conflicted = [key for key, row in claims.items() if row["state"] == "CONFLICTED"]
        material_pivots = self._material_pivots(state)
        pending_anchors = [peer["peer_id"] for peer in state["peers"].values() if peer.get("stage") == "PROMOTED_ANCHOR"]
        unresolved_discovered_peers: list[str] = []
        anchor_eligible_pending_promotion: list[str] = []
        threshold = float(state["extension"]["decision_saturation_threshold"])
        for peer in state["peers"].values():
            if peer.get("stage") in {"FULLY_AUDITED", "PROMOTED_ANCHOR"}:
                continue
            if (
                peer.get("disposition") == "NOT_MATERIAL"
                and isinstance(peer.get("max_remaining_eiv"), (int, float))
                and math.isfinite(float(peer["max_remaining_eiv"]))
                and float(peer["max_remaining_eiv"]) < threshold
            ):
                continue
            if peer.get("stage") == "ANCHOR_ELIGIBLE":
                anchor_eligible_pending_promotion.append(peer["peer_id"])
            else:
                unresolved_discovered_peers.append(peer["peer_id"])
        candidates = self._objective_candidates(state)
        high_eiv = [row for row in candidates if float(row["eiv"]) >= threshold]
        budget_exhausted = state["cost_used"] >= float(state["extension"]["budget_units"])
        blockers: list[str] = []
        blockers.extend(f"UNRESOLVED_CRITICAL_CLAIM:{key}" for key in unresolved_critical)
        blockers.extend(f"CONFLICTED_CLAIM:{key}" for key in conflicted)
        blockers.extend(f"MATERIAL_PIVOT:{row['pivot_id']}" for row in material_pivots)
        blockers.extend(f"DISCOVERED_PEER_UNRESOLVED:{peer_id}" for peer_id in unresolved_discovered_peers)
        blockers.extend(f"ANCHOR_ELIGIBLE_NOT_PROMOTED:{peer_id}" for peer_id in anchor_eligible_pending_promotion)
        blockers.extend(f"PROMOTED_ANCHOR_NOT_FULLY_AUDITED:{peer_id}" for peer_id in pending_anchors)
        if state["start"].get("mode") == "FAST_SCAN":
            blockers.append("FAST_SCAN_CANNOT_SIGN_DECISION_SATURATION")
        saturated = not blockers and not high_eiv
        if saturated:
            status = "SATURATED"
        elif budget_exhausted:
            status = "PAUSED_RESOURCE_LIMIT"
        elif any(row["state"] == "BLOCKED" and row["critical"] for row in claims.values()):
            status = "BLOCKED"
        else:
            status = "NOT_SATURATED"
        return {
            "schema": "cbi.decision-saturation.v6.1",
            "investigation_id": state["start"]["investigation_id"],
            "status": status,
            "decision_saturated": saturated,
            "unresolved_critical_claims": unresolved_critical,
            "conflicted_claims": conflicted,
            "material_open_pivots": material_pivots,
            "promoted_anchors_pending_full_audit": pending_anchors,
            "discovered_peers_pending_resolution": unresolved_discovered_peers,
            "anchor_eligible_peers_pending_promotion": anchor_eligible_pending_promotion,
            "high_eiv_objectives": high_eiv,
            "blockers": blockers,
            "budget_exhausted": budget_exhausted,
            "budget_exhaustion_is_completion": False,
        }

    def get_investigation_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        return {
            "schema": "cbi.investigation-state.v6.1",
            "investigation_id": investigation_id,
            "account_id": state["start"]["account"]["account_id"],
            "last_safe_seq": state["events"][-1]["seq"],
            "last_safe_event_hash": state["events"][-1]["event_hash"],
            "observation_count": len(state["observations"]),
            "bundle_count": len(state["bundles"]),
            "objective_count": len(state["objectives"]),
            "peer_count": len(state["peers"]),
            "claims": self._claims_view(state),
            "decision_saturation": self.evaluate_decision_saturation({"investigation_id": investigation_id}),
            "durable": True,
        }

    def get_account_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        legacy = self._state(investigation_id)
        latest_crm = list(legacy["crm_writebacks"].values())[-1] if legacy["crm_writebacks"] else None
        return {
            "schema": "cbi.account-state.v6.1",
            "investigation_id": investigation_id,
            "account": state["start"]["account"],
            "commercial_value": self.evaluate_commercial_value({"investigation_id": investigation_id}),
            "research_confidence": self.evaluate_research_confidence({"investigation_id": investigation_id}),
            "outreach_readiness": self.evaluate_outreach_readiness({"investigation_id": investigation_id}),
            "decision_saturation": self.evaluate_decision_saturation({"investigation_id": investigation_id}),
            "crm_state": {
                "status": "SYNCED" if latest_crm else "NOT_SYNCED",
                "latest_writeback_id": latest_crm.get("writeback_id") if latest_crm else None,
            },
        }

    def evaluate_commercial_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        account = self.get_account_state(arguments)
        return {
            "schema": "cbi.commercial-dimensions.v6.1",
            "investigation_id": account["investigation_id"],
            "commercial_value": account["commercial_value"],
            "research_confidence": account["research_confidence"],
            "outreach_readiness": account["outreach_readiness"],
            "crm_state": account["crm_state"],
            "legacy_a_or_above_contact_crm_cap_removed": True,
            "dimensions_are_independent": True,
        }

    @_serialized_v6_mutation
    def evaluate_investigation_closure(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        saturation = self.evaluate_decision_saturation({"investigation_id": investigation_id})
        commercial = self.evaluate_commercial_value({"investigation_id": investigation_id})
        confidence = self.evaluate_research_confidence({"investigation_id": investigation_id})
        outreach = self.evaluate_outreach_readiness({"investigation_id": investigation_id})
        legacy = self._state(investigation_id)
        latest_crm = list(legacy["crm_writebacks"].values())[-1] if legacy["crm_writebacks"] else None
        network_complete = not (
            saturation["promoted_anchors_pending_full_audit"]
            or saturation["discovered_peers_pending_resolution"]
            or saturation["anchor_eligible_peers_pending_promotion"]
        )
        dimensions = {
            "research_complete": saturation["decision_saturated"],
            "network_complete": network_complete,
            "crm_sync_complete": bool(latest_crm),
            "commercial_value_grade": commercial["commercial_value_grade"],
            "research_confidence": confidence["research_confidence"],
            "outreach_prerequisites_complete": outreach["outreach_readiness"] in {"NAMED_ROUTE_READY", "FOLLOW_UP_READY", "SEND_READY"},
            "outreach_ready": outreach["outreach_readiness"] in {"FOLLOW_UP_READY", "SEND_READY"},
        }
        if not saturation["decision_saturated"]:
            return {
                "schema": "cbi.closure-evaluation.v6.1",
                "investigation_id": investigation_id,
                "closed": False,
                "closure_id": None,
                "status": saturation["status"],
                "state_dimensions": dimensions,
                "decision_saturation": saturation,
                "blockers": saturation["blockers"],
                "crm_sync_blocks_research_closure": False,
            }
        basis_hash = state["events"][-1]["event_hash"]
        now = datetime.now(timezone.utc)
        existing = next((
            row for row in state["closures"].values()
            if not row.get("used")
            and _parse_time(row.get("expires_at"), "closure.expires_at") > now
            and (
                row.get("basis_hash") == basis_hash
                or (
                    state["events"][-1]["event_type"] == "CLOSURE_ISSUED"
                    and state["events"][-1]["payload"].get("closure_id") == row.get("closure_id")
                )
            )
        ), None)
        if existing:
            closure_id = existing["closure_id"]
            expires_at = existing["expires_at"]
            reused = True
        else:
            closure_id = f"CLOS-{secrets.token_hex(16)}"
            expires_at = _format_time(datetime.now(timezone.utc) + timedelta(minutes=30))
            payload = {
                "schema": "cbi.closure.v6.1",
                "closure_id": closure_id,
                "investigation_id": investigation_id,
                "account_id": state["start"]["account"]["account_id"],
                "status": "COMPLETE_POSITIVE" if commercial["score"] > 0 else "COMPLETE_NEGATIVE_ENTITLED",
                "issued_at": iso_utc(),
                "expires_at": expires_at,
                "basis_hash": basis_hash,
                "state_dimensions": dimensions,
                "decision_saturation_sha256": digest(saturation),
                "used": False,
            }
            self.store.append_if_tail(investigation_id, basis_hash, "CLOSURE_ISSUED", payload)
            reused = False
        return {
            "schema": "cbi.closure-evaluation.v6.1",
            "investigation_id": investigation_id,
            "closed": True,
            "closed_scope": "DECISION_SATURATION",
            "closure_id": closure_id,
            "closure_expires_at": expires_at,
            "status": "COMPLETE_POSITIVE" if commercial["score"] > 0 else "COMPLETE_NEGATIVE_ENTITLED",
            "state_dimensions": dimensions,
            "decision_saturation": saturation,
            "blockers": [],
            "crm_sync_blocks_research_closure": False,
            "reused_evaluation_receipt": reused,
        }

    @_serialized_v6_mutation
    def prepare_outreach(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        _walk_no_secrets(args, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        closure_id = _nonempty(args.get("closure_id"), "closure_id")
        closure = state["closures"].get(closure_id)
        reasons: list[str] = []
        if not closure:
            reasons.append("INVALID_CLOSURE_ID")
        elif closure.get("used"):
            reasons.append("CLOSURE_TOKEN_REPLAY")
        elif datetime.fromisoformat(str(closure["expires_at"]).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            reasons.append("CLOSURE_EXPIRED")
        elif any(event["seq"] > closure["seq"] and event["event_type"] in V6_OPERATIONAL_EVENTS for event in state["events"]):
            reasons.append("CLOSURE_STALE_AFTER_NEW_RESEARCH")
        if closure and closure.get("status") != "COMPLETE_POSITIVE":
            reasons.append("NEGATIVE_CLOSURE_NOT_OUTREACH_ELIGIBLE")
        if closure and not (closure.get("state_dimensions") or {}).get("outreach_prerequisites_complete"):
            reasons.append("OUTREACH_PREREQUISITES_INCOMPLETE")
        route = args.get("route")
        if not isinstance(route, dict):
            route = {}
            reasons.append("ROUTE_REQUIRED")
        account_id = state["start"]["account"]["account_id"]
        if not (route.get("verified") is True and route.get("current") is True and route.get("owned_by_account") is True and route.get("owner_entity_id") == account_id):
            reasons.append("ROUTE_NOT_CURRENT_VERIFIED_ACCOUNT_OWNED")
        kind = str(route.get("kind") or "").upper()
        value = str(route.get("value") or "").strip()
        if kind == "EMAIL" and not _EMAIL_RE.fullmatch(value):
            reasons.append("INVALID_EMAIL_ROUTE")
        elif kind == "PHONE":
            normalized_phone = re.sub(r"[\s()-]", "", value)
            if MASKED_CONTACT_RE.search(value) or not INTERNATIONAL_PHONE_RE.fullmatch(normalized_phone):
                reasons.append("INVALID_PHONE_ROUTE")
        elif kind in {"WHATSAPP", "ZALO"}:
            normalized_phone = re.sub(r"[\s()-]", "", value)
            if MASKED_CONTACT_RE.search(value) or not INTERNATIONAL_PHONE_RE.fullmatch(normalized_phone):
                reasons.append(f"INVALID_{kind}_INTERNATIONAL_ROUTE")
        elif kind in {"LINKEDIN", "FACEBOOK", "INSTAGRAM", "WEBSITE_FORM"} and not URL_RE.fullmatch(value):
            reasons.append("INVALID_SOCIAL_OR_FORM_URL")
        evidence_ids = route.get("evidence_ids") or []
        route_evidence = {
            row["evidence_id"]: row
            for row in state["observations"].values()
            if row.get("evidence_id")
            and row["owner_id"] == account_id
            and row["claim_key"] in {"contact.company_route", "contact.named_route"}
            and row["result"] == "POSITIVE"
        }
        if not evidence_ids or not set(evidence_ids) <= set(route_evidence):
            reasons.append("ROUTE_EVIDENCE_OWNER_MISMATCH")
        elif not any(
            isinstance(route_evidence[evidence_id].get("value"), dict)
            and str(route_evidence[evidence_id]["value"].get("value") or "").strip().casefold() == value.casefold()
            and str(route_evidence[evidence_id]["value"].get("channel") or "").upper() == kind
            and route_evidence[evidence_id]["value"].get("verified") is True
            and route_evidence[evidence_id]["value"].get("current") is True
            and route_evidence[evidence_id]["value"].get("owned_by_account") is True
            and route_evidence[evidence_id]["value"].get("masked") is not True
            and route_evidence[evidence_id]["value"].get("guessed") is not True
            and route_evidence[evidence_id]["source"].get("freshness") in {"LIVE", "CURRENT", "RECENT"}
            for evidence_id in evidence_ids
        ):
            reasons.append("ROUTE_VALUE_OR_CHANNEL_NOT_BOUND_TO_EVIDENCE")
        if kind in {"WHATSAPP", "ZALO"} and not any(
            isinstance(route_evidence.get(evidence_id, {}).get("value"), dict)
            and route_evidence[evidence_id]["value"].get("channel_proof") is True
            for evidence_id in evidence_ids
        ):
            reasons.append(f"{kind}_CHANNEL_NOT_PROVEN")
        if state["start"].get("opt_out"):
            reasons.append("ACCOUNT_OPTED_OUT")
        if args.get("history_digest") != state["start"].get("history_digest"):
            reasons.append("HISTORY_DIGEST_MISMATCH")
        if args.get("authority_digest") != state["start"].get("authority_digest"):
            reasons.append("AUTHORITY_DIGEST_MISMATCH")
        subject = str(args.get("subject") or "").strip()
        body = str(args.get("body") or "").strip()
        if not subject or not body:
            reasons.append("SUBJECT_AND_BODY_REQUIRED")
        if re.search(r"(?:customs data|supplier intelligence|海关数据|你的供应商)", f"{subject}\n{body}", flags=re.I):
            reasons.append("CUSTOMS_OR_SUPPLIER_INTELLIGENCE_LEAK")
        authority_claims = set(state["start"].get("authority_claims") or [])
        for claim, pattern in CONCRETE_CLAIM_PATTERNS.items():
            if pattern.search(f"{subject}\n{body}") and claim not in authority_claims:
                reasons.append(f"UNAUTHORIZED_CONCRETE_{claim.upper()}_CLAIM")
        stage = str(args.get("stage") or "").upper()
        if stage not in OUTREACH_STAGE_RANK:
            reasons.append("INVALID_STAGE")
        prior_stage = str(state["start"].get("history_highest_stage") or "").upper()
        if prior_stage in OUTREACH_STAGE_RANK and stage in OUTREACH_STAGE_RANK and OUTREACH_STAGE_RANK[stage] < OUTREACH_STAGE_RANK[prior_stage]:
            reasons.append("HISTORY_STAGE_REGRESSION")
        if any(event["event_type"] == "OUTREACH_PREPARED" and str(event["payload"].get("stage") or "").upper() == stage for event in state["events"]):
            reasons.append("STAGE_REPLAY")
        if stage == "FIRST_TOUCH":
            words = _word_count(body)
            if words < 80 or words > 110:
                reasons.append("FIRST_TOUCH_WORD_COUNT_OUTSIDE_80_110")
            if len(re.findall(r"https?://[^\s]+", f"{subject}\n{body}", flags=re.I)) > 1:
                reasons.append("FIRST_TOUCH_MULTIPLE_URLS")
        try:
            expires = _parse_time(args.get("expires_at"), "expires_at")
            if expires <= datetime.now(timezone.utc) or expires > datetime.now(timezone.utc) + timedelta(hours=24):
                reasons.append("OUTREACH_EXPIRY_INVALID")
        except ValidationError:
            expires = datetime.now(timezone.utc)
            reasons.append("OUTREACH_EXPIRY_INVALID")
        if reasons:
            return {"status": "DRAFT_BLOCKED", "prepared": False, "block_reasons": list(dict.fromkeys(reasons)), "prepared_id": None, "render_token": None, "action": None}
        prepared_id = f"PREP-{secrets.token_hex(12)}"
        render_token = f"RENDER-{secrets.token_hex(20)}"
        payload = {
            "prepared_id": prepared_id,
            "render_token": render_token,
            "closure_id": closure_id,
            "investigation_id": investigation_id,
            "account_id": account_id,
            "route": route,
            "history_digest": str(args.get("history_digest") or state["start"].get("history_digest") or ""),
            "authority_digest": str(args.get("authority_digest") or state["start"].get("authority_digest") or ""),
            "subject": subject,
            "body": body,
            "chinese_translation": str(args.get("chinese_translation") or ""),
            "stage": stage,
            "issued_at": iso_utc(),
            "expires_at": _format_time(expires),
            "content_sha256": digest({"subject": subject, "body": body, "route": route}),
        }
        try:
            self.store.append_if_tail(
                investigation_id,
                state["events"][-1]["event_hash"],
                "OUTREACH_PREPARED",
                payload,
            )
        except ValidationError:
            return {
                "status": "DRAFT_BLOCKED",
                "prepared": False,
                "block_reasons": ["STATE_CHANGED_DURING_PREPARATION_RETRY_REQUIRED"],
                "prepared_id": None,
                "render_token": None,
                "action": None,
            }
        return {
            "status": "PREPARED_FOR_RENDER" if kind == "EMAIL" else "PREPARED_CONTENT_ONLY",
            "prepared": True,
            "block_reasons": [],
            "prepared_id": prepared_id,
            "render_token": render_token,
            "expires_at": payload["expires_at"],
            "render_transport": "MAILTO" if kind == "EMAIL" else "CONTENT_ONLY_NO_ONE_CLICK_TRANSPORT",
            "action": None,
            "sends_message": False,
        }

    def render_outreach_action_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().render_outreach_action_card(arguments)
        if result.get("terminal_state") == "SENDABLE_DRAFT":
            result.update({
                "schema_version": "6.1.0",
                "runtime_version": V6_RUNTIME_VERSION,
                "build_id": V6_BUILD_ID,
            })
        return result

    def prepare_crm_writeback(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        target = _nonempty(args.get("target_workbook_path"), "target_workbook_path")
        state = self.get_account_state({"investigation_id": investigation_id})
        records = args.get("records") or []
        if not isinstance(records, list):
            raise ValidationError("records: array required")
        plan_id = _stable_id("CRMTX", {"investigation_id": investigation_id, "target": target, "records": records, "state": state})
        return {
            "schema": "cbi.crm-writeback-plan.v6.1",
            "writeback_plan_id": plan_id,
            "investigation_id": investigation_id,
            "target_workbook_path": target,
            "records": records,
            "account_state_sha256": digest(state),
            "requirements": [
                "ARTIFACT_TOOL_ONLY", "DYNAMIC_HEADER_SIGNATURE", "SPARSE_PATCH", "APPEND_ONLY_HISTORY_GUARD",
                "PREVIOUS_CURRENT_SEMANTIC_DIFF", "ROW_AND_CELL_ASSERTIONS", "POST_COMMIT_REIMPORT",
            ],
            "runtime_wrote_workbook": False,
        }

    def queue_host_bundle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        payload = _require_object(args.get("payload"), "payload")
        return self._v6_queue().queue(payload, str(args.get("bundle_queue_id") or ""))

    def sync_pending_bundles(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_filter = str(args.get("investigation_id") or "").strip()
        limit = int(args.get("limit", 100))
        dry_run = args.get("dry_run") is True
        if not 1 <= limit <= 1000:
            raise ValidationError("limit must be 1-1000")
        queue = self._v6_queue()
        with exclusive_file_lock(queue.root / "host-queue-sync.lock", timeout_seconds=60.0):
            rows = [row for row in queue.entries() if row["status"] not in {"SYNCED"}]
            if investigation_filter:
                rows = [row for row in rows if row["investigation_id"] == investigation_filter]
            outcomes: list[dict[str, Any]] = []
            for row in rows[:limit]:
                if dry_run:
                    outcomes.append({"bundle_queue_id": row["bundle_queue_id"], "status": "WOULD_SYNC"})
                    continue
                envelope = queue.load(row["bundle_queue_id"])
                try:
                    result = self.compile_and_append_research_bundle(envelope["payload"])
                    status = "SYNCED" if result["status"] == "ACCEPTED" else result["status"]
                    queue.record(row["bundle_queue_id"], row["request_sha256"], status, result=result)
                    outcomes.append({"bundle_queue_id": row["bundle_queue_id"], "status": status, "result": result})
                except ValidationError as exc:
                    queue.record(row["bundle_queue_id"], row["request_sha256"], "FAILED_VALIDATION", error=str(exc))
                    outcomes.append({"bundle_queue_id": row["bundle_queue_id"], "status": "FAILED_VALIDATION", "error": str(exc)})
        counts: dict[str, int] = {}
        for row in outcomes:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {"processed": len(outcomes), "counts": counts, "outcomes": outcomes, "dry_run": dry_run}

    def sync_pending_research_bundles(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.sync_pending_bundles(arguments)

    def get_portfolio_queue(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        limit = int(args.get("limit", 100))
        if not 1 <= limit <= 1000:
            raise ValidationError("limit must be 1-1000")
        rows: list[dict[str, Any]] = []
        grade_rank = {grade: index for index, grade in enumerate(COMMERCIAL_VALUE_GRADES)}
        for path in sorted(self.store.root.glob("INV-*.jsonl")):
            try:
                account = self.get_account_state({"investigation_id": path.stem})
                commercial = account["commercial_value"]["commercial_value_grade"]
                saturation = account["decision_saturation"]
                next_work = self.get_next_research_objectives({"investigation_id": path.stem, "limit": 1})
                rows.append({
                    "investigation_id": path.stem,
                    "account_id": account["account"].get("account_id"),
                    "account_name": account["account"].get("name"),
                    "commercial_value_grade": commercial,
                    "research_confidence": account["research_confidence"]["research_confidence"],
                    "decision_saturation": saturation["status"],
                    "next_eiv": next_work["objectives"][0]["eiv"] if next_work["objectives"] else 0.0,
                    "budget": next_work["budget"],
                })
            except (ValidationError, KeyError, TypeError, ValueError) as exc:
                rows.append({"investigation_id": path.stem, "status": "QUARANTINED_READ_ONLY", "error": str(exc)})
        rows.sort(key=lambda row: (grade_rank.get(row.get("commercial_value_grade", "NQ"), 99), -float(row.get("next_eiv", 0)), row["investigation_id"]))
        return {"schema": "cbi.portfolio-queue.v6.1", "count": len(rows), "queue": rows[:limit]}

    def get_investigation_health(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        investigation_id = _nonempty(args.get("investigation_id"), "investigation_id")
        try:
            state = self._v6_state(investigation_id)
            return {
                "investigation_id": investigation_id,
                "status": "READY",
                "read_only": False,
                "last_safe_seq": state["events"][-1]["seq"],
                "last_safe_event_hash": state["events"][-1]["event_hash"],
                "event_count": len(state["events"]),
                "schema_version": "cbi.investigation.v6.1",
            }
        except ValidationError as exc:
            prefix, prefix_error = self.store.read_valid_prefix(investigation_id)
            return {
                "investigation_id": investigation_id,
                "status": "QUARANTINED_READ_ONLY",
                "read_only": True,
                "error_category": "INTEGRITY_ERROR",
                "error": str(exc),
                "prefix_error": prefix_error,
                "last_safe_seq": prefix[-1]["seq"] if prefix else 0,
                "last_safe_event_hash": prefix[-1]["event_hash"] if prefix else None,
            }

    def migrate_v5_4_1_to_v6(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _require_object(arguments, "arguments")
        source_root = Path(args.get("source_session_root") or self.store.root).resolve()
        target_root = Path(_nonempty(args.get("target_root"), "target_root")).resolve()
        if not source_root.is_dir():
            raise ValidationError("migration source session root does not exist")
        if target_root == source_root or source_root in target_root.parents or target_root in source_root.parents:
            raise ValidationError("migration source and target must be distinct, non-overlapping roots")
        if target_root.exists() and any(target_root.iterdir()):
            raise ValidationError("migration target must not already contain files")
        source_files = sorted(source_root.glob("INV-*.jsonl"))
        if not source_files:
            raise ValidationError("migration source contains no investigation sessions")

        source_store = self.store.__class__(source_root)
        for source in source_files:
            source_store.read(source.stem)

        explicit_runtime_root = source_root / ".runtime"
        if (explicit_runtime_root / "canonical").is_dir() or (explicit_runtime_root / "pending").is_dir():
            source_canonical_root = explicit_runtime_root / "canonical"
            source_pending_root = explicit_runtime_root / "pending"
        else:
            source_canonical_root = source_root.parent / "canonical"
            source_pending_root = source_root.parent / "pending"

        tracked_roots = {
            "sessions": source_root,
            "canonical": source_canonical_root,
            "pending": source_pending_root,
        }

        def source_manifest() -> dict[str, str]:
            manifest: dict[str, str] = {}
            for label, root in tracked_roots.items():
                if not root.is_dir():
                    continue
                for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.name.endswith(".lock")):
                    manifest[f"{label}/{path.relative_to(root).as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
            return manifest

        source_before = source_manifest()
        target_sessions = target_root / "sessions"
        target_sessions.mkdir(parents=True, exist_ok=True)
        for source in source_files:
            shutil.copy2(source, target_sessions / source.name)
        target_runtime = self.__class__(target_sessions)
        if source_canonical_root.is_dir():
            shutil.copytree(source_canonical_root, target_runtime.canonical_registry.root, dirs_exist_ok=True)
        if source_pending_root.is_dir():
            shutil.copytree(source_pending_root, target_runtime.pending_journal.root, dirs_exist_ok=True)
        migrated: list[str] = []
        errors: list[dict[str, str]] = []
        for source in source_files:
            try:
                target_runtime._ensure_v6(source.stem)
                target_runtime.store.read(source.stem)
                migrated.append(source.stem)
            except ValidationError as exc:
                errors.append({"investigation_id": source.stem, "error": str(exc)})
        source_after = source_manifest()
        source_unchanged = source_before == source_after
        verified = not errors and len(migrated) == len(source_files) and source_unchanged
        report = {
            "schema": "cbi.migration-report.v6.1",
            "source_session_root": str(source_root),
            "target_root": str(target_root),
            "source_session_count": len(source_files),
            "migrated_session_count": len(migrated),
            "migrated_investigations": migrated,
            "errors": errors,
            "verified": verified,
            "source_manifest_sha256_before": digest(source_before),
            "source_manifest_sha256_after": digest(source_after),
            "source_unchanged": source_unchanged,
            "source_mutated": not source_unchanged,
            "switch_ready": verified,
            "switched": False,
            "activation_instruction": "Set CBI_SESSION_ROOT to the migrated sessions directory only after external acceptance and restart.",
        }
        (target_root / "V6_MIGRATION_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
