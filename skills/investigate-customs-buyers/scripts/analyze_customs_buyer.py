#!/usr/bin/env python3
"""Run the deterministic customs-buyer pipeline and always emit a JSON result."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "4.2.0"
DEFAULT_MODE = "fast-scan"


class CliUsageError(ValueError):
    """Raised instead of letting argparse terminate without JSON output."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def error_item(
    stage: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    retry_count: int = 0,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "code": code,
        "message": message.strip() or code,
        "retry_count": max(0, int(retry_count)),
        "retryable": bool(retryable),
    }


def exception_message(exc: BaseException) -> str:
    return str(exc).strip() or exc.__class__.__name__


def emergency_result(
    mode: str,
    raw_input: str = "",
    *,
    rules_version: Any = None,
    errors: list[dict[str, Any]] | None = None,
    missing_sections: list[str] | None = None,
    cli: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a self-contained fallback that conforms to the stable schema."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "mode": mode if mode in {"fast-scan", "deep-dive"} else DEFAULT_MODE,
        "rules_version": rules_version,
        "generated_at": date.today().isoformat(),
        "input_snapshot": {
            "sha256": hashlib.sha256(raw_input.encode("utf-8")).hexdigest(),
            "raw_input": raw_input,
            "immutable": True,
        },
        "record_identity": {
            "data_source": None,
            "record_date": None,
            "master_bill": None,
            "house_bill": None,
            "container_numbers": [],
        },
        "normalized_shipment": {
            "supplier": {
                "raw_name": None,
                "legal_name": None,
                "role": "UNKNOWN",
            },
            "buyer": {
                "raw_name": None,
                "legal_name": None,
                "country": None,
                "role": "UNKNOWN",
            },
            "product": {
                "raw_description": None,
                "normalized_category": "UNCLASSIFIED_OR_NON_TARGET",
                "match_level": "UNKNOWN",
                "confidence": 0.0,
                "reason_codes": ["analysis_not_completed"],
                "matched_features": [],
                "specifications": {
                    "length_mm": None,
                    "width_mm": None,
                    "thickness_mm": None,
                    "density_g_cm3": None,
                },
            },
            "quantity": {
                "declared_quantity": None,
                "declared_unit": None,
                "quantity_scope": "unknown",
                "weight_kg": None,
                "gross_weight_kg": None,
                "package_count": None,
                "package_type": None,
                "package_count_is_product_quantity": False,
                "estimated_sheets": None,
                "estimate": None,
            },
            "route": {
                "declared_origin": None,
                "manufacturing_origin": None,
                "manufacturing_origin_status": "UNKNOWN",
                "place_of_receipt": None,
                "port_of_lading": None,
                "transshipment_ports": [],
                "port_of_discharge": None,
                "final_delivery_location": None,
            },
            "field_scope": {
                "shipment_level": [],
                "line_item": [],
                "ambiguous": [],
            },
        },
        "data_quality": {
            "status": "unknown",
            "score": 0,
            "possible_contamination": False,
            "shipment_line_conflict": False,
            "unit_conflict": False,
            "origin_port_conflict": False,
            "origin_field_interpretation": "unknown",
            "scoring_suspended": False,
            "warnings": [],
            "field_scope": {
                "shipment_level": [],
                "line_item": [],
                "ambiguous": [],
            },
        },
        "entity_resolution": {
            "status": "UNKNOWN",
            "legal_name": None,
            "matched": False,
            "confidence": 0.0,
            "match_basis": [],
            "legal_registration": {},
            "address_type": "unknown",
            "official_channels": [],
            "possible_affiliates": [],
        },
        "buyer_intelligence": {
            "buyer_role": "UNKNOWN",
            "secondary_roles": [],
            "candidate_roles": [],
            "role_confidence": 0.0,
            "role_status": "UNVERIFIED",
            "reason_codes": ["analysis_not_completed"],
            "business_model": None,
            "company_scale": None,
            "purchase_pattern": "not_verified",
            "current_supplier": None,
            "direct_import_probability": 0.0,
        },
        "contacts": [],
        "contact_status": {
            "verified_procurement_contact": False,
            "official_general_channel": False,
            "message": "未找到已验证采购负责人",
        },
        "commercial_scoring": {
            "status": "not_scored",
            "components": {},
            "risk_penalties": [],
            "observed_score": None,
            "total_score": None,
            "score_range": [None, None],
            "score_completeness": 0.0,
            "provisional": True,
            "grade": "UNSCORABLE",
            "buyer_authenticity": "UNKNOWN",
            "product_fit": "UNKNOWN",
            "sales_priority": "UNSCORABLE",
            "deep_dive_eligible": False,
            "reason_codes": ["analysis_not_completed"],
        },
        "facts": [],
        "inferences": [],
        "unknowns": [
            {
                "field": "analysis",
                "status": "未显示/待核验",
                "reason_code": "analysis_not_completed",
            }
        ],
        "recommended_actions": [
            {
                "priority": 1,
                "action": "Correct the reported input or stage error, then rerun the analysis.",
                "reason_code": "analysis_not_completed",
            }
        ],
        "exclusion_reason": None,
        "evidence": [],
        "research_status": "incomplete_research",
        "products": [],
        "calculations": [],
        "calculation_scenarios": [],
        "route": {},
        "sources": [],
        "research_coverage": [],
        "manual_checks": [],
        "contact_evidence_ledger": [],
        "entities": {},
        "supplier_intelligence": {},
        "trade_history": [],
        "trade_history_summary": {},
        "field_audit": [],
        "review_ledger": [],
        "competition_matrix": {},
        "evidence_binding_summary": {},
        "hypotheses": [],
        "scores": {},
        "crm": {"crm_status": "blocked", "blocked_fields": []},
        "next_actions": [],
        "unresolved": [],
        "cross_record_contamination": {"matches": [], "status": "not_checked"},
        "quality_gate": {"research_status": "incomplete_research", "passed": False, "checks": [], "failed_gates": ["analysis_not_completed"]},
        "intelligence_dossier": {
            "version": SCHEMA_VERSION,
            "mode": mode,
            "primary_product": "full_intelligence_dossier",
            "outreach_appendix_only": True,
            "material_findings": [{"finding_id": "pipeline-failure", "classification": "UNKNOWN", "statement": "分析流程未完成，不能形成客户评级、持续采购或联系人结论。", "reasoning": "pipeline_failed_or_incomplete", "business_impact": "暂停CRM准入与外联。", "counter_explanation": None, "source_ids": [], "verification_method": "修复运行错误后重新执行完整Deep Dive。"}],
            "buyer_role_scenarios": [{"scenario": "current_best_supported", "role": "UNKNOWN", "status": "UNRESOLVED", "evidence": [], "falsification_test": "重新运行主体与业务角色核验。"}, {"scenario": "reverse_possibility", "role": "IMPORTER_OF_RECORD / TRADER / LOGISTICS PARTY", "status": "HYPOTHESIS", "evidence": [], "falsification_test": "核验采购、付款、库存和供应商准入主体。"}],
            "product_form_scenarios": [],
            "business_decision": {"current_judgment": "当前信息不足，暂停商业定性。", "recommended_target": "待核验", "first_objective": "恢复完整分析", "stop_condition": "分析仍不完整时不得外联。"},
            "value_gate": {"passed": False, "checks": [], "failed_gates": ["analysis_not_completed"], "rule": "A blocked outreach route never shortens the intelligence dossier; raw JSON is not a human-facing report."},
        },
        "strategic_intelligence": {},
        "learning_ledger": {"automatic_rule_promotion": False, "automatic_code_modification": False, "online_model_weight_update": False},
        "decision_layers": {"plugin_raw_output": {}, "assistant_audit": {}, "final_crm": {"status": "PENDING_VERIFICATION", "record": {}, "export_allowed": False}, "unresolved": [], "next_actions": []},
        "outreach_status": "BLOCKED",
        "outreach": {
            "schema_version": SCHEMA_VERSION,
            "outreach_mode": "CREATE_DRAFT",
            "outreach_status": "BLOCKED",
            "eligibility_gate": {"eligible": False, "status": "BLOCK", "block_reasons": ["analysis_not_completed"]},
            "email_routing": {"policy": "Every discovered email must be classified before drafting.", "discovered_email_count": 0, "unique_email_count": 0, "accounted_email_count": 0, "omission_check_passed": True, "primary_route": None, "alternative_routes": [], "verify_only_routes": [], "do_not_use_routes": [], "all_routes": []},
            "timezone": {"beijing_time_now": None, "buyer_local_time_now": None, "recommended_send_window": "timezone verification required", "holiday_status": "not_checked"},
            "email": {"to": "", "subject": "", "body": "", "word_count": 0, "mailto_url": None, "human_review_required": True},
            "alternate_drafts": [],
            "risk": {"risk_level": "BLOCK", "send_blocked": True},
            "human_review_required": True,
            "automatic_send_supported": False,
            "completion": {"terminal_state": "DRAFT_BLOCKED", "report_only_output_forbidden": True, "completion_contract_passed": True, "required_user_visible_sections": ["full_intelligence_dossier", "recipient_evidence", "customer_language_email", "chinese_review_translation", "draft_action_or_block_reason"], "action": {"action_id": "open-email-draft", "label": "一键打开邮件草稿 / Open email draft", "kind": "open_url", "url": None, "enabled": False, "requires_human_review": True, "sends_message": False}, "alternate_actions": [], "email_route_omission_check_passed": True, "discovered_email_count": 0, "accounted_email_count": 0, "simultaneous_multi_send_prohibited": True, "block_reasons": ["analysis_failed_or_incomplete"], "draft_transport": "mailto_wecom_tencent_enterprise_compatible", "server_side_draft_created": False, "provider_draft_id": None, "connector_receipt": None, "connector_next_step": "Resolve the analysis error, then open the reviewed mailto draft in WeCom/Tencent Enterprise Mail. Never claim a provider draft without a connector receipt."},
        },
        "claim_ledger": [],
        "audit_trail": [],
        "provenance": {},
        "errors": errors or [],
        "completed_sections": [],
        "missing_sections": list(dict.fromkeys(missing_sections or ["analysis"])),
        "cli": cli or {},
    }


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument(
        "--mode",
        choices=("fast-scan", "deep-dive"),
        default=DEFAULT_MODE,
    )
    parser.add_argument(
        "--enrichment",
        type=Path,
        help="Optional JSON evidence/contact/entity enrichment packet.",
    )
    parser.add_argument(
        "--related-records",
        type=Path,
        help="Optional JSON/CSV records used only for cross-record checks.",
    )
    parser.add_argument(
        "--evidence-bundle",
        type=Path,
        help="Optional JSON bundle of observed sources, coverage, and visual checks.",
    )
    parser.add_argument(
        "--source-image",
        action="append",
        default=[],
        help="Source screenshot path. Images are queued for visual verification unless an evidence bundle records observations.",
    )
    parser.add_argument("--contamination-db", type=Path, help="Persistent SQLite collision index.")
    parser.add_argument("--crm-output", type=Path, help="Optional single-row CRM CSV output.")
    parser.add_argument("--field-audit-output", type=Path, help="Optional field-audit JSON output.")
    parser.add_argument("--contact-ledger-output", type=Path, help="Optional contact evidence ledger JSON output.")
    parser.add_argument("--review-ledger-output", type=Path, help="Optional plugin/reviewer/final-decision ledger JSON output.")
    parser.add_argument("--trade-history-output", type=Path, help="Optional row-audited trade-history JSON output.")
    parser.add_argument("--competition-output", type=Path, help="Optional evidence-gated competition matrix JSON output.")
    parser.add_argument("--outreach-output", type=Path, help="Optional evidence-gated outreach preview/draft JSON output.")
    parser.add_argument("--strategic-output", type=Path, help="Optional relationship, decision-center, brand/OEM, pricing and route JSON output.")
    parser.add_argument("--decision-layers-output", type=Path, help="Optional plugin/audit/final-CRM layered JSON output.")
    parser.add_argument("--learning-output", type=Path, help="Optional controlled-learning ledger JSON output.")
    parser.add_argument("--feedback-db", type=Path, help="Optional append-only SQLite feedback ledger; it never modifies code or promotes rules automatically.")
    parser.add_argument(
        "--rules",
        type=Path,
        help="Optional JSON rules file; defaults to references/intelligence-rules.json.",
    )
    return parser


def parse_json_object(text: str, label: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object.")
    return value


def normalize_primary_input(
    path: Path,
    text: str,
    encoding: str,
    *,
    flatten_json: Callable[[Any], dict[str, Any]],
    normalize: Callable[..., dict[str, Any]],
    parse_text: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    stripped = text.lstrip()
    should_try_json = path.suffix.casefold() == ".json" or stripped.startswith("{")
    payload: Any = None
    if should_try_json:
        try:
            payload = json.loads(text)
        except Exception as exc:
            errors.append(
                error_item(
                    "input_parse",
                    "json_parse_failed_text_fallback",
                    f"JSON parsing failed; customs-text fallback was used: {exception_message(exc)}",
                )
            )

    if payload is not None:
        if isinstance(payload, list):
            if not payload:
                raise ValueError("Primary input JSON list is empty.")
            errors.append(
                error_item(
                    "input_parse",
                    "multiple_primary_records_first_selected",
                    "Primary input contained multiple records; only the first was analyzed. Use --related-records for comparison rows.",
                )
            )
            payload = payload[0]
        if not isinstance(payload, dict):
            raise ValueError("Primary input must be a JSON object or customs text.")
        if isinstance(payload.get("record"), dict) and isinstance(
            payload.get("parse_quality"), dict
        ):
            return payload, errors
        return normalize(flatten_json(payload), input_encoding=encoding), errors

    return normalize(parse_text(text), input_encoding=encoding), errors


def related_rows_from_json(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("related_records", "records", "shipments"):
            rows = value.get(key)
            if isinstance(rows, list):
                return rows
        return [value]
    raise ValueError("Related-record JSON must be an object or list.")


def load_related_records(
    path: Path,
    *,
    read_text_safely: Callable[[Path], tuple[str, str]],
    flatten_json: Callable[[Any], dict[str, Any]],
    normalize: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text, encoding = read_text_safely(path)
    if path.suffix.casefold() == ".csv":
        rows: list[Any] = list(csv.DictReader(text.splitlines()))
    else:
        rows = related_rows_from_json(json.loads(text))

    normalized_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("record is not an object")
            if isinstance(row.get("record"), dict):
                normalized_rows.append(row)
            else:
                normalized_rows.append(
                    normalize(flatten_json(row), input_encoding=encoding)
                )
        except Exception as exc:
            errors.append(
                error_item(
                    "related_records",
                    "related_record_skipped",
                    f"Related record {index + 1} was skipped: {exception_message(exc)}",
                )
            )
    return normalized_rows, errors


def merge_cli_errors(
    result: dict[str, Any],
    errors: list[dict[str, Any]],
    missing_sections: list[str],
) -> None:
    if errors:
        result.setdefault("errors", []).extend(errors)
    result.setdefault("missing_sections", []).extend(missing_sections)
    result["missing_sections"] = list(
        dict.fromkeys(str(item) for item in result["missing_sections"] if item)
    )
    result["completed_sections"] = list(
        dict.fromkeys(
            str(item) for item in result.get("completed_sections", []) if item
        )
    )
    if result.get("errors") or result.get("missing_sections"):
        result["status"] = (
            "partial" if result.get("completed_sections") else "failed"
        )


def safe_write_text(
    path: Path,
    content: str,
    *,
    stage: str,
    code: str,
) -> dict[str, Any] | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return None
    except Exception as exc:
        return error_item(
            stage,
            code,
            f"Could not write {path}: {exception_message(exc)}",
            retryable=True,
        )


def safe_stdout(result: dict[str, Any]) -> None:
    try:
        rendered = json.dumps(
            result,
            ensure_ascii=True,
            indent=2,
            default=str,
        )
    except Exception as exc:
        rendered = json.dumps(
            emergency_result(
                DEFAULT_MODE,
                errors=[
                    error_item(
                        "json_serialization",
                        "json_serialization_failed",
                        exception_message(exc),
                    )
                ],
                missing_sections=["json_serialization"],
            ),
            ensure_ascii=True,
            indent=2,
        )
    try:
        sys.stdout.write(rendered + "\n")
        sys.stdout.flush()
    except Exception:
        # There is no further reliable output channel when stdout itself fails.
        pass


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_input = ""
    encoding: str | None = None
    cli_metadata = {
        "input_path": str(args.input),
        "input_encoding": None,
        "enrichment_path": str(args.enrichment) if args.enrichment else None,
        "related_records_path": (
            str(args.related_records) if args.related_records else None
        ),
        "rules_path": str(args.rules) if args.rules else None,
        "evidence_bundle_path": str(args.evidence_bundle) if args.evidence_bundle else None,
        "source_images": [str(path) for path in args.source_image],
        "contamination_db": str(args.contamination_db) if args.contamination_db else None,
        "feedback_db": str(args.feedback_db) if args.feedback_db else None,
    }

    try:
        from intelligence_pipeline import (
            IntelligencePipeline,
            load_rules,
        )
        from v3_engine import V3Assembler, render_crm_csv_row, render_v3_report
        from normalize_customs_record import (
            flatten_json,
            normalize,
            parse_text,
            read_text_safely,
        )
    except Exception as exc:
        return emergency_result(
            args.mode,
            errors=[
                error_item(
                    "module_import",
                    "analysis_module_import_failed",
                    exception_message(exc),
                )
            ],
            missing_sections=["module_import", "analysis"],
            cli=cli_metadata,
        )

    try:
        raw_input, encoding = read_text_safely(args.input)
        cli_metadata["input_encoding"] = encoding
    except Exception as exc:
        return emergency_result(
            args.mode,
            errors=[
                error_item(
                    "input_read",
                    "input_read_failed",
                    f"Could not read {args.input}: {exception_message(exc)}",
                    retryable=True,
                )
            ],
            missing_sections=["input_read", "analysis"],
            cli=cli_metadata,
        )

    try:
        rules = load_rules(args.rules)
    except Exception as exc:
        return emergency_result(
            args.mode,
            raw_input,
            errors=[
                error_item(
                    "rules_load",
                    "rules_load_failed",
                    exception_message(exc),
                )
            ],
            missing_sections=["rules_load", "analysis"],
            cli=cli_metadata,
        )

    preflight_errors: list[dict[str, Any]] = []
    preflight_missing: list[str] = []
    try:
        normalized, input_errors = normalize_primary_input(
            args.input,
            raw_input,
            encoding,
            flatten_json=flatten_json,
            normalize=normalize,
            parse_text=parse_text,
        )
        preflight_errors.extend(input_errors)
        if input_errors:
            preflight_missing.append("unambiguous_input_format")
    except Exception as exc:
        return emergency_result(
            args.mode,
            raw_input,
            rules_version=rules.get("version"),
            errors=[
                error_item(
                    "input_parse",
                    "input_parse_failed",
                    exception_message(exc),
                )
            ],
            missing_sections=["input_parse", "analysis"],
            cli=cli_metadata,
        )

    enrichment: dict[str, Any] = {}
    if args.enrichment:
        try:
            enrichment_text, _ = read_text_safely(args.enrichment)
            enrichment = parse_json_object(enrichment_text, "Enrichment input")
        except Exception as exc:
            enrichment = {
                "errors": [
                    error_item(
                        "external_enrichment",
                        "enrichment_load_failed",
                        f"Could not load {args.enrichment}: {exception_message(exc)}",
                        retryable=True,
                    )
                ]
            }

    evidence_bundle: dict[str, Any] = {}
    if args.evidence_bundle:
        try:
            evidence_text, _ = read_text_safely(args.evidence_bundle)
            evidence_bundle = parse_json_object(evidence_text, "Evidence bundle")
        except Exception as exc:
            preflight_errors.append(
                error_item(
                    "evidence_bundle",
                    "evidence_bundle_load_failed",
                    f"Could not load {args.evidence_bundle}: {exception_message(exc)}",
                    retryable=True,
                )
            )
            preflight_missing.append("evidence_bundle")

    related_records: list[dict[str, Any]] = []
    if args.related_records:
        try:
            related_records, related_errors = load_related_records(
                args.related_records,
                read_text_safely=read_text_safely,
                flatten_json=flatten_json,
                normalize=normalize,
            )
            preflight_errors.extend(related_errors)
            if related_errors:
                preflight_missing.append("some_related_records")
        except Exception as exc:
            preflight_errors.append(
                error_item(
                    "related_records",
                    "related_records_load_failed",
                    f"Could not load {args.related_records}: {exception_message(exc)}",
                    retryable=True,
                )
            )
            preflight_missing.append("related_records")

    try:
        pipeline = IntelligencePipeline(rules)
        result = pipeline.run(
            normalized,
            raw_input,
            enrichment=enrichment,
            related_records=related_records,
            mode=args.mode.replace("-", "_"),
        )
        result = V3Assembler(rules).assemble(
            result,
            normalized,
            raw_input,
            mode=args.mode,
            enrichment=enrichment,
            related_records=related_records,
            evidence_bundle=evidence_bundle,
            source_images=args.source_image,
            contamination_db=args.contamination_db,
            feedback_db=args.feedback_db,
        )
    except Exception as exc:
        return emergency_result(
            args.mode,
            raw_input,
            rules_version=rules.get("version"),
            errors=preflight_errors
            + [
                error_item(
                    "pipeline",
                    "pipeline_failed",
                    exception_message(exc),
                )
            ],
            missing_sections=preflight_missing + ["pipeline", "analysis"],
            cli=cli_metadata,
        )

    result["schema_version"] = SCHEMA_VERSION
    result["mode"] = args.mode
    result["cli"] = cli_metadata
    merge_cli_errors(result, preflight_errors, preflight_missing)

    if args.report_output:
        try:
            report = render_v3_report(result)
        except Exception as exc:
            report = (
                "# 海关买家深度情报报告 v4.2\n\n"
                "## 1. 核心商业结论\n\n"
                f"- 运行状态：{result.get('status', 'partial')}\n"
                "- 人类可读报告正文生成失败，当前不能形成客户评级、持续采购、联系人或外联结论。\n"
                "- 请修复报告生成错误后重新执行完整Deep Dive；结构化审计文件仅供排错，不替代客户调查报告。\n"
            )
            merge_cli_errors(
                result,
                [error_item("report_render", "report_render_failed", exception_message(exc))],
                ["human_readable_report"],
            )
        report_error = safe_write_text(
            args.report_output,
            report,
            stage="report_write",
            code="report_write_failed",
        )
        if report_error:
            merge_cli_errors(result, [report_error], ["human_readable_report"])

    if args.crm_output:
        try:
            row = render_crm_csv_row(result)
            args.crm_output.parent.mkdir(parents=True, exist_ok=True)
            with args.crm_output.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
        except Exception as exc:
            merge_cli_errors(result, [error_item("crm_write", "crm_write_failed", exception_message(exc), retryable=True)], ["crm_output_file"])

    for path, key, stage in (
        (args.field_audit_output, "field_audit", "field_audit_write"),
        (args.contact_ledger_output, "contact_evidence_ledger", "contact_ledger_write"),
        (args.review_ledger_output, "review_ledger", "review_ledger_write"),
        (args.trade_history_output, "trade_history", "trade_history_write"),
        (args.competition_output, "competition_matrix", "competition_matrix_write"),
        (args.outreach_output, "outreach", "outreach_write"),
        (args.strategic_output, "strategic_intelligence", "strategic_write"),
        (args.decision_layers_output, "decision_layers", "decision_layers_write"),
        (args.learning_output, "learning_ledger", "learning_write"),
    ):
        if path:
            sidecar_error = safe_write_text(
                path,
                json.dumps(result.get(key) or ([] if key != "competition_matrix" else {}), ensure_ascii=False, indent=2, default=str) + "\n",
                stage=stage,
                code=f"{stage}_failed",
            )
            if sidecar_error:
                merge_cli_errors(result, [sidecar_error], [f"{key}_output_file"])

    if args.output:
        json_text = json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        output_error = safe_write_text(
            args.output,
            json_text + "\n",
            stage="json_write",
            code="json_write_failed",
        )
        if output_error:
            merge_cli_errors(result, [output_error], ["json_output_file"])

    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CliUsageError as exc:
        safe_stdout(
            emergency_result(
                DEFAULT_MODE,
                errors=[
                    error_item(
                        "cli_arguments",
                        "invalid_cli_arguments",
                        exception_message(exc),
                    )
                ],
                missing_sections=["cli_arguments", "analysis"],
            )
        )
        return 0

    try:
        result = run(args)
    except Exception as exc:
        result = emergency_result(
            args.mode,
            errors=[
                error_item(
                    "unhandled",
                    "unhandled_cli_failure",
                    exception_message(exc),
                )
            ],
            missing_sections=["analysis"],
            cli={"input_path": str(args.input)},
        )
    safe_stdout(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
