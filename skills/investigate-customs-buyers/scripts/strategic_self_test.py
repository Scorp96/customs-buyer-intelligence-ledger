#!/usr/bin/env python3
"""Adversarial strategic and controlled-learning regression tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from strategic_engine import StrategicDecisionEngine, build_decision_layers
from outreach_engine import OutreachExecutionEngine


def check(condition: bool, name: str, passed: list[str]) -> None:
    if not condition:
        raise AssertionError(name)
    passed.append(name)


def base_result(relationship: dict | None = None) -> dict:
    return {
        "normalized_shipment": {
            "buyer": {"raw_name": "Synthetic Uganda Importer Ltd"},
            "supplier": {"raw_name": "Synthetic Guangzhou Exporter Ltd"},
            "product": {"raw_description": 'Unprinted OLIN "PVC Foam Board 1.22*2.44m"'},
        },
        "record_identity": {"data_source": "synthetic-test"},
        "entities": {"relationships": [relationship] if relationship else []},
        "sources": [
            {"source_id": "official-a", "source_type": "official_domain", "evidence_grade": "A2", "source_reference": "https://example.invalid/a", "quoted_or_visible_text": "Official cross-link", "checked_at": "2026-08-03"},
            {"source_id": "independent-b", "source_type": "independent_news", "evidence_grade": "B1", "source_reference": "https://example.invalid/b", "quoted_or_visible_text": "Operating relationship", "checked_at": "2026-08-03"},
        ],
        "field_audit": [
            {"field": "buyer", "normalized_value": "Synthetic Uganda Importer Ltd"},
            {"field": "buyer_address", "normalized_value": "Synthetic Kampala Address"},
            {"field": "original_amount", "normalized_value": 11681516, "status": "plausible"},
            {"field": "currency", "normalized_value": "UGX", "status": "plausible"},
        ],
        "review_ledger": [],
        "contact_evidence_ledger": [],
        "crm": {"account_name": "UNREVIEWED CANDIDATE"},
        "unresolved": [],
        "next_actions": [],
    }


def main() -> int:
    passed: list[str] = []
    relationship = {
        "entity_a": "Synthetic Uganda Importer Ltd",
        "entity_b": "Synthetic Group HQ Ltd",
        "relationship_type": "branch_like_operating_entity",
        "relationship_status": "strongly_supported_not_legally_confirmed",
        "source_ids": ["official-a", "independent-b"],
        "merge_allowed": False,
        "confidence": 0.95,
    }
    result = base_result(relationship)
    strategic, learning = StrategicDecisionEngine().build(result, {})
    rel = strategic["relationship_resolution"]
    check(rel["commercial_relationship"] == "strongly_supported", "commercial_relationship_supported", passed)
    check(rel["legal_relationship"] == "unresolved", "legal_relationship_not_invented", passed)
    check(rel["entity_merge_allowed"] is False, "entity_merge_blocked", passed)
    check(rel["legacy_numeric_confidence_ignored_for_decision"] == 0.95, "legacy_percentage_not_decision", passed)
    center = strategic["procurement_decision_center"]
    check(center["procurement_decision_center"] == "probably_headquarters" and center["claim_class"] == "INFERENCE", "headquarters_is_inference", passed)
    check(strategic["development_route"]["route_type"] == "reverse_to_headquarters", "reverse_headquarters_route", passed)
    pricing = strategic["related_party_pricing"]
    check(pricing["related_party_pricing_risk"] is True, "related_party_price_risk", passed)
    check(pricing["market_price_benchmark_eligible"] is False, "related_price_not_market_benchmark", passed)
    brand = strategic["brand_oem_chain"]
    check(brand["brand"] == "OLIN", "brand_token_detected", passed)
    check(brand["brand_owner"] == "unknown" and brand["manufacturer_of_record"] == "unknown", "brand_owner_and_factory_not_invented", passed)
    values = strategic["commercial_value_portfolio"]
    check(len(values["dimensions"]) == 4, "four_value_dimensions", passed)
    check(values["numeric_score"] is None, "commercial_total_score_withheld", passed)
    lock_in = strategic["supplier_lock_in_decomposition"]
    check(len(lock_in["factors"]) == 8 and lock_in["numeric_score"] is None, "lock_in_decomposed_without_fake_score", passed)
    check(learning["automatic_rule_promotion"] is False, "no_automatic_rule_promotion", passed)
    check(learning["automatic_code_modification"] is False, "no_self_modifying_code", passed)
    check(learning["online_model_weight_update"] is False, "no_online_weight_update", passed)

    outreach_result = dict(result)
    outreach_result.update({
        "strategic_intelligence": strategic,
        "scores": {"enterprise_intelligence_grade": "B"},
        "buyer_intelligence": {"buyer_role": "importer"},
        "data_quality": {"scoring_suspended": False},
        "contact_evidence_ledger": [{"contact_type": "email", "value": "general@example.invalid", "verification_status": "official_current", "source_type": "official_domain", "evidence_grade": "A2", "freshness_status": "current", "source_ids": ["official-a"], "role": "general company channel", "procurement_authority_status": "unverified"}],
        "normalized_shipment": {**result["normalized_shipment"], "product": {**result["normalized_shipment"]["product"], "match_level": "EXACT"}},
    })
    outreach_enrichment = {"seller_capability_ledger": [{"claim": "PVC foam board", "status": "VERIFIED", "verified": True, "allowed_for_external_use": True, "product_category": "PVC foam board", "value_keys": ["additional_source"], "source_ids": ["seller-a"]}], "outreach_context": {"mode": "OUTREACH_PREVIEW"}}
    route_blocked = OutreachExecutionEngine().build(outreach_result, outreach_enrichment)
    check("headquarters_route_contact_unverified" in route_blocked["eligibility_gate"]["block_reasons"], "branch_outreach_blocked_until_route_verified", passed)
    outreach_enrichment["outreach_context"]["target_route_verified"] = True
    route_verified = OutreachExecutionEngine().build(outreach_result, outreach_enrichment)
    check("headquarters_route_contact_unverified" not in route_verified["eligibility_gate"]["block_reasons"], "reviewed_headquarters_route_can_proceed", passed)

    direct, _ = StrategicDecisionEngine().build(base_result(), {})
    check(direct["relationship_resolution"]["commercial_relationship"] == "unresolved", "missing_relationship_stays_unresolved", passed)
    check(direct["development_route"]["route_type"] == "direct_buyer_validation", "direct_route_only_after_unresolved_relation", passed)

    legal = dict(relationship, relationship_status="legally_confirmed", relationship_type="subsidiary", merge_allowed=True)
    confirmed, _ = StrategicDecisionEngine().build(base_result(legal), {})
    check(confirmed["relationship_resolution"]["legal_relationship"] == "confirmed", "registry_grade_can_confirm_legal_relation", passed)
    check(confirmed["relationship_resolution"]["entity_merge_allowed"] is True, "legal_merge_requires_confirmation", passed)

    layers = build_decision_layers(result, {})
    check(layers["final_crm"]["status"] == "PENDING_VERIFICATION", "plugin_raw_not_final_crm", passed)
    check(layers["final_crm"]["record"] == {}, "unreviewed_candidate_not_exported", passed)
    reviewed = base_result(relationship)
    reviewed["review_ledger"] = [
        {"field": "buyer", "plugin_output": {"value": "Synthetic Uganda Importer Ltd"}, "review_status": "reviewed", "review_decision": "accepted", "final_decision": {"value": "Synthetic Uganda Importer Ltd", "status": "confirmed", "crm_eligible": True}, "changed": False},
        {"field": "buyer_address", "plugin_output": {"value": "bad address"}, "review_status": "reviewed", "review_decision": "rejected", "final_decision": {"value": None, "status": "rejected", "crm_eligible": False}, "changed": True, "change_reason": "contamination"},
    ]
    reviewed_layers = build_decision_layers(reviewed, {})
    check("buyer_address" not in reviewed_layers["final_crm"]["record"], "rejected_field_never_enters_crm", passed)
    check(reviewed_layers["final_crm"]["status"] == "CRM_ACCEPTED", "reviewed_core_record_can_be_accepted", passed)
    enriched_layers = build_decision_layers(reviewed, {"strategic_context": {"assistant_audit": {"crm_fields": [
        {"field": "development_route", "value": "reverse_to_headquarters", "decision": "accepted", "source_ids": ["official-a"], "status": "reviewed"},
        {"field": "relationship_type", "value": "subsidiary", "decision": "accepted", "source_ids": []},
    ]}}})
    check(enriched_layers["final_crm"]["record"].get("development_route") == "reverse_to_headquarters", "source_bound_strategic_field_can_enter_crm", passed)
    check("relationship_type" not in enriched_layers["final_crm"]["record"], "source_free_strategic_field_blocked", passed)

    feedback = [
        {"event_id": "f1", "field_or_claim": "relationship", "reviewer_decision": "REJECTED", "reason_code": "name_similarity_only", "regression_case_id": "c1", "created_at": "2026-08-01T00:00:00+00:00"},
        {"event_id": "f2", "field_or_claim": "relationship", "reviewer_decision": "REJECTED", "reason_code": "name_similarity_only", "regression_case_id": "c2", "created_at": "2026-08-02T00:00:00+00:00"},
    ]
    with tempfile.TemporaryDirectory() as folder:
        db = Path(folder) / "feedback.sqlite3"
        _, learned = StrategicDecisionEngine(db).build(result, {"feedback_events": feedback})
        check(learned["persistence"]["stored_event_count"] == 2, "feedback_append_only_persisted", passed)
        check(len(learned["candidate_rules"]) == 1 and learned["candidate_rules"][0]["status"] == "candidate_not_applied", "repeated_feedback_only_creates_candidate", passed)
        _, deduped = StrategicDecisionEngine(db).build(result, {"feedback_events": feedback})
        check(deduped["persistence"]["stored_event_count"] == 2, "feedback_deduplicated", passed)
        invalid = {"rule_id": "r1", "status": "APPROVED", "approved_by": "reviewer", "approved_at": "2026-08-03", "effect_scope": "CRM acceptance", "regression_case_ids": ["c1", "c2", "c3"], "measured_precision": 1.0, "false_positive_rate": 0.0}
        valid = dict(invalid, rule_id="r2", effect_scope="manual_check_priority")
        _, governed = StrategicDecisionEngine(db).build(result, {"approved_learning_rules": [invalid, valid]})
        check(len(governed["rejected_rule_submissions"]) == 1, "crm_learning_effect_rejected", passed)
        check(len(governed["approved_bounded_rules"]) == 1, "validated_manual_hint_allowed", passed)

    print(json.dumps({"version": "4.2.0", "passed": len(passed), "tests": passed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
