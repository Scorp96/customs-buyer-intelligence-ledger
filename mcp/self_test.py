#!/usr/bin/env python3
"""MCP protocol, v6 architecture, compatibility, CRM and outreach tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SERVER = Path(__file__).with_name("server.py")
PLUGIN_ROOT = SERVER.parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from unified_runtime import CBI_MCP_TOOL_NAMES  # noqa: E402
BRANCH_PROFILE = {
    "regional_peer": ("maps_region", "local_directory", "association_exhibition_chamber"),
    "industry_peer": ("industry_directory", "search_engine", "association_exhibition_chamber"),
    "scale_peer": ("registry_scale", "industry_directory", "maps_region"),
    "same_supplier_buyer": ("supplier_official", "trade_history", "partner_reference"),
    "same_product_hs_application_buyer": ("trade_history", "hs_application_search", "industry_directory"),
    "competing_supplier_alternative": ("supplier_official", "trade_history", "product_alternative_search"),
}


def call(process: subprocess.Popen[str], request_id: int, method: str, params: dict | None = None) -> dict:
    # ASCII escaping exactly exercises the tunnel case where an escaped lone
    # surrogate reaches json.loads without requiring the test pipe itself to
    # encode that invalid Unicode code unit.
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, ensure_ascii=True) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        raise AssertionError("MCP server ended without a response: " + process.stderr.read())
    return json.loads(line)


def negative_attempt(investigation_id: str, counter: int, branch: str, family: str) -> dict:
    started = datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc) + timedelta(seconds=counter * 10)
    completed = started + timedelta(seconds=2)
    attempt_id = f"MCP-ATT-{counter:03d}"
    raw_hash = hashlib.sha256(attempt_id.encode()).hexdigest()
    return {
        "investigation_id": investigation_id,
        "attempt": {
            "attempt_id": attempt_id,
            "investigation_id": investigation_id,
            "owner_type": "ACCOUNT",
            "owner_id": "MCP-SYNTH-001",
            "module_or_branch": branch,
            "source_family": family,
            "query": f"Synthetic MCP buyer {branch} {family}",
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "checked_at": completed.isoformat(),
            "tool_or_operator": "mcp-self-test",
            "execution_id": f"MCP-EXEC-{counter:03d}",
            "result": "NEGATIVE_EXHAUSTED",
            "result_count": 0,
            "raw_result_locator": f"snapshot://mcp-{counter:03d}",
            "content_sha256": raw_hash,
            "evidence_ids": [],
            "pivots_generated": [],
            "blocked_reason": "",
            "discovered_peer_ids": [],
            "relationship_evidence_ids": {},
        },
        "evidence": [],
        "pivots": [],
        "pivots_consumed": [],
    }


def check(value: bool, name: str, passed: list[str]) -> None:
    if not value:
        raise AssertionError(name)
    passed.append(name)


def main() -> int:
    passed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cbi_v54_mcp_") as session_root:
        crm_path = Path(session_root) / "synthetic-main-crm.xlsx"
        with zipfile.ZipFile(crm_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
            archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/></workbook>')
        crm_hash = hashlib.sha256(crm_path.read_bytes()).hexdigest()
        crm_audit_path = Path(session_root) / "synthetic-crm-audit.json"
        crm_audit_path.write_text('{"synthetic":true,"status":"NO_CHANGE_VERIFIED"}\n', encoding="utf-8")
        crm_audit_hash = hashlib.sha256(crm_audit_path.read_bytes()).hexdigest()
        environment = dict(os.environ)
        environment["CBI_SESSION_ROOT"] = session_root
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=environment,
        )
        try:
            initialized = call(process, 1, "initialize", {"protocolVersion": "2025-06-18"})["result"]
            check(initialized["serverInfo"]["version"] == "6.1.0", "initialize_v610", passed)
            check(
                "Default to ANSWER_FIRST" in initialized["instructions"]
                and "Do not call any Customs Buyer Intelligence MCP tool" in initialized["instructions"]
                and "never replays Runtime receipts or host bundles" in initialized["instructions"],
                "initialize_declares_answer_first_and_no_startup_replay",
                passed,
            )
            tools = call(process, 2, "tools/list")["result"]["tools"]
            names = [item["name"] for item in tools]
            check(names == list(CBI_MCP_TOOL_NAMES), "all_forty_two_public_tools_listed", passed)
            check(all(item.get("outputSchema", {}).get("type") == "object" for item in tools), "all_tools_have_output_schema", passed)
            check(all(set(item.get("annotations", {})) >= {"readOnlyHint", "destructiveHint", "openWorldHint"} for item in tools), "all_tools_have_safety_annotations", passed)
            check(not any("title" in item or "_meta" in item for item in tools), "tunnel_conservative_tool_descriptors", passed)
            check(
                all(item["description"].startswith("Not for ANSWER_FIRST") for item in tools),
                "all_tool_descriptors_exclude_answer_first",
                passed,
            )
            check(not any("send" == name or name.startswith("send_") for name in names), "no_send_tool_exposed", passed)
            resource = call(process, 3, "resources/read", {"uri": "ui://customs-buyer-intelligence/outreach-v6.1.html"})["result"]["contents"][0]
            check("历史和新发现都会保留并入" in resource["text"] and "永不发送" in resource["text"], "history_preserving_ui_resource", passed)
            contract = call(process, 4, "tools/call", {"name": "get_runtime_contract", "arguments": {}})["result"]["structuredContent"]
            check(
                contract["runtime_version"] == "6.1.0"
                and "NEGATIVE_EXHAUSTED" in contract["enums"]["source_family_terminal_result"]
                and contract["public_source_execution_boundary"]["embedded_search_engine"] is False
                and contract["commercial_dimensions"]["contact_or_crm_caps_commercial_value"] is False
                and contract["workflow_policy"]["default_mode"] == "ANSWER_FIRST"
                and contract["workflow_policy"]["answer_first"]["cbi_mcp_tools_allowed"] == []
                and len(contract["workflow_policy"]["answer_first"]["cbi_mcp_tools_forbidden"]) == 42
                and contract["workflow_policy"]["mcp_initialize_mutates_state"] is False,
                "runtime_contract_self_describing",
                passed,
            )
            canonical_candidate = {
                "country": "Canada",
                "name": "Synthetic MCP Canonical Buyer",
                "tax_ids": ["SYNTH-MCP-CANONICAL-001"],
            }
            canonical_created = call(process, 5, "tools/call", {
                "name": "resolve_or_create_account",
                "arguments": {"candidate": canonical_candidate, "create_if_missing": True},
            })["result"]["structuredContent"]
            check(
                canonical_created["status"] == "CREATED"
                and canonical_created["match"]["account_id"] == "C001",
                "resolve_or_create_account_creates_atomically_over_mcp",
                passed,
            )
            canonical_matched = call(process, 6, "tools/call", {
                "name": "resolve_or_create_account",
                "arguments": {"candidate": canonical_candidate, "create_if_missing": False},
            })["result"]["structuredContent"]
            check(
                canonical_matched["status"] == "MATCHED"
                and canonical_matched["match"]["account_id"] == "C001",
                "resolve_or_create_account_matches_over_mcp",
                passed,
            )
            canonical_invalid = call(process, 7, "tools/call", {
                "name": "resolve_or_create_account",
                "arguments": {"candidate": {"name": "Missing country"}, "create_if_missing": False},
            })
            check(
                "error" in canonical_invalid
                and "candidate.country" in canonical_invalid["error"]["message"],
                "resolve_or_create_account_invalid_rejected_over_mcp",
                passed,
            )
            attempt_tool = next(item for item in tools if item["name"] == "append_execution_receipt")
            check(
                "result" in attempt_tool["inputSchema"]["properties"]["attempt"]["properties"]
                and "NEGATIVE_EXHAUSTED" in attempt_tool["inputSchema"]["properties"]["attempt"]["properties"]["result"]["enum"],
                "nested_attempt_enums_exposed",
                passed,
            )

            start_args = {"account": {"account_id": "MCP-SYNTH-001", "country": "Canada", "name": "Synthetic MCP Buyer"}, "mode": "EXHAUSTIVE", "history": {"events": []}, "crm_path": str(crm_path)}
            started = call(process, 10, "tools/call", {"name": "start_investigation", "arguments": start_args})["result"]["structuredContent"]
            investigation_id = started["investigation_id"]
            check(started["research_complete"] is False and len(started["source_profile"]["contact_coverage"]) >= 21, "start_investigation_valid", passed)
            public_work = call(process, 8, "tools/call", {"name": "plan_public_source_calls", "arguments": {"investigation_id": investigation_id, "limit": 10}})["result"]["structuredContent"]
            check(
                public_work["status"] == "READY"
                and public_work["runtime_executed_public_search"] is False
                and public_work["host_execution_required"] is True,
                "public_source_plan_is_not_execution_proof",
                passed,
            )
            unicode_rejected = call(process, 9, "tools/call", {"name": "start_investigation", "arguments": {
                "account": {"account_id": "MCP-UNICODE-SYNTH", "country": "Việt Nam", "name": "Buyer\udcb6 中文 📦"},
                "input": {"note": "tiếng Việt\ud800/emoji ✅"},
                "mode": "EXHAUSTIVE", "history": {"events": []},
            }})
            check(
                "error" in unicode_rejected
                and "INVALID_UNICODE_SURROGATE" in unicode_rejected["error"]["message"],
                "mcp_isolated_surrogate_rejected_before_hash",
                passed,
            )
            invalid_start = call(process, 11, "tools/call", {"name": "start_investigation", "arguments": {"account": {"account_id": "BAD", "country": "Canada"}, "mode": "ONE_EMAIL_ONLY"}})
            check("error" in invalid_start, "start_investigation_invalid_rejected", passed)

            historical_hash = hashlib.sha256(b"historical supplier route").hexdigest()
            historical_record = {
                "information_id": "INFO-MCP-HIST-001", "investigation_id": investigation_id,
                "related_account_id": "MCP-SYNTH-001", "subject_type": "SUPPLIER",
                "subject_owner_id": "SUPPLIER-SYNTH-001", "relationship_to_account": "SUPPLIER_OF_ACCOUNT",
                "information_type": "CONTACT", "value": {"channel": "EMAIL", "value": "sales@synthetic.invalid", "verified": True},
                "claim_key": "historical.supplier.email",
                "source_type": "LEGACY_CRM", "source_reference_type": "LEGACY_CRM", "source_url": "", "source_locator": "legacy-crm://mcp/history/1",
                "observed_at": "2025-08-22T00:00:00Z", "content_sha256": historical_hash,
                "confidence": "MEDIUM_HIGH", "temporal_status": "HISTORICAL", "route_scope": "SUPPLIER_REFERRAL",
                "outreach_eligible_claimed": True, "supersedes_information_ids": [],
                "conflicts_with_information_ids": [], "evidence_ids": [], "notes": "Synthetic historical route."
            }
            history_append = call(process, 17, "tools/call", {"name": "append_information_record", "arguments": {"investigation_id": investigation_id, "record": historical_record}})["result"]["structuredContent"]
            check(history_append["accepted"] is True and history_append["effective_outreach_eligible"] is False, "historical_cross_owner_information_retained", passed)
            history_view = call(process, 18, "tools/call", {"name": "get_information_history", "arguments": {"investigation_id": investigation_id}})["result"]["structuredContent"]
            check(history_view["summary"]["historical_records"] == 1 and history_view["summary"]["total_records"] == 1, "information_history_and_current_view_returned", passed)
            duplicate_info = call(process, 19, "tools/call", {"name": "append_information_record", "arguments": {"investigation_id": investigation_id, "record": historical_record}})
            check("error" in duplicate_info and "duplicate information_id" in duplicate_info["error"]["message"], "duplicate_information_id_rejected", passed)
            pending_record = dict(historical_record)
            pending_record["information_id"] = "INFO-MCP-PENDING-001"
            pending_record["content_sha256"] = hashlib.sha256(b"pending-history").hexdigest()
            pending_payload = {"investigation_id": investigation_id, "record": pending_record}
            pending = call(process, 22, "tools/call", {"name": "queue_pending_receipt", "arguments": {
                "target_tool": "append_information_record", "payload": pending_payload,
            }})["result"]["structuredContent"]
            check(pending["queued"] is True, "pending_receipt_queued", passed)
            pending_sync = call(process, 23, "tools/call", {"name": "sync_pending_receipts", "arguments": {}})["result"]["structuredContent"]
            check(pending_sync["counts"] == {"SYNCED": 1}, "pending_receipt_synced", passed)
            pending_status = call(process, 24, "tools/call", {"name": "get_pending_journal_status", "arguments": {"investigation_id": investigation_id}})["result"]["structuredContent"]
            check(pending_status["counts"] == {"SYNCED": 1}, "pending_journal_status_read", passed)

            crm_receipt = {
                "writeback_id": "MCP-CRM-WB-001", "investigation_id": investigation_id,
                "account_id": "MCP-SYNTH-001", "transaction_id": "MCP-CRM-TX-001",
                "writer": "ARTIFACT_TOOL", "target_workbook_path": str(crm_path),
                "workbook_sha256_before": crm_hash, "workbook_sha256_after": crm_hash,
                "committed_at": datetime.now(timezone.utc).isoformat(), "status": "NO_CHANGE_VERIFIED",
                "atomic_commit": True, "sparse_patch": True, "history_guard_passed": True,
                "post_commit_reimport_verified": True, "unintended_diff_count": 0,
                "touched_sheets": [], "row_assertions": [], "cell_assertions": [], "previous_current_diff": [],
                "audit_artifact_locator": str(crm_audit_path), "audit_artifact_sha256": crm_audit_hash,
            }
            crm_appended = call(process, 25, "tools/call", {"name": "append_crm_writeback_receipt", "arguments": {"investigation_id": investigation_id, "receipt": crm_receipt}})["result"]["structuredContent"]
            check(crm_appended["accepted"] is True and crm_appended["crm_sync_complete"] is True, "append_crm_writeback_receipt_valid", passed)
            crm_duplicate = call(process, 26, "tools/call", {"name": "append_crm_writeback_receipt", "arguments": {"investigation_id": investigation_id, "receipt": crm_receipt}})
            check("error" in crm_duplicate and "duplicate writeback_id" in crm_duplicate["error"]["message"], "append_crm_writeback_receipt_duplicate_rejected", passed)
            commercial = call(process, 27, "tools/call", {"name": "evaluate_commercial_readiness", "arguments": {"investigation_id": investigation_id}})["result"]["structuredContent"]
            check(
                commercial["dimensions_are_independent"] is True
                and commercial["legacy_a_or_above_contact_crm_cap_removed"] is True
                and "commercial_value" in commercial,
                "commercial_dimensions_are_independent",
                passed,
            )

            public_plan = call(process, 12, "tools/call", {"name": "plan_provider_calls", "arguments": {
                "investigation_id": investigation_id,
                "requested_capabilities": ["email_enrichment"],
                "provider_inventory": [],
                "cost_consent": False,
            }})["result"]["structuredContent"]
            check(public_plan["status"] == "PROVIDER_USE_DISABLED" and public_plan["calls"] == [], "public_only_provider_plan_disabled", passed)

            provider_start = call(process, 13, "tools/call", {"name": "start_investigation", "arguments": {
                "account": {"account_id": "MCP-PROVIDER-SYNTH", "country": "Canada"},
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
                "provider_policy": {"mode": "CONNECTED_PROVIDERS_OPTIONAL", "allowed_providers": ["Synthetic Provider"], "required_capabilities": [], "cost_consent": False},
            }})["result"]["structuredContent"]
            provider_investigation_id = provider_start["investigation_id"]
            provider_plan = call(process, 14, "tools/call", {"name": "plan_provider_calls", "arguments": {
                "investigation_id": provider_investigation_id,
                "requested_capabilities": ["email_enrichment"],
                "provider_inventory": [{
                    "provider": "Synthetic Provider", "provider_class": "CONTACT_ENRICHMENT", "status": "CONNECTED",
                    "capability_tools": {"email_enrichment": "synthetic_provider_tool"},
                    "requires_paid_credit": False, "permissions": ["read synthetic data"]
                }],
                "cost_consent": False,
            }})["result"]["structuredContent"]
            check(provider_plan["status"] == "READY" and provider_plan["runtime_invokes_other_plugins"] is False, "provider_plan_valid", passed)
            provider_call = provider_plan["calls"][0]
            provider_now = datetime.now(timezone.utc) + timedelta(seconds=1)
            provider_done = provider_now + timedelta(seconds=1)
            provider_hash = hashlib.sha256(b"synthetic-provider-empty-result").hexdigest()
            provider_receipt_args = {
                "investigation_id": provider_investigation_id,
                "receipt": {
                    "provider_receipt_id": "MCP-PR-001", "investigation_id": provider_investigation_id,
                    "account_id": "MCP-PROVIDER-SYNTH", "provider": "Synthetic Provider",
                    "provider_class": "CONTACT_ENRICHMENT", "requested_capability": "email_enrichment",
                    "target_module": "contact_coverage", "plan_id": provider_plan["plan_id"],
                    "planned_call_id": provider_call["planned_call_id"], "tool_name": provider_call["tool_name"],
                    "tool_call_id": "MCP-PROVIDER-CALL-001", "query": "MCP synthetic provider empty result",
                    "requested_at": provider_now.isoformat(), "completed_at": provider_done.isoformat(),
                    "result": "NEGATIVE", "result_count": 0,
                    "raw_result_locator": "provider-receipt://synthetic/mcp-pr-001/raw", "content_sha256": provider_hash,
                    "evidence_ids": [], "pivots_generated": [], "contacts_returned": [], "companies_returned": [],
                    "billing_or_credit_notice": "No credit consumed.", "blocked_reason": "",
                    "permissions": {"user_authorized": True, "scopes": ["read synthetic data"]},
                    "freshness": "CURRENT", "conflicts": [], "status": "SUCCESS"
                },
                "evidence": [], "pivots": [], "pivots_consumed": []
            }
            provider_appended = call(process, 15, "tools/call", {"name": "append_provider_receipt", "arguments": provider_receipt_args})["result"]["structuredContent"]
            check(provider_appended["accepted"] is True and provider_appended["closes_public_source_families"] is False, "append_provider_receipt_valid", passed)
            provider_duplicate = call(process, 16, "tools/call", {"name": "append_provider_receipt", "arguments": provider_receipt_args})
            check("error" in provider_duplicate and "duplicate provider_receipt_id" in provider_duplicate["error"]["message"], "append_provider_receipt_duplicate_rejected", passed)

            first = negative_attempt(investigation_id, 1, "regional_peer", "maps_region")
            appended = call(process, 20, "tools/call", {"name": "append_execution_receipt", "arguments": first})["result"]["structuredContent"]
            check(appended["accepted"] is True, "append_execution_receipt_valid", passed)
            duplicate = call(process, 21, "tools/call", {"name": "append_execution_receipt", "arguments": first})
            check("error" in duplicate and "duplicate attempt_id" in duplicate["error"]["message"], "append_execution_receipt_invalid_rejected", passed)
            counter = 1
            for branch, families in BRANCH_PROFILE.items():
                for family in families:
                    if branch == "regional_peer" and family == "maps_region":
                        continue
                    counter += 1
                    response = call(process, 30 + counter, "tools/call", {"name": "append_execution_receipt", "arguments": negative_attempt(investigation_id, counter, branch, family)})
                    check("result" in response, f"branch_attempt_{counter}", passed)
            anchor = call(process, 100, "tools/call", {"name": "append_peer_receipt", "arguments": {"investigation_id": investigation_id, "receipt_type": "ANCHOR_EXPANSION", "anchor_id": "MCP-SYNTH-001", "cycle_dedup_checked": True}})["result"]["structuredContent"]
            check(anchor["accepted"] is True, "append_peer_receipt_valid_anchor", passed)
            invalid_peer = call(process, 101, "tools/call", {"name": "append_peer_receipt", "arguments": {"investigation_id": investigation_id, "receipt_type": "PEER_VALIDATION", "receipt": {}}})
            check("error" in invalid_peer, "append_peer_receipt_invalid_rejected", passed)

            closure = call(process, 110, "tools/call", {"name": "evaluate_investigation_closure", "arguments": {"investigation_id": investigation_id}})["result"]["structuredContent"]
            check(closure["closed"] is False and closure["status"] in {"NOT_SATURATED", "BLOCKED", "PAUSED_RESOURCE_LIMIT"}, "evaluate_closure_valid_pending", passed)
            invalid_closure = call(process, 111, "tools/call", {"name": "evaluate_investigation_closure", "arguments": {"investigation_id": "INV-invalid"}})
            check("error" in invalid_closure, "evaluate_closure_invalid_rejected", passed)

            blocked_prepare = call(process, 120, "tools/call", {"name": "prepare_outreach", "arguments": {
                "investigation_id": investigation_id, "closure_id": "CLOS-fake", "route": {},
                "history_digest": started["history_digest"], "authority_digest": started["authority_digest"],
                "subject": "Synthetic", "body": "Synthetic", "stage": "FIRST_TOUCH",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            }})["result"]["structuredContent"]
            check(blocked_prepare["status"] == "DRAFT_BLOCKED", "prepare_outreach_valid_but_fail_closed", passed)
            invalid_prepare = call(process, 121, "tools/call", {"name": "prepare_outreach", "arguments": {}})
            check("error" in invalid_prepare, "prepare_outreach_invalid_rejected", passed)

            blocked_render = call(process, 130, "tools/call", {"name": "render_outreach_action_card", "arguments": {"investigation_id": investigation_id, "prepared_id": "PREP-fake", "render_token": "RENDER-fake"}})["result"]["structuredContent"]
            check(blocked_render["terminal_state"] == "DRAFT_BLOCKED" and blocked_render["action"]["enabled"] is False, "render_outreach_valid_but_fail_closed", passed)
            invalid_render = call(process, 131, "tools/call", {"name": "render_outreach_action_card", "arguments": {}})
            check("error" in invalid_render, "render_outreach_invalid_rejected", passed)
        finally:
            if process.stdin:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
    print(json.dumps({"runtime_version": "6.1.0", "passed": len(passed), "tests": passed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
