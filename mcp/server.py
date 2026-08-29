#!/usr/bin/env python3
"""Dependency-free MCP server for Customs Buyer Intelligence v6.1."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from unified_runtime import (  # noqa: E402
    BUILD_ID,
    CBI_MCP_TOOL_NAMES,
    COMMERCIAL_GATE_ORDER,
    COMMERCIAL_GATE_TAGS,
    CRM_WRITEBACK_REQUIRED,
    EVIDENCE_CLAIM_TYPES,
    EVIDENCE_FRESHNESS,
    EVIDENCE_GRADES,
    EVIDENCE_REFERENCE_TYPES,
    INFORMATION_CONFIDENCE,
    INFORMATION_ROUTE_SCOPES,
    INFORMATION_SOURCE_TYPES,
    INFORMATION_SUBJECT_TYPES,
    INFORMATION_TEMPORAL_STATUS,
    INFORMATION_TYPES,
    NETWORK_BRANCHES,
    PROVIDER_AVAILABILITY,
    PROVIDER_CLASSES,
    PROVIDER_MODES,
    RUNTIME_VERSION,
    SUPPLY_CHAIN_PARTY_ROLES,
    UnifiedRuntime,
    VALID_RESULTS,
    ValidationError,
)


TEMPLATE_URI = "ui://customs-buyer-intelligence/outreach-v6.1.html"
RUNTIME = UnifiedRuntime()


UI_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;padding:14px;color:#10233f;background:#f6f9fc}.card{background:#fff;border:1px solid #d7e2ef;border-radius:14px;padding:16px;box-shadow:0 4px 14px #10233f12}.top{display:flex;justify-content:space-between;gap:12px;align-items:center}.badge{font-size:12px;font-weight:700;padding:5px 9px;border-radius:999px;background:#e8f5ee;color:#17633b}.blocked{background:#fff1f0;color:#9f2d24}.row{margin-top:12px}.label{font-size:12px;color:#607089;margin-bottom:4px}.value{white-space:pre-wrap;word-break:break-word}.email{max-height:220px;overflow:auto;border:1px solid #e2e9f1;border-radius:10px;padding:10px;background:#fbfdff}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}a,button{border:0;border-radius:9px;padding:10px 14px;font-weight:700;text-decoration:none;cursor:pointer}.primary{background:#1479d1;color:white}.secondary{background:#eaf2f9;color:#17466f}.disabled{pointer-events:none;opacity:.45}.warning{margin-top:12px;padding:9px;border-radius:9px;background:#fff8e6;color:#745200;font-size:13px}</style></head>
<body><div class="card"><div class="top"><strong>已核验开发信草稿 / Verified outreach draft</strong><span id="badge" class="badge">等待结果</span></div>
<div class="row"><div class="label">收件人 / Recipient</div><div id="recipient" class="value">—</div></div>
<div class="row"><div class="label">阶段 / Stage</div><div id="stage" class="value">—</div></div>
<div class="row"><div class="label">主题 / Subject</div><div id="subject" class="value">—</div></div>
<div class="row"><div class="label">客户语言邮件 / Customer email</div><div id="body" class="value email">—</div></div>
<div class="row"><div class="label">中文审核译文</div><div id="chinese" class="value email">—</div></div>
<div id="warning" class="warning">历史和新发现都会保留并入；这里只核验当前草稿能否使用，不会删除任何线索，也永不发送。</div>
<div class="actions"><a id="open" class="primary disabled" href="#">一键打开邮件草稿</a><button id="copy" class="secondary">复制邮件正文</button></div></div>
<script>
const $=id=>document.getElementById(id);let latest={};
function render(x){latest=x||{};const ok=latest.terminal_state==='SENDABLE_DRAFT'&&latest.action?.enabled;$('badge').textContent=latest.terminal_state||'等待结果';$('badge').className='badge'+(ok?'':' blocked');$('recipient').textContent=latest.recipient||'未验证';$('stage').textContent=latest.stage||'—';$('subject').textContent=latest.subject||'—';$('body').textContent=latest.body||'—';$('chinese').textContent=latest.chinese_translation||'—';$('warning').textContent=ok?'按钮只打开本机草稿；不会自动发送。':'草稿不可用：'+((latest.block_reasons||[]).join('、')||'未满足当前草稿使用条件');$('open').href=ok?latest.action.url:'#';$('open').className='primary'+(ok?'':' disabled');}
$('copy').onclick=async()=>{if(!latest.body)return;try{await navigator.clipboard.writeText(latest.body);$('copy').textContent='已复制';}catch(e){$('copy').textContent='复制失败';}};
window.addEventListener('message',e=>{if(e.source!==window.parent)return;const m=e.data;if(m?.method==='ui/notifications/tool-result')render(m.params?.structuredContent);},{passive:true});if(window.openai?.toolOutput)render(window.openai.toolOutput);
</script></body></html>'''


def _object_schema(
    required: list[str],
    properties: dict[str, Any] | None = None,
    *,
    additional: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": additional,
        "required": required,
        "properties": properties or {name: {} for name in required},
    }


STRING = {"type": "string"}
NONEMPTY = {"type": "string", "minLength": 1}
STRING_ARRAY = {"type": "array", "items": NONEMPTY}
SHA256 = {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"}
TIMESTAMP = {"type": "string", "format": "date-time"}


ACCOUNT_SCHEMA = _object_schema(["country"], {
    "account_id": STRING,
    "country": NONEMPTY,
    "name": STRING,
    "aliases": STRING_ARRAY,
    "tax_id": STRING,
    "tax_ids": STRING_ARRAY,
    "address": STRING,
    "addresses": STRING_ARRAY,
    "external_ids": STRING_ARRAY,
}, additional=True)

SUPPLY_CHAIN_PARTY_SCHEMA = _object_schema(["entity_id", "name"], {
    "entity_id": NONEMPTY,
    "name": NONEMPTY,
    "role": {"type": "string", "enum": sorted(SUPPLY_CHAIN_PARTY_ROLES)},
    "evidence_ids": STRING_ARRAY,
    "confidence": STRING,
}, additional=True)

INFORMATION_VALUE_SCHEMA = _object_schema([], {
    "channel": {"type": "string", "enum": ["EMAIL", "PHONE", "WHATSAPP", "ZALO", "SOCIAL", "FORM", "OTHER"]},
    "value": {},
    "verified": {"type": "boolean"},
    "masked": {"type": "boolean"},
    "guessed": {"type": "boolean"},
    "channel_proof": {"type": "boolean"},
    "role": {"type": "string", "enum": sorted(SUPPLY_CHAIN_PARTY_ROLES)},
    "entity_id": STRING,
    "name": STRING,
}, additional=True)

INFORMATION_RECORD_SCHEMA = _object_schema([
    "information_id", "investigation_id", "related_account_id", "subject_type", "subject_owner_id",
    "relationship_to_account", "information_type", "claim_key", "value", "source_type",
    "source_reference_type", "source_url", "source_locator",
    "observed_at", "content_sha256", "confidence", "temporal_status", "route_scope",
    "outreach_eligible_claimed", "supersedes_information_ids", "conflicts_with_information_ids",
    "evidence_ids", "notes",
], {
    "information_id": NONEMPTY,
    "investigation_id": NONEMPTY,
    "related_account_id": NONEMPTY,
    "subject_type": {"type": "string", "enum": sorted(INFORMATION_SUBJECT_TYPES)},
    "subject_owner_id": NONEMPTY,
    "relationship_to_account": NONEMPTY,
    "information_type": {"type": "string", "enum": sorted(INFORMATION_TYPES)},
    "claim_key": NONEMPTY,
    "value": INFORMATION_VALUE_SCHEMA,
    "source_type": {"type": "string", "enum": sorted(INFORMATION_SOURCE_TYPES)},
    "source_reference_type": {"type": "string", "enum": sorted(EVIDENCE_REFERENCE_TYPES)},
    "source_url": STRING,
    "source_locator": NONEMPTY,
    "observed_at": TIMESTAMP,
    "content_sha256": SHA256,
    "confidence": {"type": "string", "enum": sorted(INFORMATION_CONFIDENCE)},
    "temporal_status": {"type": "string", "enum": sorted(INFORMATION_TEMPORAL_STATUS)},
    "route_scope": {"type": "string", "enum": sorted(INFORMATION_ROUTE_SCOPES)},
    "outreach_eligible_claimed": {"type": "boolean"},
    "supersedes_information_ids": STRING_ARRAY,
    "conflicts_with_information_ids": STRING_ARRAY,
    "evidence_ids": STRING_ARRAY,
    "notes": STRING,
})
INFORMATION_RECORD_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"source_reference_type": {"const": "PUBLIC_URL"}}},
        "then": {"properties": {"source_url": {"type": "string", "minLength": 1, "pattern": "^https?://\\S+$"}}},
        "else": {"properties": {"source_url": {"type": "string", "maxLength": 0}}},
    }
]

EVIDENCE_SCHEMA = _object_schema([
    "evidence_id", "owner_type", "owner_id", "claim_key", "module_or_branch", "source_type",
    "source_family", "reference_type", "url", "locator", "observed_at", "content_sha256", "snapshot_locator",
    "claim_type", "freshness", "evidence_grade", "boundary", "conflict",
], {
    "evidence_id": NONEMPTY,
    "owner_type": {"type": "string", "enum": ["ACCOUNT", "PEER"]},
    "owner_id": NONEMPTY,
    "claim_key": NONEMPTY,
    "module_or_branch": NONEMPTY,
    "source_type": NONEMPTY,
    "source_family": NONEMPTY,
    "reference_type": {"type": "string", "enum": sorted(EVIDENCE_REFERENCE_TYPES)},
    "url": STRING,
    "locator": STRING,
    "observed_at": TIMESTAMP,
    "content_sha256": SHA256,
    "snapshot_locator": NONEMPTY,
    "claim_type": {"type": "string", "enum": sorted(EVIDENCE_CLAIM_TYPES)},
    "freshness": {"type": "string", "enum": sorted(EVIDENCE_FRESHNESS)},
    "evidence_grade": {"type": "string", "enum": sorted(EVIDENCE_GRADES)},
    "boundary": {"type": "string", "minLength": 1, "description": "Required narrative scope/boundary; this is deliberately not a guessed enum."},
    "conflict": {},
    "commercial_gate_tags": {
        "type": "array",
        "items": {"type": "string", "enum": sorted(COMMERCIAL_GATE_TAGS)},
        "uniqueItems": True,
    },
})
EVIDENCE_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"reference_type": {"const": "PUBLIC_URL"}}},
        "then": {"properties": {"url": {"type": "string", "minLength": 1, "pattern": "^https?://\\S+$"}}},
        "else": {"properties": {"url": {"type": "string", "maxLength": 0}}},
    }
]

PIVOT_SCHEMA = _object_schema([
    "pivot_id", "pivot_type", "pivot_value", "generated_by_attempt_id", "generated_at",
    "consumed_by_attempt_id", "consumed_at", "consumption_result", "status",
], {
    "pivot_id": NONEMPTY,
    "pivot_type": NONEMPTY,
    "pivot_value": NONEMPTY,
    "generated_by_attempt_id": NONEMPTY,
    "generated_at": TIMESTAMP,
    "consumed_by_attempt_id": STRING,
    "consumed_at": STRING,
    "consumption_result": STRING,
    "status": {"type": "string", "enum": ["OPEN", "CONSUMED"]},
})

PIVOT_CONSUMPTION_SCHEMA = _object_schema(["pivot_id", "consumption_result"], {
    "pivot_id": NONEMPTY,
    "consumption_result": NONEMPTY,
})

SOURCE_ATTEMPT_SCHEMA = _object_schema([
    "attempt_id", "investigation_id", "owner_type", "owner_id", "module_or_branch", "source_family",
    "query", "started_at", "completed_at", "checked_at", "tool_or_operator", "execution_id", "result",
    "result_count", "raw_result_locator", "content_sha256", "evidence_ids", "pivots_generated", "blocked_reason",
], {
    "attempt_id": NONEMPTY,
    "investigation_id": NONEMPTY,
    "owner_type": {"type": "string", "enum": ["ACCOUNT", "PEER"]},
    "owner_id": NONEMPTY,
    "module_or_branch": NONEMPTY,
    "source_family": NONEMPTY,
    "query": NONEMPTY,
    "started_at": TIMESTAMP,
    "completed_at": TIMESTAMP,
    "checked_at": TIMESTAMP,
    "tool_or_operator": NONEMPTY,
    "execution_id": NONEMPTY,
    "result": {"type": "string", "enum": sorted(VALID_RESULTS)},
    "result_count": {"type": "integer", "minimum": 0},
    "raw_result_locator": NONEMPTY,
    "content_sha256": SHA256,
    "evidence_ids": STRING_ARRAY,
    "pivots_generated": STRING_ARRAY,
    "blocked_reason": STRING,
    "discovered_peer_ids": STRING_ARRAY,
    "relationship_evidence_ids": {"type": "object", "additionalProperties": STRING_ARRAY},
})

PROVIDER_CONTACT_SCHEMA = _object_schema([
    "contact_id", "kind", "value", "owner_entity_id", "masked", "guessed", "provider_verified",
    "route_eligible", "evidence_id", "channel_proof",
], {
    "contact_id": NONEMPTY,
    "kind": {"type": "string", "enum": ["EMAIL", "PHONE", "WHATSAPP", "ZALO", "SOCIAL", "OTHER"]},
    "value": NONEMPTY,
    "owner_entity_id": NONEMPTY,
    "masked": {"type": "boolean"},
    "guessed": {"type": "boolean"},
    "provider_verified": {"type": "boolean"},
    "route_eligible": {"type": "boolean"},
    "evidence_id": STRING,
    "channel_proof": {"type": "boolean"},
})

PROVIDER_RECEIPT_SCHEMA = _object_schema([
    "provider_receipt_id", "investigation_id", "account_id", "provider", "provider_class",
    "requested_capability", "target_module", "plan_id", "planned_call_id", "tool_name", "tool_call_id",
    "query", "requested_at", "completed_at", "result", "result_count", "raw_result_locator",
    "content_sha256", "evidence_ids", "pivots_generated", "contacts_returned", "companies_returned",
    "billing_or_credit_notice", "blocked_reason", "permissions", "freshness", "conflicts", "status",
], {
    "provider_receipt_id": NONEMPTY,
    "investigation_id": NONEMPTY,
    "account_id": NONEMPTY,
    "provider": NONEMPTY,
    "provider_class": {"type": "string", "enum": sorted(PROVIDER_CLASSES)},
    "requested_capability": NONEMPTY,
    "target_module": NONEMPTY,
    "plan_id": NONEMPTY,
    "planned_call_id": NONEMPTY,
    "tool_name": NONEMPTY,
    "tool_call_id": NONEMPTY,
    "query": NONEMPTY,
    "requested_at": TIMESTAMP,
    "completed_at": TIMESTAMP,
    "result": {"type": "string", "enum": ["POSITIVE", "NEGATIVE", "BLOCKED"]},
    "result_count": {"type": "integer", "minimum": 0},
    "raw_result_locator": NONEMPTY,
    "content_sha256": SHA256,
    "evidence_ids": STRING_ARRAY,
    "pivots_generated": STRING_ARRAY,
    "contacts_returned": {"type": "array", "items": PROVIDER_CONTACT_SCHEMA},
    "companies_returned": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    "billing_or_credit_notice": STRING,
    "blocked_reason": STRING,
    "permissions": _object_schema(["user_authorized", "scopes"], {
        "user_authorized": {"type": "boolean"},
        "scopes": STRING_ARRAY,
    }),
    "freshness": {"type": "string", "enum": sorted(EVIDENCE_FRESHNESS)},
    "conflicts": {"type": "array", "items": {}},
    "status": {"type": "string", "enum": ["SUCCESS", "BLOCKED"]},
})

CRM_DIFF_SCHEMA = _object_schema(["sheet", "record_key", "column", "previous", "current"], {
    "sheet": NONEMPTY,
    "record_key": NONEMPTY,
    "column": NONEMPTY,
    "previous": {},
    "current": {},
})

CRM_WRITEBACK_RECEIPT_SCHEMA = _object_schema(sorted(CRM_WRITEBACK_REQUIRED), {
    "writeback_id": NONEMPTY,
    "investigation_id": NONEMPTY,
    "account_id": NONEMPTY,
    "transaction_id": NONEMPTY,
    "writer": {"type": "string", "const": "ARTIFACT_TOOL"},
    "target_workbook_path": NONEMPTY,
    "workbook_sha256_before": SHA256,
    "workbook_sha256_after": SHA256,
    "committed_at": TIMESTAMP,
    "status": {"type": "string", "enum": ["COMMITTED", "NO_CHANGE_VERIFIED"]},
    "atomic_commit": {"type": "boolean", "const": True},
    "sparse_patch": {"type": "boolean", "const": True},
    "history_guard_passed": {"type": "boolean", "const": True},
    "post_commit_reimport_verified": {"type": "boolean", "const": True},
    "unintended_diff_count": {"type": "integer", "const": 0},
    "touched_sheets": STRING_ARRAY,
    "row_assertions": {"type": "array", "items": {"type": "object", "minProperties": 1, "additionalProperties": True}},
    "cell_assertions": {"type": "array", "items": {"type": "object", "minProperties": 1, "additionalProperties": True}},
    "previous_current_diff": {"type": "array", "items": CRM_DIFF_SCHEMA},
    "audit_artifact_locator": NONEMPTY,
    "audit_artifact_sha256": SHA256,
})

PEER_SECTION_SCHEMA = _object_schema(["passed", "attempt_ids", "evidence_ids"], {
    "passed": {"type": "boolean"},
    "attempt_ids": STRING_ARRAY,
    "evidence_ids": STRING_ARRAY,
})

PEER_RECEIPT_SCHEMA = _object_schema([
    "peer_id", "canonical_key", "discovered_by_attempt_id", "branch", "inherited_anchor_facts",
    "canonical_dedup_checked", "entity", "product", "trade_business", "relationship",
    "company_profile", "contact_coverage", "promotion_decision", "promotion_reason",
], {
    "peer_id": NONEMPTY,
    "canonical_key": NONEMPTY,
    "discovered_by_attempt_id": NONEMPTY,
    "branch": {"type": "string", "enum": list(NETWORK_BRANCHES)},
    "inherited_anchor_facts": {"type": "boolean", "const": False},
    "canonical_dedup_checked": {"type": "boolean", "const": True},
    "entity": PEER_SECTION_SCHEMA,
    "product": PEER_SECTION_SCHEMA,
    "trade_business": PEER_SECTION_SCHEMA,
    "relationship": PEER_SECTION_SCHEMA,
    "company_profile": PEER_SECTION_SCHEMA,
    "contact_coverage": PEER_SECTION_SCHEMA,
    "promotion_decision": {"type": "string", "enum": ["PROMOTE", "DO_NOT_PROMOTE"]},
    "promotion_reason": NONEMPTY,
    "target_fit_grade": {"type": "string", "enum": ["C", "B", "B+", "A", "A+"]},
    "promotion_evidence_grade": {"type": "string", "enum": ["C", "B", "A"]},
    "commercial_novelty": {"type": "boolean"},
    "canonical_status": {"type": "string", "enum": ["NEW", "EXISTING", "AMBIGUOUS"]},
})

ROUTE_SCHEMA = _object_schema([
    "kind", "value", "verified", "current", "owned_by_account", "owner_entity_id", "evidence_ids",
], {
    "kind": {"type": "string", "enum": ["EMAIL", "PHONE", "WHATSAPP", "ZALO", "SOCIAL", "FORM"]},
    "value": NONEMPTY,
    "verified": {"type": "boolean"},
    "current": {"type": "boolean"},
    "owned_by_account": {"type": "boolean"},
    "owner_entity_id": NONEMPTY,
    "evidence_ids": STRING_ARRAY,
})

V61_SOURCE_SCHEMA = _object_schema([
    "source_family", "source_type", "reference_type", "locator",
    "authority_level", "freshness", "observed_at",
], {
    "source_family": NONEMPTY,
    "source_type": NONEMPTY,
    "reference_type": {"type": "string", "enum": [
        "PUBLIC_URL", "LOCAL_ARTIFACT", "USER_INPUT", "LEGACY_CRM",
        "PROVIDER_RECEIPT", "DERIVED_CALCULATION",
    ]},
    "url": STRING,
    "locator": NONEMPTY,
    "content_sha256": SHA256,
    "raw_content": {},
    "raw_excerpt": STRING,
    "authority_level": {"type": "string", "enum": [
        "A1_OFFICIAL_PRIMARY", "A2_REGULATORY_OR_GOVERNMENT", "B1_OFFICIAL_COMPANY",
        "B2_REPUTABLE_INDUSTRY_OR_DIRECTORY", "C1_PUBLIC_PROFESSIONAL_OR_SOCIAL",
        "C2_SECONDARY_PUBLIC", "D1_USER_SUPPLIED_UNVERIFIED", "D2_DERIVED_OR_INFERRED",
    ]},
    "freshness": {"type": "string", "enum": ["LIVE", "CURRENT", "RECENT", "HISTORICAL", "STALE", "UNKNOWN"]},
    "observed_at": TIMESTAMP,
})

V61_OBSERVATION_SCHEMA = _object_schema(["claim_key", "result", "source", "boundary"], {
    "observation_id": STRING,
    "evidence_id": STRING,
    "claim_key": NONEMPTY,
    "result": {"type": "string", "enum": [
        "POSITIVE", "NEGATIVE", "NEGATIVE_EXHAUSTED", "BLOCKED",
        "NOT_APPLICABLE", "REFUTED", "CONFLICT",
    ]},
    "owner_type": {"type": "string", "enum": ["ACCOUNT", "PEER", "PERSON", "SUPPLIER", "PRODUCT"]},
    "owner_id": STRING,
    "value": {},
    "network_branch": STRING,
    "source": V61_SOURCE_SCHEMA,
    "boundary": NONEMPTY,
    "blocked_reason": STRING,
    "not_applicable_reason": STRING,
    "search_exhaustion": {"type": "object", "additionalProperties": True},
    "pivots": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    "search_cost": {"type": "number", "minimum": 0},
}, additional=True)

V61_OBJECTIVE_SCHEMA = _object_schema(["claim_key", "query_or_navigation", "source_family"], {
    "objective_id": STRING,
    "claim_key": NONEMPTY,
    "query_or_navigation": NONEMPTY,
    "source_family": NONEMPTY,
    "network_branch": STRING,
    "probability": {"type": "number", "minimum": 0, "maximum": 1},
    "decision_impact": {"type": "number", "minimum": 0, "maximum": 1},
    "evidence_quality_gain": {"type": "number", "minimum": 0, "maximum": 1},
    "commercial_weight": {"type": "number", "minimum": 0},
    "search_cost": {"type": "number", "exclusiveMinimum": 0},
}, additional=True)

V61_PEER_ASSESSMENT_SCHEMA = _object_schema([], {
    "entity_verified": {"type": "boolean"},
    "product_fit_verified": {"type": "boolean"},
    "business_or_trade_verified": {"type": "boolean"},
    "relationship_verified": {"type": "boolean"},
    "commercial_novelty": {"type": "boolean"},
    "canonical_new": {"type": "boolean", "description": "Assertion checked against the Runtime-derived canonical result."},
    "fact_evidence_ids": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            key: STRING_ARRAY for key in [
                "entity_verified", "product_fit_verified", "business_or_trade_verified",
                "relationship_verified", "commercial_novelty",
            ]
        },
    },
    "commercial_novelty_basis": STRING,
    "disposition": {"type": "string", "enum": ["PENDING", "NOT_MATERIAL"]},
    "decision_basis": STRING,
    "max_remaining_eiv": {"type": "number", "minimum": 0},
    "full_audit_complete": {"type": "boolean"},
    "network_branch_states": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": True}},
    "contact_coverage": {"type": "object", "additionalProperties": True},
}, additional=True)


def tool_descriptors() -> list[dict[str, Any]]:
    tools = [
        {
            "name": "get_runtime_contract",
            "description": "Return every public enum, required nested field, immutable Source Profile, network policy, separated state dimension and transport boundary so callers never guess accepted values.",
            "inputSchema": _object_schema([], {}),
        },
        {
            "name": "get_runtime_health",
            "description": "Verify local session, canonical-registry and Pending Journal hash chains. This proves local Runtime health only; a successful call also proves the current MCP route, while an unavailable tunnel cannot call this tool.",
            "inputSchema": _object_schema([], {"investigation_id": STRING}),
        },
        {
            "name": "get_investigation_health",
            "description": "Verify one durable investigation hash chain and return its last safe state, or quarantine it read-only on integrity failure.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "resolve_or_create_account",
            "description": "Resolve exact ID, tax ID, alias/name, address or external identifiers against the append-only canonical registry; return ambiguity instead of guessing, or atomically allocate a new C-number.",
            "inputSchema": _object_schema(["candidate"], {
                "candidate": ACCOUNT_SCHEMA,
                "requested_account_id": STRING,
                "create_if_missing": {"type": "boolean"},
            }),
        },
        {
            "name": "start_investigation",
            "description": "Resolve the canonical Account and idempotently create or resume an append-only EXHAUSTIVE or preliminary FAST_SCAN investigation. FAST_SCAN can never issue research_complete.",
            "inputSchema": _object_schema(["account"], {
                "account": ACCOUNT_SCHEMA,
                "input": {"type": "object", "additionalProperties": True},
                "mode": {"type": "string", "enum": ["EXHAUSTIVE", "FAST_SCAN"]},
                "history": _object_schema([], {
                    "events": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "opt_out": {"type": "boolean"},
                }, additional=True),
                "crm_path": STRING,
                "authority_claims": STRING_ARRAY,
                "manual_visual_queue": STRING_ARRAY,
                "additional_source_families": {"type": "object", "additionalProperties": STRING_ARRAY},
                "provider_policy": _object_schema([], {
                    "mode": {"type": "string", "enum": sorted(PROVIDER_MODES)},
                    "allowed_providers": STRING_ARRAY,
                    "required_capabilities": STRING_ARRAY,
                    "cost_consent": {"type": "boolean"},
                }),
                "network_policy": _object_schema([], {
                    "max_anchor_depth": {"type": "integer", "minimum": 0, "description": "Deprecated v5.3 resource hint; never a v5.4 completion or promotion cap."},
                    "max_promoted_anchors": {"type": "integer", "minimum": 0, "description": "Deprecated v5.3 resource hint; never a v5.4 completion or promotion cap."},
                    "minimum_target_fit": {"type": "string", "enum": ["A", "A+"]},
                    "minimum_evidence_grade": {"type": "string", "enum": ["B", "A"]},
                    "require_commercial_novelty": {"type": "boolean", "const": True},
                    "require_canonical_new": {"type": "boolean", "const": True},
                    "closure_strategy": {"type": "string", "const": "QUEUE_PIVOT_SATURATION"},
                }),
                "supply_chain_parties": {
                    "type": "object",
                    "additionalProperties": {
                        "oneOf": [SUPPLY_CHAIN_PARTY_SCHEMA, {"type": "array", "items": SUPPLY_CHAIN_PARTY_SCHEMA}],
                    },
                },
                "idempotency_key": STRING,
                "resume_existing": {"type": "boolean"},
                "create_account_if_missing": {"type": "boolean"},
                "priority_grade": {"type": "string", "enum": ["A+", "A", "A-", "B+", "B", "B-", "C", "D", "NQ"]},
                "budget_units": {"type": "number", "minimum": 0},
                "decision_saturation_threshold": {"type": "number", "minimum": 0},
                "claim_catalog": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": True}},
            }),
        },
        {
            "name": "resume_investigation",
            "description": "Resume a durable investigation after any MCP or host transport restart without recreating state.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "submit_research_objective",
            "description": "Append one claim-bound research objective and compute its Expected Information Value; planning is not execution proof.",
            "inputSchema": _object_schema(["investigation_id", "objective"], {
                "investigation_id": NONEMPTY,
                "objective": V61_OBJECTIVE_SCHEMA,
            }),
        },
        {
            "name": "compile_and_append_research_bundle",
            "description": "Compile and append 1-1000 host observations with normalization, IDs, hashes, claim mapping, Evidence, Pivots, conflicts, partial success and idempotent replay.",
            "inputSchema": _object_schema(["investigation_id", "bundle"], {
                "investigation_id": NONEMPTY,
                "bundle": _object_schema(["observations"], {
                    "bundle_id": STRING,
                    "execution_id": STRING,
                    "observations": {"type": "array", "minItems": 1, "maxItems": 1000, "items": V61_OBSERVATION_SCHEMA},
                }, additional=True),
            }),
        },
        {
            "name": "get_claims",
            "description": "Return claim state, Evidence bindings, conflicts and blockers without mutating research.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "get_account_state",
            "description": "Return independent Commercial Value, Research Confidence, Outreach Readiness and CRM state dimensions.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "get_investigation_state",
            "description": "Return the durable claim-driven investigation state and last safe hash-chain position.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "get_next_research_objectives",
            "description": "Rank unresolved claims and material Pivots by Expected Information Value under the account budget; budget exhaustion pauses but never closes research.",
            "inputSchema": _object_schema(["investigation_id"], {
                "investigation_id": NONEMPTY,
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            }),
        },
        {
            "name": "get_portfolio_queue",
            "description": "Rank durable investigations by commercial priority, unresolved decision value, confidence and remaining budget.",
            "inputSchema": _object_schema([], {"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
        },
        {
            "name": "append_information_record",
            "description": "Append any sourced historical, buyer-owned, cross-entity, supplier, referral, product-channel, conflict or low-confidence finding. Information is never discarded merely because it is not Buyer Direct; outreach eligibility is computed separately.",
            "inputSchema": _object_schema(["investigation_id", "record"], {
                "investigation_id": NONEMPTY, "record": INFORMATION_RECORD_SCHEMA,
            }),
        },
        {
            "name": "get_information_history",
            "description": "Return every append-only information record plus a derived current view. Superseded and conflicting history remains visible and is never overwritten or deleted.",
            "inputSchema": _object_schema(["investigation_id"], {
                "investigation_id": {"type": "string"}, "related_account_id": {"type": "string"},
            }),
        },
        {
            "name": "plan_public_source_calls",
            "description": "Return the next missing public Source Family, network and open-Pivot calls for host-side web/browser execution. Planning performs no search and is never Evidence; every real result still requires append_execution_receipt.",
            "inputSchema": _object_schema(["investigation_id"], {
                "investigation_id": NONEMPTY,
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            }),
        },
        {
            "name": "plan_provider_calls",
            "description": "Plan exact Codex-level calls to explicitly authorized and connected provider plugins. This Runtime does not call, install, connect, pay for, or impersonate another provider; it returns a plan whose real results must be appended separately.",
            "inputSchema": _object_schema(["investigation_id", "requested_capabilities", "provider_inventory", "cost_consent"], {
                "investigation_id": {"type": "string"},
                "requested_capabilities": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "provider_inventory": {"type": "array", "items": _object_schema([
                    "provider", "provider_class", "status", "capability_tools", "permissions", "requires_paid_credit",
                ], {
                    "provider": NONEMPTY,
                    "provider_class": {"type": "string", "enum": sorted(PROVIDER_CLASSES)},
                    "status": {"type": "string", "enum": sorted(PROVIDER_AVAILABILITY)},
                    "capability_tools": {"type": "object", "additionalProperties": NONEMPTY},
                    "permissions": STRING_ARRAY,
                    "requires_paid_credit": {"type": "boolean"},
                })},
                "cost_consent": {"type": "boolean"},
            }),
        },
        {
            "name": "append_execution_receipt",
            "description": "Append one immutable SourceAttempt with same-owner Evidence, raw-result hash/locator, generated Pivots and later independent Pivot consumption. Duplicate IDs, self-proof locators, false N/A and cross-owner bindings are rejected.",
            "inputSchema": _object_schema(["investigation_id", "attempt"], {
                "investigation_id": NONEMPTY, "attempt": SOURCE_ATTEMPT_SCHEMA,
                "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                "pivots": {"type": "array", "items": PIVOT_SCHEMA},
                "pivots_consumed": {"type": "array", "items": PIVOT_CONSUMPTION_SCHEMA},
                "manual_visual_items_resolved": {"type": "array", "items": {"type": "string"}},
            }),
        },
        {
            "name": "append_provider_receipt",
            "description": "Append the real result of one exact planned provider-tool call with owner-bound Evidence, contact safety, permissions, cost notice, raw locator/hash and Pivots. Provider data never replaces public Source Families or self-closes research.",
            "inputSchema": _object_schema(["investigation_id", "receipt"], {
                "investigation_id": {"type": "string"},
                "receipt": PROVIDER_RECEIPT_SCHEMA,
                "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                "pivots": {"type": "array", "items": PIVOT_SCHEMA},
                "pivots_consumed": {"type": "array", "items": PIVOT_CONSUMPTION_SCHEMA},
            }),
        },
        {
            "name": "append_peer_receipt",
            "description": "Append an independently proven Peer or close an Anchor expansion. PROMOTE requires fit/Evidence minimums, canonical NEW and commercial novelty; qualified Peers are never dropped by fixed depth/count caps, and Closure waits for queue/Pivot saturation.",
            "inputSchema": _object_schema(["investigation_id", "receipt_type"], {
                "investigation_id": {"type": "string"},
                "receipt_type": {"type": "string", "enum": ["PEER_VALIDATION", "ANCHOR_EXPANSION"]},
                "receipt": PEER_RECEIPT_SCHEMA, "anchor_id": STRING, "cycle_dedup_checked": {"type": "boolean"},
            }),
        },
        {
            "name": "append_peer_discovery",
            "description": "Append a branch-bound Peer discovery with relationship Evidence and canonical dedup; no Anchor promotion is implied.",
            "inputSchema": _object_schema(["investigation_id", "peer"], {
                "investigation_id": NONEMPTY,
                "peer": {"type": "object", "additionalProperties": True},
            }),
        },
        {
            "name": "evaluate_peer",
            "description": "Move a Peer monotonically through DISCOVERED, QUALIFIED, ANCHOR_ELIGIBLE or FULLY_AUDITED. Every positive qualification fact requires claim-compatible Peer-owned Evidence; contact coverage is not an eligibility gate.",
            "inputSchema": _object_schema(["investigation_id", "peer_id", "assessment"], {
                "investigation_id": NONEMPTY,
                "peer_id": NONEMPTY,
                "assessment": V61_PEER_ASSESSMENT_SCHEMA,
            }),
        },
        {
            "name": "promote_anchor",
            "description": "Promote an ANCHOR_ELIGIBLE Peer and require claim/EIV-driven six-branch research without imposing a contact-coverage gate.",
            "inputSchema": _object_schema(["investigation_id", "peer_id", "promotion_reason"], {
                "investigation_id": NONEMPTY,
                "peer_id": NONEMPTY,
                "promotion_reason": NONEMPTY,
            }),
        },
        {
            "name": "get_material_pivots",
            "description": "Return only unresolved material Pivots or optional Pivots whose EIV exceeds the investigation threshold.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "close_pivot",
            "description": "Close one Pivot as consumed, specifically not material, or blocked while preserving its complete history.",
            "inputSchema": _object_schema(["investigation_id", "pivot_id", "status", "reason"], {
                "investigation_id": NONEMPTY,
                "pivot_id": NONEMPTY,
                "status": {"type": "string", "enum": ["CONSUMED", "NOT_MATERIAL", "BLOCKED"]},
                "reason": NONEMPTY,
                "consumed_by_objective_id": STRING,
                "max_remaining_eiv": {"type": "number", "minimum": 0},
            }),
        },
        {
            "name": "append_crm_writeback_receipt",
            "description": "Append immutable proof of the unique main CRM workbook's external Artifact Tool atomic commit or verified no-change transaction. The Runtime checks the actual post-commit OOXML file/hash, audit artifact, history guard, row/cell assertions and semantic diff; it does not write Excel itself.",
            "inputSchema": _object_schema(["investigation_id", "receipt"], {
                "investigation_id": NONEMPTY,
                "receipt": CRM_WRITEBACK_RECEIPT_SCHEMA,
            }),
        },
        {
            "name": "prepare_crm_writeback",
            "description": "Prepare a deterministic Artifact Tool transaction plan. This tool does not open, edit or write the workbook.",
            "inputSchema": _object_schema(["investigation_id", "target_workbook_path"], {
                "investigation_id": NONEMPTY,
                "target_workbook_path": NONEMPTY,
                "records": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            }),
        },
        {
            "name": "evaluate_commercial_readiness",
            "description": "Compatibility entry point returning the four independent v6 dimensions; contact and CRM no longer cap Commercial Value.",
            "inputSchema": _object_schema(["investigation_id"], {
                "investigation_id": NONEMPTY,
            }),
        },
        {
            "name": "evaluate_commercial_value",
            "description": "Evaluate A+ through NQ Commercial Value from company, product, trade and procurement facts independently of contact, outreach and CRM state.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "evaluate_research_confidence",
            "description": "Evaluate R0 through R5 Research Confidence from claim support, authority, recency, conflicts and exhaustion proof.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "evaluate_outreach_readiness",
            "description": "Evaluate BLOCKED through SEND_READY separately from Commercial Value and CRM synchronization.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "evaluate_decision_saturation",
            "description": "Evaluate claim resolution, material Pivots, promoted Anchors and remaining high-EIV work. Budget exhaustion only pauses.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": NONEMPTY}),
        },
        {
            "name": "evaluate_investigation_closure",
            "description": "Issue or reuse a non-expired short-lived Closure only when Decision Saturation passes; any later operational fact, Peer, Provider, CRM or research event makes it stale.",
            "inputSchema": _object_schema(["investigation_id"], {"investigation_id": {"type": "string"}}),
        },
        {
            "name": "prepare_outreach",
            "description": "Consume one valid Closure ID and bind Account-owned Route, history, authority, exact Subject, Body, Stage and expiry. It returns DRAFT_BLOCKED until every gate passes and never sends.",
            "inputSchema": _object_schema(["investigation_id", "closure_id", "route", "history_digest", "authority_digest", "subject", "body", "stage", "expires_at"], {
                "investigation_id": NONEMPTY, "closure_id": NONEMPTY, "route": ROUTE_SCHEMA,
                "history_digest": {"type": "string"}, "authority_digest": {"type": "string"}, "subject": {"type": "string"},
                "body": {"type": "string"}, "chinese_translation": {"type": "string"}, "stage": {"type": "string"}, "expires_at": {"type": "string"},
            }),
        },
        {
            "name": "render_outreach_action_card",
            "description": "Render only the exact one-time result created by prepare_outreach. The action opens a local UTF-8 mailto draft and never sends or claims a provider receipt.",
            "inputSchema": _object_schema(["investigation_id", "prepared_id", "render_token"], {
                "investigation_id": {"type": "string"}, "prepared_id": {"type": "string"}, "render_token": {"type": "string"},
            }),
            "_meta": {"ui": {"resourceUri": TEMPLATE_URI}, "openai/outputTemplate": TEMPLATE_URI,
                "openai/toolInvocation/invoking": "正在核验全路线 Closure 与开发信…", "openai/toolInvocation/invoked": "全路线门禁核验完成"},
        },
        {
            "name": "queue_pending_receipt",
            "description": "Persist one append-only receipt locally when MCP/provider transport is unavailable. Only append-only write tools are accepted; request SHA-256 prevents duplicate queue entries.",
            "inputSchema": _object_schema(["target_tool", "payload"], {
                "target_tool": {"type": "string", "enum": [
                    "append_information_record", "append_execution_receipt", "append_provider_receipt", "append_peer_receipt",
                    "append_crm_writeback_receipt",
                ]},
                "payload": {"oneOf": [
                    _object_schema(["investigation_id", "record"], {
                        "investigation_id": NONEMPTY,
                        "record": INFORMATION_RECORD_SCHEMA,
                    }),
                    _object_schema(["investigation_id", "attempt"], {
                        "investigation_id": NONEMPTY,
                        "attempt": SOURCE_ATTEMPT_SCHEMA,
                        "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                        "pivots": {"type": "array", "items": PIVOT_SCHEMA},
                        "pivots_consumed": {"type": "array", "items": PIVOT_CONSUMPTION_SCHEMA},
                        "manual_visual_items_resolved": STRING_ARRAY,
                    }),
                    _object_schema(["investigation_id", "receipt"], {
                        "investigation_id": NONEMPTY,
                        "receipt": PROVIDER_RECEIPT_SCHEMA,
                        "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                        "pivots": {"type": "array", "items": PIVOT_SCHEMA},
                        "pivots_consumed": {"type": "array", "items": PIVOT_CONSUMPTION_SCHEMA},
                    }),
                    _object_schema(["investigation_id", "receipt_type"], {
                        "investigation_id": NONEMPTY,
                        "receipt_type": {"type": "string", "enum": ["PEER_VALIDATION", "ANCHOR_EXPANSION"]},
                        "receipt": PEER_RECEIPT_SCHEMA,
                        "anchor_id": STRING,
                        "cycle_dedup_checked": {"type": "boolean"},
                    }),
                    _object_schema(["investigation_id", "receipt"], {
                        "investigation_id": NONEMPTY,
                        "receipt": CRM_WRITEBACK_RECEIPT_SCHEMA,
                    }),
                ]},
                "journal_id": STRING,
            }),
        },
        {
            "name": "get_pending_journal_status",
            "description": "Read pending, failed, synchronized and content-equivalent journal receipts without mutating investigation state.",
            "inputSchema": _object_schema([], {"investigation_id": STRING}),
        },
        {
            "name": "sync_pending_receipts",
            "description": "Replay Pending Receipt Journal entries through the same Runtime validators, deduplicate only proven-equivalent receipts, and retain failed entries for correction/retry.",
            "inputSchema": _object_schema([], {
                "investigation_id": STRING,
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                "dry_run": {"type": "boolean"},
            }),
        },
        {
            "name": "queue_host_bundle",
            "description": "Persist a research bundle in the process-independent host queue when the MCP route is unavailable; credentials are rejected.",
            "inputSchema": _object_schema(["payload"], {
                "payload": _object_schema(["investigation_id", "bundle"], {
                    "investigation_id": NONEMPTY,
                    "bundle": {"type": "object", "additionalProperties": True},
                }),
                "bundle_queue_id": STRING,
            }),
        },
        {
            "name": "sync_pending_bundles",
            "description": "Replay host-queued research bundles idempotently with partial-success reporting and without deleting failed envelopes.",
            "inputSchema": _object_schema([], {
                "investigation_id": STRING,
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                "dry_run": {"type": "boolean"},
            }),
        },
        {
            "name": "sync_pending_research_bundles",
            "description": "Compatibility alias for sync_pending_bundles used by host recovery scripts.",
            "inputSchema": _object_schema([], {
                "investigation_id": STRING,
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                "dry_run": {"type": "boolean"},
            }),
        },
        {
            "name": "migrate_v5_4_1_to_v6",
            "description": "Copy non-empty v5.4.1 sessions, their matching canonical registry and pending data to a non-overlapping v6.1 root, verify every hash chain and source manifest, and never switch automatically.",
            "inputSchema": _object_schema(["target_root"], {
                "source_session_root": STRING,
                "target_root": NONEMPTY,
            }),
        },
    ]

    # The Secure MCP Tunnel currently performs a strict discovery-time parse of
    # tools/list. Keep the wire descriptor to the conservative MCP fields used
    # by OpenAI's bundled tunnel stub. Rich UI resources remain available over
    # resources/list and resources/read, while every tool stays fully callable.
    read_only_tools = {
        "get_runtime_contract", "get_runtime_health", "get_investigation_health", "get_information_history",
        "get_claims", "get_account_state", "get_investigation_state", "get_next_research_objectives",
        "get_portfolio_queue", "get_material_pivots", "plan_public_source_calls", "prepare_crm_writeback",
        "evaluate_commercial_readiness", "evaluate_commercial_value", "evaluate_research_confidence",
        "evaluate_outreach_readiness", "evaluate_decision_saturation", "get_pending_journal_status",
    }
    tool_names = tuple(tool["name"] for tool in tools)
    if tool_names != CBI_MCP_TOOL_NAMES:
        raise RuntimeError("MCP tool registry drifted from the Runtime contract")
    for tool in tools:
        tool.pop("title", None)
        tool.pop("_meta", None)
        tool["description"] = (
            "Not for ANSWER_FIRST ordinary buyer/contact lookups; use only after an explicit persistent, "
            "formal-audit, outreach, or plugin-diagnostic request. " + tool["description"]
        )
        tool["outputSchema"] = {"type": "object", "additionalProperties": True}
        tool["annotations"] = {
            "readOnlyHint": tool["name"] in read_only_tools,
            "destructiveHint": False,
            "openWorldHint": False,
        }
    return tools


TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "get_runtime_contract": RUNTIME.get_runtime_contract,
    "get_runtime_health": RUNTIME.get_runtime_health,
    "get_investigation_health": RUNTIME.get_investigation_health,
    "resolve_or_create_account": RUNTIME.resolve_or_create_account,
    "start_investigation": RUNTIME.start_investigation,
    "resume_investigation": RUNTIME.resume_investigation,
    "submit_research_objective": RUNTIME.submit_research_objective,
    "compile_and_append_research_bundle": RUNTIME.compile_and_append_research_bundle,
    "get_claims": RUNTIME.get_claims,
    "get_account_state": RUNTIME.get_account_state,
    "get_investigation_state": RUNTIME.get_investigation_state,
    "get_next_research_objectives": RUNTIME.get_next_research_objectives,
    "get_portfolio_queue": RUNTIME.get_portfolio_queue,
    "append_information_record": RUNTIME.append_information_record,
    "get_information_history": RUNTIME.get_information_history,
    "plan_public_source_calls": RUNTIME.plan_public_source_calls,
    "plan_provider_calls": RUNTIME.plan_provider_calls,
    "append_execution_receipt": RUNTIME.append_execution_receipt,
    "append_provider_receipt": RUNTIME.append_provider_receipt,
    "append_peer_receipt": RUNTIME.append_peer_receipt,
    "append_peer_discovery": RUNTIME.append_peer_discovery,
    "evaluate_peer": RUNTIME.evaluate_peer,
    "promote_anchor": RUNTIME.promote_anchor,
    "get_material_pivots": RUNTIME.get_material_pivots,
    "close_pivot": RUNTIME.close_pivot,
    "append_crm_writeback_receipt": RUNTIME.append_crm_writeback_receipt,
    "prepare_crm_writeback": RUNTIME.prepare_crm_writeback,
    "evaluate_commercial_readiness": RUNTIME.evaluate_commercial_readiness,
    "evaluate_commercial_value": RUNTIME.evaluate_commercial_value,
    "evaluate_research_confidence": RUNTIME.evaluate_research_confidence,
    "evaluate_outreach_readiness": RUNTIME.evaluate_outreach_readiness,
    "evaluate_decision_saturation": RUNTIME.evaluate_decision_saturation,
    "evaluate_investigation_closure": RUNTIME.evaluate_investigation_closure,
    "prepare_outreach": RUNTIME.prepare_outreach,
    "render_outreach_action_card": RUNTIME.render_outreach_action_card,
    "queue_pending_receipt": RUNTIME.queue_pending_receipt,
    "get_pending_journal_status": RUNTIME.get_pending_journal_status,
    "sync_pending_receipts": RUNTIME.sync_pending_receipts,
    "queue_host_bundle": RUNTIME.queue_host_bundle,
    "sync_pending_bundles": RUNTIME.sync_pending_bundles,
    "sync_pending_research_bundles": RUNTIME.sync_pending_research_bundles,
    "migrate_v5_4_1_to_v6": RUNTIME.migrate_v5_4_1_to_v6,
}


def handle(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion") or "2025-06-18",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {"name": "customs-buyer-intelligence", "version": RUNTIME_VERSION},
            "instructions": (
                "Default to ANSWER_FIRST for ordinary buyer, company, contact, email, phone, person, and route lookups. "
                "In ANSWER_FIRST, use host-visible public web/search/browser sources, immediately return the latest "
                "decision-useful findings with concrete links and boundaries, and provide two tailored content-only "
                "drafts: one development email and one instant-chat message. Do not call any Customs Buyer Intelligence "
                "MCP tool, access CRM/workbooks, create Runtime history, receipts, audit/Closure records, executable links, "
                "or one-click actions in ANSWER_FIRST. Only an explicit batch-writeback, full-audit, formal CRM/Closure, "
                "outreach-preparation, or plugin-diagnostic request enables the relevant MCP tools. MCP initialization "
                "never replays Runtime receipts or host bundles. Persistent workflows must use get_runtime_contract, "
                "compile real host observations through the v6.1 Evidence Compiler, rank work by EIV, keep Commercial "
                "Value/Research Confidence/Outreach Readiness/CRM state independent, and use Decision Saturation rather "
                "than a Source Family checklist. After transport loss use resume_investigation; never invent Evidence, "
                "Routes, Closure IDs, drafts or sends."
            ),
        }
    if method == "ping": return {}
    if method == "tools/list": return {"tools": tool_descriptors()}
    if method == "resources/list": return {"resources": [{"uri": TEMPLATE_URI, "name": "History-preserving verified buyer outreach card", "mimeType": "text/html;profile=mcp-app"}]}
    if method == "resources/templates/list": return {"resourceTemplates": []}
    if method == "resources/read":
        if params.get("uri") != TEMPLATE_URI: raise ValidationError("Unknown resource URI")
        return {"contents": [{"uri": TEMPLATE_URI, "mimeType": "text/html;profile=mcp-app", "text": UI_HTML, "_meta": {"ui": {"prefersBorder": True}}}]}
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOL_HANDLERS: raise ValidationError("Unknown tool")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        result = TOOL_HANDLERS[name](arguments)
        summary = f"{name}: " + str(result.get("status") or ("ACCEPTED" if result.get("accepted") else result.get("terminal_state") or "OK"))
        response: dict[str, Any] = {"content": [{"type": "text", "text": summary}], "structuredContent": result}
        if name == "render_outreach_action_card": response["_meta"] = {"ui": {"resourceUri": TEMPLATE_URI}}
        return response
    raise ValidationError(f"Unsupported method: {method}")


def respond(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> None:
    payload = {"jsonrpc": "2.0", "id": request_id}; payload["error" if error else "result"] = error or result
    # ASCII escaping keeps the stdio frame unambiguous through strict JSON-RPC
    # relays while preserving the exact Unicode strings after JSON decoding.
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"); sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message: continue
            try: respond(message["id"], handle(message.get("method", ""), message.get("params") or {}))
            except Exception as exc: respond(message["id"], error={"code": -32602, "message": str(exc), "data": {"runtime_version": RUNTIME_VERSION, "build_id": BUILD_ID}})
        except Exception as exc: print(f"Invalid MCP input: {exc}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__": raise SystemExit(main())
