from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import unicodedata
import zipfile
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .errors import ValidationError
from .resilience import CanonicalRegistry, PendingReceiptJournal, exclusive_file_lock


RUNTIME_VERSION = "5.4.1"
BUILD_ID = "CBI-V5.4.1-ANSWER-FIRST-NO-STARTUP-WRITE-V1"

CBI_MCP_TOOL_NAMES = (
    "get_runtime_contract",
    "get_runtime_health",
    "resolve_or_create_account",
    "start_investigation",
    "append_information_record",
    "get_information_history",
    "plan_public_source_calls",
    "plan_provider_calls",
    "append_execution_receipt",
    "append_provider_receipt",
    "append_peer_receipt",
    "append_crm_writeback_receipt",
    "evaluate_commercial_readiness",
    "evaluate_investigation_closure",
    "prepare_outreach",
    "render_outreach_action_card",
    "queue_pending_receipt",
    "get_pending_journal_status",
    "sync_pending_receipts",
)

PROVIDER_MODES = {
    "PUBLIC_ONLY",
    "CONNECTED_PROVIDERS_OPTIONAL",
    "CONNECTED_PROVIDERS_REQUIRED",
}

PROVIDER_AVAILABILITY = {
    "NOT_INSTALLED",
    "INSTALLED_NOT_CONNECTED",
    "CONNECTED",
    "PERMISSION_BLOCKED",
    "CREDIT_BLOCKED",
    "UNAVAILABLE",
}

PROVIDER_CLASSES = {
    "CONTACT_ENRICHMENT",
    "ABM_INTENT",
    "GTM_ORCHESTRATION",
    "LOGISTICS_TRACKING",
    "TRADE_DATA_INFRA",
}

PROVIDER_CLASS_MODULES: dict[str, set[str]] = {
    "CONTACT_ENRICHMENT": {"company_profile", "buying_group", "contact_coverage"},
    "ABM_INTENT": {"company_profile", "buying_group", "sales_crm_outreach_readiness"},
    "GTM_ORCHESTRATION": {"company_profile", "buying_group", "sales_crm_outreach_readiness"},
    "LOGISTICS_TRACKING": {"customs_integrity", "ultimate_buyer_resolution", "trade_supplier_continuity"},
    "TRADE_DATA_INFRA": {
        "customs_integrity",
        "buyer_entity_resolution",
        "ultimate_buyer_resolution",
        "product_identity_boundary",
        "company_profile",
        "trade_supplier_continuity",
    },
}

PROVIDER_RESULTS = {"POSITIVE", "NEGATIVE", "BLOCKED"}

PROVIDER_RECEIPT_REQUIRED = {
    "provider_receipt_id",
    "investigation_id",
    "account_id",
    "provider",
    "provider_class",
    "requested_capability",
    "target_module",
    "plan_id",
    "planned_call_id",
    "tool_name",
    "tool_call_id",
    "query",
    "requested_at",
    "completed_at",
    "result",
    "result_count",
    "raw_result_locator",
    "content_sha256",
    "evidence_ids",
    "pivots_generated",
    "contacts_returned",
    "companies_returned",
    "billing_or_credit_notice",
    "blocked_reason",
    "permissions",
    "freshness",
    "conflicts",
    "status",
}

PROVIDER_CONTACT_REQUIRED = {
    "contact_id",
    "kind",
    "value",
    "owner_entity_id",
    "masked",
    "guessed",
    "provider_verified",
    "route_eligible",
    "evidence_id",
    "channel_proof",
}

REQUIRED_MODULES = (
    "history_and_account_lock",
    "customs_integrity",
    "buyer_entity_resolution",
    "ultimate_buyer_resolution",
    "product_identity_boundary",
    "company_profile",
    "trade_supplier_continuity",
    "buying_group",
    "contact_coverage",
    "network_fission",
    "evidence_conflict_resolution",
    "sales_crm_outreach_readiness",
)

RESEARCH_CORE_MODULES = tuple(
    module
    for module in REQUIRED_MODULES
    if module not in {"network_fission", "sales_crm_outreach_readiness"}
)

NETWORK_POLICY_DEFAULTS = {
    "minimum_target_fit": "A",
    "minimum_evidence_grade": "B",
    "require_commercial_novelty": True,
    "require_canonical_new": True,
    "closure_strategy": "QUEUE_PIVOT_SATURATION",
}

# v5.3 exposed these as hard completion-adjacent caps.  v5.4 accepts them only
# as migration hints so older callers do not break, but never rejects or drops
# a qualified Peer because a fixed depth/count was reached.  Resource exhaustion
# leaves the Anchor queue open and therefore pauses rather than closes research.
LEGACY_NETWORK_BUDGET_FIELDS = {"max_anchor_depth", "max_promoted_anchors"}

TARGET_FIT_RANK = {"C": 1, "B": 2, "B+": 3, "A": 4, "A+": 5}
PROMOTION_EVIDENCE_RANK = {"C": 1, "B": 2, "A": 3}

SUPPLY_CHAIN_PARTY_ROLES = {
    "BUYER",
    "IMPORTER_OF_RECORD",
    "EXPORTER",
    "TRADING_INTERMEDIARY",
    "DECLARED_MANUFACTURER",
    "PROBABLE_ACTUAL_MANUFACTURER",
    "SUPPLIER_GROUP",
}

NETWORK_BRANCHES = (
    "regional_peer",
    "industry_peer",
    "scale_peer",
    "same_supplier_buyer",
    "same_product_hs_application_buyer",
    "competing_supplier_alternative",
)

CONTACT_SOURCE_PROFILE = (
    "official_home",
    "official_contact",
    "official_about_footer_mobile",
    "official_documents_media",
    "official_news_jobs",
    "government_registry",
    "tax_court_regulatory",
    "google_maps_business",
    "local_maps",
    "linkedin_company",
    "linkedin_people",
    "facebook",
    "instagram_x_youtube",
    "whatsapp_public",
    "zalo_public",
    "local_directory",
    "association_exhibition_chamber",
    "reverse_phone_email",
    "domain_mx_public",
    "address_tax_alias_director_reverse",
    "supplier_peer_partner_referral",
    "ecommerce_public_store",
)

SOURCE_PROFILE_BY_MODULE: dict[str, tuple[str, ...]] = {
    "history_and_account_lock": ("crm_history", "decision_event_history", "route_history"),
    "customs_integrity": ("user_customs_record", "shipment_identifiers", "customs_math"),
    "buyer_entity_resolution": ("government_registry", "official_home", "address_tax_alias_director_reverse"),
    "ultimate_buyer_resolution": ("customs_parties", "official_home", "supplier_peer_partner_referral"),
    "product_identity_boundary": ("customs_product_text", "hs_authority", "official_product_material"),
    "company_profile": ("official_home", "official_about_footer_mobile", "government_registry", "local_directory"),
    "trade_supplier_continuity": ("trade_history", "supplier_official", "customs_parties", "partner_reference"),
    "buying_group": ("official_team", "linkedin_people", "government_registry", "official_news_jobs"),
    "contact_coverage": CONTACT_SOURCE_PROFILE,
    "network_fission": NETWORK_BRANCHES,
    "evidence_conflict_resolution": ("primary_source_recheck", "independent_corroboration", "conflict_search"),
    # CRM writeback is not a web/source search. v5.4 proves it with the
    # structured append_crm_writeback_receipt tool instead of a generic
    # SourceAttempt that could falsely claim a workbook commit.
    "sales_crm_outreach_readiness": ("product_authority", "history_digest", "route_ownership"),
}

SOURCE_PROFILE_BY_BRANCH: dict[str, tuple[str, ...]] = {
    "regional_peer": ("maps_region", "local_directory", "association_exhibition_chamber"),
    "industry_peer": ("industry_directory", "search_engine", "association_exhibition_chamber"),
    "scale_peer": ("registry_scale", "industry_directory", "maps_region"),
    "same_supplier_buyer": ("supplier_official", "trade_history", "partner_reference"),
    "same_product_hs_application_buyer": ("trade_history", "hs_application_search", "industry_directory"),
    "competing_supplier_alternative": ("supplier_official", "trade_history", "product_alternative_search"),
}

ATTEMPT_REQUIRED = {
    "attempt_id",
    "investigation_id",
    "owner_type",
    "owner_id",
    "module_or_branch",
    "source_family",
    "query",
    "started_at",
    "completed_at",
    "checked_at",
    "tool_or_operator",
    "execution_id",
    "result",
    "result_count",
    "raw_result_locator",
    "content_sha256",
    "evidence_ids",
    "pivots_generated",
    "blocked_reason",
}

EVIDENCE_REQUIRED = {
    "evidence_id",
    "owner_type",
    "owner_id",
    "claim_key",
    "module_or_branch",
    "source_type",
    "source_family",
    "reference_type",
    "url",
    "locator",
    "observed_at",
    "content_sha256",
    "snapshot_locator",
    "claim_type",
    "freshness",
    "evidence_grade",
    "boundary",
    "conflict",
}

PIVOT_REQUIRED = {
    "pivot_id",
    "pivot_type",
    "pivot_value",
    "generated_by_attempt_id",
    "generated_at",
    "consumed_by_attempt_id",
    "consumed_at",
    "consumption_result",
    "status",
}

INFORMATION_REQUIRED = {
    "information_id",
    "investigation_id",
    "related_account_id",
    "subject_type",
    "subject_owner_id",
    "relationship_to_account",
    "information_type",
    "claim_key",
    "value",
    "source_type",
    "source_reference_type",
    "source_url",
    "source_locator",
    "observed_at",
    "content_sha256",
    "confidence",
    "temporal_status",
    "route_scope",
    "outreach_eligible_claimed",
    "supersedes_information_ids",
    "conflicts_with_information_ids",
    "evidence_ids",
    "notes",
}

INFORMATION_SUBJECT_TYPES = {
    "ACCOUNT",
    "PEER",
    "PERSON",
    "COMPANY",
    "BRAND",
    "SUPPLIER",
    "REFERRAL",
    "CHANNEL",
    "ADDRESS",
    "OTHER",
}

INFORMATION_TYPES = {
    "FACT",
    "CONTACT",
    "ROUTE",
    "CONFLICT",
    "BLOCKED_SOURCE",
    "NEGATIVE_SEARCH_NOTE",
    "PIVOT",
    "HISTORICAL",
    "PARTY_ROLE",
}

INFORMATION_SOURCE_TYPES = {
    "OFFICIAL",
    "OFFICIAL_CONTACT",
    "GOVERNMENT",
    "REGISTRY",
    "DIRECTORY",
    "MAPS",
    "SOCIAL",
    "CUSTOMS",
    "TRADE_DATA",
    "PROVIDER",
    "USER_INPUT",
    "LEGACY_CRM",
    "DERIVED_CALCULATION",
    "OTHER_PUBLIC",
}

INFORMATION_CONFIDENCE = {"HIGH", "MEDIUM_HIGH", "MEDIUM", "LOW"}
INFORMATION_TEMPORAL_STATUS = {"CURRENT", "HISTORICAL", "UNKNOWN"}
INFORMATION_ROUTE_SCOPES = {
    "BUYER_DIRECT",
    "CROSS_ENTITY",
    "SUPPLIER_REFERRAL",
    "PRODUCT_CHANNEL",
    "IDENTITY_ONLY",
    "NOT_A_ROUTE",
}

EVIDENCE_REFERENCE_TYPES = {
    "PUBLIC_URL",
    "USER_INPUT",
    "CUSTOMS_RECORD",
    "LEGACY_CRM",
    "CRM_RECORD",
    "LOCAL_ARTIFACT",
    "PROVIDER_RECEIPT",
    "DERIVED_CALCULATION",
}

EVIDENCE_CLAIM_TYPES = {
    "FACT",
    "INFERENCE",
    "HYPOTHESIS",
    "RECOMMENDATION",
    "PROVIDER_ASSERTION",
    "CONTACT",
    "IDENTITY",
    "LEGAL_STATUS",
    "BUSINESS_PROFILE",
    "PRODUCT",
    "CUSTOMS",
    "TRADE",
    "SUPPLY_CHAIN",
    "RELATIONSHIP",
    "AUTHORITY",
    "ROUTE",
    "NEGATIVE_SEARCH",
    "CRM_WRITEBACK",
}

EVIDENCE_FRESHNESS = {
    "CURRENT",
    "RECENT",
    "STALE",
    "HISTORICAL",
    "UNKNOWN",
}

EVIDENCE_GRADES = {"A1", "A2", "B1", "B2", "C1", "C2", "D"}

COMMERCIAL_GATE_TAGS = {
    "CUSTOMS_IMPORT_FACT",
    "PRODUCT_MATCH",
    "LEGAL_EXISTENCE",
    "OFFICIAL_PRESENCE",
    "OFFICIAL_CONTACT",
    "DECISION_CHAIN",
    "CONTACT_SOURCE",
    "PVC_BUSINESS_RELATIONSHIP",
    "DEVELOPMENT_ROUTE",
}

COMMERCIAL_GATE_ORDER = (
    "CUSTOMS_IMPORT_FACT",
    "PRODUCT_MATCH",
    "LEGAL_EXISTENCE",
    "OFFICIAL_PRESENCE",
    "OFFICIAL_CONTACT",
    "DECISION_CHAIN",
    "CONTACT_SOURCE",
    "PVC_BUSINESS_RELATIONSHIP",
    "DEVELOPMENT_ROUTE",
    "CRM_STATUS",
)

COMMERCIAL_PUBLIC_REFERENCE_GATES = {
    "OFFICIAL_PRESENCE",
    "OFFICIAL_CONTACT",
    "DECISION_CHAIN",
    "CONTACT_SOURCE",
    "DEVELOPMENT_ROUTE",
}

COMMERCIAL_CURRENT_GATES = {
    "PRODUCT_MATCH",
    "LEGAL_EXISTENCE",
    "OFFICIAL_PRESENCE",
    "OFFICIAL_CONTACT",
    "DECISION_CHAIN",
    "CONTACT_SOURCE",
    "PVC_BUSINESS_RELATIONSHIP",
    "DEVELOPMENT_ROUTE",
}

COMMERCIAL_FACTUAL_CLAIM_TYPES = {
    "FACT",
    "CONTACT",
    "IDENTITY",
    "LEGAL_STATUS",
    "BUSINESS_PROFILE",
    "PRODUCT",
    "CUSTOMS",
    "TRADE",
    "SUPPLY_CHAIN",
    "RELATIONSHIP",
    "AUTHORITY",
    "ROUTE",
    "PROVIDER_ASSERTION",
}

COMMERCIAL_ACCEPTABLE_EVIDENCE_GRADES = {"A1", "A2", "B1"}

COMMERCIAL_GATE_EVIDENCE_POLICY: dict[str, dict[str, set[str]]] = {
    "CUSTOMS_IMPORT_FACT": {
        "modules": {"customs_integrity", "ultimate_buyer_resolution", "trade_supplier_continuity"},
        "claim_types": {"CUSTOMS", "TRADE"},
    },
    "PRODUCT_MATCH": {
        "modules": {"product_identity_boundary", "company_profile", "trade_supplier_continuity"},
        "claim_types": {"PRODUCT", "BUSINESS_PROFILE", "TRADE"},
    },
    "LEGAL_EXISTENCE": {
        "modules": {"buyer_entity_resolution", "company_profile"},
        "claim_types": {"LEGAL_STATUS", "IDENTITY"},
    },
    "OFFICIAL_PRESENCE": {
        "modules": {"buyer_entity_resolution", "company_profile", "contact_coverage"},
        "claim_types": {"IDENTITY", "BUSINESS_PROFILE", "FACT"},
    },
    "OFFICIAL_CONTACT": {
        "modules": {"contact_coverage"},
        "claim_types": {"CONTACT", "ROUTE"},
    },
    "DECISION_CHAIN": {
        "modules": {"buying_group", "contact_coverage"},
        "claim_types": {"AUTHORITY", "CONTACT", "FACT"},
    },
    "CONTACT_SOURCE": {
        "modules": {"contact_coverage"},
        "claim_types": {"CONTACT", "ROUTE"},
    },
    "PVC_BUSINESS_RELATIONSHIP": {
        "modules": {"product_identity_boundary", "company_profile", "trade_supplier_continuity"},
        "claim_types": {"PRODUCT", "TRADE", "BUSINESS_PROFILE", "RELATIONSHIP"},
    },
    "DEVELOPMENT_ROUTE": {
        "modules": {"contact_coverage", "sales_crm_outreach_readiness"},
        "claim_types": {"CONTACT", "ROUTE"},
    },
}


def _validate_commercial_tag_binding(
    tags: list[str],
    module_or_branch: str,
    claim_type: str,
    evidence_id: str,
) -> None:
    for tag in tags:
        policy = COMMERCIAL_GATE_EVIDENCE_POLICY[tag]
        if module_or_branch not in policy["modules"]:
            raise ValidationError(
                f"{evidence_id}: commercial gate {tag} is incompatible with module {module_or_branch}"
            )
        if claim_type not in policy["claim_types"]:
            raise ValidationError(
                f"{evidence_id}: commercial gate {tag} is incompatible with claim_type {claim_type}"
            )

PUBLIC_INFORMATION_SOURCE_TYPES = {
    "OFFICIAL",
    "OFFICIAL_CONTACT",
    "GOVERNMENT",
    "REGISTRY",
    "DIRECTORY",
    "MAPS",
    "SOCIAL",
    "OTHER_PUBLIC",
}

CRM_WRITEBACK_REQUIRED = {
    "writeback_id",
    "investigation_id",
    "account_id",
    "transaction_id",
    "writer",
    "target_workbook_path",
    "workbook_sha256_before",
    "workbook_sha256_after",
    "committed_at",
    "status",
    "atomic_commit",
    "sparse_patch",
    "history_guard_passed",
    "post_commit_reimport_verified",
    "unintended_diff_count",
    "touched_sheets",
    "row_assertions",
    "cell_assertions",
    "previous_current_diff",
    "audit_artifact_locator",
    "audit_artifact_sha256",
}

VALID_RESULTS = {
    "POSITIVE",
    "NEGATIVE",
    "NEGATIVE_EXHAUSTED",
    "BLOCKED",
    "NOT_APPLICABLE",
    "NOT_APPLICABLE_JUSTIFIED",
}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63}$", re.I)
INTERNATIONAL_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
MASKED_CONTACT_RE = re.compile(r"(?:\*{2,}|•{2,}|…|\.{3,}|\b[xX]{3,}\b|\[(?:at|dot)\])")
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
FORBIDDEN_SELF_PROOF = re.compile(r"^(AUDIT_QUERY:|WEB-SEARCH-QUERY:|VALIDATOR:|SELF_CERTIFIED:)", re.I)
BLOCKED_AS_NA = re.compile(r"(?:403|401|429|login|paywall|captcha|anti[- ]?bot|blocked|登录|付费墙|验证码|反爬)", re.I)
UNSAFE_OUTREACH = re.compile(
    r"(?:customs|import records?|shipment records?|incumbent supplier|your supplier|hs\s*code|海关|进口记录|现有供应商)",
    re.I,
)
CONCRETE_CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    "dimension": re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m)"
        r"(?:\s*[x×]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m))?\b",
        re.I,
    ),
    "density": re.compile(r"\b(?:density|密度)(?:\s+(?:is|of|为))?\s*[:=]?\s*\d", re.I),
    "price": re.compile(
        r"(?:(?:\$|usd|eur|rmb|cny)\s*\d|\b\d+(?:\.\d+)?\s*(?:usd|eur|rmb|cny)\b|(?:price|价格|报价)(?:\s+is|为)?\s*[:=]?\s*\d)",
        re.I,
    ),
    "certification": re.compile(r"\b(?:certified|certification|iso\s*\d+|ce\s+certified|认证)\b", re.I),
    "performance": re.compile(r"\b(?:guarantee[ds]?|waterproof|fireproof|flame[- ]retardant|weather[- ]resistant|impact[- ]resistant|防火|防水|耐候|抗冲击|质保)\b", re.I),
}
STAGE_RANK = {"FIRST_TOUCH": 10, "FOLLOW_UP": 20, "MEETING": 30, "SAMPLE": 40, "PI": 50, "ORDER": 60, "PAYMENT": 70, "NEGOTIATION": 80}


_ACTIVE_INPUT_SANITIZATION: ContextVar[dict[str, Any] | None] = ContextVar(
    "cbi_active_input_sanitization",
    default=None,
)


def _sanitize_unicode_scalars(value: Any, path: str = "$") -> tuple[Any, list[dict[str, Any]]]:
    """NFC-normalize valid text and report invalid UTF-16 surrogate code units.

    v5.4 rejects isolated surrogates before validation, hashing or persistence.
    Replacing them would silently change search queries and break evidence/hash
    lineage. Valid Unicode is normalized to NFC at the same public boundary.
    """

    if isinstance(value, str):
        code_units: dict[str, int] = {}
        for character in value:
            codepoint = ord(character)
            if 0xD800 <= codepoint <= 0xDFFF:
                label = f"U+{codepoint:04X}"
                code_units[label] = code_units.get(label, 0) + 1
        if code_units:
            return value, [{
                "issue_type": "ISOLATED_UTF16_SURROGATE",
                "path": path,
                "count": sum(code_units.values()),
                "code_units": [
                    {"code_unit": label, "count": count}
                    for label, count in sorted(code_units.items())
                ],
            }]
        normalized = unicodedata.normalize("NFC", value)
        if normalized == value:
            return value, []
        return normalized, [{
            "issue_type": "NFC_NORMALIZED",
            "path": path,
            "before_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "after_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        }]

    if isinstance(value, list):
        output: list[Any] = []
        issues: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            cleaned, found = _sanitize_unicode_scalars(item, f"{path}[{index}]")
            output.append(cleaned)
            issues.extend(found)
        return output, issues

    if isinstance(value, tuple):
        cleaned, issues = _sanitize_unicode_scalars(list(value), path)
        return tuple(cleaned), issues

    if isinstance(value, dict):
        output: dict[Any, Any] = {}
        original_keys: dict[Any, Any] = {}
        issues: list[dict[str, Any]] = []
        for key, item in value.items():
            cleaned_key, key_issues = _sanitize_unicode_scalars(key, f"{path}.<key>")
            if cleaned_key in original_keys and original_keys[cleaned_key] != key:
                raise ValidationError(f"{path}: Unicode key sanitization collision")
            original_keys[cleaned_key] = key
            child_path = f"{path}[{json.dumps(cleaned_key, ensure_ascii=True)}]"
            cleaned_item, item_issues = _sanitize_unicode_scalars(item, child_path)
            output[cleaned_key] = cleaned_item
            issues.extend(key_issues)
            issues.extend(item_issues)
        return output, issues

    return value, []


def _sanitization_report(issues: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not issues:
        return None
    return {
        "status": "NORMALIZED_UNICODE_NFC",
        "policy": "VALID_UNICODE_SCALARS_ONLY_THEN_NFC",
        "normalized_field_count": len(issues),
        "fields": issues,
        "warning": "Valid Unicode text was NFC-normalized before validation, hashing, persistence, and MCP output.",
    }


def unicode_safe_entrypoint(method: Any) -> Any:
    """Normalize every public Runtime tool input and expose the audit report."""

    @wraps(method)
    def wrapped(self: Any, arguments: Any) -> Any:
        cleaned, issues = _sanitize_unicode_scalars(arguments)
        invalid = [item for item in issues if item.get("issue_type") == "ISOLATED_UTF16_SURROGATE"]
        if invalid:
            paths = ",".join(item["path"] for item in invalid[:10])
            raise ValidationError(
                "INVALID_UNICODE_SURROGATE: isolated UTF-16 surrogate rejected before hashing; "
                f"repair the original text and retry (paths: {paths})"
            )
        report = _sanitization_report(issues)
        token = _ACTIVE_INPUT_SANITIZATION.set(report)
        try:
            result = method(self, cleaned)
            if report and isinstance(result, dict):
                result = {**result, "input_sanitization": report}
            return result
        finally:
            _ACTIVE_INPUT_SANITIZATION.reset(token)

    return wrapped


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field}: timezone-aware timestamp required")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError(f"{field}: invalid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field}: timezone offset required")
    return parsed.astimezone(timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    material = value if isinstance(value, (bytes, bytearray)) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field}: object required")
    return value


def require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field}: array required")
    return value


def required_fields(value: dict[str, Any], fields: Iterable[str], field: str) -> None:
    missing = sorted(name for name in fields if name not in value)
    if missing:
        raise ValidationError(f"{field}: missing fields: {','.join(missing)}")


def nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field}: non-empty string required")
    return value.strip()


def valid_hash(value: Any, field: str) -> str:
    text = nonempty(value, field).casefold()
    if not SHA256_RE.fullmatch(text):
        raise ValidationError(f"{field}: SHA-256 required")
    return text


def _valid_locator(value: Any, content_sha256: str, field: str) -> str:
    locator = nonempty(value, field)
    if FORBIDDEN_SELF_PROOF.search(locator):
        raise ValidationError(f"{field}: self-authored or validator locator is forbidden")
    if URL_RE.fullmatch(locator) or locator.startswith((
        "snapshot://",
        "artifact://",
        "page-snapshot://",
        "provider-receipt://",
        "source-attempt://",
        "legacy-crm://",
        "crm-record://",
        "user-input://",
    )):
        return locator
    path = Path(locator)
    if path.is_absolute() and path.is_file():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != content_sha256.casefold():
            raise ValidationError(f"{field}: local artifact hash mismatch")
        return str(path)
    raise ValidationError(f"{field}: actual URL, snapshot locator, or hashed local artifact required")


def _validate_reference(
    reference_type: Any,
    url_value: Any,
    locator_value: Any,
    content_sha256: str,
    field: str,
) -> tuple[str, str, str]:
    """Validate URL evidence without forcing non-web evidence to invent a URL."""

    reference = nonempty(reference_type, f"{field}.reference_type").upper()
    if reference not in EVIDENCE_REFERENCE_TYPES:
        raise ValidationError(
            f"{field}.reference_type invalid; allowed: " + ",".join(sorted(EVIDENCE_REFERENCE_TYPES))
        )
    url = str(url_value or "").strip()
    locator = nonempty(locator_value, f"{field}.locator")
    if reference == "PUBLIC_URL":
        if not url or not URL_RE.fullmatch(url):
            raise ValidationError(f"{field}: PUBLIC_URL requires a concrete http(s) URL")
    elif url:
        raise ValidationError(f"{field}: non-public reference types must not carry a fabricated URL")

    normalized_locator = _valid_locator(locator, content_sha256, f"{field}.locator")
    prefix_rules: dict[str, tuple[str, ...]] = {
        "USER_INPUT": ("user-input://", "artifact://", "snapshot://"),
        "CUSTOMS_RECORD": ("user-input://", "artifact://", "source-attempt://", "snapshot://"),
        "LEGACY_CRM": ("legacy-crm://",),
        "CRM_RECORD": ("crm-record://",),
        "LOCAL_ARTIFACT": ("artifact://", "snapshot://", "page-snapshot://"),
        "PROVIDER_RECEIPT": ("provider-receipt://",),
        "DERIVED_CALCULATION": ("source-attempt://", "artifact://", "snapshot://"),
    }
    if reference != "PUBLIC_URL" and not Path(normalized_locator).is_absolute():
        allowed = prefix_rules[reference]
        if not normalized_locator.startswith(allowed):
            raise ValidationError(
                f"{field}: {reference} requires one of these locator schemes: " + ",".join(allowed)
            )
    return reference, url, normalized_locator


def _validate_xlsx_container(path: Path, field: str) -> None:
    if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise ValidationError(f"{field}: .xlsx or .xlsm workbook required")
    if not path.is_file():
        raise ValidationError(f"{field}: committed workbook does not exist")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError(f"{field}: invalid OOXML workbook container") from exc
    required = {"[Content_Types].xml", "xl/workbook.xml"}
    if not required <= names:
        raise ValidationError(f"{field}: OOXML workbook structure is incomplete")


def _word_count(body: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", body))


class SessionStore:
    def __init__(self, root: str | Path | None = None):
        configured = root or os.environ.get("CBI_SESSION_ROOT")
        if configured:
            self.root = Path(configured)
        else:
            local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            self.root = Path(local) / "XingHuai" / "CustomsBuyerIntelligence" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, investigation_id: str) -> Path:
        if not re.fullmatch(r"INV-[0-9TZ-]+-[0-9a-f]{12}", investigation_id):
            raise ValidationError("investigation_id: invalid")
        return self.root / f"{investigation_id}.jsonl"

    def _read_unlocked(self, investigation_id: str) -> list[dict[str, Any]]:
        path = self.path(investigation_id)
        if not path.is_file():
            raise ValidationError("investigation not found")
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"session log corrupt at line {line_number}") from exc
            if event.get("seq") != line_number or event.get("prev_hash") != previous:
                raise ValidationError(f"session chain broken at line {line_number}")
            claimed = event.get("event_hash")
            unsigned = {key: value for key, value in event.items() if key != "event_hash"}
            actual = digest(unsigned)
            if claimed != actual:
                raise ValidationError(f"session event hash mismatch at line {line_number}")
            previous = claimed
            events.append(event)
        if not events or events[0].get("event_type") != "INVESTIGATION_STARTED":
            raise ValidationError("session header missing")
        return events

    def read(self, investigation_id: str) -> list[dict[str, Any]]:
        lock_path = self.root / f".{investigation_id}.write.lock"
        with exclusive_file_lock(lock_path, timeout_seconds=30.0):
            return self._read_unlocked(investigation_id)

    def _read_valid_prefix_unlocked(self, investigation_id: str) -> tuple[list[dict[str, Any]], str]:
        """Return the longest valid event prefix without altering a corrupt log."""
        path = self.path(investigation_id)
        if not path.is_file():
            return [], "investigation not found"
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return events, f"session log corrupt at line {line_number}"
            claimed = event.get("event_hash")
            unsigned = {key: value for key, value in event.items() if key != "event_hash"}
            if event.get("seq") != line_number or event.get("prev_hash") != previous:
                return events, f"session chain broken at line {line_number}"
            if claimed != digest(unsigned):
                return events, f"session event hash mismatch at line {line_number}"
            events.append(event)
            previous = claimed
        if not events or events[0].get("event_type") != "INVESTIGATION_STARTED":
            return events, "session header missing"
        return events, ""

    def read_valid_prefix(self, investigation_id: str) -> tuple[list[dict[str, Any]], str]:
        lock_path = self.root / f".{investigation_id}.write.lock"
        with exclusive_file_lock(lock_path, timeout_seconds=30.0):
            return self._read_valid_prefix_unlocked(investigation_id)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self.path(payload["investigation_id"])
        event = self._event(1, "0" * 64, "INVESTIGATION_STARTED", payload)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ValidationError("investigation_id collision") from exc
        return event

    def append(self, investigation_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        lock_path = self.root / f".{investigation_id}.write.lock"
        with exclusive_file_lock(lock_path, timeout_seconds=15.0):
            events = self._read_unlocked(investigation_id)
            event = self._event(len(events) + 1, events[-1]["event_hash"], event_type, payload)
            with self.path(investigation_id).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def append_many(self, investigation_id: str, rows: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        """Append a validated batch under one writer lock and one fsync."""
        if not rows:
            return []
        lock_path = self.root / f".{investigation_id}.write.lock"
        with exclusive_file_lock(lock_path, timeout_seconds=30.0):
            events = self._read_unlocked(investigation_id)
            previous = events[-1]["event_hash"]
            seq = len(events)
            appended: list[dict[str, Any]] = []
            for event_type, payload in rows:
                seq += 1
                event = self._event(seq, previous, event_type, payload)
                previous = event["event_hash"]
                appended.append(event)
            with self.path(investigation_id).open("a", encoding="utf-8", newline="\n") as handle:
                for event in appended:
                    handle.write(canonical_json(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return appended

    def append_if_tail(
        self,
        investigation_id: str,
        expected_tail_hash: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append only when the caller's evaluated state is still current."""

        lock_path = self.root / f".{investigation_id}.write.lock"
        with exclusive_file_lock(lock_path, timeout_seconds=30.0):
            events = self._read_unlocked(investigation_id)
            if events[-1]["event_hash"] != expected_tail_hash:
                raise ValidationError("investigation changed after evaluation; retry required")
            event = self._event(len(events) + 1, expected_tail_hash, event_type, payload)
            with self.path(investigation_id).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    @staticmethod
    def _event(seq: int, previous: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "seq": seq,
            "prev_hash": previous,
            "event_type": event_type,
            "recorded_at": iso_utc(),
            "payload": payload,
        }
        sanitization = _ACTIVE_INPUT_SANITIZATION.get()
        if sanitization:
            event["input_sanitization"] = sanitization
        event["event_hash"] = digest(event)
        return event


class UnifiedRuntime:
    def __init__(self, session_root: str | Path | None = None):
        self.store = SessionStore(session_root)
        explicit_root = session_root is not None or bool(os.environ.get("CBI_SESSION_ROOT"))
        data_root = self.store.root / ".runtime" if explicit_root else self.store.root.parent
        canonical_root = Path(os.environ.get("CBI_CANONICAL_ROOT") or data_root / "canonical")
        pending_root = Path(os.environ.get("CBI_PENDING_ROOT") or data_root / "pending")
        self.canonical_registry = CanonicalRegistry(canonical_root, self.store.root)
        self.pending_journal = PendingReceiptJournal(pending_root)

    @unicode_safe_entrypoint
    def resolve_or_create_account(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        candidate = require_object(args.get("candidate") or args.get("account"), "candidate")
        country = nonempty(candidate.get("country"), "candidate.country")
        normalized_candidate = {**candidate, "country": country}
        requested_account_id = str(args.get("requested_account_id") or candidate.get("account_id") or "").strip()
        create_if_missing = args.get("create_if_missing", True)
        if not isinstance(create_if_missing, bool):
            raise ValidationError("create_if_missing must be boolean")
        result = self.canonical_registry.resolve_or_create(
            normalized_candidate,
            requested_account_id=requested_account_id,
            create_if_missing=create_if_missing,
        )
        return {
            **result,
            "candidate_sha256": digest(normalized_candidate),
            "registry_path": str(self.canonical_registry.log.path),
            "append_only": True,
        }

    @unicode_safe_entrypoint
    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the enums and nested-record requirements callers must not guess."""
        require_object(arguments, "arguments")
        return {
            "runtime_version": RUNTIME_VERSION,
            "build_id": BUILD_ID,
            "workflow_policy": {
                "default_mode": "ANSWER_FIRST",
                "answer_first": {
                    "scope": "ORDINARY_BUYER_COMPANY_CONTACT_LOOKUP",
                    "host_public_research_required": True,
                    "cbi_mcp_tools_allowed": [],
                    "cbi_mcp_tools_forbidden": list(CBI_MCP_TOOL_NAMES),
                    "runtime_persistence_allowed": False,
                    "crm_or_workbook_access_allowed": False,
                    "audit_or_closure_allowed": False,
                    "executable_outreach_allowed": False,
                    "response_requirements": [
                        "LATEST_DECISION_USEFUL_FINDINGS",
                        "CONCRETE_SOURCE_LINKS_AND_BOUNDARIES",
                        "TAILORED_DEVELOPMENT_EMAIL_CONTENT",
                        "TAILORED_INSTANT_CHAT_CONTENT",
                        "EXPLICIT_NO_WRITE_NO_SEND_STATE",
                    ],
                },
                "persistent_modes_require_explicit_user_request": [
                    "BATCH_COMMIT",
                    "FULL_AUDIT",
                    "FORMAL_CRM_OR_CLOSURE",
                    "OUTREACH_PREPARATION",
                    "PLUGIN_DIAGNOSTICS",
                ],
                "batch_commit_triggers_include": [
                    "新增到表格",
                    "批量写回",
                    "正式入库",
                    "合并到最新CRM",
                ],
                "continuation_or_item_count_authorizes_persistence": False,
                "mcp_initialize_mutates_state": False,
                "pending_sync_requires_explicit_tool_call": True,
            },
            "schemas": {
                "investigation": "cbi.investigation.v5.4",
                "pending_receipt": "cbi.pending-receipt.v5.4",
                "crm_writeback_receipt": "cbi.crm-writeback.v5.4",
            },
            "enums": {
                "mode": ["EXHAUSTIVE", "FAST_SCAN"],
                "attempt_result": sorted(VALID_RESULTS),
                "source_family_terminal_result": [
                    "POSITIVE",
                    "NEGATIVE_EXHAUSTED",
                    "NOT_APPLICABLE_JUSTIFIED",
                ],
                "information_type": sorted(INFORMATION_TYPES),
                "information_source_type": sorted(INFORMATION_SOURCE_TYPES),
                "information_subject_type": sorted(INFORMATION_SUBJECT_TYPES),
                "information_confidence": sorted(INFORMATION_CONFIDENCE),
                "information_temporal_status": sorted(INFORMATION_TEMPORAL_STATUS),
                "information_route_scope": sorted(INFORMATION_ROUTE_SCOPES),
                "provider_mode": sorted(PROVIDER_MODES),
                "provider_availability": sorted(PROVIDER_AVAILABILITY),
                "provider_class": sorted(PROVIDER_CLASSES),
                "provider_result": sorted(PROVIDER_RESULTS),
                "peer_receipt_type": ["PEER_VALIDATION", "ANCHOR_EXPANSION"],
                "peer_promotion_decision": ["PROMOTE", "DO_NOT_PROMOTE"],
                "target_fit_grade": list(TARGET_FIT_RANK),
                "promotion_evidence_grade": list(PROMOTION_EVIDENCE_RANK),
                "evidence_reference_type": sorted(EVIDENCE_REFERENCE_TYPES),
                "evidence_claim_type": sorted(EVIDENCE_CLAIM_TYPES),
                "evidence_freshness": sorted(EVIDENCE_FRESHNESS),
                "evidence_grade": sorted(EVIDENCE_GRADES),
                "commercial_gate_tag": sorted(COMMERCIAL_GATE_TAGS),
                "commercial_gate_status": ["PASS", "MISSING", "CONFLICT"],
                "supply_chain_party_role": sorted(SUPPLY_CHAIN_PARTY_ROLES),
            },
            "required_fields": {
                "information_record": sorted(INFORMATION_REQUIRED),
                "source_attempt": sorted(ATTEMPT_REQUIRED),
                "evidence": sorted(EVIDENCE_REQUIRED),
                "pivot": sorted(PIVOT_REQUIRED),
                "provider_receipt": sorted(PROVIDER_RECEIPT_REQUIRED),
                "provider_contact": sorted(PROVIDER_CONTACT_REQUIRED),
                "crm_writeback_receipt": sorted(CRM_WRITEBACK_REQUIRED),
            },
            "field_policies": {
                "evidence.claim_type": {
                    "type": "enum",
                    "fixed_enum": True,
                    "allowed_values": sorted(EVIDENCE_CLAIM_TYPES),
                },
                "evidence.freshness": {"type": "enum", "fixed_enum": True, "allowed_values": sorted(EVIDENCE_FRESHNESS)},
                "evidence.evidence_grade": {"type": "enum", "fixed_enum": True, "allowed_values": sorted(EVIDENCE_GRADES)},
                "evidence.commercial_gate_tags": {
                    "type": "unique_enum_array",
                    "required_for_all_evidence": False,
                    "allowed_values": sorted(COMMERCIAL_GATE_TAGS),
                    "reason": "Only evidence intentionally submitted as commercial-grade proof participates in A/A+ readiness.",
                },
                "evidence.reference_type": {
                    "type": "conditional_reference",
                    "fixed_enum": True,
                    "allowed_values": sorted(EVIDENCE_REFERENCE_TYPES),
                    "public_url_required_when": "PUBLIC_URL",
                    "non_url_evidence_requires_exact_locator": True,
                },
                "evidence.boundary": {
                    "type": "non_empty_narrative",
                    "fixed_enum": False,
                    "reason": "The boundary must state the exact factual scope; an enum would erase material limitations.",
                },
                "evidence.source_type": {
                    "type": "source_family_compatible_string",
                    "fixed_enum": False,
                    "reason": "Public Source Families are immutable per investigation and may be extended only at start.",
                },
            },
            "modules": list(REQUIRED_MODULES),
            "research_core_modules": list(RESEARCH_CORE_MODULES),
            "source_profile_by_module": {key: list(value) for key, value in SOURCE_PROFILE_BY_MODULE.items()},
            "network_branches": list(NETWORK_BRANCHES),
            "source_profile_by_network_branch": {key: list(value) for key, value in SOURCE_PROFILE_BY_BRANCH.items()},
            "network_policy_defaults": dict(NETWORK_POLICY_DEFAULTS),
            "network_saturation_policy": {
                "strategy": "QUEUE_PIVOT_SATURATION",
                "fixed_depth_or_anchor_count_closes_research": False,
                "fixed_depth_or_anchor_count_rejects_qualified_peer": False,
                "resource_exhaustion_state": "PAUSED_RESOURCE_LIMIT",
                "closure_requires": [
                    "ALL_SIX_BRANCHES_TERMINAL_FOR_EVERY_ANCHOR",
                    "ALL_DISCOVERED_PEERS_INDEPENDENTLY_RECEIPTED",
                    "ALL_PROMOTED_ANCHORS_REEXPANDED",
                    "ANCHOR_QUEUE_EMPTY",
                    "OPEN_HIGH_YIELD_PIVOTS_ZERO",
                    "CYCLE_DEDUP_COMPLETE",
                ],
            },
            "state_dimensions": [
                "research_complete",
                "network_complete",
                "crm_sync_complete",
                "commercial_result_ready",
                "outreach_prerequisites_complete",
                "outreach_ready",
            ],
            "coverage_semantics": {
                "POSITIVE": "real result plus same-owner Evidence",
                "NEGATIVE": "intermediate negative observation; not terminal in v5.4",
                "NEGATIVE_EXHAUSTED": "real negative raw proof and Source Family exhausted",
                "NOT_APPLICABLE_JUSTIFIED": "country-specific applicability reason; blocked sources cannot use this",
                "BLOCKED": "remains incomplete and must never be converted to N/A",
            },
            "transport_boundary": {
                "local_runtime_health_is_not_tunnel_health": True,
                "pending_journal_can_be_written_and_replayed_locally": True,
                "transparent_remote_fallback_while_the_tunnel_is_down": False,
            },
            "public_source_execution_boundary": {
                "embedded_search_engine": False,
                "planner_tool": "plan_public_source_calls",
                "host_must_execute_visible_search_or_browser_tools": True,
                "planning_is_execution_proof": False,
                "receipt_tool": "append_execution_receipt",
                "closure_requires_real_receipts": True,
            },
            "crm_writeback_boundary": {
                "structured_receipt_tool": "append_crm_writeback_receipt",
                "source_attempt_alone_can_prove_crm_sync": False,
                "writer_required": "ARTIFACT_TOOL",
                "actual_post_commit_workbook_hash_verified": True,
            },
            "commercial_result_policy": {
                "independent_from_research_closure": True,
                "preserves_all_historical_and_new_information": True,
                "gates": list(COMMERCIAL_GATE_ORDER),
                "gate_statuses": ["PASS", "MISSING", "CONFLICT"],
                "a_or_above_requires_every_gate_pass": True,
                "maximum_grade_when_any_gate_is_not_pass": "B+",
                "runtime_assigns_final_sales_grade": False,
                "public_reference_gates": sorted(COMMERCIAL_PUBLIC_REFERENCE_GATES),
                "accepted_evidence_grades": sorted(COMMERCIAL_ACCEPTABLE_EVIDENCE_GRADES),
                "evidence_binding_policy": {
                    gate: {
                        "modules": sorted(policy["modules"]),
                        "claim_types": sorted(policy["claim_types"]),
                    }
                    for gate, policy in COMMERCIAL_GATE_EVIDENCE_POLICY.items()
                },
                "planner_or_attempt_without_claim_evidence_is_sufficient": False,
            },
        }

    @unicode_safe_entrypoint
    def get_runtime_health(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = str(args.get("investigation_id") or "").strip()
        errors: list[str] = []
        checked_sessions = 0
        if investigation_id:
            try:
                self.store.read(investigation_id)
                checked_sessions = 1
            except ValidationError as exc:
                errors.append(str(exc))
        else:
            for path in sorted(self.store.root.glob("INV-*.jsonl")):
                try:
                    self.store.read(path.stem)
                    checked_sessions += 1
                except ValidationError as exc:
                    errors.append(f"{path.name}: {exc}")
        try:
            canonical_entries = self.canonical_registry.entries()
            canonical_count = len(canonical_entries)
        except ValidationError as exc:
            canonical_entries = []
            canonical_count = 0
            errors.append(str(exc))
        try:
            pending = self.pending_journal.entries()
        except ValidationError as exc:
            pending = []
            errors.append(str(exc))
        pending_counts: dict[str, int] = {}
        for row in pending:
            pending_counts[row["status"]] = pending_counts.get(row["status"], 0) + 1
        origin_counts: dict[str, int] = {}
        numeric_ids: list[int] = []
        for row in canonical_entries:
            origin = str(row.get("origin") or "UNKNOWN")
            origin_counts[origin] = origin_counts.get(origin, 0) + 1
            match = re.fullmatch(r"C(\d+)", str(row.get("account_id") or ""), flags=re.I)
            if match:
                numeric_ids.append(int(match.group(1)))
        canonical_metrics = {
            "unique_accounts_loaded": canonical_count,
            "origin_counts": origin_counts,
            "highest_numeric_c_number": max(numeric_ids) if numeric_ids else None,
            "lowest_numeric_c_number": min(numeric_ids) if numeric_ids else None,
            "metric_scope": "LOCAL_APPEND_ONLY_REGISTRY_PLUS_DISCOVERABLE_SESSION_HEADERS",
            "is_highest_c_number": False,
            "proves_external_production_crm_total": False,
        }
        return {
            "status": "READY" if not errors else "DEGRADED",
            "runtime_version": RUNTIME_VERSION,
            "build_id": BUILD_ID,
            "local_runtime": True,
            "tunnel_reachability_proven": False,
            "checked_sessions": checked_sessions,
            "canonical_accounts": canonical_count,
            "canonical_metrics": canonical_metrics,
            "pending_receipt_counts": pending_counts,
            "errors": errors,
            "recovery": {
                "queue_tool": "queue_pending_receipt",
                "sync_tool": "sync_pending_receipts",
                "safe_retry_targets": sorted(PendingReceiptJournal.ALLOWED_TARGETS),
            },
        }

    @unicode_safe_entrypoint
    def queue_pending_receipt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        target_tool = nonempty(args.get("target_tool"), "target_tool")
        payload = require_object(args.get("payload"), "payload")
        journal_id = str(args.get("journal_id") or "").strip()
        return self.pending_journal.queue(target_tool, payload, journal_id)

    @unicode_safe_entrypoint
    def get_pending_journal_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = str(args.get("investigation_id") or "").strip()
        rows = self.pending_journal.entries()
        if investigation_id:
            rows = [row for row in rows if row["investigation_id"] == investigation_id]
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "investigation_id": investigation_id or None,
            "entries": rows,
            "counts": counts,
            "pending": sum(count for status, count in counts.items() if status not in {"SYNCED", "DEDUPLICATED"}),
            "append_only": True,
        }

    def _pending_equivalent(self, target_tool: str, payload: dict[str, Any]) -> bool:
        investigation_id = str(payload.get("investigation_id") or "")
        try:
            state = self._state(investigation_id)
        except ValidationError:
            return False
        if target_tool == "append_information_record":
            raw = payload.get("record") or {}
            existing = state["information_records"].get(raw.get("information_id"))
            return bool(
                existing
                and existing.get("content_sha256") == raw.get("content_sha256")
                and existing.get("source_locator") == raw.get("source_locator")
            )
        if target_tool == "append_execution_receipt":
            raw = payload.get("attempt") or {}
            existing = state["attempts"].get(raw.get("attempt_id"))
            return bool(
                existing
                and existing.get("content_sha256") == raw.get("content_sha256")
                and existing.get("execution_id") == raw.get("execution_id")
                and set(existing.get("evidence_ids") or []) == set(raw.get("evidence_ids") or [])
            )
        if target_tool == "append_provider_receipt":
            raw = payload.get("receipt") or {}
            existing = state["provider_receipts"].get(raw.get("provider_receipt_id"))
            return bool(
                existing
                and existing.get("content_sha256") == raw.get("content_sha256")
                and existing.get("tool_call_id") == raw.get("tool_call_id")
            )
        if target_tool == "append_peer_receipt":
            receipt_type = str(payload.get("receipt_type") or "PEER_VALIDATION").upper()
            if receipt_type == "ANCHOR_EXPANSION":
                return str(payload.get("anchor_id") or "") in state["anchor_closed"]
            raw = payload.get("receipt") or {}
            existing = state["peers"].get(raw.get("peer_id"))
            return bool(
                existing
                and existing.get("canonical_key") == raw.get("canonical_key")
                and existing.get("discovered_by_attempt_id") == raw.get("discovered_by_attempt_id")
                and existing.get("promotion_decision") == str(raw.get("promotion_decision") or "").upper()
            )
        if target_tool == "append_crm_writeback_receipt":
            raw = payload.get("receipt") or {}
            existing = state["crm_writebacks"].get(raw.get("writeback_id"))
            return bool(
                existing
                and existing.get("transaction_id") == raw.get("transaction_id")
                and existing.get("workbook_sha256_after") == str(raw.get("workbook_sha256_after") or "").casefold()
                and existing.get("audit_artifact_sha256") == str(raw.get("audit_artifact_sha256") or "").casefold()
            )
        return False

    @unicode_safe_entrypoint
    def sync_pending_receipts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = str(args.get("investigation_id") or "").strip()
        limit = args.get("limit", 100)
        if not isinstance(limit, int):
            raise ValidationError("limit: integer required")
        dry_run = args.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ValidationError("dry_run: boolean required")
        return self.pending_journal.sync(
            {
                "append_information_record": self.append_information_record,
                "append_execution_receipt": self.append_execution_receipt,
                "append_provider_receipt": self.append_provider_receipt,
                "append_peer_receipt": self.append_peer_receipt,
                "append_crm_writeback_receipt": self.append_crm_writeback_receipt,
            },
            investigation_id=investigation_id,
            limit=limit,
            dry_run=dry_run,
            equivalent=self._pending_equivalent,
        )

    def _find_reusable_investigation(
        self,
        account_id: str,
        *,
        mode: str,
        idempotency_key: str,
        resume_existing: bool,
    ) -> dict[str, Any] | None:
        candidates: list[tuple[float, dict[str, Any]]] = []
        for path in self.store.root.glob("INV-*.jsonl"):
            try:
                events = self.store.read(path.stem)
            except ValidationError:
                continue
            start = events[0]["payload"]
            if str(start.get("account", {}).get("account_id") or "").casefold() != account_id.casefold():
                continue
            if idempotency_key and start.get("start_idempotency_key") == idempotency_key:
                return start
            if not resume_existing or start.get("mode") != mode:
                continue
            if any(event["event_type"] == "CLOSURE_ISSUED" for event in events):
                continue
            candidates.append((path.stat().st_mtime, start))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _normalize_network_policy(raw: Any) -> dict[str, Any]:
        policy = require_object(raw or {}, "network_policy")
        unexpected = sorted(set(policy) - set(NETWORK_POLICY_DEFAULTS) - LEGACY_NETWORK_BUDGET_FIELDS)
        if unexpected:
            raise ValidationError("network_policy: unsupported fields: " + ",".join(unexpected))
        active_policy = {key: value for key, value in policy.items() if key in NETWORK_POLICY_DEFAULTS}
        merged = {**NETWORK_POLICY_DEFAULTS, **active_policy}
        legacy_budget_hints: dict[str, int] = {}
        for field in sorted(LEGACY_NETWORK_BUDGET_FIELDS):
            if field not in policy:
                continue
            value = policy[field]
            if not isinstance(value, int) or value < 0:
                raise ValidationError(f"network_policy.{field}: non-negative integer required")
            legacy_budget_hints[field] = value
        fit = str(merged["minimum_target_fit"]).upper()
        evidence = str(merged["minimum_evidence_grade"]).upper()
        if fit not in TARGET_FIT_RANK:
            raise ValidationError("network_policy.minimum_target_fit invalid; allowed: " + ",".join(TARGET_FIT_RANK))
        if evidence not in PROMOTION_EVIDENCE_RANK:
            raise ValidationError("network_policy.minimum_evidence_grade invalid; allowed: " + ",".join(PROMOTION_EVIDENCE_RANK))
        if TARGET_FIT_RANK[fit] < TARGET_FIT_RANK[NETWORK_POLICY_DEFAULTS["minimum_target_fit"]]:
            raise ValidationError("network_policy.minimum_target_fit cannot weaken the Runtime minimum A")
        if PROMOTION_EVIDENCE_RANK[evidence] < PROMOTION_EVIDENCE_RANK[NETWORK_POLICY_DEFAULTS["minimum_evidence_grade"]]:
            raise ValidationError("network_policy.minimum_evidence_grade cannot weaken the Runtime minimum B")
        for field in ("require_commercial_novelty", "require_canonical_new"):
            if merged[field] is not True:
                raise ValidationError(f"network_policy.{field} is a non-relaxable true gate")
        if str(merged.get("closure_strategy") or "").upper() != "QUEUE_PIVOT_SATURATION":
            raise ValidationError("network_policy.closure_strategy must be QUEUE_PIVOT_SATURATION")
        return {
            **merged,
            "minimum_target_fit": fit,
            "minimum_evidence_grade": evidence,
            "closure_strategy": "QUEUE_PIVOT_SATURATION",
            "legacy_budget_hints": legacy_budget_hints,
            "legacy_budget_hints_enforced": False,
            "fixed_caps_are_completion_conditions": False,
        }

    @staticmethod
    def _normalize_supply_chain_parties(raw: Any) -> dict[str, list[dict[str, Any]]]:
        parties = require_object(raw or {}, "supply_chain_parties")
        output: dict[str, list[dict[str, Any]]] = {role: [] for role in sorted(SUPPLY_CHAIN_PARTY_ROLES)}
        for raw_role, value in parties.items():
            role = str(raw_role).upper()
            if role not in SUPPLY_CHAIN_PARTY_ROLES:
                raise ValidationError(
                    "supply_chain_parties role invalid; allowed: " + ",".join(sorted(SUPPLY_CHAIN_PARTY_ROLES))
                )
            rows = value if isinstance(value, list) else [value]
            for index, row in enumerate(rows):
                item = require_object(row, f"supply_chain_parties.{role}[{index}]")
                entity_id = nonempty(item.get("entity_id"), f"supply_chain_parties.{role}[{index}].entity_id")
                name = nonempty(item.get("name"), f"supply_chain_parties.{role}[{index}].name")
                output[role].append({**item, "entity_id": entity_id, "name": name, "role": role})
        return output

    @staticmethod
    def _start_response(payload: dict[str, Any], session_log: str, *, resumed_existing: bool) -> dict[str, Any]:
        return {
            "investigation_id": payload["investigation_id"],
            "canonical_account_id": payload["account"]["account_id"],
            "canonical_resolution": payload.get("canonical_resolution"),
            "mode": payload["mode"],
            "required_modules": payload["required_modules"],
            "source_profile": payload["source_profile"],
            "network_branches": payload["network_branches"],
            "network_policy": payload.get("network_policy", NETWORK_POLICY_DEFAULTS),
            "supply_chain_parties": payload.get("supply_chain_parties", {}),
            "anchor_queue": payload["anchor_queue"],
            "history_digest": payload["history_digest"],
            "authority_digest": payload["authority_digest"],
            "provider_policy": payload["provider_policy"],
            "state_dimensions": {
                "research_complete": False,
                "network_complete": False,
                "crm_sync_complete": False,
                "commercial_result_ready": False,
                "outreach_ready": False,
            },
            "status": "PENDING",
            "research_complete": False,
            "resumed_existing": resumed_existing,
            "session_log": session_log,
        }

    @unicode_safe_entrypoint
    def start_investigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        account = require_object(args.get("account"), "account")
        requested_account_id = str(account.get("account_id") or "").strip()
        country = nonempty(account.get("country"), "account.country")
        mode = str(args.get("mode") or "EXHAUSTIVE").upper()
        if mode not in {"EXHAUSTIVE", "FAST_SCAN"}:
            raise ValidationError("mode: EXHAUSTIVE or FAST_SCAN required")
        history = require_object(args.get("history") or {}, "history")
        events = require_list(history.get("events") or [], "history.events")
        opt_out = bool(history.get("opt_out")) or any(str(item.get("event_type", "")).upper() in {"OPT_OUT", "UNSUBSCRIBE", "DO_NOT_CONTACT"} for item in events if isinstance(item, dict))
        highest_stage = ""
        highest_rank = -1
        for item in events:
            if not isinstance(item, dict):
                raise ValidationError("history.events: every entry must be an object")
            stage = str(item.get("stage") or item.get("event_type") or "").upper()
            if stage in STAGE_RANK and STAGE_RANK[stage] > highest_rank:
                highest_stage, highest_rank = stage, STAGE_RANK[stage]
        idempotency_key = str(args.get("idempotency_key") or "").strip()
        if idempotency_key and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", idempotency_key):
            raise ValidationError("idempotency_key: 8-128 safe characters required")
        resume_existing = args.get("resume_existing", True)
        if not isinstance(resume_existing, bool):
            raise ValidationError("resume_existing must be boolean")
        additional = require_object(args.get("additional_source_families") or {}, "additional_source_families")
        source_profile: dict[str, list[str]] = {}
        for module in REQUIRED_MODULES:
            extras = additional.get(module) or []
            if not isinstance(extras, list) or not all(isinstance(x, str) and x.strip() for x in extras):
                raise ValidationError(f"additional_source_families.{module}: string array required")
            source_profile[module] = sorted(set(SOURCE_PROFILE_BY_MODULE[module]) | {x.strip() for x in extras})
        authority_claims = args.get("authority_claims") or []
        if not isinstance(authority_claims, list) or not all(isinstance(x, str) and x.strip() for x in authority_claims):
            raise ValidationError("authority_claims: string array required")
        manual_queue = args.get("manual_visual_queue") or []
        if not isinstance(manual_queue, list) or not all(isinstance(x, str) and x.strip() for x in manual_queue):
            raise ValidationError("manual_visual_queue: string array required")
        raw_provider_policy = require_object(args.get("provider_policy") or {}, "provider_policy")
        provider_mode = str(raw_provider_policy.get("mode") or "PUBLIC_ONLY").upper()
        if provider_mode not in PROVIDER_MODES:
            raise ValidationError("provider_policy.mode invalid")
        allowed_providers = raw_provider_policy.get("allowed_providers") or []
        if not isinstance(allowed_providers, list) or not all(isinstance(x, str) and x.strip() for x in allowed_providers):
            raise ValidationError("provider_policy.allowed_providers: string array required")
        required_capabilities = raw_provider_policy.get("required_capabilities") or []
        if not isinstance(required_capabilities, list) or not all(isinstance(x, str) and x.strip() for x in required_capabilities):
            raise ValidationError("provider_policy.required_capabilities: string array required")
        if provider_mode == "PUBLIC_ONLY" and (allowed_providers or required_capabilities):
            raise ValidationError("PUBLIC_ONLY cannot authorize providers or require provider capabilities")
        if provider_mode != "PUBLIC_ONLY" and not allowed_providers:
            raise ValidationError("connected-provider modes require an explicit allowed_providers list")
        if provider_mode == "CONNECTED_PROVIDERS_REQUIRED" and not required_capabilities:
            raise ValidationError("CONNECTED_PROVIDERS_REQUIRED requires required_capabilities")
        provider_policy = {
            "mode": provider_mode,
            "allowed_providers": sorted(set(x.strip() for x in allowed_providers), key=str.casefold),
            "required_capabilities": sorted(set(x.strip() for x in required_capabilities), key=str.casefold),
            "cost_consent": raw_provider_policy.get("cost_consent") is True,
        }
        investigation_input = require_object(args.get("input") or {}, "input")
        network_policy = self._normalize_network_policy(args.get("network_policy"))
        supply_chain_parties = self._normalize_supply_chain_parties(
            args.get("supply_chain_parties") or investigation_input.get("supply_chain_parties") or {}
        )
        create_account_if_missing = args.get("create_account_if_missing", True)
        if not isinstance(create_account_if_missing, bool):
            raise ValidationError("create_account_if_missing must be boolean")
        canonical = self.canonical_registry.resolve_or_create(
            {**account, "country": country},
            requested_account_id=requested_account_id,
            create_if_missing=create_account_if_missing,
        )
        if canonical["status"] == "AMBIGUOUS_MATCH":
            raise ValidationError(
                "account canonical resolution is ambiguous; call resolve_or_create_account and select an exact existing account_id"
            )
        if canonical["status"] == "NOT_FOUND" or not canonical.get("match"):
            raise ValidationError("account canonical resolution did not find or create an account")
        account_id = canonical["match"]["account_id"]
        reusable = self._find_reusable_investigation(
            account_id,
            mode=mode,
            idempotency_key=idempotency_key,
            resume_existing=resume_existing,
        )
        if reusable is not None:
            return self._start_response(
                reusable,
                str(self.store.path(reusable["investigation_id"])),
                resumed_existing=True,
            )
        investigation_id = f"INV-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
        history_digest = digest(history)
        authority_digest = digest(sorted(set(authority_claims)))
        payload = {
            "schema": "cbi.investigation.v5.4",
            "runtime_version": RUNTIME_VERSION,
            "build_id": BUILD_ID,
            "investigation_id": investigation_id,
            "account": {**account, "account_id": account_id, "country": country},
            "canonical_resolution": canonical,
            "start_idempotency_key": idempotency_key,
            "mode": mode,
            "input": investigation_input,
            "crm_path": str(args.get("crm_path") or ""),
            "required_modules": list(REQUIRED_MODULES),
            "source_profile": source_profile,
            "network_branches": list(NETWORK_BRANCHES),
            "network_source_profile": {key: list(value) for key, value in SOURCE_PROFILE_BY_BRANCH.items()},
            "network_policy": network_policy,
            "anchor_depths": {account_id: 0},
            "anchor_queue": [account_id],
            "supply_chain_parties": supply_chain_parties,
            "history_digest": history_digest,
            "history_highest_stage": highest_stage,
            "opt_out": opt_out,
            "authority_claims": sorted(set(authority_claims)),
            "authority_digest": authority_digest,
            "manual_visual_queue": list(dict.fromkeys(manual_queue)),
            "provider_policy": provider_policy,
            "completion_policy": "SOURCE_FAMILY_PIVOT_NETWORK_EVIDENCE_EXHAUSTION_ONLY",
            "fixed_time_or_page_counts_are_completion": False,
        }
        self.store.create(payload)
        return self._start_response(payload, str(self.store.path(investigation_id)), resumed_existing=False)

    def _state(self, investigation_id: str) -> dict[str, Any]:
        events = self.store.read(investigation_id)
        start = events[0]["payload"]
        state: dict[str, Any] = {
            "events": events,
            "start": start,
            "attempts": {},
            "executions": set(),
            "evidence": {},
            "information_records": {},
            "pivots": {},
            "peers": {},
            "anchor_queue": list(start["anchor_queue"]),
            "anchor_closed": set(),
            "anchor_depths": dict(start.get("anchor_depths") or {start["account"]["account_id"]: 0}),
            "manual_visual_queue": set(start.get("manual_visual_queue") or []),
            "provider_plans": {},
            "provider_receipts": {},
            "provider_tool_calls": set(),
            "provider_planned_calls": set(),
            "crm_writebacks": {},
            "crm_transactions": set(),
            "closures": {},
            "preparations": {},
            "rendered_tokens": set(),
        }
        for event in events[1:]:
            payload = event["payload"]
            kind = event["event_type"]
            if kind == "EXECUTION_RECEIPT_APPENDED":
                attempt = payload["attempt"]
                state["attempts"][attempt["attempt_id"]] = attempt
                state["executions"].add(attempt["execution_id"])
                for item in payload["evidence"]:
                    state["evidence"][item["evidence_id"]] = item
                for pivot in payload["pivots_generated"]:
                    state["pivots"][pivot["pivot_id"]] = dict(pivot)
                for consumed in payload["pivots_consumed"]:
                    state["pivots"][consumed["pivot_id"]].update(consumed)
                for item in payload.get("manual_visual_items_resolved") or []:
                    state["manual_visual_queue"].discard(item)
            elif kind == "INFORMATION_RECORD_APPENDED":
                record = payload["record"]
                state["information_records"][record["information_id"]] = record
            elif kind == "PEER_RECEIPT_APPENDED":
                receipt = payload["receipt"]
                state["peers"][receipt["peer_id"]] = receipt
                if receipt["promotion_decision"] == "PROMOTE" and receipt["peer_id"] not in state["anchor_queue"] and receipt["peer_id"] not in state["anchor_closed"]:
                    state["anchor_queue"].append(receipt["peer_id"])
                    state["anchor_depths"][receipt["peer_id"]] = int(receipt.get("anchor_depth", 1))
            elif kind == "PROVIDER_PLAN_CREATED":
                state["provider_plans"][payload["plan_id"]] = dict(payload)
            elif kind == "PROVIDER_RECEIPT_APPENDED":
                receipt = payload["receipt"]
                state["provider_receipts"][receipt["provider_receipt_id"]] = receipt
                state["provider_tool_calls"].add(receipt["tool_call_id"])
                state["provider_planned_calls"].add(receipt["planned_call_id"])
                for item in payload["evidence"]:
                    state["evidence"][item["evidence_id"]] = item
                for pivot in payload["pivots_generated"]:
                    state["pivots"][pivot["pivot_id"]] = dict(pivot)
                for consumed in payload["pivots_consumed"]:
                    state["pivots"][consumed["pivot_id"]].update(consumed)
            elif kind == "ANCHOR_EXPANSION_CLOSED":
                anchor_id = payload["anchor_id"]
                state["anchor_closed"].add(anchor_id)
                state["anchor_queue"] = [item for item in state["anchor_queue"] if item != anchor_id]
            elif kind == "CRM_WRITEBACK_RECEIPT_APPENDED":
                receipt = payload["receipt"]
                state["crm_writebacks"][receipt["writeback_id"]] = receipt
                state["crm_transactions"].add(receipt["transaction_id"])
            elif kind == "CLOSURE_ISSUED":
                state["closures"][payload["closure_id"]] = {**payload, "seq": event["seq"]}
            elif kind == "OUTREACH_PREPARED":
                state["preparations"][payload["prepared_id"]] = {**payload, "seq": event["seq"]}
                closure = state["closures"].get(payload["closure_id"])
                if closure is not None:
                    closure["used"] = True
            elif kind == "OUTREACH_RENDERED":
                state["rendered_tokens"].add(payload["render_token"])
        return state

    @staticmethod
    def _information_route_warnings(record: dict[str, Any], account_id: str) -> list[str]:
        """Classify use without suppressing or deleting the underlying information."""
        if record["outreach_eligible_claimed"] is not True:
            return []
        warnings: list[str] = []
        if record["information_type"] not in {"CONTACT", "ROUTE"}:
            warnings.append("INFORMATION_TYPE_IS_NOT_A_CONTACT_OR_ROUTE")
        if record["subject_owner_id"] != account_id:
            warnings.append("SUBJECT_OWNER_IS_NOT_THE_BUYER_ACCOUNT")
        if record["route_scope"] != "BUYER_DIRECT":
            warnings.append("ROUTE_SCOPE_IS_NOT_BUYER_DIRECT")
        if record["temporal_status"] != "CURRENT":
            warnings.append("CONTACT_IS_NOT_CONFIRMED_CURRENT")
        if record["confidence"] not in {"HIGH", "MEDIUM_HIGH"}:
            warnings.append("CONFIDENCE_TOO_LOW_FOR_DIRECT_OUTREACH")

        value = record["value"]
        if value.get("verified") is not True:
            warnings.append("CONTACT_NOT_VERIFIED")
        if value.get("masked") is True:
            warnings.append("MASKED_CONTACT")
        if value.get("guessed") is True:
            warnings.append("GUESSED_CONTACT")
        channel = str(value.get("channel") or "").upper()
        route_value = str(value.get("value") or "").strip()
        if not channel or not route_value:
            warnings.append("CONTACT_CHANNEL_OR_VALUE_MISSING")
        elif channel == "EMAIL" and not EMAIL_RE.fullmatch(route_value):
            warnings.append("INVALID_EMAIL_FORMAT")
        elif channel in {"WHATSAPP", "ZALO"} and value.get("channel_proof") is not True:
            warnings.append(f"{channel}_CHANNEL_NOT_PROVEN")
        return sorted(set(warnings))

    @unicode_safe_entrypoint
    def append_information_record(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Append any sourced lead/fact while computing, not conflating, its permitted use."""
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        raw = require_object(args.get("record"), "record")
        required_fields(raw, INFORMATION_REQUIRED, "record")
        if raw["investigation_id"] != investigation_id:
            raise ValidationError("record.investigation_id mismatch")

        information_id = nonempty(raw["information_id"], "record.information_id")
        if information_id in state["information_records"]:
            raise ValidationError(f"duplicate information_id: {information_id}")
        account_id = state["start"]["account"]["account_id"]
        if raw["related_account_id"] != account_id:
            raise ValidationError("record.related_account_id must be the investigation Account")

        subject_type = nonempty(raw["subject_type"], "record.subject_type").upper()
        information_type = nonempty(raw["information_type"], "record.information_type").upper()
        claim_key = nonempty(raw["claim_key"], "record.claim_key")
        confidence = nonempty(raw["confidence"], "record.confidence").upper()
        temporal_status = nonempty(raw["temporal_status"], "record.temporal_status").upper()
        route_scope = nonempty(raw["route_scope"], "record.route_scope").upper()
        if subject_type not in INFORMATION_SUBJECT_TYPES:
            raise ValidationError("record.subject_type invalid")
        if information_type not in INFORMATION_TYPES:
            raise ValidationError("record.information_type invalid")
        if confidence not in INFORMATION_CONFIDENCE:
            raise ValidationError("record.confidence invalid")
        if temporal_status not in INFORMATION_TEMPORAL_STATUS:
            raise ValidationError("record.temporal_status invalid")
        if route_scope not in INFORMATION_ROUTE_SCOPES:
            raise ValidationError("record.route_scope invalid")

        subject_owner_id = nonempty(raw["subject_owner_id"], "record.subject_owner_id")
        relationship = nonempty(raw["relationship_to_account"], "record.relationship_to_account")
        source_type = nonempty(raw["source_type"], "record.source_type").upper()
        if state["start"].get("schema") in {"cbi.investigation.v5.3", "cbi.investigation.v5.4", "cbi.investigation.v6"} and source_type not in INFORMATION_SOURCE_TYPES:
            raise ValidationError(
                "record.source_type invalid; allowed: " + ",".join(sorted(INFORMATION_SOURCE_TYPES))
            )
        value = require_object(raw["value"], "record.value")
        if not value:
            raise ValidationError("record.value must contain the observed information")
        if information_type == "PARTY_ROLE":
            role = str(value.get("role") or "").upper()
            if role not in SUPPLY_CHAIN_PARTY_ROLES:
                raise ValidationError(
                    "record.value.role invalid; allowed: " + ",".join(sorted(SUPPLY_CHAIN_PARTY_ROLES))
                )
            entity_id = nonempty(value.get("entity_id"), "record.value.entity_id")
            entity_name = nonempty(value.get("name"), "record.value.name")
            value = {**value, "role": role, "entity_id": entity_id, "name": entity_name}
        if not isinstance(raw["outreach_eligible_claimed"], bool):
            raise ValidationError("record.outreach_eligible_claimed must be boolean")

        observed = parse_time(raw["observed_at"], "record.observed_at")
        content_sha256 = valid_hash(raw["content_sha256"], "record.content_sha256")
        source_reference_type, source_url, source_locator = _validate_reference(
            raw["source_reference_type"],
            raw["source_url"],
            raw["source_locator"],
            content_sha256,
            "record.source_reference",
        )
        if source_type in PUBLIC_INFORMATION_SOURCE_TYPES and source_reference_type != "PUBLIC_URL":
            raise ValidationError("record: public source_type requires source_reference_type PUBLIC_URL")
        required_reference_by_source = {
            "USER_INPUT": "USER_INPUT",
            "LEGACY_CRM": "LEGACY_CRM",
            "PROVIDER": "PROVIDER_RECEIPT",
            "DERIVED_CALCULATION": "DERIVED_CALCULATION",
        }
        expected_reference = required_reference_by_source.get(source_type)
        if expected_reference and source_reference_type != expected_reference:
            raise ValidationError(
                f"record: source_type {source_type} requires source_reference_type {expected_reference}"
            )

        list_fields: dict[str, list[str]] = {}
        for field in ("supersedes_information_ids", "conflicts_with_information_ids", "evidence_ids"):
            items = require_list(raw[field], f"record.{field}")
            if not all(isinstance(item, str) and item.strip() for item in items):
                raise ValidationError(f"record.{field} must contain non-empty strings")
            normalized_items = [item.strip() for item in items]
            if len(set(normalized_items)) != len(normalized_items):
                raise ValidationError(f"record.{field} contains duplicates")
            if information_id in normalized_items:
                raise ValidationError(f"record.{field} cannot reference itself")
            list_fields[field] = normalized_items

        record = {
            **raw,
            "information_id": information_id,
            "related_account_id": account_id,
            "subject_type": subject_type,
            "subject_owner_id": subject_owner_id,
            "relationship_to_account": relationship,
            "information_type": information_type,
            "claim_key": claim_key,
            "source_type": source_type,
            "source_reference_type": source_reference_type,
            "source_url": source_url,
            "source_locator": source_locator,
            "observed_at": iso_utc(observed),
            "content_sha256": content_sha256,
            "confidence": confidence,
            "temporal_status": temporal_status,
            "route_scope": route_scope,
            "supersedes_information_ids": list_fields["supersedes_information_ids"],
            "conflicts_with_information_ids": list_fields["conflicts_with_information_ids"],
            "evidence_ids": list_fields["evidence_ids"],
            "notes": str(raw["notes"] or ""),
        }
        usage_warnings = self._information_route_warnings(record, account_id)
        unresolved_lineage = sorted({
            item
            for field in ("supersedes_information_ids", "conflicts_with_information_ids")
            for item in record[field]
            if item not in state["information_records"]
        })
        unresolved_evidence = sorted(item for item in record["evidence_ids"] if item not in state["evidence"])
        if source_reference_type == "PUBLIC_URL" and information_type in {"FACT", "CONTACT", "ROUTE", "PARTY_ROLE"}:
            if not record["evidence_ids"]:
                raise ValidationError("record: public positive information requires Claim-bound evidence_ids")
            if unresolved_evidence:
                raise ValidationError("record: public Evidence references must already exist")
        for evidence_id in record["evidence_ids"]:
            evidence_item = state["evidence"].get(evidence_id)
            if evidence_item is None:
                continue
            if evidence_item.get("claim_key") != claim_key:
                raise ValidationError(f"record: Evidence claim_key mismatch: {evidence_id}")
            if evidence_item.get("owner_id") not in {account_id, subject_owner_id}:
                raise ValidationError(f"record: Evidence owner mismatch: {evidence_id}")
            if source_reference_type == "PUBLIC_URL" and evidence_item.get("reference_type") != "PUBLIC_URL":
                raise ValidationError(f"record: public Claim requires PUBLIC_URL Evidence: {evidence_id}")
        if unresolved_lineage:
            usage_warnings.append("UNRESOLVED_EXTERNAL_INFORMATION_LINEAGE")
        if unresolved_evidence:
            usage_warnings.append("UNRESOLVED_EXTERNAL_EVIDENCE_REFERENCE")
        usage_warnings = sorted(set(usage_warnings))
        effective_outreach_eligible = raw["outreach_eligible_claimed"] is True and not usage_warnings
        record["outreach_eligible_effective"] = effective_outreach_eligible
        record["usage_warnings"] = usage_warnings

        self.store.append(investigation_id, "INFORMATION_RECORD_APPENDED", {"record": record})
        post_state = self._state(investigation_id)
        historical_count = sum(
            item["temporal_status"] == "HISTORICAL" or item["information_type"] == "HISTORICAL"
            for item in post_state["information_records"].values()
        )
        return {
            "accepted": True,
            "information_id": information_id,
            "append_only": True,
            "historical_records_preserved": historical_count,
            "total_information_records": len(post_state["information_records"]),
            "effective_outreach_eligible": effective_outreach_eligible,
            "usage_warnings": usage_warnings,
            "policy": "PRESERVE_HISTORY_APPEND_NEW_INFORMATION_CLASSIFY_USE_SEPARATELY",
        }

    @unicode_safe_entrypoint
    def get_information_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the complete timeline plus a non-destructive derived current view."""
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        account_id = state["start"]["account"]["account_id"]
        requested_account = str(args.get("related_account_id") or account_id)
        if requested_account != account_id:
            raise ValidationError("related_account_id must match the investigation Account")

        records = list(state["information_records"].values())
        existing_ids = set(state["information_records"])
        superseded_ids = {
            item
            for record in records
            for item in record["supersedes_information_ids"]
            if item in existing_ids
        }
        current_candidates = [record for record in records if record["information_id"] not in superseded_ids]
        by_type: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        for record in records:
            by_type[record["information_type"]] = by_type.get(record["information_type"], 0) + 1
            by_scope[record["route_scope"]] = by_scope.get(record["route_scope"], 0) + 1
        return {
            "investigation_id": investigation_id,
            "related_account_id": account_id,
            "records": records,
            "merged_current_view": current_candidates,
            "declared_supply_chain_parties": state["start"].get("supply_chain_parties", {}),
            "supply_chain_parties": [
                record
                for record in current_candidates
                if record["information_type"] == "PARTY_ROLE"
            ],
            "summary": {
                "total_records": len(records),
                "historical_records": sum(
                    item["temporal_status"] == "HISTORICAL" or item["information_type"] == "HISTORICAL"
                    for item in records
                ),
                "current_candidates": len(current_candidates),
                "superseded_but_preserved": len(superseded_ids),
                "conflict_records": sum(bool(item["conflicts_with_information_ids"]) or item["information_type"] == "CONFLICT" for item in records),
                "effective_outreach_routes": sum(item["outreach_eligible_effective"] is True for item in records),
                "by_information_type": by_type,
                "by_route_scope": by_scope,
            },
            "preservation_policy": "NO_INFORMATION_RECORD_IS_DELETED_OR_OVERWRITTEN; CURRENT_VIEW_IS_DERIVED",
        }

    def _required_families(self, state: dict[str, Any], owner_id: str, module_or_branch: str) -> set[str]:
        if module_or_branch in NETWORK_BRANCHES:
            return set(state["start"]["network_source_profile"][module_or_branch])
        return set(state["start"]["source_profile"][module_or_branch])

    def _validate_evidence(self, item: dict[str, Any], attempt: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        required_fields(item, EVIDENCE_REQUIRED, "evidence")
        evidence_id = nonempty(item["evidence_id"], "evidence.evidence_id")
        if evidence_id in state["evidence"]:
            raise ValidationError(f"duplicate evidence_id: {evidence_id}")
        for field in ("owner_type", "owner_id", "claim_key", "module_or_branch", "source_type", "source_family"):
            nonempty(item[field], f"evidence.{field}")
        if item["owner_id"] != attempt["owner_id"] or item["owner_type"] != attempt["owner_type"]:
            raise ValidationError(f"{evidence_id}: evidence owner mismatch")
        if item["module_or_branch"] != attempt["module_or_branch"]:
            raise ValidationError(f"{evidence_id}: evidence module/branch mismatch")
        if item["source_family"] != attempt["source_family"]:
            raise ValidationError(f"{evidence_id}: evidence source family mismatch")
        source_type = item["source_type"].strip().casefold()
        family = attempt["source_family"].strip().casefold()
        if source_type != family and family not in source_type and source_type not in family:
            raise ValidationError(f"{evidence_id}: incompatible source type")
        observed = parse_time(item["observed_at"], "evidence.observed_at")
        completed = parse_time(attempt["completed_at"], "attempt.completed_at")
        if observed > completed + timedelta(minutes=5):
            raise ValidationError(f"{evidence_id}: observed_at occurs after execution")
        evidence_hash = valid_hash(item["content_sha256"], "evidence.content_sha256")
        reference_type, url, locator = _validate_reference(
            item["reference_type"], item["url"], item["locator"], evidence_hash, f"{evidence_id}.reference"
        )
        snapshot = nonempty(item["snapshot_locator"], "evidence.snapshot_locator")
        _valid_locator(snapshot, evidence_hash, "evidence.snapshot_locator")
        claim_type = nonempty(item["claim_type"], "evidence.claim_type").upper()
        freshness = nonempty(item["freshness"], "evidence.freshness").upper()
        evidence_grade = nonempty(item["evidence_grade"], "evidence.evidence_grade").upper()
        if claim_type not in EVIDENCE_CLAIM_TYPES:
            raise ValidationError(f"{evidence_id}: evidence claim_type invalid")
        if freshness not in EVIDENCE_FRESHNESS:
            raise ValidationError(f"{evidence_id}: evidence freshness invalid")
        if evidence_grade not in EVIDENCE_GRADES:
            raise ValidationError(f"{evidence_id}: evidence_grade invalid")
        commercial_gate_tags = item.get("commercial_gate_tags") or []
        if not isinstance(commercial_gate_tags, list) or not all(
            isinstance(tag, str) and tag.strip() for tag in commercial_gate_tags
        ):
            raise ValidationError(f"{evidence_id}: commercial_gate_tags must be a string array")
        commercial_gate_tags = [tag.strip().upper() for tag in commercial_gate_tags]
        if len(set(commercial_gate_tags)) != len(commercial_gate_tags):
            raise ValidationError(f"{evidence_id}: commercial_gate_tags contains duplicates")
        invalid_tags = sorted(set(commercial_gate_tags) - COMMERCIAL_GATE_TAGS)
        if invalid_tags:
            raise ValidationError(f"{evidence_id}: invalid commercial_gate_tags: {','.join(invalid_tags)}")
        _validate_commercial_tag_binding(
            commercial_gate_tags,
            item["module_or_branch"],
            claim_type,
            evidence_id,
        )
        if not str(item["boundary"]).strip():
            raise ValidationError(f"{evidence_id}: evidence boundary required")
        return {
            **item,
            "reference_type": reference_type,
            "url": url,
            "locator": locator,
            "content_sha256": evidence_hash,
            "claim_type": claim_type,
            "freshness": freshness,
            "evidence_grade": evidence_grade,
            "commercial_gate_tags": commercial_gate_tags,
        }

    @unicode_safe_entrypoint
    def append_execution_receipt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        attempt = require_object(args.get("attempt"), "attempt")
        required_fields(attempt, ATTEMPT_REQUIRED, "attempt")
        if attempt["investigation_id"] != investigation_id:
            raise ValidationError("attempt.investigation_id mismatch")
        attempt_id = nonempty(attempt["attempt_id"], "attempt.attempt_id")
        execution_id = nonempty(attempt["execution_id"], "attempt.execution_id")
        if attempt_id in state["attempts"]:
            raise ValidationError(f"duplicate attempt_id: {attempt_id}")
        if execution_id in state["executions"]:
            raise ValidationError(f"duplicate execution_id: {execution_id}")
        for field in ("owner_type", "owner_id", "module_or_branch", "source_family", "query", "tool_or_operator"):
            nonempty(attempt[field], f"attempt.{field}")
        module = attempt["module_or_branch"]
        if module not in REQUIRED_MODULES and module not in NETWORK_BRANCHES:
            raise ValidationError("attempt.module_or_branch is not a mandatory module or network branch")
        account_id = state["start"]["account"]["account_id"]
        discovered_owners = {
            peer_id
            for prior in state["attempts"].values()
            for peer_id in (prior.get("discovered_peer_ids") or [])
        }
        valid_owners = {account_id} | set(state["peers"]) | discovered_owners
        if attempt["owner_id"] not in valid_owners:
            raise ValidationError("attempt.owner_id is not the Account or an independently validated Peer")
        required_profile = self._required_families(state, attempt["owner_id"], module)
        if attempt["source_family"] not in required_profile:
            raise ValidationError("attempt.source_family outside immutable Source Profile")
        started = parse_time(attempt["started_at"], "attempt.started_at")
        completed = parse_time(attempt["completed_at"], "attempt.completed_at")
        checked = parse_time(attempt["checked_at"], "attempt.checked_at")
        if started > completed or checked != completed:
            raise ValidationError("attempt timestamps are inconsistent")
        result = str(attempt["result"]).upper()
        if result not in VALID_RESULTS:
            raise ValidationError("attempt.result invalid")
        if not isinstance(attempt["result_count"], int) or attempt["result_count"] < 0:
            raise ValidationError("attempt.result_count must be a non-negative integer")
        if result == "POSITIVE" and attempt["result_count"] < 1:
            raise ValidationError("POSITIVE attempt requires result_count >= 1")
        if result != "POSITIVE" and attempt["result_count"] != 0:
            raise ValidationError("non-positive attempt requires result_count = 0")
        attempt_hash = valid_hash(attempt["content_sha256"], "attempt.content_sha256")
        _valid_locator(attempt["raw_result_locator"], attempt_hash, "attempt.raw_result_locator")
        evidence_ids = require_list(attempt["evidence_ids"], "attempt.evidence_ids")
        generated_ids = require_list(attempt["pivots_generated"], "attempt.pivots_generated")
        blocked_reason = str(attempt["blocked_reason"] or "").strip()
        if result == "POSITIVE" and not evidence_ids:
            raise ValidationError("POSITIVE attempt requires evidence_ids")
        if result != "POSITIVE" and evidence_ids:
            raise ValidationError("Negative, blocked, or N/A attempts cannot carry Evidence")
        if result == "BLOCKED" and not blocked_reason:
            raise ValidationError("BLOCKED attempt requires blocked_reason")
        if result in {"NOT_APPLICABLE", "NOT_APPLICABLE_JUSTIFIED"}:
            if not blocked_reason or state["start"]["account"]["country"].casefold() not in blocked_reason.casefold():
                raise ValidationError("NOT_APPLICABLE requires a country-specific applicability reason")
            if BLOCKED_AS_NA.search(blocked_reason):
                raise ValidationError("blocked/login/paywall/403 source cannot be marked NOT_APPLICABLE")
        if result in {"POSITIVE", "NEGATIVE", "NEGATIVE_EXHAUSTED"} and blocked_reason:
            raise ValidationError("completed positive/negative attempt cannot carry blocked_reason")
        evidence_input = require_list(args.get("evidence") or [], "evidence")
        if len(set(str(x) for x in evidence_ids)) != len(evidence_ids):
            raise ValidationError("attempt.evidence_ids contains duplicates")
        evidence: list[dict[str, Any]] = []
        for item in evidence_input:
            evidence.append(self._validate_evidence(require_object(item, "evidence[]"), attempt, state))
        if set(evidence_ids) != {item["evidence_id"] for item in evidence}:
            raise ValidationError("attempt.evidence_ids do not exactly match appended Evidence")
        pivots_input = require_list(args.get("pivots") or [], "pivots")
        pivots_generated: list[dict[str, Any]] = []
        if len(set(str(x) for x in generated_ids)) != len(generated_ids):
            raise ValidationError("attempt.pivots_generated contains duplicates")
        for raw in pivots_input:
            pivot = require_object(raw, "pivots[]")
            required_fields(pivot, PIVOT_REQUIRED, "pivot")
            pivot_id = nonempty(pivot["pivot_id"], "pivot.pivot_id")
            if pivot_id in state["pivots"]:
                raise ValidationError(f"duplicate pivot_id: {pivot_id}")
            if pivot["generated_by_attempt_id"] != attempt_id:
                raise ValidationError(f"{pivot_id}: generator attempt mismatch")
            if parse_time(pivot["generated_at"], "pivot.generated_at") != completed:
                raise ValidationError(f"{pivot_id}: generated_at must equal attempt completion")
            nonempty(pivot["pivot_type"], "pivot.pivot_type")
            nonempty(pivot["pivot_value"], "pivot.pivot_value")
            if pivot["status"] != "OPEN" or any(pivot[field] not in ("", None) for field in ("consumed_by_attempt_id", "consumed_at", "consumption_result")):
                raise ValidationError(f"{pivot_id}: new pivot must be OPEN and unconsumed")
            pivots_generated.append(dict(pivot))
        if set(generated_ids) != {item["pivot_id"] for item in pivots_generated}:
            raise ValidationError("attempt.pivots_generated do not exactly match appended PivotEvents")
        consumed_input = require_list(args.get("pivots_consumed") or [], "pivots_consumed")
        pivots_consumed: list[dict[str, Any]] = []
        for raw in consumed_input:
            consumed = require_object(raw, "pivots_consumed[]")
            pivot_id = nonempty(consumed.get("pivot_id"), "pivots_consumed.pivot_id")
            if pivot_id not in state["pivots"]:
                raise ValidationError(f"{pivot_id}: unknown pivot")
            pivot = state["pivots"][pivot_id]
            if pivot.get("status") != "OPEN":
                raise ValidationError(f"{pivot_id}: pivot already consumed")
            if pivot["generated_by_attempt_id"] == attempt_id:
                raise ValidationError(f"{pivot_id}: an Attempt cannot consume its own Pivot")
            generated_at = parse_time(pivot["generated_at"], "pivot.generated_at")
            if completed <= generated_at:
                raise ValidationError(f"{pivot_id}: Pivot consumption must be later than generation")
            if pivot["pivot_value"].casefold() not in attempt["query"].casefold():
                raise ValidationError(f"{pivot_id}: consuming Query does not contain Pivot value")
            pivots_consumed.append({
                "pivot_id": pivot_id,
                "consumed_by_attempt_id": attempt_id,
                "consumed_at": attempt["completed_at"],
                "consumption_result": nonempty(consumed.get("consumption_result"), "pivots_consumed.consumption_result"),
                "status": "CONSUMED",
            })
        discovered = attempt.get("discovered_peer_ids") or []
        relationship_evidence_ids = attempt.get("relationship_evidence_ids") or {}
        if not isinstance(discovered, list) or not all(isinstance(x, str) and x.strip() for x in discovered):
            raise ValidationError("attempt.discovered_peer_ids: string array required")
        if not isinstance(relationship_evidence_ids, dict):
            raise ValidationError("attempt.relationship_evidence_ids: object required")
        for peer_id in discovered:
            ids = relationship_evidence_ids.get(peer_id) or []
            if module not in NETWORK_BRANCHES or not ids or not set(ids) <= set(evidence_ids):
                raise ValidationError(f"{peer_id}: discovery requires relationship Evidence from the same Branch Attempt")
        resolved = require_list(args.get("manual_visual_items_resolved") or [], "manual_visual_items_resolved")
        if not set(resolved) <= state["manual_visual_queue"]:
            raise ValidationError("manual_visual_items_resolved contains unknown items")
        normalized_attempt = {
            **attempt,
            "result": result,
            "content_sha256": attempt_hash,
            "discovered_peer_ids": list(dict.fromkeys(discovered)),
            "relationship_evidence_ids": relationship_evidence_ids,
        }
        self.store.append(investigation_id, "EXECUTION_RECEIPT_APPENDED", {
            "attempt": normalized_attempt,
            "evidence": evidence,
            "pivots_generated": pivots_generated,
            "pivots_consumed": pivots_consumed,
            "manual_visual_items_resolved": resolved,
        })
        return {
            "accepted": True,
            "attempt_id": attempt_id,
            "evidence_count": len(evidence),
            "pivots_generated": len(pivots_generated),
            "pivots_consumed": len(pivots_consumed),
            "append_only": True,
        }

    @unicode_safe_entrypoint
    def plan_public_source_calls(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Expose the next public-source work without pretending that planning is search execution."""

        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        limit = args.get("limit", 200)
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValidationError("limit must be between 1 and 1000")
        account = state["start"]["account"]
        country = str(account.get("country") or "").strip()
        account_name = str(account.get("name") or account.get("account_id") or "").strip()
        terminal = {"POSITIVE", "NEGATIVE_EXHAUSTED", "NOT_APPLICABLE_JUSTIFIED", "NOT_APPLICABLE"}
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()

        def add_item(
            owner_id: str,
            owner_label: str,
            module_or_branch: str,
            source_family: str,
            reason: str,
            pivot_id: str = "",
            pivot_value: str = "",
        ) -> None:
            key = (owner_id, module_or_branch, source_family, pivot_id)
            if key in seen or len(items) >= limit:
                return
            seen.add(key)
            terms = [f'"{owner_label}"', f'"{country}"', source_family.replace("_", " ")]
            if pivot_value:
                terms.insert(1, f'"{pivot_value}"')
            query = " ".join(item for item in terms if item and item != '\"\"')
            work_item = {
                "owner_type": "ACCOUNT" if owner_id == account["account_id"] else "PEER",
                "owner_id": owner_id,
                "module_or_branch": module_or_branch,
                "source_family": source_family,
                "reason": reason,
                "query": query,
                "pivot_id": pivot_id,
                "pivot_value": pivot_value,
                "execution_required": True,
                "receipt_required": True,
                "search_execution_performed": False,
            }
            work_item["work_item_id"] = "PWEB-" + digest(work_item)[:20]
            items.append(work_item)

        # Open Pivots are highest priority because Closure cannot proceed until a
        # later independent Attempt consumes each one with its value in the Query.
        for pivot_id, pivot in sorted(state["pivots"].items()):
            if pivot.get("status") != "OPEN" or len(items) >= limit:
                continue
            origin = state["attempts"].get(pivot.get("generated_by_attempt_id"))
            if origin is None:
                continue
            owner_id = origin["owner_id"]
            peer = state["peers"].get(owner_id) or {}
            owner_label = str(peer.get("canonical_key") or owner_id)
            add_item(
                owner_id,
                owner_label,
                origin["module_or_branch"],
                origin["source_family"],
                "OPEN_PIVOT_REQUIRES_LATER_INDEPENDENT_ATTEMPT",
                pivot_id,
                str(pivot.get("pivot_value") or ""),
            )

        for module in REQUIRED_MODULES:
            if module == "network_fission" or len(items) >= limit:
                continue
            required = state["start"]["source_profile"][module]
            for family in required:
                latest = self._latest_family_result(state, account["account_id"], module, family)
                if latest not in terminal:
                    reason = "MISSING_SOURCE_ATTEMPT" if latest == "PENDING" else f"NON_TERMINAL_SOURCE_STATE:{latest}"
                    add_item(account["account_id"], account_name, module, family, reason)

        for anchor_id in list(state["anchor_queue"]):
            if len(items) >= limit:
                break
            peer = state["peers"].get(anchor_id) or {}
            owner_label = account_name if anchor_id == account["account_id"] else str(peer.get("canonical_key") or anchor_id)
            for branch in NETWORK_BRANCHES:
                for family in state["start"]["network_source_profile"][branch]:
                    latest = self._latest_family_result(state, anchor_id, branch, family)
                    if latest not in terminal:
                        reason = "MISSING_NETWORK_ATTEMPT" if latest == "PENDING" else f"NON_TERMINAL_NETWORK_STATE:{latest}"
                        add_item(anchor_id, owner_label, branch, family, reason)

        basis_hash = state["events"][-1]["event_hash"]
        return {
            "plan_id": "PUBLIC-" + digest({"basis_hash": basis_hash, "items": items})[:24],
            "investigation_id": investigation_id,
            "basis_hash": basis_hash,
            "status": "READY" if items else "NO_PLANNED_CALLS_RECHECK_CLOSURE",
            "calls": items,
            "returned_count": len(items),
            "truncated": len(items) >= limit,
            "embedded_search_engine": False,
            "runtime_executed_public_search": False,
            "host_execution_required": bool(items),
            "execution_boundary": (
                "The Codex/ChatGPT host must execute each applicable public web, browser, registry, maps, "
                "directory, or social-page action and append its real receipt. This plan is never Evidence."
            ),
        }

    @unicode_safe_entrypoint
    def plan_provider_calls(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Create an auditable plan for Codex-level calls to connected provider plugins.

        This runtime never invokes another plugin directly.  It only authorizes exact
        provider/capability/tool combinations and later verifies their receipts.
        """
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        policy = state["start"]["provider_policy"]
        requested = require_list(args.get("requested_capabilities"), "requested_capabilities")
        if not requested or not all(isinstance(item, str) and item.strip() for item in requested):
            raise ValidationError("requested_capabilities: non-empty string array required")
        requested_capabilities = sorted(set(item.strip() for item in requested), key=str.casefold)
        inventory_input = require_list(args.get("provider_inventory") or [], "provider_inventory")

        if policy["mode"] == "PUBLIC_ONLY":
            return {
                "investigation_id": investigation_id,
                "status": "PROVIDER_USE_DISABLED",
                "provider_mode": policy["mode"],
                "plan_id": None,
                "calls": [],
                "missing_capabilities": requested_capabilities,
                "blocked": ["PUBLIC_ONLY_REQUIRES_A_NEW_EXPLICITLY_AUTHORIZED_INVESTIGATION"],
                "external_execution_required": False,
                "runtime_invokes_other_plugins": False,
            }

        allowed = {item.casefold(): item for item in policy["allowed_providers"]}
        inventory: list[dict[str, Any]] = []
        seen_providers: set[str] = set()
        for raw in inventory_input:
            item = require_object(raw, "provider_inventory[]")
            required_fields(
                item,
                {"provider", "provider_class", "status", "capability_tools", "requires_paid_credit", "permissions"},
                "provider_inventory[]",
            )
            provider = nonempty(item["provider"], "provider_inventory.provider")
            provider_key = provider.casefold()
            if provider_key in seen_providers:
                raise ValidationError(f"duplicate provider inventory entry: {provider}")
            seen_providers.add(provider_key)
            provider_class = str(item["provider_class"]).upper()
            if provider_class not in PROVIDER_CLASSES:
                raise ValidationError(f"{provider}: provider_class invalid")
            status = str(item["status"]).upper()
            if status not in PROVIDER_AVAILABILITY:
                raise ValidationError(f"{provider}: provider status invalid")
            capability_tools = require_object(item["capability_tools"], f"{provider}.capability_tools")
            normalized_tools: dict[str, str] = {}
            for capability, tool_name in capability_tools.items():
                normalized_tools[nonempty(capability, f"{provider}.capability")] = nonempty(tool_name, f"{provider}.tool_name")
            permissions = require_list(item["permissions"], f"{provider}.permissions")
            if not all(isinstance(value, str) and value.strip() for value in permissions):
                raise ValidationError(f"{provider}.permissions: string array required")
            inventory.append({
                "provider": provider,
                "provider_class": provider_class,
                "status": status,
                "capability_tools": normalized_tools,
                "requires_paid_credit": item["requires_paid_credit"] is True,
                "permissions": sorted(set(value.strip() for value in permissions)),
            })

        cost_consent = policy["cost_consent"] and args.get("cost_consent") is True
        calls: list[dict[str, Any]] = []
        blocked: list[str] = []
        covered: set[str] = set()
        for item in sorted(inventory, key=lambda row: row["provider"].casefold()):
            provider = item["provider"]
            if provider.casefold() not in allowed:
                for capability in requested_capabilities:
                    if capability in item["capability_tools"]:
                        blocked.append(f"PROVIDER_NOT_AUTHORIZED:{provider}:{capability}")
                continue
            for capability in requested_capabilities:
                tool_name = item["capability_tools"].get(capability)
                if not tool_name:
                    continue
                if item["status"] != "CONNECTED":
                    blocked.append(f"PROVIDER_NOT_CONNECTED:{provider}:{capability}:{item['status']}")
                    continue
                if item["requires_paid_credit"] and not cost_consent:
                    blocked.append(f"PAID_CREDIT_CONSENT_REQUIRED:{provider}:{capability}")
                    continue
                covered.add(capability)
                calls.append({
                    "planned_call_id": f"PCALL-{secrets.token_hex(10)}",
                    "provider": provider,
                    "provider_class": item["provider_class"],
                    "requested_capability": capability,
                    "tool_name": tool_name,
                    "permissions": item["permissions"],
                    "requires_paid_credit": item["requires_paid_credit"],
                    "cost_authorized": (not item["requires_paid_credit"]) or cost_consent,
                })
        missing = sorted(set(requested_capabilities) - covered, key=str.casefold)
        for capability in missing:
            if not any(capability in item["capability_tools"] for item in inventory):
                blocked.append(f"NO_PROVIDER_TOOL_FOR_CAPABILITY:{capability}")
        status = "READY" if calls and not missing and not blocked else ("PARTIAL" if calls else "BLOCKED")
        plan_id = f"PPLAN-{secrets.token_hex(12)}"
        issued = utc_now()
        payload = {
            "plan_id": plan_id,
            "investigation_id": investigation_id,
            "account_id": state["start"]["account"]["account_id"],
            "provider_mode": policy["mode"],
            "requested_capabilities": requested_capabilities,
            "calls": calls,
            "missing_capabilities": missing,
            "blocked": list(dict.fromkeys(blocked)),
            "cost_consent": cost_consent,
            "inventory_sha256": digest(inventory),
            "issued_at": iso_utc(issued),
            "expires_at": iso_utc(issued + timedelta(hours=1)),
            "status": status,
        }
        self.store.append(investigation_id, "PROVIDER_PLAN_CREATED", payload)
        return {
            **payload,
            "external_execution_required": bool(calls),
            "runtime_invokes_other_plugins": False,
            "execution_boundary": "Codex must call each listed provider tool, then append the real result with append_provider_receipt.",
        }

    def _validate_provider_evidence(
        self,
        item: dict[str, Any],
        receipt: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        required_fields(item, EVIDENCE_REQUIRED, "provider evidence")
        evidence_id = nonempty(item["evidence_id"], "provider evidence.evidence_id")
        if evidence_id in state["evidence"]:
            raise ValidationError(f"duplicate evidence_id: {evidence_id}")
        account_id = state["start"]["account"]["account_id"]
        if item["owner_type"] != "ACCOUNT" or item["owner_id"] != account_id:
            raise ValidationError(f"{evidence_id}: provider evidence owner mismatch")
        if item["module_or_branch"] != receipt["target_module"]:
            raise ValidationError(f"{evidence_id}: provider evidence target module mismatch")
        if item["source_family"] != receipt["provider"] or str(item["source_type"]).upper() != receipt["provider_class"]:
            raise ValidationError(f"{evidence_id}: provider evidence source mismatch")
        for field in ("claim_key", "boundary"):
            nonempty(item[field], f"provider evidence.{field}")
        if parse_time(item["observed_at"], "provider evidence.observed_at") > parse_time(receipt["completed_at"], "receipt.completed_at") + timedelta(minutes=5):
            raise ValidationError(f"{evidence_id}: observed_at occurs after provider execution")
        evidence_hash = valid_hash(item["content_sha256"], "provider evidence.content_sha256")
        reference_type, url, locator = _validate_reference(
            item["reference_type"], item["url"], item["locator"], evidence_hash, f"{evidence_id}.reference"
        )
        if reference_type != "PROVIDER_RECEIPT":
            raise ValidationError(f"{evidence_id}: provider Evidence requires reference_type PROVIDER_RECEIPT")
        snapshot = nonempty(item["snapshot_locator"], "provider evidence.snapshot_locator")
        _valid_locator(snapshot, evidence_hash, "provider evidence.snapshot_locator")
        claim_type = nonempty(item["claim_type"], "provider evidence.claim_type").upper()
        freshness = nonempty(item["freshness"], "provider evidence.freshness").upper()
        evidence_grade = nonempty(item["evidence_grade"], "provider evidence.evidence_grade").upper()
        if claim_type not in EVIDENCE_CLAIM_TYPES:
            raise ValidationError(f"{evidence_id}: provider evidence claim_type invalid")
        if freshness not in EVIDENCE_FRESHNESS:
            raise ValidationError(f"{evidence_id}: provider evidence freshness invalid")
        if evidence_grade not in EVIDENCE_GRADES:
            raise ValidationError(f"{evidence_id}: provider evidence_grade invalid")
        commercial_gate_tags = item.get("commercial_gate_tags") or []
        if not isinstance(commercial_gate_tags, list) or not all(
            isinstance(tag, str) and tag.strip() for tag in commercial_gate_tags
        ):
            raise ValidationError(f"{evidence_id}: commercial_gate_tags must be a string array")
        commercial_gate_tags = [tag.strip().upper() for tag in commercial_gate_tags]
        if len(set(commercial_gate_tags)) != len(commercial_gate_tags):
            raise ValidationError(f"{evidence_id}: commercial_gate_tags contains duplicates")
        invalid_tags = sorted(set(commercial_gate_tags) - COMMERCIAL_GATE_TAGS)
        if invalid_tags:
            raise ValidationError(f"{evidence_id}: invalid commercial_gate_tags: {','.join(invalid_tags)}")
        _validate_commercial_tag_binding(
            commercial_gate_tags,
            item["module_or_branch"],
            claim_type,
            evidence_id,
        )
        return {
            **item,
            "reference_type": reference_type,
            "url": url,
            "locator": locator,
            "content_sha256": evidence_hash,
            "claim_type": claim_type,
            "freshness": freshness,
            "evidence_grade": evidence_grade,
            "commercial_gate_tags": commercial_gate_tags,
        }

    def _validate_provider_contact(
        self,
        item: dict[str, Any],
        receipt: dict[str, Any],
        evidence: dict[str, dict[str, Any]],
        account_id: str,
    ) -> dict[str, Any]:
        required_fields(item, PROVIDER_CONTACT_REQUIRED, "provider contact")
        contact_id = nonempty(item["contact_id"], "provider contact.contact_id")
        kind = str(item["kind"]).upper()
        value = nonempty(item["value"], "provider contact.value")
        owner = nonempty(item["owner_entity_id"], "provider contact.owner_entity_id")
        masked_detected = bool(MASKED_CONTACT_RE.search(value))
        if masked_detected and item["masked"] is not True:
            raise ValidationError(f"{contact_id}: masked contact was mislabeled")
        route_eligible = item["route_eligible"] is True
        for field in ("masked", "guessed", "provider_verified", "route_eligible", "channel_proof"):
            if not isinstance(item[field], bool):
                raise ValidationError(f"{contact_id}: {field} must be boolean")
        if route_eligible:
            if owner != account_id:
                raise ValidationError(f"{contact_id}: third-party provider contact cannot become Buyer Direct")
            if item["masked"] is True or item["guessed"] is True or item["provider_verified"] is not True:
                raise ValidationError(f"{contact_id}: masked, guessed, or unverified provider contact cannot become a Route")
            evidence_id = nonempty(item["evidence_id"], "provider contact.evidence_id")
            if evidence_id not in evidence:
                raise ValidationError(f"{contact_id}: route-eligible provider contact requires same-receipt Evidence")
            if kind == "EMAIL" and not EMAIL_RE.fullmatch(value):
                raise ValidationError(f"{contact_id}: invalid provider email")
            if kind == "PHONE" and not INTERNATIONAL_PHONE_RE.fullmatch(re.sub(r"[\s()-]", "", value)):
                raise ValidationError(f"{contact_id}: invalid provider phone")
            if kind in {"WHATSAPP", "ZALO"}:
                normalized = re.sub(r"[\s()-]", "", value)
                claim = str(evidence[evidence_id]["claim_key"]).casefold()
                if not INTERNATIONAL_PHONE_RE.fullmatch(normalized) or item["channel_proof"] is not True or kind.casefold() not in claim:
                    raise ValidationError(f"{contact_id}: phone cannot auto-promote to {kind}")
            if kind not in {"EMAIL", "PHONE", "WHATSAPP", "ZALO"}:
                raise ValidationError(f"{contact_id}: unsupported route-eligible provider contact kind")
        return {**item, "kind": kind, "value": value, "owner_entity_id": owner, "route_eligible": route_eligible}

    @unicode_safe_entrypoint
    def append_provider_receipt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        if state["start"]["provider_policy"]["mode"] == "PUBLIC_ONLY":
            raise ValidationError("PUBLIC_ONLY investigation cannot append provider receipts")
        receipt = require_object(args.get("receipt"), "receipt")
        required_fields(receipt, PROVIDER_RECEIPT_REQUIRED, "receipt")
        if receipt["investigation_id"] != investigation_id:
            raise ValidationError("receipt.investigation_id mismatch")
        provider_receipt_id = nonempty(receipt["provider_receipt_id"], "receipt.provider_receipt_id")
        if provider_receipt_id in state["provider_receipts"]:
            raise ValidationError(f"duplicate provider_receipt_id: {provider_receipt_id}")
        tool_call_id = nonempty(receipt["tool_call_id"], "receipt.tool_call_id")
        if tool_call_id in state["provider_tool_calls"]:
            raise ValidationError(f"duplicate provider tool_call_id: {tool_call_id}")
        account_id = state["start"]["account"]["account_id"]
        if receipt["account_id"] != account_id:
            raise ValidationError("provider receipt owner mismatch")
        provider = nonempty(receipt["provider"], "receipt.provider")
        if provider.casefold() not in {item.casefold() for item in state["start"]["provider_policy"]["allowed_providers"]}:
            raise ValidationError("provider was not explicitly authorized")
        provider_class = str(receipt["provider_class"]).upper()
        if provider_class not in PROVIDER_CLASSES:
            raise ValidationError("receipt.provider_class invalid")
        target_module = nonempty(receipt["target_module"], "receipt.target_module")
        if target_module not in REQUIRED_MODULES or target_module == "network_fission":
            raise ValidationError("receipt.target_module must be a non-network required module")
        if target_module not in PROVIDER_CLASS_MODULES[provider_class]:
            raise ValidationError("provider class cannot supply Evidence for receipt.target_module")
        plan_id = nonempty(receipt["plan_id"], "receipt.plan_id")
        plan = state["provider_plans"].get(plan_id)
        if plan is None:
            raise ValidationError("provider plan not found")
        if utc_now() > parse_time(plan["expires_at"], "provider plan.expires_at"):
            raise ValidationError("provider plan expired")
        planned_call_id = nonempty(receipt["planned_call_id"], "receipt.planned_call_id")
        if planned_call_id in state["provider_planned_calls"]:
            raise ValidationError("planned provider call already receipted")
        planned = next((item for item in plan["calls"] if item["planned_call_id"] == planned_call_id), None)
        if planned is None:
            raise ValidationError("planned provider call not found")
        requested_capability = nonempty(receipt["requested_capability"], "receipt.requested_capability")
        tool_name = nonempty(receipt["tool_name"], "receipt.tool_name")
        if (
            planned["provider"] != provider
            or planned["provider_class"] != provider_class
            or planned["requested_capability"] != requested_capability
            or planned["tool_name"] != tool_name
        ):
            raise ValidationError("provider receipt does not match the exact planned call")
        query = nonempty(receipt["query"], "receipt.query")
        requested_at = parse_time(receipt["requested_at"], "receipt.requested_at")
        completed_at = parse_time(receipt["completed_at"], "receipt.completed_at")
        if requested_at > completed_at or requested_at < parse_time(plan["issued_at"], "provider plan.issued_at") - timedelta(minutes=5):
            raise ValidationError("provider receipt timestamps are inconsistent")
        result = str(receipt["result"]).upper()
        status = str(receipt["status"]).upper()
        if result not in PROVIDER_RESULTS or status not in {"SUCCESS", "BLOCKED"}:
            raise ValidationError("provider receipt result/status invalid")
        if not isinstance(receipt["result_count"], int) or receipt["result_count"] < 0:
            raise ValidationError("provider receipt result_count must be a non-negative integer")
        evidence_ids = require_list(receipt["evidence_ids"], "receipt.evidence_ids")
        generated_ids = require_list(receipt["pivots_generated"], "receipt.pivots_generated")
        if len(evidence_ids) != len(set(str(item) for item in evidence_ids)):
            raise ValidationError("provider receipt evidence_ids contains duplicates")
        if len(generated_ids) != len(set(str(item) for item in generated_ids)):
            raise ValidationError("provider receipt pivots_generated contains duplicates")
        blocked_reason = str(receipt["blocked_reason"] or "").strip()
        if result == "POSITIVE":
            if status != "SUCCESS" or receipt["result_count"] < 1 or not evidence_ids:
                raise ValidationError("positive provider receipt requires successful results and Evidence")
            if blocked_reason:
                raise ValidationError("successful provider receipt cannot carry blocked_reason")
        elif result == "NEGATIVE":
            if status != "SUCCESS" or receipt["result_count"] != 0 or evidence_ids or blocked_reason:
                raise ValidationError("negative provider receipt must be successful, empty, and unblocked")
        else:
            if status != "BLOCKED" or receipt["result_count"] != 0 or evidence_ids or not blocked_reason:
                raise ValidationError("blocked provider receipt requires a concrete blocked_reason and no Evidence")
        receipt_hash = valid_hash(receipt["content_sha256"], "receipt.content_sha256")
        _valid_locator(receipt["raw_result_locator"], receipt_hash, "receipt.raw_result_locator")
        permissions = require_object(receipt["permissions"], "receipt.permissions")
        scopes = require_list(permissions.get("scopes") or [], "receipt.permissions.scopes")
        if not all(isinstance(value, str) and value.strip() for value in scopes):
            raise ValidationError("receipt.permissions.scopes: string array required")
        if not set(value.strip() for value in scopes) <= set(planned["permissions"]):
            raise ValidationError("provider receipt contains an unplanned permission scope")
        if result != "BLOCKED" and permissions.get("user_authorized") is not True:
            raise ValidationError("successful provider result requires user_authorized permission receipt")
        require_list(receipt["conflicts"], "receipt.conflicts")
        receipt_freshness = nonempty(receipt["freshness"], "receipt.freshness").upper()
        if receipt_freshness not in EVIDENCE_FRESHNESS:
            raise ValidationError("receipt.freshness invalid")
        nonempty(receipt["billing_or_credit_notice"], "receipt.billing_or_credit_notice")

        evidence_input = require_list(args.get("evidence") or [], "evidence")
        evidence_items: list[dict[str, Any]] = []
        for raw in evidence_input:
            evidence_items.append(self._validate_provider_evidence(require_object(raw, "evidence[]"), receipt, state))
        if set(evidence_ids) != {item["evidence_id"] for item in evidence_items}:
            raise ValidationError("provider receipt evidence_ids do not exactly match appended Evidence")
        evidence_by_id = {item["evidence_id"]: item for item in evidence_items}

        contacts_input = require_list(receipt["contacts_returned"], "receipt.contacts_returned")
        contacts = [
            self._validate_provider_contact(require_object(item, "contacts_returned[]"), receipt, evidence_by_id, account_id)
            for item in contacts_input
        ]
        companies = require_list(receipt["companies_returned"], "receipt.companies_returned")
        if not all(isinstance(item, dict) for item in companies):
            raise ValidationError("receipt.companies_returned: object array required")

        provider_origin = f"PROVIDER::{provider_receipt_id}"
        pivots_input = require_list(args.get("pivots") or [], "pivots")
        pivots_generated: list[dict[str, Any]] = []
        for raw in pivots_input:
            pivot = require_object(raw, "pivots[]")
            required_fields(pivot, PIVOT_REQUIRED, "provider pivot")
            pivot_id = nonempty(pivot["pivot_id"], "provider pivot.pivot_id")
            if pivot_id in state["pivots"]:
                raise ValidationError(f"duplicate pivot_id: {pivot_id}")
            if pivot["generated_by_attempt_id"] != provider_origin:
                raise ValidationError(f"{pivot_id}: provider Pivot origin mismatch")
            if parse_time(pivot["generated_at"], "provider pivot.generated_at") != completed_at:
                raise ValidationError(f"{pivot_id}: provider Pivot time mismatch")
            nonempty(pivot["pivot_type"], "provider pivot.pivot_type")
            nonempty(pivot["pivot_value"], "provider pivot.pivot_value")
            if pivot["status"] != "OPEN" or any(pivot[field] not in ("", None) for field in ("consumed_by_attempt_id", "consumed_at", "consumption_result")):
                raise ValidationError(f"{pivot_id}: new provider Pivot must be OPEN and unconsumed")
            pivots_generated.append(dict(pivot))
        if set(generated_ids) != {item["pivot_id"] for item in pivots_generated}:
            raise ValidationError("provider receipt pivots_generated do not exactly match appended Pivots")

        consumed_input = require_list(args.get("pivots_consumed") or [], "pivots_consumed")
        pivots_consumed: list[dict[str, Any]] = []
        for raw in consumed_input:
            consumed = require_object(raw, "pivots_consumed[]")
            pivot_id = nonempty(consumed.get("pivot_id"), "pivots_consumed.pivot_id")
            pivot = state["pivots"].get(pivot_id)
            if not pivot or pivot.get("status") != "OPEN":
                raise ValidationError(f"{pivot_id}: unknown or already-consumed Pivot")
            if pivot["generated_by_attempt_id"] == provider_origin:
                raise ValidationError(f"{pivot_id}: a provider receipt cannot consume its own Pivot")
            if completed_at <= parse_time(pivot["generated_at"], "pivot.generated_at"):
                raise ValidationError(f"{pivot_id}: provider Pivot consumption must be later than generation")
            if pivot["pivot_value"].casefold() not in query.casefold():
                raise ValidationError(f"{pivot_id}: provider Query does not contain Pivot value")
            pivots_consumed.append({
                "pivot_id": pivot_id,
                "consumed_by_attempt_id": provider_origin,
                "consumed_at": receipt["completed_at"],
                "consumption_result": nonempty(consumed.get("consumption_result"), "pivots_consumed.consumption_result"),
                "status": "CONSUMED",
            })

        normalized = {
            **receipt,
            "provider_class": provider_class,
            "target_module": target_module,
            "result": result,
            "status": status,
            "freshness": receipt_freshness,
            "content_sha256": receipt_hash,
            "contacts_returned": contacts,
            "companies_returned": companies,
        }
        self.store.append(investigation_id, "PROVIDER_RECEIPT_APPENDED", {
            "receipt": normalized,
            "evidence": evidence_items,
            "pivots_generated": pivots_generated,
            "pivots_consumed": pivots_consumed,
        })
        return {
            "accepted": True,
            "provider_receipt_id": provider_receipt_id,
            "provider": provider,
            "requested_capability": requested_capability,
            "result": result,
            "evidence_count": len(evidence_items),
            "contacts_returned": len(contacts),
            "route_eligible_contacts": sum(1 for item in contacts if item["route_eligible"]),
            "pivots_generated": len(pivots_generated),
            "pivots_consumed": len(pivots_consumed),
            "closes_public_source_families": False,
            "append_only": True,
        }

    def _section_proof(self, section: Any, peer_id: str, state: dict[str, Any], label: str) -> None:
        value = require_object(section, f"peer.{label}")
        if value.get("passed") is not True:
            raise ValidationError(f"peer.{label}: independent gate not passed")
        attempts = require_list(value.get("attempt_ids"), f"peer.{label}.attempt_ids")
        evidence = require_list(value.get("evidence_ids"), f"peer.{label}.evidence_ids")
        if not attempts:
            raise ValidationError(f"peer.{label}: independent Attempts required")
        if label != "contact_coverage" and not evidence:
            raise ValidationError(f"peer.{label}: independent Evidence required")
        for attempt_id in attempts:
            attempt = state["attempts"].get(attempt_id)
            if not attempt or attempt["owner_id"] != peer_id:
                raise ValidationError(f"peer.{label}: Attempt is absent or inherited")
            if label != "contact_coverage" and attempt["result"] != "POSITIVE":
                raise ValidationError(f"peer.{label}: positive independent proof required")
        for evidence_id in evidence:
            item = state["evidence"].get(evidence_id)
            if not item or item["owner_id"] != peer_id:
                raise ValidationError(f"peer.{label}: Evidence is absent or inherited from Anchor")
        if label == "contact_coverage":
            status, _ = self._coverage_status(state, peer_id, "contact_coverage")
            if status not in {"COMPLETE_POSITIVE", "COMPLETE_NEGATIVE_ENTITLED"}:
                raise ValidationError(f"peer.contact_coverage: full Source Profile is not closed ({status})")

    @unicode_safe_entrypoint
    def append_peer_receipt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        receipt_type = str(args.get("receipt_type") or "PEER_VALIDATION").upper()
        if receipt_type == "ANCHOR_EXPANSION":
            anchor_id = nonempty(args.get("anchor_id"), "anchor_id")
            if anchor_id not in state["anchor_queue"]:
                raise ValidationError("anchor_id is not in the active Anchor queue")
            if args.get("cycle_dedup_checked") is not True:
                raise ValidationError("Anchor expansion requires cycle dedup")
            discovered: set[str] = set()
            branch_status: dict[str, str] = {}
            for branch in NETWORK_BRANCHES:
                status, _ = self._coverage_status(state, anchor_id, branch, branch=True)
                branch_status[branch] = status
                if status not in {"COMPLETE_POSITIVE", "COMPLETE_NEGATIVE_ENTITLED"}:
                    raise ValidationError(f"anchor {anchor_id}: branch not closed: {branch}={status}")
                for attempt in state["attempts"].values():
                    if attempt["owner_id"] == anchor_id and attempt["module_or_branch"] == branch:
                        discovered.update(attempt.get("discovered_peer_ids") or [])
            missing_peers = discovered - set(state["peers"])
            if missing_peers:
                raise ValidationError("discovered Peer receipts missing: " + ",".join(sorted(missing_peers)))
            self.store.append(investigation_id, "ANCHOR_EXPANSION_CLOSED", {
                "anchor_id": anchor_id,
                "branch_status": branch_status,
                "cycle_dedup_checked": True,
                "discovered_peer_ids": sorted(discovered),
            })
            return {"accepted": True, "receipt_type": receipt_type, "anchor_id": anchor_id, "branch_status": branch_status}
        if receipt_type != "PEER_VALIDATION":
            raise ValidationError("receipt_type invalid")
        receipt = require_object(args.get("receipt"), "receipt")
        required_fields(receipt, {
            "peer_id", "canonical_key", "discovered_by_attempt_id", "branch", "inherited_anchor_facts",
            "canonical_dedup_checked", "entity", "product", "trade_business", "relationship",
            "company_profile", "contact_coverage", "promotion_decision", "promotion_reason",
        }, "receipt")
        peer_id = nonempty(receipt["peer_id"], "receipt.peer_id")
        if peer_id in state["peers"] or peer_id == state["start"]["account"]["account_id"]:
            raise ValidationError("duplicate or colliding Peer ID")
        nonempty(receipt["canonical_key"], "receipt.canonical_key")
        if receipt["inherited_anchor_facts"] is not False or receipt["canonical_dedup_checked"] is not True:
            raise ValidationError("Peer must be independently proven and canonically deduplicated")
        if any(item["canonical_key"].casefold() == receipt["canonical_key"].casefold() for item in state["peers"].values()):
            raise ValidationError("Peer canonical duplicate")
        branch = receipt["branch"]
        if branch not in NETWORK_BRANCHES:
            raise ValidationError("receipt.branch invalid")
        discovery = state["attempts"].get(receipt["discovered_by_attempt_id"])
        if not discovery or discovery["module_or_branch"] != branch or peer_id not in discovery.get("discovered_peer_ids", []):
            raise ValidationError("Peer discovery is not bound to the declared Branch Attempt")
        relationship = require_object(receipt["relationship"], "peer.relationship")
        if relationship.get("passed") is not True:
            raise ValidationError("peer.relationship: gate not passed")
        relationship_ids = require_list(relationship.get("evidence_ids"), "peer.relationship.evidence_ids")
        if not relationship_ids or not set(relationship_ids) <= set(discovery.get("relationship_evidence_ids", {}).get(peer_id, [])):
            raise ValidationError("Peer Relationship Evidence did not come from the discovery Branch Attempt")
        for label in ("entity", "product", "trade_business", "company_profile", "contact_coverage"):
            self._section_proof(receipt[label], peer_id, state, label)
        decision = str(receipt["promotion_decision"]).upper()
        if decision not in {"PROMOTE", "DO_NOT_PROMOTE"}:
            raise ValidationError("promotion_decision invalid; allowed: PROMOTE,DO_NOT_PROMOTE")
        nonempty(receipt["promotion_reason"], "receipt.promotion_reason")
        normalized = {**receipt, "promotion_decision": decision}
        if decision == "PROMOTE" and state["start"].get("schema") in {"cbi.investigation.v5.3", "cbi.investigation.v5.4"}:
            policy = state["start"].get("network_policy") or NETWORK_POLICY_DEFAULTS
            required_fields(receipt, {
                "target_fit_grade",
                "promotion_evidence_grade",
                "commercial_novelty",
                "canonical_status",
            }, "receipt promotion gate")
            target_fit = str(receipt["target_fit_grade"]).upper()
            evidence_grade = str(receipt["promotion_evidence_grade"]).upper()
            canonical_status = str(receipt["canonical_status"]).upper()
            if target_fit not in TARGET_FIT_RANK:
                raise ValidationError("receipt.target_fit_grade invalid; allowed: " + ",".join(TARGET_FIT_RANK))
            if evidence_grade not in PROMOTION_EVIDENCE_RANK:
                raise ValidationError(
                    "receipt.promotion_evidence_grade invalid; allowed: " + ",".join(PROMOTION_EVIDENCE_RANK)
                )
            if TARGET_FIT_RANK[target_fit] < TARGET_FIT_RANK[policy["minimum_target_fit"]]:
                raise ValidationError("Peer promotion rejected: target fit below network policy")
            if PROMOTION_EVIDENCE_RANK[evidence_grade] < PROMOTION_EVIDENCE_RANK[policy["minimum_evidence_grade"]]:
                raise ValidationError("Peer promotion rejected: Evidence grade below network policy")
            if policy["require_commercial_novelty"] and receipt["commercial_novelty"] is not True:
                raise ValidationError("Peer promotion rejected: commercial_novelty must be true")
            if policy["require_canonical_new"] and canonical_status != "NEW":
                raise ValidationError("Peer promotion rejected: canonical_status must be NEW")
            parent_anchor_id = discovery["owner_id"]
            if parent_anchor_id not in state["anchor_depths"]:
                raise ValidationError("Peer promotion rejected: discovery owner is not an active Anchor")
            anchor_depth = int(state["anchor_depths"][parent_anchor_id]) + 1
            promoted_count = sum(
                item.get("promotion_decision") == "PROMOTE"
                for item in state["peers"].values()
            )
            normalized.update({
                "target_fit_grade": target_fit,
                "promotion_evidence_grade": evidence_grade,
                "commercial_novelty": True,
                "canonical_status": canonical_status,
                "parent_anchor_id": parent_anchor_id,
                "anchor_depth": anchor_depth,
                "promotion_gate": "PASSED",
                "promotion_sequence": promoted_count + 1,
                "network_closure_strategy": "QUEUE_PIVOT_SATURATION",
                "fixed_depth_or_anchor_cap_applied": False,
            })
        self.store.append(investigation_id, "PEER_RECEIPT_APPENDED", {"receipt": normalized})
        return {
            "accepted": True,
            "receipt_type": receipt_type,
            "peer_id": peer_id,
            "promotion_decision": decision,
            "promotion_gate": normalized.get("promotion_gate", "NOT_REQUIRED"),
            "anchor_depth": normalized.get("anchor_depth"),
            "promotion_sequence": normalized.get("promotion_sequence"),
            "fixed_depth_or_anchor_cap_applied": normalized.get("fixed_depth_or_anchor_cap_applied", False),
            "independent": True,
        }

    def _coverage_status(self, state: dict[str, Any], owner_id: str, module: str, *, branch: bool = False) -> tuple[str, dict[str, Any]]:
        required = self._required_families(state, owner_id, module)
        attempts = [item for item in state["attempts"].values() if item["owner_id"] == owner_id and item["module_or_branch"] == module]
        by_family: dict[str, list[dict[str, Any]]] = {}
        for attempt in attempts:
            by_family.setdefault(attempt["source_family"], []).append(attempt)
        missing = sorted(required - set(by_family))
        latest_results = {family: str(rows[-1]["result"]).upper() for family, rows in by_family.items()}
        blocked = sorted(family for family, result in latest_results.items() if result == "BLOCKED")
        strict_negative = state["start"].get("schema") in {"cbi.investigation.v5.3", "cbi.investigation.v5.4"}
        terminal_results = {
            "POSITIVE",
            "NEGATIVE_EXHAUSTED",
            "NOT_APPLICABLE",
            "NOT_APPLICABLE_JUSTIFIED",
        } if strict_negative else {"POSITIVE", "NEGATIVE", "NEGATIVE_EXHAUSTED", "NOT_APPLICABLE", "NOT_APPLICABLE_JUSTIFIED"}
        insufficient_negative = sorted(
            family
            for family, result in latest_results.items()
            if result not in terminal_results and result != "BLOCKED"
        )
        open_pivots = sorted(
            pivot_id
            for pivot_id, pivot in state["pivots"].items()
            if pivot["status"] == "OPEN"
            and pivot.get("generated_by_attempt_id") in state["attempts"]
            and state["attempts"][pivot["generated_by_attempt_id"]]["owner_id"] == owner_id
            and state["attempts"][pivot["generated_by_attempt_id"]]["module_or_branch"] == module
        )
        positive = any(row["result"] == "POSITIVE" for rows in by_family.values() for row in rows)
        if blocked:
            status = "INCOMPLETE_BLOCKED"
        elif missing:
            status = "PENDING"
        elif insufficient_negative:
            status = "PENDING"
        elif open_pivots:
            status = "INCOMPLETE_PIVOTS_REMAIN"
        else:
            status = "COMPLETE_POSITIVE" if positive else "COMPLETE_NEGATIVE_ENTITLED"
        return status, {
            "required": sorted(required),
            "attempted": sorted(by_family),
            "family_results": latest_results,
            "missing": missing,
            "blocked": blocked,
            "negative_not_exhausted": insufficient_negative,
            "open_pivots": open_pivots,
            "positive": positive,
            "branch": branch,
        }

    @staticmethod
    def _latest_family_result(
        state: dict[str, Any],
        owner_id: str,
        module: str,
        family: str,
    ) -> str:
        rows = [
            attempt
            for attempt in state["attempts"].values()
            if attempt["owner_id"] == owner_id
            and attempt["module_or_branch"] == module
            and attempt["source_family"] == family
        ]
        return str(rows[-1]["result"]).upper() if rows else "PENDING"

    @unicode_safe_entrypoint
    def append_crm_writeback_receipt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Append proof of an external Artifact Tool atomic workbook commit.

        The Runtime validates the actual post-commit workbook and audit artifact;
        it does not impersonate the Artifact Tool or mutate Excel by itself.
        """

        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        raw = require_object(args.get("receipt"), "receipt")
        required_fields(raw, CRM_WRITEBACK_REQUIRED, "receipt")
        if raw["investigation_id"] != investigation_id:
            raise ValidationError("receipt.investigation_id mismatch")
        account_id = state["start"]["account"]["account_id"]
        if raw["account_id"] != account_id:
            raise ValidationError("receipt.account_id mismatch")
        writeback_id = nonempty(raw["writeback_id"], "receipt.writeback_id")
        transaction_id = nonempty(raw["transaction_id"], "receipt.transaction_id")
        if writeback_id in state["crm_writebacks"]:
            raise ValidationError(f"duplicate writeback_id: {writeback_id}")
        if transaction_id in state["crm_transactions"]:
            raise ValidationError(f"duplicate CRM transaction_id: {transaction_id}")
        writer = nonempty(raw["writer"], "receipt.writer").upper()
        if writer != "ARTIFACT_TOOL":
            raise ValidationError("receipt.writer must be ARTIFACT_TOOL")

        configured_path = str(state["start"].get("crm_path") or "").strip()
        if not configured_path:
            raise ValidationError("investigation.crm_path is empty; unique main CRM target was not declared")
        target_path = Path(nonempty(raw["target_workbook_path"], "receipt.target_workbook_path"))
        if not target_path.is_absolute():
            raise ValidationError("receipt.target_workbook_path must be absolute")
        configured_resolved = Path(configured_path).resolve()
        target_resolved = target_path.resolve()
        if os.path.normcase(str(configured_resolved)) != os.path.normcase(str(target_resolved)):
            raise ValidationError("receipt target is not the investigation's unique main CRM workbook")
        _validate_xlsx_container(target_resolved, "receipt.target_workbook_path")

        before_hash = valid_hash(raw["workbook_sha256_before"], "receipt.workbook_sha256_before")
        after_hash = valid_hash(raw["workbook_sha256_after"], "receipt.workbook_sha256_after")
        actual_after_hash = hashlib.sha256(target_resolved.read_bytes()).hexdigest()
        if after_hash != actual_after_hash:
            raise ValidationError("receipt.workbook_sha256_after does not match the actual committed workbook")
        status = nonempty(raw["status"], "receipt.status").upper()
        if status not in {"COMMITTED", "NO_CHANGE_VERIFIED"}:
            raise ValidationError("receipt.status must be COMMITTED or NO_CHANGE_VERIFIED")

        for field in (
            "atomic_commit",
            "sparse_patch",
            "history_guard_passed",
            "post_commit_reimport_verified",
        ):
            if raw[field] is not True:
                raise ValidationError(f"receipt.{field} must be true")
        if not isinstance(raw["unintended_diff_count"], int) or raw["unintended_diff_count"] != 0:
            raise ValidationError("receipt.unintended_diff_count must be integer 0")
        committed_at = parse_time(raw["committed_at"], "receipt.committed_at")

        touched_sheets = require_list(raw["touched_sheets"], "receipt.touched_sheets")
        if not all(isinstance(item, str) and item.strip() for item in touched_sheets):
            raise ValidationError("receipt.touched_sheets must contain non-empty strings")
        touched_sheets = list(dict.fromkeys(item.strip() for item in touched_sheets))
        row_assertions = require_list(raw["row_assertions"], "receipt.row_assertions")
        cell_assertions = require_list(raw["cell_assertions"], "receipt.cell_assertions")
        previous_current_diff = require_list(raw["previous_current_diff"], "receipt.previous_current_diff")
        for field, rows in (
            ("row_assertions", row_assertions),
            ("cell_assertions", cell_assertions),
            ("previous_current_diff", previous_current_diff),
        ):
            if not all(isinstance(item, dict) and item for item in rows):
                raise ValidationError(f"receipt.{field} must contain non-empty objects")
        for index, diff_row in enumerate(previous_current_diff):
            required_fields(diff_row, {"sheet", "record_key", "column", "previous", "current"}, f"receipt.previous_current_diff[{index}]")
            for field in ("sheet", "record_key", "column"):
                nonempty(diff_row[field], f"receipt.previous_current_diff[{index}].{field}")
            if diff_row["previous"] == diff_row["current"]:
                raise ValidationError(f"receipt.previous_current_diff[{index}] is not an actual change")

        if status == "COMMITTED":
            if before_hash == after_hash:
                raise ValidationError("COMMITTED receipt requires a changed workbook hash")
            if not touched_sheets or not row_assertions or not cell_assertions or not previous_current_diff:
                raise ValidationError("COMMITTED receipt requires touched sheets, row/cell assertions, and semantic diff")
        else:
            if before_hash != after_hash:
                raise ValidationError("NO_CHANGE_VERIFIED requires identical before/after workbook hashes")
            if touched_sheets or previous_current_diff:
                raise ValidationError("NO_CHANGE_VERIFIED cannot declare touched sheets or semantic changes")

        audit_hash = valid_hash(raw["audit_artifact_sha256"], "receipt.audit_artifact_sha256")
        audit_locator = _valid_locator(raw["audit_artifact_locator"], audit_hash, "receipt.audit_artifact_locator")
        normalized = {
            **raw,
            "writeback_id": writeback_id,
            "transaction_id": transaction_id,
            "writer": writer,
            "target_workbook_path": str(target_resolved),
            "workbook_sha256_before": before_hash,
            "workbook_sha256_after": after_hash,
            "committed_at": iso_utc(committed_at),
            "status": status,
            "touched_sheets": touched_sheets,
            "audit_artifact_locator": audit_locator,
            "audit_artifact_sha256": audit_hash,
            "schema": "cbi.crm-writeback.v5.4",
        }
        normalized["receipt_sha256"] = digest(normalized)
        self.store.append(investigation_id, "CRM_WRITEBACK_RECEIPT_APPENDED", {"receipt": normalized})
        return {
            "accepted": True,
            "writeback_id": writeback_id,
            "transaction_id": transaction_id,
            "status": status,
            "crm_sync_complete": True,
            "target_workbook_path": str(target_resolved),
            "workbook_sha256_after": after_hash,
            "receipt_sha256": normalized["receipt_sha256"],
            "append_only": True,
            "runtime_mutated_workbook": False,
            "validated_external_writer": "ARTIFACT_TOOL",
        }

    @staticmethod
    def _material_conflict(value: Any) -> bool:
        if value in (None, False, "", 0):
            return False
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return str(value).strip().casefold() not in {"", "none", "no", "false", "resolved"}

    @staticmethod
    def _current_information_records(state: dict[str, Any]) -> list[dict[str, Any]]:
        records = list(state["information_records"].values())
        existing_ids = set(state["information_records"])
        superseded_ids = {
            information_id
            for record in records
            for information_id in record.get("supersedes_information_ids", [])
            if information_id in existing_ids
        }
        return [record for record in records if record["information_id"] not in superseded_ids]

    @staticmethod
    def _commercial_evidence_view(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidence_id": item["evidence_id"],
            "owner_id": item["owner_id"],
            "claim_key": item["claim_key"],
            "claim_type": item["claim_type"],
            "module_or_branch": item["module_or_branch"],
            "source_type": item["source_type"],
            "source_family": item["source_family"],
            "reference_type": item["reference_type"],
            "url": item["url"],
            "locator": item["locator"],
            "observed_at": item["observed_at"],
            "freshness": item["freshness"],
            "evidence_grade": item["evidence_grade"],
            "boundary": item["boundary"],
            "conflict": item["conflict"],
        }

    def _commercial_readiness(self, state: dict[str, Any]) -> dict[str, Any]:
        """Evaluate evidence-to-customer-to-development readiness without changing history.

        This deliberately does not assign a sales grade.  It only proves whether
        the evidence floor for entering A/A+ has been met and caps the permitted
        grade at B+ while any required commercial fact is missing or conflicted.
        """

        account_id = state["start"]["account"]["account_id"]
        current_records = self._current_information_records(state)
        account_evidence = [
            item for item in state["evidence"].values()
            if item.get("owner_id") == account_id
        ]
        gates: list[dict[str, Any]] = []

        for gate_name in COMMERCIAL_GATE_ORDER[:-1]:
            tagged = [
                item for item in account_evidence
                if gate_name in (item.get("commercial_gate_tags") or [])
            ]
            conflict_evidence = [item for item in tagged if self._material_conflict(item.get("conflict"))]
            valid: list[dict[str, Any]] = []
            rejection_reasons: set[str] = set()
            for item in tagged:
                if self._material_conflict(item.get("conflict")):
                    rejection_reasons.add("MATERIAL_EVIDENCE_CONFLICT")
                    continue
                if item.get("claim_type") not in COMMERCIAL_FACTUAL_CLAIM_TYPES:
                    rejection_reasons.add("NON_FACTUAL_CLAIM_TYPE")
                    continue
                if item.get("evidence_grade") not in COMMERCIAL_ACCEPTABLE_EVIDENCE_GRADES:
                    rejection_reasons.add("EVIDENCE_GRADE_BELOW_B1")
                    continue
                if gate_name in COMMERCIAL_CURRENT_GATES and item.get("freshness") not in {"CURRENT", "RECENT"}:
                    rejection_reasons.add("CURRENT_OR_RECENT_EVIDENCE_REQUIRED")
                    continue
                if gate_name in COMMERCIAL_PUBLIC_REFERENCE_GATES and item.get("reference_type") != "PUBLIC_URL":
                    rejection_reasons.add("CONCRETE_PUBLIC_URL_EVIDENCE_REQUIRED")
                    continue
                valid.append(item)

            valid_ids = {item["evidence_id"] for item in valid}
            relevant_records = [
                record for record in current_records
                if valid_ids.intersection(record.get("evidence_ids") or [])
            ]
            record_conflicts = [
                record for record in relevant_records
                if record.get("information_type") == "CONFLICT"
                or bool(record.get("conflicts_with_information_ids"))
            ]
            supporting_records: list[dict[str, Any]] = []

            if gate_name == "OFFICIAL_CONTACT":
                official_sources = {"OFFICIAL", "OFFICIAL_CONTACT", "GOVERNMENT", "REGISTRY", "MAPS"}
                supporting_records = [
                    record for record in relevant_records
                    if record.get("information_type") in {"CONTACT", "ROUTE"}
                    and record.get("subject_owner_id") == account_id
                    and record.get("temporal_status") == "CURRENT"
                    and record.get("source_reference_type") == "PUBLIC_URL"
                    and record.get("source_type") in official_sources
                    and require_object(record.get("value"), "record.value").get("verified") is True
                ]
                if not supporting_records:
                    rejection_reasons.add("CURRENT_VERIFIED_ACCOUNT_OWNED_OFFICIAL_CONTACT_RECORD_REQUIRED")
            elif gate_name == "CONTACT_SOURCE":
                supporting_records = [
                    record for record in relevant_records
                    if record.get("information_type") in {"CONTACT", "ROUTE"}
                    and record.get("temporal_status") == "CURRENT"
                    and record.get("source_reference_type") == "PUBLIC_URL"
                    and bool(record.get("source_url"))
                ]
                if not supporting_records:
                    rejection_reasons.add("CURRENT_CONTACT_RECORD_BOUND_TO_CONCRETE_SOURCE_REQUIRED")
            elif gate_name == "DECISION_CHAIN":
                supporting_records = [
                    record for record in relevant_records
                    if record.get("subject_type") == "PERSON"
                    and record.get("temporal_status") == "CURRENT"
                    and record.get("source_reference_type") == "PUBLIC_URL"
                    and any(
                        str(require_object(record.get("value"), "record.value").get(field) or "").strip()
                        for field in ("role", "title", "position")
                    )
                ]
                if not supporting_records:
                    rejection_reasons.add("CURRENT_NAMED_DECISION_CHAIN_RECORD_WITH_ROLE_REQUIRED")
            elif gate_name == "DEVELOPMENT_ROUTE":
                supporting_records = [
                    record for record in relevant_records
                    if record.get("information_type") in {"CONTACT", "ROUTE"}
                    and record.get("temporal_status") == "CURRENT"
                    and record.get("outreach_eligible_effective") is True
                ]
                if not supporting_records:
                    rejection_reasons.add("CURRENT_VERIFIED_BUYER_DIRECT_DEVELOPMENT_ROUTE_REQUIRED")

            needs_record = gate_name in {"OFFICIAL_CONTACT", "CONTACT_SOURCE", "DECISION_CHAIN", "DEVELOPMENT_ROUTE"}
            if conflict_evidence or record_conflicts:
                status = "CONFLICT"
            elif valid and (not needs_record or supporting_records):
                status = "PASS"
            else:
                status = "MISSING"
            if not tagged:
                rejection_reasons.add("NO_INTENTIONALLY_TAGGED_COMMERCIAL_EVIDENCE")

            gates.append({
                "gate": gate_name,
                "status": status,
                "evidence": [self._commercial_evidence_view(item) for item in valid],
                "conflicting_evidence": [self._commercial_evidence_view(item) for item in conflict_evidence],
                "supporting_information_ids": [record["information_id"] for record in supporting_records],
                "rejection_reasons": sorted(rejection_reasons),
            })

        latest_crm_receipt = list(state["crm_writebacks"].values())[-1] if state["crm_writebacks"] else None
        crm_pass = bool(
            latest_crm_receipt
            and latest_crm_receipt.get("status") in {"COMMITTED", "NO_CHANGE_VERIFIED"}
            and latest_crm_receipt.get("post_commit_reimport_verified") is True
        )
        gates.append({
            "gate": "CRM_STATUS",
            "status": "PASS" if crm_pass else "MISSING",
            "writeback_id": latest_crm_receipt.get("writeback_id") if latest_crm_receipt else None,
            "transaction_id": latest_crm_receipt.get("transaction_id") if latest_crm_receipt else None,
            "target_workbook_path": latest_crm_receipt.get("target_workbook_path") if latest_crm_receipt else None,
            "workbook_sha256_after": latest_crm_receipt.get("workbook_sha256_after") if latest_crm_receipt else None,
            "rejection_reasons": [] if crm_pass else ["STRUCTURED_ATOMIC_CRM_WRITEBACK_RECEIPT_REQUIRED"],
        })

        status_counts = {
            status: sum(gate["status"] == status for gate in gates)
            for status in ("PASS", "MISSING", "CONFLICT")
        }
        ready = status_counts["PASS"] == len(COMMERCIAL_GATE_ORDER)
        return {
            "schema": "cbi.commercial-readiness.v5.4",
            "runtime_version": RUNTIME_VERSION,
            "investigation_id": state["start"]["investigation_id"],
            "account_id": account_id,
            "commercial_result_ready": ready,
            "may_enter_a_or_above": ready,
            "maximum_allowed_grade": "A+" if ready else "B+",
            "runtime_assigned_sales_grade": None,
            "gates": gates,
            "status_counts": status_counts,
            "missing_gates": [gate["gate"] for gate in gates if gate["status"] == "MISSING"],
            "conflicted_gates": [gate["gate"] for gate in gates if gate["status"] == "CONFLICT"],
            "policy": "PRESERVE_ALL_INFORMATION; A_OR_ABOVE_REQUIRES_10_OF_10_COMMERCIAL_GATES; ANY_GAP_CAPS_AT_B+",
            "execution_boundary": "This evaluates appended Evidence, current Information and CRM receipts; it does not perform web search, assign a final sales grade or guarantee conversion.",
        }

    @unicode_safe_entrypoint
    def evaluate_commercial_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        return self._commercial_readiness(self._state(investigation_id))

    def _state_dimensions(
        self,
        state: dict[str, Any],
        modules: dict[str, Any],
        network: dict[str, Any],
        *,
        missing_peer_receipts: list[str],
        open_pivots: list[str],
    ) -> dict[str, Any]:
        account_id = state["start"]["account"]["account_id"]
        complete_states = {"COMPLETE_POSITIVE", "COMPLETE_NEGATIVE_ENTITLED"}
        research_complete = all(modules[module]["status"] in complete_states for module in RESEARCH_CORE_MODULES)
        network_complete = (
            not state["anchor_queue"]
            and not missing_peer_receipts
            and not open_pivots
            and all(
                branch_detail["status"] in complete_states
                for anchor in network.values()
                for branch_detail in anchor.values()
            )
        )
        legacy_crm_result = self._latest_family_result(
            state,
            account_id,
            "sales_crm_outreach_readiness",
            "crm_writeback_gate",
        )
        latest_crm_receipt = list(state["crm_writebacks"].values())[-1] if state["crm_writebacks"] else None
        crm_sync_complete = bool(
            latest_crm_receipt
            and latest_crm_receipt.get("status") in {"COMMITTED", "NO_CHANGE_VERIFIED"}
            and latest_crm_receipt.get("post_commit_reimport_verified") is True
        )
        outreach_results = {
            family: self._latest_family_result(
                state,
                account_id,
                "sales_crm_outreach_readiness",
                family,
            )
            for family in ("product_authority", "history_digest", "route_ownership")
        }
        outreach_prerequisites_complete = all(result == "POSITIVE" for result in outreach_results.values())
        commercial = self._commercial_readiness(state)
        outreach_ready = (
            research_complete
            and network_complete
            and crm_sync_complete
            and outreach_prerequisites_complete
            and not state["start"].get("opt_out")
        )
        if not research_complete:
            workflow_state = "RESEARCH_INCOMPLETE"
        elif not network_complete:
            workflow_state = "RESEARCH_COMPLETE_NETWORK_PENDING"
        elif not crm_sync_complete:
            workflow_state = "RESEARCH_COMPLETE_CRM_SYNC_PENDING"
        elif not outreach_ready:
            workflow_state = "RESEARCH_COMPLETE_OUTREACH_BLOCKED"
        else:
            workflow_state = "OUTREACH_READY"
        return {
            "research_complete": research_complete,
            "network_complete": network_complete,
            "crm_sync_complete": crm_sync_complete,
            "commercial_result_ready": commercial["commercial_result_ready"],
            "may_enter_a_or_above": commercial["may_enter_a_or_above"],
            "maximum_allowed_grade": commercial["maximum_allowed_grade"],
            "outreach_prerequisites_complete": outreach_prerequisites_complete,
            "outreach_ready": outreach_ready,
            "workflow_state": workflow_state,
            "crm_writeback_gate_result": "STRUCTURED_RECEIPT_VERIFIED" if crm_sync_complete else "PENDING",
            "crm_writeback_receipt_id": latest_crm_receipt.get("writeback_id") if latest_crm_receipt else None,
            "legacy_crm_source_attempt_result": legacy_crm_result,
            "legacy_crm_source_attempt_is_atomic_proof": False,
            "outreach_prerequisite_results": outreach_results,
        }

    @unicode_safe_entrypoint
    def evaluate_investigation_closure(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        account_id = state["start"]["account"]["account_id"]
        modules: dict[str, Any] = {}
        blockers: list[str] = []
        operational_blockers: list[str] = []
        provider_policy = state["start"]["provider_policy"]
        provider_receipts = list(state["provider_receipts"].values())
        successful_provider_capabilities = sorted({
            item["requested_capability"]
            for item in provider_receipts
            if item["status"] == "SUCCESS" and item["result"] in {"POSITIVE", "NEGATIVE"}
        }, key=str.casefold)
        blocked_provider_capabilities = sorted({
            item["requested_capability"]
            for item in provider_receipts
            if item["status"] == "BLOCKED" or item["result"] == "BLOCKED"
        }, key=str.casefold)
        required_provider_capabilities = list(provider_policy["required_capabilities"])
        missing_provider_capabilities = sorted(
            set(required_provider_capabilities) - set(successful_provider_capabilities),
            key=str.casefold,
        )
        provider_lanes = {
            "mode": provider_policy["mode"],
            "allowed_providers": provider_policy["allowed_providers"],
            "required_capabilities": required_provider_capabilities,
            "successful_capabilities": successful_provider_capabilities,
            "blocked_capabilities": blocked_provider_capabilities,
            "missing_capabilities": missing_provider_capabilities,
            "plan_count": len(state["provider_plans"]),
            "receipt_count": len(provider_receipts),
            "public_source_replacement_allowed": False,
            "status": "NOT_REQUESTED" if provider_policy["mode"] == "PUBLIC_ONLY" else "OPTIONAL",
        }
        if provider_policy["mode"] == "CONNECTED_PROVIDERS_REQUIRED":
            if missing_provider_capabilities:
                provider_lanes["status"] = "INCOMPLETE_BLOCKED" if set(missing_provider_capabilities) & set(blocked_provider_capabilities) else "PENDING"
                for capability in missing_provider_capabilities:
                    if capability in blocked_provider_capabilities:
                        blockers.append(f"PROVIDER_CAPABILITY:{capability}:INCOMPLETE_BLOCKED")
                    else:
                        blockers.append(f"PROVIDER_CAPABILITY:{capability}:PENDING")
            else:
                provider_lanes["status"] = "COMPLETE"
        if state["start"]["mode"] != "EXHAUSTIVE":
            blockers.append("FAST_SCAN_CANNOT_SIGN_RESEARCH_COMPLETE")
        for module in REQUIRED_MODULES:
            if module == "network_fission":
                if state["anchor_queue"]:
                    status = "INCOMPLETE_PIVOTS_REMAIN"
                    detail = {"anchor_queue": list(state["anchor_queue"]), "missing": [], "blocked": [], "open_pivots": []}
                else:
                    status = "COMPLETE_POSITIVE" if state["peers"] else "COMPLETE_NEGATIVE_ENTITLED"
                    detail = {"anchor_queue": [], "closed_anchors": sorted(state["anchor_closed"]), "peer_count": len(state["peers"])}
            else:
                status, detail = self._coverage_status(state, account_id, module)
            modules[module] = {"status": status, **detail}
            if status not in {"COMPLETE_POSITIVE", "COMPLETE_NEGATIVE_ENTITLED"}:
                target = operational_blockers if module == "sales_crm_outreach_readiness" else blockers
                target.append(f"MODULE:{module}:{status}")
        network: dict[str, Any] = {}
        for anchor_id in sorted(state["anchor_closed"] | set(state["anchor_queue"])):
            network[anchor_id] = {}
            for branch in NETWORK_BRANCHES:
                status, detail = self._coverage_status(state, anchor_id, branch, branch=True)
                network[anchor_id][branch] = {"status": status, **detail}
                if status not in {"COMPLETE_POSITIVE", "COMPLETE_NEGATIVE_ENTITLED"}:
                    blockers.append(f"BRANCH:{anchor_id}:{branch}:{status}")
        discovered = set()
        for attempt in state["attempts"].values():
            discovered.update(attempt.get("discovered_peer_ids") or [])
        missing_peer_receipts = sorted(discovered - set(state["peers"])
        )
        if missing_peer_receipts:
            blockers.append("MISSING_PEER_RECEIPTS:" + ",".join(missing_peer_receipts))
        promoted = sorted(peer_id for peer_id, receipt in state["peers"].items() if receipt["promotion_decision"] == "PROMOTE")
        missing_promoted_expansion = sorted(set(promoted) - state["anchor_closed"])
        if missing_promoted_expansion:
            blockers.append("PROMOTED_PEER_NOT_REEXPANDED:" + ",".join(missing_promoted_expansion))
        open_pivots = sorted(pivot_id for pivot_id, pivot in state["pivots"].items() if pivot["status"] == "OPEN")
        if open_pivots:
            blockers.append("OPEN_PIVOTS:" + ",".join(open_pivots))
        if state["manual_visual_queue"]:
            blockers.append("MANUAL_VISUAL_QUEUE:" + ",".join(sorted(state["manual_visual_queue"])))
        if state["anchor_queue"]:
            blockers.append("ANCHOR_QUEUE:" + ",".join(state["anchor_queue"]))
        dimensions = self._state_dimensions(
            state,
            modules,
            network,
            missing_peer_receipts=missing_peer_receipts,
            open_pivots=open_pivots,
        )
        if not dimensions["crm_sync_complete"]:
            operational_blockers.append("CRM_SYNC_INCOMPLETE")
        if not dimensions["outreach_prerequisites_complete"]:
            operational_blockers.append("OUTREACH_PREREQUISITES_INCOMPLETE")
        if state["start"].get("opt_out"):
            operational_blockers.append("ACCOUNT_OPTED_OUT")
        blockers = list(dict.fromkeys(blockers))
        operational_blockers = list(dict.fromkeys(operational_blockers))
        if blockers:
            if any("INCOMPLETE_BLOCKED" in item for item in blockers):
                overall = "INCOMPLETE_BLOCKED"
            elif open_pivots or state["anchor_queue"] or missing_promoted_expansion:
                overall = "INCOMPLETE_PIVOTS_REMAIN"
            elif state["start"]["mode"] == "FAST_SCAN":
                overall = "PAUSED_RESOURCE_LIMIT"
            else:
                overall = "PENDING"
            return {
                "investigation_id": investigation_id,
                "closed": False,
                "research_complete": dimensions["research_complete"],
                "network_complete": dimensions["network_complete"],
                "crm_sync_complete": dimensions["crm_sync_complete"],
                "outreach_ready": dimensions["outreach_ready"],
                "state_dimensions": dimensions,
                "status": overall,
                "modules": modules,
                "network": network,
                "open_pivots": open_pivots,
                "anchor_queue": state["anchor_queue"],
                "missing_peer_receipts": missing_peer_receipts,
                "manual_visual_queue": sorted(state["manual_visual_queue"]),
                "provider_lanes": provider_lanes,
                "blockers": blockers,
                "operational_blockers": operational_blockers,
                "closure_id": None,
            }
        basis_hash = state["events"][-1]["event_hash"]
        prior_for_basis = next(
            (
                item
                for item in state["closures"].values()
                if not item.get("used")
                and (
                    item.get("basis_hash") == basis_hash
                    or (
                        state["events"][-1]["event_type"] == "CLOSURE_ISSUED"
                        and state["events"][-1]["payload"].get("closure_id") == item.get("closure_id")
                    )
                )
            ),
            None,
        )
        if prior_for_basis:
            return {
                "investigation_id": investigation_id,
                "closed": True,
                "research_complete": dimensions["research_complete"],
                "network_complete": dimensions["network_complete"],
                "crm_sync_complete": dimensions["crm_sync_complete"],
                "outreach_ready": dimensions["outreach_ready"],
                "state_dimensions": dimensions,
                "status": prior_for_basis["status"],
                "modules": modules,
                "network": network,
                "open_pivots": [],
                "anchor_queue": [],
                "blockers": [],
                "provider_lanes": provider_lanes,
                "closure_id": prior_for_basis["closure_id"],
                "closure_expires_at": prior_for_basis["expires_at"],
                "operational_blockers": operational_blockers,
                "reused_evaluation_receipt": True,
            }
        closure_id = f"CLOS-{secrets.token_hex(16)}"
        positive = any(modules[module]["status"] == "COMPLETE_POSITIVE" for module in RESEARCH_CORE_MODULES) or any(
            branch_detail["status"] == "COMPLETE_POSITIVE"
            for anchor in network.values()
            for branch_detail in anchor.values()
        )
        status = "COMPLETE_POSITIVE" if positive else "COMPLETE_NEGATIVE_ENTITLED"
        issued = utc_now()
        payload = {
            "closure_id": closure_id,
            "investigation_id": investigation_id,
            "account_id": account_id,
            "status": status,
            "issued_at": iso_utc(issued),
            "expires_at": iso_utc(issued + timedelta(minutes=30)),
            "basis_hash": basis_hash,
            "modules_sha256": digest(modules),
            "network_sha256": digest(network),
            "provider_lanes_sha256": digest(provider_lanes),
            "state_dimensions": dimensions,
            "operational_blockers": operational_blockers,
            "used": False,
        }
        self.store.append(investigation_id, "CLOSURE_ISSUED", payload)
        return {
            "investigation_id": investigation_id,
            "closed": True,
            "closed_scope": "RESEARCH_AND_NETWORK",
            "research_complete": dimensions["research_complete"],
            "network_complete": dimensions["network_complete"],
            "crm_sync_complete": dimensions["crm_sync_complete"],
            "outreach_ready": dimensions["outreach_ready"],
            "state_dimensions": dimensions,
            "status": status,
            "modules": modules,
            "network": network,
            "open_pivots": [],
            "anchor_queue": [],
            "blockers": [],
            "provider_lanes": provider_lanes,
            "operational_blockers": operational_blockers,
            "closure_id": closure_id,
            "closure_expires_at": payload["expires_at"],
            "reused_evaluation_receipt": False,
        }

    def _route_gate(self, route: dict[str, Any], state: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        required_fields(route, {"kind", "value", "verified", "current", "owned_by_account", "owner_entity_id", "evidence_ids"}, "route")
        kind = str(route["kind"]).upper()
        value = str(route["value"]).strip()
        account_id = state["start"]["account"]["account_id"]
        if route["verified"] is not True or route["current"] is not True or route["owned_by_account"] is not True or route["owner_entity_id"] != account_id:
            issues.append("ROUTE_NOT_CURRENT_VERIFIED_ACCOUNT_OWNED")
        if kind == "EMAIL" and (not EMAIL_RE.fullmatch(value) or MASKED_CONTACT_RE.search(value)):
            issues.append("INVALID_EMAIL_ROUTE")
        elif kind == "PHONE" and (MASKED_CONTACT_RE.search(value) or not INTERNATIONAL_PHONE_RE.fullmatch(re.sub(r"[\s()-]", "", value))):
            issues.append("INVALID_PHONE_ROUTE")
        elif kind in {"WHATSAPP", "ZALO"}:
            normalized = re.sub(r"[\s()-]", "", value)
            if not INTERNATIONAL_PHONE_RE.fullmatch(normalized):
                issues.append(f"INVALID_{kind}_INTERNATIONAL_ROUTE")
        elif kind in {"LINKEDIN", "FACEBOOK", "INSTAGRAM", "WEBSITE_FORM"} and not URL_RE.fullmatch(value):
            issues.append("INVALID_SOCIAL_OR_FORM_URL")
        evidence_ids = route["evidence_ids"] if isinstance(route["evidence_ids"], list) else []
        if not evidence_ids:
            issues.append("ROUTE_EVIDENCE_REQUIRED")
        for evidence_id in evidence_ids:
            item = state["evidence"].get(evidence_id)
            if not item or item["owner_id"] != account_id:
                issues.append("ROUTE_EVIDENCE_OWNER_MISMATCH")
                continue
            claim = str(item["claim_key"]).casefold()
            if kind == "WHATSAPP" and "whatsapp" not in claim:
                issues.append("PHONE_CANNOT_AUTO_PROMOTE_TO_WHATSAPP")
            if kind == "ZALO" and "zalo" not in claim:
                issues.append("PHONE_CANNOT_AUTO_PROMOTE_TO_ZALO")
        return list(dict.fromkeys(issues))

    @unicode_safe_entrypoint
    def prepare_outreach(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        closure_id = nonempty(args.get("closure_id"), "closure_id")
        issues: list[str] = []
        closure = state["closures"].get(closure_id)
        if closure is None:
            issues.append("INVALID_CLOSURE_ID")
        else:
            if closure.get("used"):
                issues.append("CLOSURE_TOKEN_REPLAY")
            if utc_now() > parse_time(closure["expires_at"], "closure.expires_at"):
                issues.append("CLOSURE_EXPIRED")
            newer_operational = any(
                event["seq"] > closure["seq"]
                and event["event_type"] in {
                    "EXECUTION_RECEIPT_APPENDED",
                    "PEER_RECEIPT_APPENDED",
                    "ANCHOR_EXPANSION_CLOSED",
                    "PROVIDER_PLAN_CREATED",
                    "PROVIDER_RECEIPT_APPENDED",
                    "CRM_WRITEBACK_RECEIPT_APPENDED",
                }
                for event in state["events"]
            )
            if newer_operational:
                issues.append("CLOSURE_STALE_AFTER_NEW_RESEARCH")
        if state["start"]["opt_out"]:
            issues.append("ACCOUNT_OPTED_OUT")
        dimensions = closure.get("state_dimensions", {}) if closure else {}
        if not dimensions.get("research_complete"):
            issues.append("RESEARCH_INCOMPLETE")
        if not dimensions.get("network_complete"):
            issues.append("NETWORK_INCOMPLETE")
        if not dimensions.get("crm_sync_complete"):
            issues.append("CRM_SYNC_INCOMPLETE")
        if not dimensions.get("outreach_prerequisites_complete"):
            issues.append("OUTREACH_PREREQUISITES_INCOMPLETE")
        if args.get("history_digest") != state["start"]["history_digest"]:
            issues.append("HISTORY_DIGEST_MISMATCH")
        if args.get("authority_digest") != state["start"]["authority_digest"]:
            issues.append("AUTHORITY_DIGEST_MISMATCH")
        route = args.get("route")
        if not isinstance(route, dict):
            issues.append("ROUTE_REQUIRED")
            route = {}
        else:
            try:
                issues.extend(self._route_gate(route, state))
            except ValidationError as exc:
                issues.append(str(exc))
        subject = str(args.get("subject") or "").strip()
        body = str(args.get("body") or "").strip()
        stage = str(args.get("stage") or "").upper()
        if not subject or not body:
            issues.append("SUBJECT_AND_BODY_REQUIRED")
        if stage not in STAGE_RANK:
            issues.append("INVALID_STAGE")
        prior_stage = state["start"].get("history_highest_stage") or ""
        if prior_stage in STAGE_RANK and stage in STAGE_RANK and STAGE_RANK[stage] < STAGE_RANK[prior_stage]:
            issues.append("HISTORY_STAGE_REGRESSION")
        if any(item.get("stage") == stage for item in state["preparations"].values()):
            issues.append("STAGE_REPLAY")
        combined = f"{subject}\n{body}"
        if UNSAFE_OUTREACH.search(combined):
            issues.append("CUSTOMS_OR_SUPPLIER_INTELLIGENCE_LEAK")
        authority_claims = set(state["start"]["authority_claims"])
        for claim, pattern in CONCRETE_CLAIM_PATTERNS.items():
            if pattern.search(combined) and claim not in authority_claims:
                issues.append(f"UNAUTHORIZED_CONCRETE_{claim.upper()}_CLAIM")
        if stage == "FIRST_TOUCH":
            words = _word_count(body)
            if words < 80 or words > 110:
                issues.append("FIRST_TOUCH_WORD_COUNT_OUTSIDE_80_110")
            if len(re.findall(r"https?://[^\s]+", combined, flags=re.I)) > 1:
                issues.append("FIRST_TOUCH_MULTIPLE_URLS")
        requested_expiry = args.get("expires_at")
        try:
            expires = parse_time(requested_expiry, "expires_at")
            if expires <= utc_now() or expires > utc_now() + timedelta(hours=24):
                issues.append("OUTREACH_EXPIRY_INVALID")
        except ValidationError:
            issues.append("OUTREACH_EXPIRY_INVALID")
            expires = utc_now()
        issues = list(dict.fromkeys(issues))
        if issues:
            return {"status": "DRAFT_BLOCKED", "prepared": False, "block_reasons": issues, "prepared_id": None, "render_token": None, "action": None}
        prepared_id = f"PREP-{secrets.token_hex(12)}"
        render_token = f"RENDER-{secrets.token_hex(20)}"
        payload = {
            "prepared_id": prepared_id,
            "render_token": render_token,
            "closure_id": closure_id,
            "investigation_id": investigation_id,
            "account_id": state["start"]["account"]["account_id"],
            "route": route,
            "history_digest": args["history_digest"],
            "authority_digest": args["authority_digest"],
            "subject": subject,
            "body": body,
            "chinese_translation": str(args.get("chinese_translation") or ""),
            "stage": stage,
            "issued_at": iso_utc(),
            "expires_at": iso_utc(expires),
            "content_sha256": digest({"subject": subject, "body": body, "stage": stage, "route": route}),
        }
        self.store.append(investigation_id, "OUTREACH_PREPARED", payload)
        return {
            "status": "PREPARED_FOR_RENDER",
            "prepared": True,
            "block_reasons": [],
            "prepared_id": prepared_id,
            "render_token": render_token,
            "expires_at": payload["expires_at"],
            "action": None,
            "sends_message": False,
        }

    @unicode_safe_entrypoint
    def render_outreach_action_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = require_object(arguments, "arguments")
        unexpected = sorted(set(args) - {"investigation_id", "prepared_id", "render_token"})
        if unexpected:
            return {
                "terminal_state": "DRAFT_BLOCKED",
                "block_reasons": ["RENDER_PAYLOAD_MUTATION:" + ",".join(unexpected)],
                "action": {"enabled": False, "url": None, "sends_message": False},
                "server_side_draft_created": False,
                "provider_draft_id": None,
            }
        investigation_id = nonempty(args.get("investigation_id"), "investigation_id")
        state = self._state(investigation_id)
        prepared_id = nonempty(args.get("prepared_id"), "prepared_id")
        render_token = nonempty(args.get("render_token"), "render_token")
        prepared = state["preparations"].get(prepared_id)
        reasons: list[str] = []
        if prepared is None:
            reasons.append("PREPARED_OUTREACH_NOT_FOUND")
        else:
            if prepared["render_token"] != render_token:
                reasons.append("RENDER_TOKEN_MISMATCH")
            if render_token in state["rendered_tokens"]:
                reasons.append("RENDER_TOKEN_REPLAY")
            if utc_now() > parse_time(prepared["expires_at"], "prepared.expires_at"):
                reasons.append("PREPARED_OUTREACH_EXPIRED")
        if reasons:
            return {
                "terminal_state": "DRAFT_BLOCKED",
                "block_reasons": reasons,
                "action": {"enabled": False, "url": None, "sends_message": False},
                "server_side_draft_created": False,
                "provider_draft_id": None,
            }
        route = prepared["route"]
        if str(route["kind"]).upper() != "EMAIL":
            mailto = None
            reasons.append("MAILTO_REQUIRES_EMAIL_ROUTE")
        else:
            mailto = f"mailto:{quote(str(route['value']), safe='@+._-')}?subject={quote(prepared['subject'])}&body={quote(prepared['body'])}"
            if len(mailto) > 8000:
                mailto = None
                reasons.append("MAILTO_TOO_LONG")
        if reasons:
            return {
                "terminal_state": "DRAFT_BLOCKED",
                "block_reasons": reasons,
                "action": {"enabled": False, "url": None, "sends_message": False},
                "server_side_draft_created": False,
                "provider_draft_id": None,
            }
        self.store.append(investigation_id, "OUTREACH_RENDERED", {
            "prepared_id": prepared_id,
            "render_token": render_token,
            "rendered_at": iso_utc(),
        })
        return {
            "schema_version": "5.4.1",
            "runtime_version": RUNTIME_VERSION,
            "build_id": BUILD_ID,
            "terminal_state": "SENDABLE_DRAFT",
            "recipient": route["value"],
            "route_kind": route["kind"],
            "subject": prepared["subject"],
            "body": prepared["body"],
            "chinese_translation": prepared["chinese_translation"],
            "stage": prepared["stage"],
            "block_reasons": [],
            "action": {"label": "一键打开邮件草稿 / Open email draft", "kind": "open_url", "url": mailto, "enabled": True, "sends_message": False, "requires_preview": True},
            "server_side_draft_created": False,
            "provider_draft_id": None,
            "connector_receipt": None,
            "simultaneous_multi_send_prohibited": True,
            "send_boundary": "This tool only opens a local UTF-8 mailto draft. It never sends and never claims a provider-side draft receipt.",
        }
