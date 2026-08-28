#!/usr/bin/env python3
"""Adversarial v4.2 regressions, including historical quality and anti-overreach cases."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from intelligence_pipeline import IntelligencePipeline, load_rules
from normalize_customs_record import flatten_json, normalize
from v3_engine import CrossRecordStore, ProductTaxonomy, V3Assembler, classify_source, link_type, render_v3_report
from batch_analyze_customs import main as batch_main


def check(condition: bool, name: str, passed: list[str]) -> None:
    if not condition:
        raise AssertionError(name)
    passed.append(name)


def run_record(row: dict, *, mode: str = "fast-scan", enrichment: dict | None = None, evidence: dict | None = None, db: Path | None = None, related: list[dict] | None = None) -> dict:
    rules = load_rules(None)
    normalized = normalize(flatten_json(row), input_encoding="utf-8")
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True)
    base = IntelligencePipeline(rules).run(normalized, raw, enrichment=enrichment or {}, related_records=related or [], mode=mode.replace("-", "_"))
    return V3Assembler(rules).assemble(base, normalized, raw, mode=mode, enrichment=enrichment or {}, evidence_bundle=evidence or {}, contamination_db=db, related_records=related or [])


def make_minimal_xlsx(path: Path) -> None:
    files = {
        "[Content_Types].xml": """<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>""",
        "_rels/.rels": """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>采购商</t></is></c><c r="B1" t="inlineStr"><is><t>产品</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Synthetic XLSX Buyer</t></is></c><c r="B2" t="inlineStr"><is><t>PVC Foam Board 1220x2440 10mm</t></is></c></row></sheetData></worksheet>""",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def main() -> int:
    passed: list[str] = []
    taxonomy = ProductTaxonomy()
    edge = taxonomy.classify({"product": "PVC edge band 0.8 x 21 mm furniture edging"}, {})
    check("EDGE" in edge["normalized_category"] and edge["match_level"] != "EXACT", "edge_band_not_foam_board", passed)
    paper = taxonomy.classify({"product": "PS paper foam board for display 5 mm"}, {})
    check(paper["normalized_category"] == "PAPER_FACED_PS_OR_KT_BOARD" and paper["match_level"] != "EXACT", "ps_paper_board_not_target", passed)
    marine = taxonomy.classify({"product": "structural PVC foam core for marine sandwich panel"}, {})
    check(marine["normalized_category"] == "STRUCTURAL_CROSSLINKED_PVC_MARINE_CORE" and marine["match_level"] == "NONE", "marine_core_separated", passed)
    check(classify_source("https://www.dnb.com/company/example") == "third_party_directory", "dnb_is_directory", passed)
    check(link_type("google_business_profile", "https://www.google.com/maps/search/?api=1&query=Synthetic") == "地图搜索入口", "google_search_not_business_profile", passed)
    accessory = taxonomy.classify({"product": "Metal Line Outer Corner for 5mm wall panel 2950x0.5mm"}, {})
    check(accessory["normalized_category"] == "WALL_PANEL_TRIM_ACCESSORY" and accessory["match_level"] == "RELATED", "trim_accessory_not_foam_board", passed)

    base_row = {"数据源": "Synthetic Customs", "日期": "2026-06-17", "主单号": "TESTBILL001", "供应商": "Synthetic Supplier Ltd", "采购商": "Synthetic Buyer One Inc", "采购商地址": "100 Test Road, Manila, Philippines", "产品": "PVC Foam Board 1220x2440 17mm 0.65g", "重量（kg）": 394, "N O P A C K A G E S": 6, "T Y P E P K G S": "BG", "目的地": "Philippines"}
    enrichment = {
        "sources": [
            {"source_id": "src-web", "url": "https://example.invalid/contact", "source_type": "official_domain", "evidence_grade": "A2", "official": True, "checked_at": "2026-08-03", "quoted_or_visible_text": "General enquiries: info@synthetic.invalid"},
            {"source_id": "src-dir", "url": "https://www.dnb.com/company/synthetic", "source_type": "third_party_directory", "evidence_grade": "C2", "checked_at": "2026-08-03"},
        ],
        "contacts": [
            {"email": "info@synthetic.invalid", "source_ids": ["src-web"], "source_type": "official_domain", "verification_status": "official_current", "role": "general company channel"},
            {"social": "https://instagram.com/synthetic-old", "source_ids": ["src-dir"], "verification_status": "official_historical", "role": "historical social"},
        ],
        "field_claims": [
            {"field": "sec_number", "raw_value": "CS200400001", "source_ids": ["src-dir"], "confidence": 0.9},
            {"field": "public_general_email", "raw_value": "info@synthetic.invalid", "source_ids": ["src-web"], "current_status_claim": True},
        ],
        "entity_relationships": [{"entity_a": "Synthetic Buyer One Inc", "entity_b": "Synthetic Brand", "relationship_type": "operated_brand", "source_ids": ["src-web", "src-dir"], "relationship_evidence": ["cross-linked pages", "same phone"]}],
        "trade_history": [
            {"record_id": "t1", "date": "2026-01-10", "master_bill": "HIST001", "item_number": "1", "buyer": "Synthetic Buyer One Inc", "supplier": "Synthetic Supplier Ltd", "product_raw": "5mm wall panel", "quantity": 1000, "uom": "PCE", "data_level": "item", "provider": "Provider A", "source_ids": ["src-dir"]},
            {"record_id": "t1-dup", "date": "2026-01-10", "master_bill": "HIST001", "item_number": "1", "buyer": "Synthetic Buyer One Inc", "supplier": "Synthetic Supplier Ltd", "product_raw": "5mm wall panel", "quantity": 1000, "uom": "PCE", "data_level": "item", "provider": "Provider A", "source_ids": ["src-dir"]},
            {"record_id": "t2", "date": "2026-05-10", "master_bill": "HIST002", "item_number": "2", "buyer": "Synthetic Buyer One Inc", "supplier": "Synthetic Supplier Ltd", "product_raw": "WPC wall panel", "quantity": 800, "uom": "PCE", "data_level": "item", "provider": "Provider A", "source_ids": ["src-dir"]},
        ],
        "assistant_reviews": {"sec_number": {"decision": "accepted", "assistant_review": "Directory lead retained as plausible, not official.", "final_status": "plausible", "change_reason": "Official registry confirmation is missing.", "source_ids": ["src-dir"]}},
        "competition": {"score": 85, "rows": [{"capability": "matching_trim_accessories", "incumbent_status": "OBSERVED", "our_status": "UNKNOWN", "source_ids": ["src-dir"]}]},
        "research_coverage": [
            {"step": "official_homepage", "status": "checked", "result_summary": "Official website opened", "source_ids": ["src-web"]},
            {"step": "official_contact_page", "status": "checked", "result_summary": "General email found", "source_ids": ["src-web"]},
            {"step": "official_footer", "status": "checked_no_hit", "result_summary": "No legal name in footer"},
            {"step": "instagram_bio", "status": "blocked", "url": "https://instagram.com/synthetic"},
            {"step": "google_business_profile", "status": "checked_no_hit", "url": "https://www.google.com/maps/search/?api=1&query=Synthetic", "result_summary": "Search entry only; no confirmed profile"},
        ],
    }
    result = run_record(base_row, enrichment=enrichment)
    check(result["schema_version"] == "4.2.0", "schema_v42", passed)
    check(result["scores"]["conversion_probability"]["point_estimate"] is None, "fake_conversion_probability_withheld", passed)
    check(result["decision_layers"]["final_crm"]["export_allowed"] is False, "unreviewed_crm_export_blocked", passed)
    check(result["outreach"]["outreach_status"] == "DRAFT_READY", "official_general_contact_allows_draft", passed)
    check(result["outreach"]["completion"]["terminal_state"] == "SENDABLE_DRAFT", "mandatory_outreach_terminal_state", passed)
    check(result["outreach"]["completion"]["action"]["enabled"] is True, "mandatory_draft_action_enabled", passed)
    check(result["outreach"]["automatic_send_supported"] is False, "outreach_never_auto_sends", passed)
    check(result["research_status"] == "fast_scan_complete", "fast_scan_not_false_incomplete", passed)
    check(any(item.get("type") == "manual_visual_check_required" for item in result["manual_checks"]), "blocked_social_manual_queue", passed)
    check(any(item.get("verification_status") == "official_current" for item in result["contact_evidence_ledger"]), "official_current_contact", passed)
    check(any(item.get("verification_status") == "directory_current" for item in result["contact_evidence_ledger"]), "directory_social_not_official", passed)
    check(all(item.get("procurement_authority_status") != "confirmed" for item in result["contact_evidence_ledger"]), "general_email_not_procurement", passed)
    sec = next(item for item in result["field_audit"] if item.get("field") == "sec_number")
    check(sec["status"] == "plausible" and sec["official_confirmation"] is False and sec["rejection_reason"] == "official_registry_confirmation_missing", "directory_legal_id_not_confirmed", passed)
    check(result["evidence_binding_summary"]["all_external_fields_source_bound"] is True, "external_fields_source_bound", passed)
    relationship = result["entities"]["relationships"][0]
    check(relationship["relationship_status"] == "strongly_supported_not_legally_confirmed" and relationship["merge_allowed"] is False, "brand_relation_not_legally_merged", passed)
    weak_legal = dict(enrichment)
    weak_legal["entity_relationships"] = [{"entity_a": "Synthetic Buyer One Inc", "entity_b": "Synthetic Brand", "relationship_type": "subsidiary", "source_ids": ["src-dir"], "legal_identifier": True}]
    weak_legal_result = run_record(base_row, enrichment=weak_legal)
    check(weak_legal_result["entities"]["relationships"][0]["relationship_status"] != "legally_confirmed", "directory_legal_identifier_cannot_confirm_control", passed)
    check(result["trade_history_summary"]["duplicate_count"] == 1 and result["trade_history_summary"]["repeat_purchase_status"] == "repeat_purchase_observed", "trade_history_deduped_and_dated", passed)
    check(result["competition_matrix"]["score"] is None and result["competition_matrix"]["score_status"] == "withheld", "competitive_score_withheld", passed)
    check(next(item for item in result["review_ledger"] if item["field"] == "sec_number")["change_reason"], "assistant_review_layered", passed)
    related_shared = normalize(flatten_json({"采购商": "Unrelated Logistics Entity", "采购商地址": "500 Port Road info@synthetic.invalid"}), input_encoding="utf-8")
    shared_result = run_record(base_row, enrichment=enrichment, related=[related_shared])
    shared_email = next(item for item in shared_result["contact_evidence_ledger"] if item.get("value") == "info@synthetic.invalid")
    check("shared_logistics_or_customs_email" in shared_email["risk_note"] and shared_email["recommended_use"] == "secondary_or_verification_only", "shared_email_quarantined", passed)
    stale_result = run_record(base_row, enrichment={"sources": [{"source_id": "src-old", "url": "https://old.synthetic.invalid/contact", "source_type": "official_domain", "official": True, "checked_at": "2025-01-01"}], "contacts": [{"email": "old@synthetic.invalid", "source_ids": ["src-old"], "source_type": "official_domain", "verification_status": "official_current"}]})
    check(stale_result["contact_evidence_ledger"][0]["verification_status"] == "official_historical", "stale_official_contact_downgraded", passed)
    check(all(item.get("claim_class") == "HYPOTHESIS" for item in result["calculation_scenarios"]), "scenarios_are_hypotheses", passed)
    check({item.get("claim_class") for item in result["claim_ledger"]}.issubset({"FACT", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION", "UNKNOWN"}), "claim_classes_closed", passed)
    report = render_v3_report(result)
    required_headings = ("核心商业结论", "数据污染", "产品标准化", "历史采购", "决策人", "CRM审核结果", "事实、推理")
    check(report.count("\n## ") == 18 and "https://example.invalid/contact" in report and all(item in report for item in required_headings), "fixed_18_section_report_with_links", passed)
    check('"email_routing":' not in report and '"quality_gate":' not in report and "json.dumps" not in report, "human_report_has_no_raw_json_dump", passed)
    report_action_url = result["outreach"]["completion"]["action"]["url"]
    check("外联执行附录" in report and "SENDABLE_DRAFT" in report and report_action_url and report_action_url in report and report.count("中文审核译文") == 1, "report_includes_single_review_copy_and_draft_action", passed)

    # Historical substance regression: the detailed United Pacific-style report must retain
    # contamination, amount closure, product-form alternatives, counter-scenarios and actions.
    united_row = {
        "数据源": "Philippines Import", "日期": "2026-05-11", "采购商": "United Pacific Venture Inc",
        "产品": "PVC sheet, 352 Plates, pre-cut and laminated components", "数量": "352 Plates",
        "重量（kg）": 100817, "FOB": 27138.89, "CUSTOMS VALUE": 61811.96, "目的地": "Philippines",
    }
    united = run_record(united_row, enrichment={
        "intelligence_findings": [
            {"classification": "FACT", "statement": "申报数量为352 Plates；重量字段为100,817 kg。", "business_impact": "必须先确认商品行与整份申报的字段作用域。", "counter_explanation": "重量可能属于整份申报而不是本商品行。", "verification_method": "核对报关商品行和Packing List。"},
            {"classification": "INFERENCE", "statement": "产品更接近预切/覆膜组件，而非可直接按标准大板张数解释的普通原板。", "reasoning": "品名包含pre-cut and laminated components。", "business_impact": "先确认加工形态，再决定兴怀切入产品。", "counter_explanation": "也可能是数据库翻译或拼接错误。", "verification_method": "索取产品照片和尺寸清单。"},
        ],
        "buyer_role_scenarios": [
            {"scenario": "commercial_operator", "role": "Importer / distributor candidate", "status": "INFERENCE", "evidence": ["consignee row"], "falsification_test": "核验官网和库存经营。"},
            {"scenario": "reverse_possibility", "role": "Importer of record or trader", "status": "HYPOTHESIS", "evidence": ["buyer role unverified"], "falsification_test": "核验付款和采购决策主体。"},
        ],
        "product_form_scenarios": [
            {"scenario": "precut_laminated_components", "product_form": "预切/覆膜组件", "assumptions": ["品名语义"], "status": "plausible", "verification_method": "产品照片和BOM"},
            {"scenario": "standard_sheet_data_error", "product_form": "普通原板但字段污染", "assumptions": ["翻译或行级作用域错误"], "status": "reverse_possibility", "verification_method": "原始申报"},
        ],
        "business_decision": {"current_judgment": "先核验产品形态和金额作用域，暂不按普通大板报价。", "recommended_target": "采购或产品负责人", "first_objective": "取得照片、尺寸和包装清单", "stop_condition": "无法确认产品形态时停止规格承诺。"},
    })
    united["calculations"].extend([
        {"calculation_id": "declared_unit_weight", "formula": "100817 / 352", "inputs": {"weight_kg": 100817, "plates": 352}, "result": 286.4119, "unit": "kg/Plate", "status": "scope_conflict", "warning": "不应把整票重量直接除以商品行数量。", "reproducible": True},
        {"calculation_id": "fob_unit_value", "formula": "27138.89 / 100817", "inputs": {"FOB_USD": 27138.89, "weight_kg": 100817}, "result": 0.2692, "unit": "USD/kg", "status": "scope_unverified", "warning": "仅用于发现字段作用域异常。", "reproducible": True},
        {"calculation_id": "amount_scope_closure", "formula": "compare FOB with customs value", "inputs": {"FOB_USD": 27138.89, "customs_value_USD": 61811.96}, "result": 34673.07, "unit": "USD difference", "status": "scope_unverified", "warning": "两金额可能来自不同层级或含运保费，不得直接作市场价格。", "reproducible": True},
    ])
    united_report = render_v3_report(united)
    check(all(token in united_report for token in ("352 Plates", "100,817", "27,138.89", "61,811.96", "预切/覆膜", "reverse_possibility")), "historical_detailed_report_substance_preserved", passed)
    check((united.get("scores", {}).get("conversion_probability") or {}).get("point_estimate") is None, "historical_report_drops_fake_probabilities", passed)

    # Viet Synthetic anti-overreach regression: one row can establish a lead, not an A buyer,
    # repeat demand, warehousing, a sole supplier, a sheet count or unsupported specifications.
    kim_row = {
        "数据源": "Vietnam Import", "日期": "2026-05-28", "采购商": "Viet Synthetic Trading And Production Company Limited",
        "供应商": "Zibo Dingtian Plastics Co., Ltd", "产品": "Foam Board (no Printed Pictures Or Letters)",
        "重量（kg）": 25001, "O R I G I N A L_ A M O U N T": 16250.65, "目的地": "Vietnam",
    }
    kim = run_record(kim_row, enrichment={})
    kim_report = render_v3_report(kim)
    check(kim["scores"].get("enterprise_intelligence_grade") != "A", "single_shipment_never_auto_a_grade", passed)
    boundary = next(item for item in kim["intelligence_dossier"]["material_findings"] if item.get("finding_id") == "trade-continuity-boundary")
    check("不能证明持续采购" in boundary["statement"] and kim["trade_history_summary"].get("repeat_purchase_status") != "repeat_purchase_observed", "single_shipment_continuity_boundary", passed)
    forbidden_positive_claims = ("不是试单", "具备仓储能力", "具备销售渠道", "当前供应商单一", "800–1500张")
    check(not any(claim in kim_report for claim in forbidden_positive_claims), "viet_synthetic_overreach_phrases_blocked", passed)
    check(kim["normalized_shipment"]["quantity"].get("estimated_sheets") in {None, ""}, "missing_thickness_blocks_sheet_count", passed)

    # Outreach blockage is appendix-only and must not collapse the Deep Dive.
    blocked = run_record(base_row, enrichment={"contacts": []})
    blocked_report = render_v3_report(blocked)
    check(blocked["outreach"]["completion"]["terminal_state"] == "DRAFT_BLOCKED" and blocked_report.count("\n## ") == 18 and "核心商业结论" in blocked_report and "下一步动作" in blocked_report, "draft_blocked_keeps_full_dossier", passed)

    accessory_row = dict(base_row)
    accessory_row.update({"产品": "Metal Line Outer Corner for 5mm wall panel 2950x0.5mm, 100pcs/box", "数量": "4600 Pieces", "N O P A C K A G E S": 19, "重量（kg）": 1613.22})
    accessory_result = run_record(accessory_row, enrichment={"calculation_assumptions": {}})
    check(accessory_result["normalized_shipment"]["product"]["normalized_category"] == "WALL_PANEL_TRIM_ACCESSORY", "accessory_pipeline_category", passed)
    check(len(accessory_result["calculation_scenarios"]) == 3 and all(item["ranking_status"] == "insufficient_evidence_to_rank" for item in accessory_result["calculation_scenarios"]), "material_alternatives_not_fake_ranked", passed)
    box_calc = next(item for item in accessory_result["calculations"] if item["calculation_id"] == "implied_inner_box_count")
    check(box_calc["result"] == 46 and box_calc["package_level_interpretation"] == "different_level_or_conflict", "inner_boxes_vs_outer_packages", passed)

    deep = run_record(base_row, mode="deep-dive", enrichment={})
    check(deep["status"] in {"complete", "partial"} and deep["research_status"] == "incomplete_research", "deep_status_axes_separated", passed)

    with tempfile.TemporaryDirectory() as folder:
        db = Path(folder) / "collision.sqlite3"
        first = run_record(base_row, db=db)
        second_row = dict(base_row)
        second_row.update({"采购商": "Unrelated Buyer Two LLC", "采购商地址": "900 Other Street, Cebu, Philippines"})
        second = run_record(second_row, db=db)
        check(first["cross_record_contamination"]["status"] == "clear_in_available_index", "first_record_clear", passed)
        check(second["cross_record_contamination"]["status"] == "conflict", "persistent_bill_collision", passed)
        contaminated = [item for item in second["field_audit"] if item.get("status") == "contaminated"]
        check(bool(contaminated) and all(not item.get("crm_eligible") for item in contaminated), "crm_quarantines_contamination", passed)
        check(second["scores"]["enterprise_intelligence_grade"] == "UNSCORABLE", "collision_suspends_scores", passed)

        store = CrossRecordStore(db)
        store.close()
        check(db.exists(), "sqlite_index_persistent", passed)

        batch_input = Path(folder) / "batch.json"
        batch_output = Path(folder) / "batch-output"
        batch_input.write_text(json.dumps([base_row, second_row], ensure_ascii=False), encoding="utf-8")
        check(batch_main(["--input", str(batch_input), "--output-dir", str(batch_output), "--resume"]) == 0, "batch_json_executes", passed)
        manifest = json.loads((batch_output / "batch-manifest.json").read_text(encoding="utf-8"))
        check(manifest["processed_count"] == 2 and all((batch_output / name).exists() for name in ("crm-import.csv", "review-ledger.jsonl", "trade-history-audit.jsonl", "competition-matrix.jsonl", "research-coverage.jsonl")), "batch_outputs_complete", passed)
        check(batch_main(["--input", str(batch_input), "--output-dir", str(batch_output), "--resume"]) == 0, "batch_resume_executes", passed)
        resumed = json.loads((batch_output / "batch-manifest.json").read_text(encoding="utf-8"))
        check(all(item["resumed"] for item in resumed["records"]), "batch_resume_by_hash", passed)
        xlsx_input = Path(folder) / "batch.xlsx"
        xlsx_output = Path(folder) / "xlsx-output"
        make_minimal_xlsx(xlsx_input)
        check(batch_main(["--input", str(xlsx_input), "--output-dir", str(xlsx_output)]) == 0, "batch_xlsx_executes", passed)
        xlsx_manifest = json.loads((xlsx_output / "batch-manifest.json").read_text(encoding="utf-8"))
        check(xlsx_manifest["processed_count"] == 1, "batch_xlsx_row_read", passed)

    print(json.dumps({"version": "4.2.0", "passed": len(passed), "tests": passed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
