#!/usr/bin/env python3
"""Regression scenarios for the v4.2 exhaustive-routing WeCom-safe outreach appendix."""

from __future__ import annotations

from copy import deepcopy

import outreach_engine
from outreach_engine import OutreachExecutionEngine


def base_result(*, country: str = "Philippines", description: str = "PVC foam board", buyer_role: str = "IMPORTER", role: str | None = None, position: str = "current_confirmed", verification: str = "official_current", grade: str = "A1") -> dict:
    return {
        "normalized_shipment": {
            "buyer": {"raw_name": "Example Buyer Corp", "legal_name": "Example Buyer Corp", "country": country},
            "supplier": {"raw_name": "Incumbent Plastic Co Ltd", "legal_name": "Incumbent Plastic Co Ltd"},
            "product": {"raw_description": description, "normalized_category": "ORDINARY_PVC_FOAM_BOARD", "match_level": "EXACT"},
            "quantity": {"weight_kg": 394.0, "gross_weight_kg": 395.92, "declared_quantity": 6, "package_count": 6},
        },
        "record_identity": {"master_bill": "SYNPHMASTER0001", "house_bill": None, "container_numbers": ["SYNX7601738"]},
        "buyer_intelligence": {"buyer_role": buyer_role, "business_model": None},
        "scores": {"enterprise_intelligence_grade": "B", "stage": "S2"},
        "data_quality": {"scoring_suspended": False},
        "contact_evidence_ledger": [
            {
                "contact_type": "email", "value": "info@examplebuyer.com", "person_name": "Alex Lee" if role else None,
                "role": role, "position_status": position if role else "not_applicable", "procurement_authority_status": "confirmed" if role and "Purchasing" in role else "unconfirmed",
                "verification_status": verification, "evidence_grade": grade, "risk_note": [], "source_reference": "https://examplebuyer.com/contact",
                "source_date": "2026-07-20", "recommended_use": "formal_company_outreach", "channel_use": "official_company_general",
            }
        ],
    }


def enrichment(**context) -> dict:
    return {"outreach_context": {"current_datetime": "2026-08-03T08:00:00+00:00", **context}}


def run(result: dict | None = None, packet: dict | None = None) -> dict:
    return OutreachExecutionEngine().build(result or base_result(), packet or enrichment())


def check(condition: bool, label: str, passed: list[str]) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def main() -> int:
    passed: list[str] = []

    # 1. Current official general mailbox: route internally; do not invent procurement.
    out = run()
    check(out["contact"]["email"] == "info@examplebuyer.com" and "Please forward" in out["email"]["body"], "general_mailbox_routes_internally", passed)
    check(out["outreach_mode"] == "CREATE_DRAFT", "create_draft_is_default", passed)
    check(out["completion"]["terminal_state"] == "SENDABLE_DRAFT", "safe_default_finishes_sendable", passed)
    check(out["completion"]["report_only_output_forbidden"] is True and out["completion"]["completion_contract_passed"] is True, "report_only_completion_forbidden", passed)
    check(out["completion"]["action"]["enabled"] is True and out["completion"]["action"]["url"].startswith("mailto:"), "one_click_draft_action_ready", passed)
    check(out["completion"]["draft_transport"] == "mailto_wecom_tencent_enterprise_compatible", "wecom_tencent_mailto_is_default", passed)
    check(out["completion"]["server_side_draft_created"] is False and out["completion"]["provider_draft_id"] is None and out["completion"]["connector_receipt"] is None, "mailto_never_fakes_provider_receipt", passed)
    check("Gmail" not in out["completion"]["connector_next_step"] and "Outlook" not in out["completion"]["connector_next_step"], "no_unrequested_gmail_outlook_claim", passed)
    check(80 <= out["email"]["word_count"] <= 110 and out["email"]["human_style"]["passed"] is True and out["email"]["human_style"]["question_count"] == 1, "short_human_style_first_email", passed)
    check(out["timezone"]["beijing_time_now"] and out["timezone"]["buyer_local_time_now"] and out["timezone"]["beijing_equivalent_window"], "beijing_and_buyer_time_visible", passed)

    # Exhaustive multi-email routing: show every address, but only draft safe sequential routes.
    multi_source = base_result(role="Purchasing Manager")
    multi_source["contact_evidence_ledger"].extend([
        {"contact_id": "contact-002", "contact_type": "email", "value": "info@examplebuyer.com", "person_name": None, "role": "General company channel", "position_status": "not_applicable", "procurement_authority_status": "unconfirmed", "verification_status": "official_current", "evidence_grade": "A2", "risk_note": [], "source_reference": "https://examplebuyer.com/contact", "source_date": "2026-07-20", "recommended_use": "formal_company_outreach", "channel_use": "official_company_general"},
        {"contact_id": "contact-003", "contact_type": "email", "value": "sales@examplebuyer.com", "person_name": "Sam Tan", "role": "Sales Manager", "position_status": "current_confirmed", "procurement_authority_status": "unconfirmed", "verification_status": "official_current", "evidence_grade": "A2", "risk_note": ["role_not_verified_as_procurement"], "source_reference": "https://examplebuyer.com/team", "source_date": "2026-07-20", "recommended_use": "secondary_or_verification_only", "channel_use": "historical_or_verification_lead"},
        {"contact_id": "contact-004", "contact_type": "email", "value": "hr@examplebuyer.com", "person_name": None, "role": "HR", "position_status": "not_applicable", "procurement_authority_status": "unconfirmed", "verification_status": "official_current", "evidence_grade": "A2", "risk_note": ["role_not_verified_as_procurement"], "source_reference": "https://examplebuyer.com/careers", "source_date": "2026-07-20", "recommended_use": "secondary_or_verification_only", "channel_use": "historical_or_verification_lead"},
        {"contact_id": "contact-005", "contact_type": "email", "value": "old@examplebuyer.com", "person_name": None, "role": "General", "position_status": "not_applicable", "procurement_authority_status": "unconfirmed", "verification_status": "official_historical", "evidence_grade": "B2", "risk_note": [], "source_reference": "https://archive.examplebuyer.com", "source_date": "2024-01-01", "recommended_use": "verify_before_use", "channel_use": "historical_or_verification_lead"},
    ])
    multi_result = run(multi_source)
    routes = multi_result["email_routing"]
    check(routes["discovered_email_count"] == 5 and routes["accounted_email_count"] == 5 and routes["omission_check_passed"] is True, "every_discovered_email_accounted_for", passed)
    check(routes["primary_route"]["email"] == "info@examplebuyer.com" and routes["primary_route"]["route_class"] == "DIRECT_PROCUREMENT", "verified_procurement_route_ranked_first", passed)
    check(any(item["email"] == "sales@examplebuyer.com" for item in routes["alternative_routes"]) and any(item["email"] == "hr@examplebuyer.com" for item in routes["do_not_use_routes"]) and any(item["email"] == "old@examplebuyer.com" for item in routes["verify_only_routes"]), "alternate_hr_and_historical_routes_separated", passed)
    check(all(item["action"]["sends_message"] is False for item in multi_result["alternate_drafts"]) and multi_result["completion"]["simultaneous_multi_send_prohibited"] is True, "multi_email_never_becomes_blast", passed)

    # 2-3. Historical and inferred email never enter To.
    historical = run(base_result(verification="official_historical", grade="B2"))
    check(not historical["email"]["to"] and historical["outreach_status"] == "BLOCKED", "historical_email_blocked", passed)
    check(historical["completion"]["terminal_state"] == "DRAFT_BLOCKED" and historical["completion"]["action"]["enabled"] is False, "historical_terminal_block", passed)
    inferred = run(base_result(verification="inferred", grade="D"))
    check(not inferred["email"]["to"] and "only_inferred_email" in inferred["eligibility_gate"]["block_reasons"], "inferred_email_blocked", passed)

    # 4-5. Account Executive and Sales keep their titles and are referral routes.
    account = run(base_result(role="Account Executive"))
    check(account["contact"]["role"] == "Account Executive" and account["contact"]["procurement_authority_status"] == "unconfirmed", "account_executive_not_procurement", passed)
    sales = run(base_result(role="Sales Manager"))
    check(sales["contact"]["role"] == "Sales Manager" and "person responsible" in sales["email"]["body"], "sales_contact_is_referral_route", passed)

    # 6-7. Logistics-only buyers and departed named contacts are blocked.
    broker = run(base_result(buyer_role="CUSTOMS_BROKER"))
    check("customs_broker_only" in broker["eligibility_gate"]["block_reasons"], "broker_not_sales_target", passed)
    check(broker["completion"]["terminal_state"] == "NO_OUTREACH_RECOMMENDED", "broker_no_outreach_terminal", passed)
    departed = run(base_result(role="Purchasing Manager", position="departed"))
    check(not departed["email"]["to"] and departed["outreach_status"] == "BLOCKED", "departed_contact_blocked", passed)

    # 8-9. Incumbent supply is internal, and no public email blocks drafting.
    incumbent = run()
    check("Incumbent Plastic" not in incumbent["email"]["body"], "incumbent_not_disclosed", passed)
    no_mail = base_result()
    no_mail["contact_evidence_ledger"] = []
    no_mail_result = run(no_mail)
    check(no_mail_result["outreach_status"] == "BLOCKED", "no_public_email_blocks", passed)
    check(no_mail_result["completion"]["terminal_state"] == "DRAFT_BLOCKED" and no_mail_result["completion"]["block_reasons"], "no_email_has_visible_block_reason", passed)

    # 10-13. Language evidence/fallback and IANA/DST behavior.
    check(run(base_result(country="Philippines"))["language"]["primary"] == "English", "philippines_english", passed)
    check(run(base_result(country="Puerto Rico"), {**enrichment(), "buyer_profile": {"city": "San Juan"}})["language"]["primary"] == "Spanish", "puerto_rico_spanish", passed)
    check(run(base_result(country="Peru"), {**enrichment(), "buyer_profile": {"city": "Lima"}})["language"]["primary"] == "Spanish", "peru_spanish", passed)
    paris = run(base_result(country="France"), {"buyer_profile": {"city": "Paris"}, "outreach_context": {"current_datetime": "2026-07-01T08:00:00+00:00"}})
    check(paris["timezone"]["buyer_iana_timezone"] == "Europe/Paris" and paris["timezone"]["dst_status"] == "active", "iana_dst_active", passed)
    peru = run(base_result(country="Peru"), {"buyer_profile": {"city": "Lima"}, "outreach_context": {"current_datetime": "2026-08-03T13:55:00+08:00", "primary_language": "English"}})
    check(peru["timezone"]["time_difference"] == "-13 hours buyer minus Guangzhou" and "21:30:00+08:00" in peru["timezone"]["beijing_equivalent_window"], "peru_window_converted_to_beijing", passed)

    # Windows Python may not ship an IANA tz database. Seller Beijing time has
    # an exact dependency-free UTC+08:00 fallback; buyer time stays fail-closed.
    original_zoneinfo = outreach_engine.ZoneInfo
    def unavailable_zoneinfo(_: str):
        raise outreach_engine.ZoneInfoNotFoundError("synthetic missing timezone database")
    outreach_engine.ZoneInfo = unavailable_zoneinfo
    try:
        no_tzdata = run(
            base_result(country="Philippines"),
            {"outreach_context": {"current_datetime": "2026-08-03T08:00:00+00:00", "buyer_timezone": "Unknown/Manual_Only"}},
        )
    finally:
        outreach_engine.ZoneInfo = original_zoneinfo
    check(
        no_tzdata["timezone"]["beijing_time_now"].endswith("+08:00")
        and no_tzdata["timezone"]["buyer_local_time_now"] is None
        and "manual verification required" in no_tzdata["timezone"]["reason"],
        "missing_tzdata_uses_exact_beijing_fallback_and_fails_buyer_closed",
        passed,
    )

    # 14-17. Buyer type drives hypotheses; specific capabilities remain evidence-gated.
    advertising = run(base_result(description="PVC advertising board for printing"))
    check(advertising["buyer"]["buyer_type"] == "advertising_material_supplier", "advertising_buyer_type", passed)
    furniture = run(base_result(description="PVC cabinet furniture board"))
    check(furniture["buyer"]["buyer_type"] == "furniture_material_supplier", "furniture_buyer_type", passed)
    wall = run(base_result(description="decorative PVC wall cladding"))
    check(wall["buyer"]["buyer_type"] == "decorative_wall_system_supplier" and "matching finishing" not in wall["email"]["body"], "wall_capability_not_assumed", passed)
    industrial_packet = {**enrichment(), "buyer_profile": {"buyer_type": "industrial_end_user", "status": "CONFIRMED"}}
    industrial = run(base_result(), industrial_packet)
    check(industrial["buyer"]["buyer_type"] == "industrial_end_user", "industrial_buyer_type", passed)

    # 18-19. Inferred buyer specification and unverified seller capabilities cannot cross the firewall.
    inferred_spec_packet = enrichment(primary_product="17mm 0.65 density PVC foam board")
    inferred_spec = run(base_result(description="PVC Foam Board 1220x2440 17mm .65g"), inferred_spec_packet)
    check("17mm" not in inferred_spec["email"]["body"] and "0.65" not in inferred_spec["email"]["body"], "inferred_spec_not_external", passed)
    unverified_packet = {**enrichment(primary_product="matching metal profiles", value_keys=["matching_profiles"]), "seller_capability_ledger": [{"claim": "XingHuai makes all matching metal profiles", "status": "UNVERIFIED", "verified": False, "allowed_for_external_use": False, "product_category": "matching metal profiles", "value_keys": ["matching_profiles"]}]}
    unverified = run(base_result(), unverified_packet)
    check("matching metal" not in unverified["email"]["body"] and "matching finishing" not in unverified["email"]["body"], "unverified_seller_capability_not_external", passed)

    # 20-23. Firewall and quality controls catch leakage, overlength, and marketing subjects.
    leak_supplier = enrichment(draft={"subject": "PVC Boards for Supplier Evaluation", "body": "We know your current supplier Incumbent Plastic Co Ltd. Could you reply?"})
    check(not run(packet=leak_supplier)["external_content_firewall"]["passed"], "supplier_name_firewall", passed)
    leak_weight = enrichment(draft={"subject": "PVC Boards for Supplier Evaluation", "body": "We saw your customs shipment of 394.0 kg. Could you reply?"})
    check(not run(packet=leak_weight)["external_content_firewall"]["passed"], "customs_weight_firewall", passed)
    long_body = " ".join(["relevant"] * 115) + "?"
    long_mail = run(packet=enrichment(draft={"subject": "PVC Boards for Supplier Evaluation", "body": long_body}))
    check("first_email_over_110_words" in long_mail["risk"]["risk_reasons"], "over_110_words_flagged", passed)
    spam_subject = run(packet=enrichment(draft={"subject": "Best Price Limited Time PVC Boards", "body": "I am Mark Zhou from XingHuai, a PVC board manufacturer. We offer a supplier evaluation. Could you identify the buyer?"}))
    check(not spam_subject["external_content_firewall"]["passed"], "marketing_subject_blocked", passed)
    placeholder = run(packet=enrichment(draft={"subject": "PVC Boards for Supplier Evaluation", "body": "Hello. [Your Name] can supply PVC boards. Could you identify the buyer?"}))
    check(not placeholder["external_content_firewall"]["passed"] and placeholder["completion"]["action"]["enabled"] is False, "placeholder_disables_action", passed)
    ai_style_body = "I reviewed your public catalog and analyzed your products. Please provide density, weight per sheet, flatness, packaging, FOB price, CIF price, lead time, and technical data sheet. Can you reply? Can you also send specifications?\n\nMark Zhou\nGuangzhou XingHuai New Materials Co., Ltd.\nMobile / WhatsApp: +86 180 2710 1852\nWebsite: www.xinghuai.com"
    ai_style = run(packet=enrichment(draft={"subject": "PVC Boards for Supplier Evaluation", "body": ai_style_body}))
    check("research_process_disclosure_or_ai_style_phrase" in ai_style["email"]["human_style"]["blocking_issues"] and "technical_questionnaire_density" in ai_style["email"]["human_style"]["blocking_issues"] and ai_style["outreach_status"] == "BLOCKED", "ai_style_technical_questionnaire_blocked", passed)

    # 24-27. Contact-history and explicit-confirmation blocks.
    duplicate = run(packet=enrichment(last_first_email_at="2026-08-02T08:00:00+00:00"))
    check("duplicate_contact_window" in duplicate["risk"]["risk_reasons"] and duplicate["outreach_status"] == "BLOCKED", "duplicate_72h_block", passed)
    check(run(packet=enrichment(unsubscribed=True))["outreach_status"] == "BLOCKED", "unsubscribe_block", passed)
    check(run(packet=enrichment(rejected_contact=True))["outreach_status"] == "BLOCKED", "refusal_block", passed)
    no_preview = run(packet=enrichment(mode="SEND_CONFIRMED", send_confirmed=True, user_previewed=False))
    check(no_preview["outreach_status"] == "BLOCKED" and no_preview["risk"]["send_blocked"], "send_without_preview_blocked", passed)

    # 28-30. Long mailto falls back; language evidence overrides country; schedule avoids weekends and discloses holiday gap.
    huge = " ".join(["specification"] * 500) + "?"
    long_url = run(packet=enrichment(draft={"subject": "PVC Boards for Supplier Evaluation", "body": huge}))
    check(long_url["email"]["mailto_url"] is None and long_url["email"]["mailto_status"] == "too_long_use_email_draft_api", "long_mailto_falls_back", passed)
    override_packet = {**enrichment(), "language_evidence": {"primary": "English", "secondary": "Spanish", "confidence": 95, "reason": "Official website and contact profile", "source_ids": ["src-language"]}}
    override = run(base_result(country="Puerto Rico"), override_packet)
    check(override["language"]["primary"] == "English" and override["language"]["confidence"] == 95, "contact_language_overrides_country", passed)
    spanish_body = """Estimado equipo de Example Buyer Corp:

Soy Mark Zhou de Guangzhou XingHuai New Materials Co., Ltd., fabricante chino de tableros de PVC. Por favor, reenvíe este mensaje a la persona responsable de evaluar proveedores para esta categoría.

Nos gustaría ser considerados como una fuente de fábrica adicional para tableros de PVC, con una evaluación controlada de especificaciones.

¿Podría indicarme quién gestiona esta categoría?

Saludos cordiales,

Mark Zhou
Guangzhou XingHuai New Materials Co., Ltd.
Mobile / WhatsApp: +86 180 2710 1852
Website: www.xinghuai.com"""
    spanish_packet = {"buyer_profile": {"city": "San Juan"}, "outreach_context": {"current_datetime": "2026-08-03T08:00:00+00:00", "draft": {"language": "Spanish", "subject": "Tableros de PVC para evaluar proveedor", "body": spanish_body, "structure_attestation": {"who": True, "what": True, "relevance": True, "value": True, "cta": True}}}}
    spanish = run(base_result(country="Puerto Rico"), spanish_packet)
    check(spanish["email"]["language_match_confirmed"] is True and spanish["outreach_status"] == "DRAFT_READY", "reviewed_local_language_draft_passes", passed)
    schedule = run(base_result(country="Philippines"))
    scheduled = schedule["timezone"]["buyer_local_send_time"]
    check(schedule["timezone"]["working_day"] is True and schedule["timezone"]["holiday_status"] == "not_checked_requires_current_calendar" and scheduled, "weekend_avoided_holiday_gap_disclosed", passed)

    # Additional invariants: one CTA, no automatic send, safe follow-up rhythm.
    ready = run()
    check(ready["email"]["body"].count("?") == 1, "one_clear_cta", passed)
    check(ready["automatic_send_supported"] is False and ready["human_review_required"] is True, "never_auto_send", passed)
    check("no automatic same-day escalation" in ready["other_channels"]["recommended_sequence"].lower(), "no_default_same_day_multichannel", passed)

    print(f"outreach_self_test: {len(passed)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
