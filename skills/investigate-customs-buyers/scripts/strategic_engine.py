#!/usr/bin/env python3
"""Strategic decision and controlled-learning layer for buyer intelligence.

The deterministic plugin proposes and audits.  It does not become the final
commercial judge, modify its own code, or promote feedback into rules without
explicit approval and regression evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STRATEGIC_VERSION = "4.2.0"
RELATIONSHIP_TYPES = {
    "parent_company", "subsidiary", "overseas_branch", "branch_like_operating_entity",
    "controlled_distributor", "common_owner", "brand_operator", "import_title_entity",
    "exclusive_agent", "related_local_operating_entity", "possible_affiliate", "independent_buyer",
}
RELATIONSHIP_STATUSES = {"legally_confirmed", "strongly_supported_not_legally_confirmed", "probable", "unverified", "rejected"}
VALUE_DIMENSIONS = ("independent_buyer_value", "local_channel_value", "headquarters_oem_value", "regional_market_entry_value")
LOCK_IN_FACTORS = ("legal_or_control_relationship", "brand_control", "headquarters_procurement", "local_inventory_network", "exclusive_packaging", "internal_settlement", "technical_after_sales", "price_only")
LEARNING_EFFECTS = {"research_priority", "manual_check_priority", "ranking_hint"}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def key(value: Any) -> str:
    return clean(value).casefold()


def list_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FeedbackStore:
    """Append-only local feedback ledger; never changes rules or model weights."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def record_and_load(self, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.path:
            normalized = self._normalize(events)
            return normalized, {"persistence": "not_requested", "database": None, "stored_event_count": len(normalized)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS feedback_events (event_hash TEXT PRIMARY KEY, event_json TEXT NOT NULL, created_at TEXT NOT NULL)")
            for event in self._normalize(events):
                connection.execute("INSERT OR IGNORE INTO feedback_events(event_hash,event_json,created_at) VALUES(?,?,?)", (stable_hash(event), json.dumps(event, ensure_ascii=False, sort_keys=True), event.get("created_at") or datetime.now(timezone.utc).isoformat()))
            connection.commit()
            rows = connection.execute("SELECT event_json FROM feedback_events ORDER BY created_at,event_hash").fetchall()
            loaded = [json.loads(row[0]) for row in rows]
            return loaded, {"persistence": "append_only_sqlite", "database": str(self.path), "stored_event_count": len(loaded)}
        finally:
            connection.close()

    @staticmethod
    def _normalize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index, raw in enumerate(events, 1):
            decision = clean(raw.get("reviewer_decision") or raw.get("decision")).upper() or "UNREVIEWED"
            output.append({
                "event_id": clean(raw.get("event_id")) or f"feedback-{index:04d}",
                "task_type": clean(raw.get("task_type")) or "buyer_intelligence",
                "field_or_claim": clean(raw.get("field_or_claim") or raw.get("field")),
                "plugin_output": raw.get("plugin_output"),
                "reviewer_decision": decision,
                "final_decision": raw.get("final_decision"),
                "reason_code": clean(raw.get("reason_code")) or "unspecified",
                "source_ids": [str(item) for item in raw.get("source_ids") or [] if item],
                "regression_case_id": clean(raw.get("regression_case_id")) or None,
                "outcome": clean(raw.get("outcome")) or None,
                "created_at": clean(raw.get("created_at")) or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            })
        return output


class StrategicDecisionEngine:
    def __init__(self, feedback_db: Path | None = None) -> None:
        self.feedback_store = FeedbackStore(feedback_db)

    def build(self, result: dict[str, Any], enrichment: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        enrichment = enrichment if isinstance(enrichment, dict) else {}
        context = enrichment.get("strategic_context") if isinstance(enrichment.get("strategic_context"), dict) else {}
        relationship = self._relationship(result)
        decision_center = self._decision_center(result, context, relationship)
        brand_chain = self._brand_chain(result, context)
        pricing = self._pricing(result, context, relationship)
        values = self._values(context, relationship, decision_center, result)
        lock_in = self._lock_in(context, relationship, decision_center)
        route = self._route(relationship, decision_center, brand_chain, result)
        strategic = {
            "schema_version": STRATEGIC_VERSION,
            "relationship_resolution": relationship,
            "procurement_decision_center": decision_center,
            "commercial_value_portfolio": values,
            "related_party_pricing": pricing,
            "brand_oem_chain": brand_chain,
            "supplier_lock_in_decomposition": lock_in,
            "development_route": route,
            "evidence_completeness": self._completeness(relationship, decision_center, brand_chain, result),
            "decision_policy": "Use categorical evidence states by default. Numeric probability is withheld unless a documented model, complete components, calibration evidence, and acceptance thresholds are supplied.",
        }
        learning = self._learning(enrichment)
        return strategic, learning

    @staticmethod
    def _source_details(result: dict[str, Any], source_ids: list[str]) -> list[dict[str, Any]]:
        source_map = {item.get("source_id"): item for item in list_dicts(result.get("sources"))}
        return [{
            "source_id": source_id,
            "source_type": source_map.get(source_id, {}).get("source_type"),
            "evidence_grade": source_map.get(source_id, {}).get("evidence_grade"),
            "source_url": source_map.get(source_id, {}).get("source_reference"),
            "exact_excerpt": source_map.get(source_id, {}).get("quoted_or_visible_text"),
            "retrieved_at": source_map.get(source_id, {}).get("checked_at"),
        } for source_id in source_ids]

    def _relationship(self, result: dict[str, Any]) -> dict[str, Any]:
        relationships = list_dicts(result.get("entities", {}).get("relationships"))
        ranked = sorted(relationships, key=lambda item: {"legally_confirmed": 4, "strongly_supported_not_legally_confirmed": 3, "probable": 2, "unverified": 1}.get(item.get("relationship_status"), 0), reverse=True)
        if not ranked:
            return {"relationship_type": "unresolved", "commercial_relationship": "unresolved", "legal_relationship": "unresolved", "claim_class": "UNKNOWN", "evidence": [], "missing_evidence": ["official cross-link or independent relationship evidence", "registry ownership/director record"], "entity_merge_allowed": False}
        best = ranked[0]
        raw_type = clean(best.get("relationship_type")) or "possible_affiliate"
        relation_type = raw_type if raw_type in RELATIONSHIP_TYPES else "possible_affiliate"
        status = best.get("relationship_status") if best.get("relationship_status") in RELATIONSHIP_STATUSES else "unverified"
        if status == "legally_confirmed":
            commercial, legal, claim_class = "confirmed", "confirmed", "FACT"
        elif status == "strongly_supported_not_legally_confirmed":
            commercial, legal, claim_class = "strongly_supported", "unresolved", "INFERENCE"
        else:
            commercial, legal, claim_class = "unverified", "unresolved", "HYPOTHESIS"
        source_ids = [str(item) for item in best.get("source_ids") or [] if item]
        return {"relationship_type": relation_type, "commercial_relationship": commercial, "legal_relationship": legal, "claim_class": claim_class, "entity_a": best.get("entity_a"), "entity_b": best.get("entity_b"), "evidence": self._source_details(result, source_ids), "source_ids": source_ids, "missing_evidence": best.get("missing_evidence") or ([] if legal == "confirmed" else ["official registry ownership/director/control record"]), "entity_merge_allowed": bool(best.get("merge_allowed")) and legal == "confirmed", "legacy_numeric_confidence_ignored_for_decision": best.get("confidence")}

    @staticmethod
    def _decision_center(result: dict[str, Any], context: dict[str, Any], relationship: dict[str, Any]) -> dict[str, Any]:
        candidates = list_dicts(context.get("decision_centers"))
        verified = [item for item in candidates if item.get("source_ids") and clean(item.get("status")).upper() in {"CONFIRMED", "SUPPORTED_INFERENCE"}]
        if verified:
            best = verified[0]
            return {"importing_entity": best.get("importing_entity") or result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name"), "commercial_operator": best.get("commercial_operator"), "brand_controller": best.get("brand_controller"), "procurement_decision_center": best.get("procurement_decision_center"), "payment_entity": best.get("payment_entity") or "unknown", "inventory_owner": best.get("inventory_owner") or "unknown", "supplier_qualification_owner": best.get("supplier_qualification_owner") or "unknown", "status": clean(best.get("status")).upper(), "claim_class": "FACT" if clean(best.get("status")).upper() == "CONFIRMED" else "INFERENCE", "source_ids": best.get("source_ids") or [], "missing_evidence": best.get("missing_evidence") or []}
        branch_like = relationship.get("relationship_type") in {"overseas_branch", "branch_like_operating_entity", "related_local_operating_entity", "subsidiary", "controlled_distributor"} and relationship.get("commercial_relationship") in {"confirmed", "strongly_supported"}
        return {"importing_entity": result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name"), "commercial_operator": relationship.get("entity_a") if branch_like else "unknown", "brand_controller": relationship.get("entity_b") if branch_like else "unknown", "procurement_decision_center": "probably_headquarters" if branch_like else "unknown", "payment_entity": "unknown", "inventory_owner": "unknown", "supplier_qualification_owner": "probably_headquarters" if branch_like else "unknown", "status": "SUPPORTED_INFERENCE" if branch_like else "UNRESOLVED", "claim_class": "INFERENCE" if branch_like else "UNKNOWN", "source_ids": relationship.get("source_ids") or [], "missing_evidence": ["current procurement owner", "payment entity", "inventory owner", "supplier qualification owner"]}

    @staticmethod
    def _brand_chain(result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        supplied = context.get("brand_chain") if isinstance(context.get("brand_chain"), dict) else {}
        raw_product = clean(result.get("normalized_shipment", {}).get("product", {}).get("raw_description"))
        brand = clean(supplied.get("brand"))
        if not brand:
            match = re.search(r"(?i)\b([a-z][a-z0-9-]{2,20})\s*[\"']?\s*pvc\b", raw_product)
            if match and key(match.group(1)) not in {"unprinted", "printed", "white", "rigid", "foam"}:
                brand = match.group(1).upper()
        source_ids = [str(item) for item in supplied.get("source_ids") or [] if item]
        owner = supplied.get("brand_owner") if source_ids else "unknown"
        operator = supplied.get("brand_operator") if source_ids else "unknown"
        manufacturer = supplied.get("manufacturer") if source_ids and clean(supplied.get("manufacturer_status")).upper() == "CONFIRMED" else "unknown"
        return {"brand": brand or "unknown", "brand_owner": owner or "unknown", "brand_operator": operator or "unknown", "exporter": result.get("normalized_shipment", {}).get("supplier", {}).get("raw_name"), "manufacturer_of_record": manufacturer, "trademark_match": supplied.get("trademark_match") or "unresolved", "manufacturer_status": "confirmed" if manufacturer != "unknown" else "unresolved", "source_ids": source_ids, "claim_class": "FACT" if source_ids and owner != "unknown" else "HYPOTHESIS" if brand != "unknown" else "UNKNOWN", "visual_verification_required": manufacturer == "unknown" or not source_ids, "missing_evidence": supplied.get("missing_evidence") or ["trademark owner record", "packaging/label photo", "certificate applicant and manufacturer", "factory or OEM disclosure"]}

    @staticmethod
    def _pricing(result: dict[str, Any], context: dict[str, Any], relationship: dict[str, Any]) -> dict[str, Any]:
        audit = {item.get("field"): item for item in list_dicts(result.get("field_audit"))}
        related = relationship.get("commercial_relationship") in {"confirmed", "strongly_supported"} and relationship.get("relationship_type") != "independent_buyer"
        supplied = context.get("pricing_context") if isinstance(context.get("pricing_context"), dict) else {}
        benchmark_allowed = bool(supplied.get("market_price_benchmark_eligible")) and not related and bool(supplied.get("comparable_scope_verified"))
        return {"related_party_pricing_risk": related, "risk_claim_class": "INFERENCE" if related else "UNKNOWN", "market_price_benchmark_eligible": benchmark_allowed, "declared_value": audit.get("original_amount", {}).get("normalized_value"), "currency": audit.get("currency", {}).get("normalized_value"), "value_scope_status": audit.get("original_amount", {}).get("status") or "unresolved", "reasons": (["commercial relationship is confirmed or strongly supported", "internal settlement or customs valuation may differ from arm's-length market price"] if related else ["relationship and price scope are not sufficient for market benchmarking"]), "required_before_benchmark": ["arm's-length transaction status", "FOB/CIF scope", "line-item value and weight scope", "product thickness/density/grade", "current comparable quote"]}

    @staticmethod
    def _values(context: dict[str, Any], relationship: dict[str, Any], decision_center: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        supplied = {clean(item.get("dimension")): item for item in list_dicts(context.get("commercial_value_dimensions"))}
        related = relationship.get("commercial_relationship") in {"confirmed", "strongly_supported"} and relationship.get("relationship_type") != "independent_buyer"
        rows = []
        for dimension in VALUE_DIMENSIONS:
            raw = supplied.get(dimension, {})
            source_ids = [str(item) for item in raw.get("source_ids") or [] if item]
            if raw and source_ids:
                grade = clean(raw.get("grade")).upper() or "UNRESOLVED"
                status, rationale = clean(raw.get("status")).upper() or "SUPPORTED_INFERENCE", clean(raw.get("rationale"))
            elif dimension == "independent_buyer_value" and related:
                grade, status, rationale = "LOW", "SUPPORTED_INFERENCE", "The importer appears commercially related to another supply-chain entity; direct independent-buyer substitution is structurally weak."
            elif dimension == "headquarters_oem_value" and related:
                grade, status, rationale = "POTENTIAL", "SUPPORTED_INFERENCE", "Headquarters/OEM qualification may be more logical than replacing the related local importer; factory ownership and OEM openness remain unverified."
            elif dimension == "local_channel_value" and related:
                grade, status, rationale = "POTENTIAL", "SUPPORTED_INFERENCE", "A related local operator may still have channel, inventory, or market intelligence value."
            else:
                grade, status, rationale = "UNRESOLVED", "UNVERIFIED", "Insufficient evidence for this value dimension."
            rows.append({"dimension": dimension, "grade": grade, "status": status, "rationale": rationale, "source_ids": source_ids, "acceptance_criteria": raw.get("acceptance_criteria") or "Bind current entity, decision authority, product demand, and reachable owner evidence."})
        return {"score_mode": "categorical_evidence_states", "dimensions": rows, "numeric_score": None, "numeric_score_status": "withheld_no_calibrated_complete_model", "warning": "Do not collapse independent-buyer, local-channel, headquarters-OEM, and regional-entry value into one total score."}

    @staticmethod
    def _lock_in(context: dict[str, Any], relationship: dict[str, Any], decision_center: dict[str, Any]) -> dict[str, Any]:
        supplied = {clean(item.get("factor")): item for item in list_dicts(context.get("lock_in_factors"))}
        related = relationship.get("commercial_relationship") in {"confirmed", "strongly_supported"}
        rows = []
        for factor in LOCK_IN_FACTORS:
            raw = supplied.get(factor, {})
            if raw.get("source_ids"):
                level, status = clean(raw.get("level")).upper() or "UNKNOWN", clean(raw.get("status")).upper() or "SUPPORTED_INFERENCE"
            elif factor == "legal_or_control_relationship" and related:
                level, status = ("VERY_HIGH", "CONFIRMED") if relationship.get("legal_relationship") == "confirmed" else ("HIGH", "SUPPORTED_INFERENCE")
            elif factor == "headquarters_procurement" and decision_center.get("status") == "SUPPORTED_INFERENCE":
                level, status = "HIGH", "SUPPORTED_INFERENCE"
            else:
                level, status = "UNKNOWN", "UNRESOLVED"
            rows.append({"factor": factor, "level": level, "status": status, "source_ids": raw.get("source_ids") or [], "rationale": raw.get("rationale"), "verification_method": raw.get("verification_method") or "Obtain dated legal, brand, procurement, packaging, inventory, settlement, or service evidence as applicable."})
        supported_high = [row for row in rows if row["level"] in {"HIGH", "VERY_HIGH"} and row["status"] in {"CONFIRMED", "SUPPORTED_INFERENCE"}]
        composite = "HIGH" if len(supported_high) >= 2 else "ELEVATED" if supported_high else "UNRESOLVED"
        return {"composite_level": composite, "numeric_score": None, "numeric_score_status": "withheld_no_complete_weighted_model", "factors": rows, "main_barrier": supported_high[0]["factor"] if supported_high else "unresolved"}

    @staticmethod
    def _route(relationship: dict[str, Any], decision_center: dict[str, Any], brand_chain: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        branch_like = relationship.get("relationship_type") in {"overseas_branch", "branch_like_operating_entity", "related_local_operating_entity", "subsidiary", "controlled_distributor"} and relationship.get("commercial_relationship") in {"confirmed", "strongly_supported"}
        if branch_like:
            return {"route_type": "reverse_to_headquarters", "recommended_target": "headquarters_supply_chain_or_supplier_qualification_team", "positioning": "OEM, controlled trial, or backup-factory qualification", "do_not_position_as": "replace the local entity's current supplier", "first_objective": "verify procurement control, current manufacturer, OEM openness, and supplier qualification owner", "next_steps": ["verify legal/commercial relationship", "identify headquarters supply-chain owner", "separate brand owner/exporter/manufacturer", "prepare evidence-backed OEM capability comparison", "request one controlled specification trial"], "claim_class": "RECOMMENDATION"}
        return {"route_type": "direct_buyer_validation", "recommended_target": "verified buyer or category owner", "positioning": "additional-source evaluation", "do_not_position_as": "assume a quality or price problem", "first_objective": "verify buyer role and one priority specification", "next_steps": ["verify decision-maker", "confirm product/specification", "confirm supplier-evaluation process"], "claim_class": "RECOMMENDATION"}

    @staticmethod
    def _completeness(relationship: dict[str, Any], decision_center: dict[str, Any], brand_chain: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        checks = {
            "legal_relationship": relationship.get("legal_relationship") == "confirmed",
            "commercial_relationship": relationship.get("commercial_relationship") in {"confirmed", "strongly_supported"},
            "procurement_decision_center": decision_center.get("status") in {"CONFIRMED", "SUPPORTED_INFERENCE"},
            "brand_owner": brand_chain.get("brand_owner") != "unknown",
            "manufacturer_of_record": brand_chain.get("manufacturer_of_record") != "unknown",
            "verified_procurement_contact": any(item.get("procurement_authority_status") == "confirmed" and item.get("verification_status") == "official_current" for item in list_dicts(result.get("contact_evidence_ledger"))),
        }
        return {"checks": checks, "complete": all(checks.values()), "missing": [name for name, passed in checks.items() if not passed]}

    def _learning(self, enrichment: dict[str, Any]) -> dict[str, Any]:
        events, persistence = self.feedback_store.record_and_load(list_dicts(enrichment.get("feedback_events")))
        patterns = Counter((event.get("field_or_claim"), event.get("reason_code"), event.get("reviewer_decision")) for event in events if event.get("reviewer_decision") not in {"UNREVIEWED", ""})
        candidates = [{"field_or_claim": field, "reason_code": reason, "reviewer_decision": decision, "supporting_event_count": count, "status": "candidate_not_applied", "required_next_step": "Add independent cases, measure false positives, create regression fixtures, and obtain explicit approval."} for (field, reason, decision), count in patterns.items() if count >= 2]
        approved, rejected = [], []
        for raw in list_dicts(enrichment.get("approved_learning_rules")):
            effect = clean(raw.get("effect_scope"))
            cases = [str(item) for item in raw.get("regression_case_ids") or [] if item]
            precision = raw.get("measured_precision")
            false_positive = raw.get("false_positive_rate")
            valid = clean(raw.get("status")).upper() == "APPROVED" and bool(raw.get("approved_by")) and bool(raw.get("approved_at")) and effect in LEARNING_EFFECTS and len(cases) >= 3 and isinstance(precision, (int, float)) and precision >= 0.9 and isinstance(false_positive, (int, float)) and false_positive <= 0.05
            entry = {"rule_id": raw.get("rule_id"), "rule_version": raw.get("rule_version"), "effect_scope": effect, "regression_case_ids": cases, "measured_precision": precision, "false_positive_rate": false_positive, "approved_by": raw.get("approved_by"), "approved_at": raw.get("approved_at"), "status": "approved_bounded_hint" if valid else "rejected_not_applied"}
            (approved if valid else rejected).append(entry)
        return {"schema_version": STRATEGIC_VERSION, "feedback_events": events, "candidate_rules": candidates, "approved_bounded_rules": approved, "rejected_rule_submissions": rejected, "persistence": persistence, "automatic_rule_promotion": False, "automatic_code_modification": False, "online_model_weight_update": False, "allowed_learning_effects": sorted(LEARNING_EFFECTS), "prohibited_learning_effects": ["identity merge", "legal relationship confirmation", "contact verification", "procurement authority", "CRM acceptance", "automatic outreach or sending"], "governance": "Feedback may reprioritize research/manual checks only after approval and regression evidence; it never upgrades facts or writes code by itself."}


def build_decision_layers(result: dict[str, Any], enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    enrichment = enrichment if isinstance(enrichment, dict) else {}
    reviews = list_dicts(result.get("review_ledger"))
    accepted, modified, rejected, pending = [], [], [], []
    final_record: dict[str, Any] = {}
    for item in reviews:
        field = item.get("field")
        final = item.get("final_decision") or {}
        review_status = item.get("review_status")
        decision = item.get("review_decision")
        if review_status != "reviewed":
            pending.append({"field": field, "plugin_output": item.get("plugin_output"), "status": "PENDING_VERIFICATION"})
        elif decision == "rejected" or not final.get("crm_eligible"):
            rejected.append({"field": field, "plugin_output": item.get("plugin_output"), "reason": item.get("change_reason") or decision})
        else:
            entry = {"field": field, "value": final.get("value"), "status": final.get("status"), "reason": item.get("change_reason")}
            (modified if item.get("changed") else accepted).append(entry)
            final_record[field] = final.get("value")
    strategic_audit = enrichment.get("strategic_context", {}).get("assistant_audit") if isinstance(enrichment.get("strategic_context"), dict) and isinstance(enrichment.get("strategic_context", {}).get("assistant_audit"), dict) else {}
    for item in list_dicts(strategic_audit.get("crm_fields")):
        field = clean(item.get("field"))
        decision = clean(item.get("decision")).casefold()
        if not field:
            continue
        if decision == "accepted" and item.get("source_ids"):
            entry = {"field": field, "value": item.get("value"), "status": item.get("status") or "reviewed", "reason": item.get("reason")}
            accepted.append(entry)
            final_record[field] = item.get("value")
        elif decision in {"rejected", "blocked"}:
            rejected.append({"field": field, "plugin_output": item.get("value"), "reason": item.get("reason") or decision})
        else:
            pending.append({"field": field, "plugin_output": item.get("value"), "status": "PENDING_VERIFICATION"})
    status = "CRM_ACCEPTED" if final_record and not any(item.get("field") in {"buyer", "legal_name", "buyer_address"} for item in pending) else "PENDING_VERIFICATION"
    return {
        "plugin_raw_output": {"record_identity": result.get("record_identity"), "normalized_shipment": result.get("normalized_shipment"), "field_audit": result.get("field_audit"), "candidate_relationships": result.get("entities", {}).get("relationships"), "candidate_contacts": result.get("contact_evidence_ledger"), "candidate_crm": result.get("crm")},
        "assistant_audit": {"accepted": accepted, "modified": modified, "rejected": rejected, "pending": pending, "new_inferences": strategic_audit.get("new_inferences") or [], "commercial_decisions": strategic_audit.get("commercial_decisions") or [], "policy": "Strategic CRM fields require an explicit accepted decision plus source_ids; unsupported strategic candidates remain pending or rejected."},
        "final_crm": {"status": status, "record": final_record, "accepted_field_count": len(final_record), "pending_fields": [item.get("field") for item in pending], "rejected_fields": [item.get("field") for item in rejected], "export_allowed": status == "CRM_ACCEPTED", "policy": "Only explicitly reviewed and CRM-eligible final decisions are exportable. Plugin candidates remain separate."},
        "unresolved": result.get("unresolved") or [],
        "next_actions": result.get("next_actions") or [],
    }
