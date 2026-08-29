#!/usr/bin/env python3
"""Evidence-gated outreach planning for customs-buyer-intelligence.

This module never sends messages.  It creates a reviewable plan/draft and keeps
customs intelligence behind an explicit external-content firewall.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


OUTREACH_VERSION = "4.2.0"
MODES = {"RESEARCH_ONLY", "OUTREACH_PREVIEW", "CREATE_DRAFT", "SEND_CONFIRMED"}
SELLER = {
    "company": "Guangzhou XingHuai New Materials Co., Ltd.",
    "contact": "Mark Zhou",
    "mobile_whatsapp": "+86 180 2710 1852",
    "website": "www.xinghuai.com",
    "timezone": "Asia/Shanghai",
}

COUNTRY_LANGUAGE = {
    "philippines": ("English", None),
    "puerto rico": ("Spanish", "English"),
    "peru": ("Spanish", "English"),
    "mexico": ("Spanish", "English"),
    "ecuador": ("Spanish", "English"),
    "costa rica": ("Spanish", "English"),
    "brazil": ("Portuguese", "English"),
    "indonesia": ("Indonesian", "English"),
    "vietnam": ("Vietnamese", "English"),
    "france": ("French", "English"),
    "japan": ("Japanese", "English"),
    "south korea": ("Korean", "English"),
    "republic of korea": ("Korean", "English"),
    "sri lanka": ("English", None),
    "india": ("English", None),
}

COUNTRY_TIMEZONE = {
    "philippines": "Asia/Manila",
    "puerto rico": "America/Puerto_Rico",
    "peru": "America/Lima",
    "vietnam": "Asia/Ho_Chi_Minh",
    "indonesia": None,
    "brazil": None,
    "mexico": None,
    "ecuador": "America/Guayaquil",
    "costa rica": "America/Costa_Rica",
    "france": "Europe/Paris",
    "japan": "Asia/Tokyo",
    "south korea": "Asia/Seoul",
    "republic of korea": "Asia/Seoul",
    "sri lanka": "Asia/Colombo",
    "india": "Asia/Kolkata",
}

CITY_TIMEZONE = {
    "san juan": "America/Puerto_Rico",
    "carolina": "America/Puerto_Rico",
    "davao": "Asia/Manila",
    "da nang": "Asia/Ho_Chi_Minh",
    "danang": "Asia/Ho_Chi_Minh",
    "lima": "America/Lima",
    "paris": "Europe/Paris",
    "tokyo": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "jakarta": "Asia/Jakarta",
    "surabaya": "Asia/Jakarta",
    "bandung": "Asia/Jakarta",
    "medan": "Asia/Jakarta",
}

FIXED_TIMEZONE_OFFSETS = {
    "Asia/Shanghai": timedelta(hours=8),
    "Asia/Manila": timedelta(hours=8),
    "America/Puerto_Rico": timedelta(hours=-4),
    "America/Lima": timedelta(hours=-5),
    "Asia/Ho_Chi_Minh": timedelta(hours=7),
    "America/Guayaquil": timedelta(hours=-5),
    "America/Costa_Rica": timedelta(hours=-6),
    "Asia/Tokyo": timedelta(hours=9),
    "Asia/Seoul": timedelta(hours=9),
    "Asia/Jakarta": timedelta(hours=7),
    "Asia/Colombo": timedelta(hours=5, minutes=30),
    "Asia/Kolkata": timedelta(hours=5, minutes=30),
}


class EuropeParisFallback(tzinfo):
    """Dependency-free EU daylight-saving rules for the built-in Paris route."""

    standard_offset = timedelta(hours=1)
    daylight_offset = timedelta(hours=1)

    @staticmethod
    def _last_sunday(year: int, month: int, hour: int) -> datetime:
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        last_day = next_month - timedelta(days=1)
        sunday = last_day - timedelta(days=(last_day.weekday() + 1) % 7)
        return sunday.replace(hour=hour, minute=0, second=0, microsecond=0)

    def dst(self, value: datetime | None) -> timedelta:
        if value is None:
            return timedelta(0)
        local = value.replace(tzinfo=None)
        start_local = self._last_sunday(local.year, 3, 2)
        end_local = self._last_sunday(local.year, 10, 3)
        if end_local - timedelta(hours=1) <= local < end_local and value.fold:
            return timedelta(0)
        return self.daylight_offset if start_local <= local < end_local else timedelta(0)

    def utcoffset(self, value: datetime | None) -> timedelta:
        return self.standard_offset + self.dst(value)

    def tzname(self, value: datetime | None) -> str:
        return "CEST" if self.dst(value) else "CET"

    def fromutc(self, value: datetime) -> datetime:
        if value.tzinfo is not self:
            raise ValueError("fromutc requires a datetime using this timezone")
        utc_value = value.replace(tzinfo=None)
        start_utc = self._last_sunday(utc_value.year, 3, 1)
        end_utc = self._last_sunday(utc_value.year, 10, 1)
        daylight = start_utc <= utc_value < end_utc
        offset = self.standard_offset + (self.daylight_offset if daylight else timedelta(0))
        fold = 1 if end_utc <= utc_value < end_utc + timedelta(hours=1) else 0
        return (utc_value + offset).replace(tzinfo=self, fold=fold)


def timezone_or_fallback(zone_name: str) -> tuple[tzinfo, bool]:
    """Load IANA data, or use exact built-in rules for configured market zones."""
    try:
        return ZoneInfo(zone_name), False
    except ZoneInfoNotFoundError:
        if zone_name in FIXED_TIMEZONE_OFFSETS:
            return timezone(FIXED_TIMEZONE_OFFSETS[zone_name], name=zone_name), True
        if zone_name == "Europe/Paris":
            return EuropeParisFallback(), True
        raise

BUYER_TYPE_VALUES = {
    "decorative_wall_system_supplier": ["additional_source", "matching_profiles"],
    "brand_operator": ["additional_source", "private_label_evaluation"],
    "advertising_material_supplier": ["additional_source", "mixed_container_loading"],
    "furniture_material_supplier": ["specification_evaluation", "sheet_consistency"],
    "industrial_end_user": ["controlled_sample", "supplier_qualification"],
    "manufacturer": ["controlled_sample", "supplier_qualification"],
    "importer": ["additional_source", "supply_risk_diversification"],
    "distributor": ["additional_source", "selected_specification"],
    "wholesaler": ["additional_source", "selected_specification"],
    "retailer": ["selected_specification", "private_label_evaluation"],
    "trading_company": ["mixed_container_loading", "selected_specification"],
}

VALUE_TEXT = {
    "additional_source": "an additional factory-source evaluation",
    "backup_factory": "a backup-factory evaluation",
    "matching_profiles": "matching finishing-profile evaluation",
    "private_label_evaluation": "private-label evaluation",
    "mixed_container_loading": "mixed-loading evaluation",
    "specification_evaluation": "specification-controlled evaluation",
    "sheet_consistency": "sheet consistency review",
    "controlled_sample": "a controlled sample evaluation",
    "supplier_qualification": "your supplier-qualification process",
    "supply_risk_diversification": "source diversification",
    "selected_specification": "a selected specification trial",
}

HARD_BLOCK_TERMS = {
    "fireproof": "unsupported_fireproof_claim",
    "100% waterproof": "unsupported_absolute_waterproof_claim",
    "currently certified": "unverified_current_certification",
    "best price": "spam_or_unverified_price_claim",
    "lowest price": "spam_or_unverified_price_claim",
    "guaranteed": "unsupported_guarantee",
    "limited time": "false_urgency",
    "free sample": "unverified_offer",
    "xhhbjc.com": "prohibited_legacy_domain",
}

INTERNAL_TERMS = {
    "customs": "customs_source",
    "bill of lading": "bill_of_lading",
    "container number": "container_number",
    "imported from": "supplier_or_trade_intelligence",
    "we saw your import": "customs_surveillance_language",
    "we know you imported": "customs_surveillance_language",
    "your current supplier": "supplier_intelligence",
    "采购量": "customs_quantity",
    "提单": "bill_of_lading",
    "集装箱": "container_number",
    "现有供应商": "supplier_intelligence",
}


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def key(value: Any) -> str:
    return text(value).casefold()


def list_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def parse_dt(value: Any) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", value, flags=re.UNICODE))


def claim_entry(raw: dict[str, Any], index: int, *, seller: bool) -> dict[str, Any]:
    status = text(raw.get("status") or raw.get("capability_status") or ("VERIFIED" if raw.get("verified") else "UNVERIFIED")).upper()
    if seller and status not in {"VERIFIED", "CONDITIONAL", "UNVERIFIED", "EXPIRED_EVIDENCE", "NOT_SUPPORTED"}:
        status = "UNVERIFIED"
    claim_type = text(raw.get("claim_type") or "FACT").upper()
    if claim_type not in {"FACT", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"}:
        claim_type = "HYPOTHESIS"
    verified = bool(raw.get("verified")) or (seller and status == "VERIFIED")
    external = bool(raw.get("allowed_for_external_use")) and verified and claim_type == "FACT"
    return {
        "claim_id": text(raw.get("claim_id")) or ("seller" if seller else "buyer") + f"-{index:03d}",
        "claim": text(raw.get("claim")),
        "claim_type": claim_type,
        "status": status if seller else text(raw.get("status") or ("CONFIRMED" if verified else "UNVERIFIED_HYPOTHESIS")).upper(),
        "source": raw.get("source") or raw.get("source_reference"),
        "source_date": raw.get("source_date"),
        "confidence": raw.get("confidence", 100 if verified else 0),
        "verified": verified,
        "allowed_for_external_use": external,
        "reason": text(raw.get("reason")),
        "product_category": text(raw.get("product_category") or raw.get("product")),
        "value_keys": [text(item) for item in raw.get("value_keys") or [] if text(item)],
    }


class OutreachExecutionEngine:
    """Build a deterministic, review-only outreach package."""

    def build(self, result: dict[str, Any], enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
        enrichment = enrichment if isinstance(enrichment, dict) else {}
        context = enrichment.get("outreach_context") if isinstance(enrichment.get("outreach_context"), dict) else {}
        mode = text(context.get("mode") or "CREATE_DRAFT").upper()
        if mode not in MODES:
            mode = "CREATE_DRAFT"

        buyer_ledger = self._buyer_ledger(enrichment)
        seller_ledger = self._seller_ledger(enrichment)
        buyer_type, type_status = self._buyer_type(result, enrichment)
        email_routing = self._email_routing(result)
        contact = self._select_contact(result, email_routing)
        language = self._language(result, enrichment, contact)
        timezone_plan = self._timezone(result, enrichment)
        strategy = self._strategy(result, enrichment, buyer_type, type_status, buyer_ledger, seller_ledger)
        eligibility = self._eligibility(result, context, contact, seller_ledger, strategy)

        email = self._empty_email(contact, language)
        other_channels = self._empty_channels()
        firewall = {"passed": True, "blocked_items": [], "internal_fields_never_external": self._internal_fields()}
        risk = self._risk(context, contact, email, eligibility, firewall)
        quality = self._quality(result, strategy, email, risk, firewall)
        alternate_drafts: list[dict[str, Any]] = []

        if mode != "RESEARCH_ONLY" and eligibility["eligible"]:
            email = self._email(result, context, contact, language, strategy)
            firewall = self._firewall(result, email, seller_ledger)
            risk = self._risk(context, contact, email, eligibility, firewall)
            quality = self._quality(result, strategy, email, risk, firewall)
            other_channels = self._channels(contact, strategy, risk)
            alternate_drafts = self._alternate_drafts(result, context, language, strategy, seller_ledger, email_routing)

        status = self._state(mode, eligibility, risk, quality, context)
        send_blocked = status in {"BLOCKED", "RESEARCH_ONLY"} or mode != "SEND_CONFIRMED" or not bool(context.get("user_previewed"))
        risk["send_blocked"] = send_blocked
        risk["send_note"] = "This plugin creates reviewable previews/drafts only; an email connector requires a separate explicit user confirmation to send."
        follow_up = self._follow_up(timezone_plan, email, status)
        completion = self._completion(result, status, eligibility, email, firewall, risk, email_routing, alternate_drafts)

        return {
            "schema_version": OUTREACH_VERSION,
            "outreach_mode": mode,
            "outreach_status": status,
            "buyer": {
                "name": result.get("normalized_shipment", {}).get("buyer", {}).get("legal_name") or result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name"),
                "country": result.get("normalized_shipment", {}).get("buyer", {}).get("country"),
                "city": self._buyer_city(result, enrichment),
                "buyer_type": buyer_type,
                "buyer_type_status": type_status,
                "grade": result.get("scores", {}).get("enterprise_intelligence_grade"),
                "stage": result.get("scores", {}).get("stage"),
            },
            "contact": contact,
            "email_routing": email_routing,
            "buyer_evidence_ledger": buyer_ledger,
            "seller_capability_ledger": seller_ledger,
            "eligibility_gate": eligibility,
            "language": language,
            "timezone": timezone_plan,
            "strategy": strategy,
            "email": email,
            "alternate_drafts": alternate_drafts,
            "other_channels": other_channels,
            "external_content_firewall": firewall,
            "risk": risk,
            "quality": quality,
            "follow_up": follow_up,
            "completion": completion,
            "reply_handling_order": ["confirm_contact_identity", "confirm_need", "confirm_technical_specification", "quote", "sample", "supplier_qualification"],
            "success_criteria": [
                "Obtain the correct category owner or a verified internal referral.",
                "Confirm one priority product/specification or supplier-evaluation step.",
                "Do not expose customs, incumbent-supplier, inferred-specification, or private-contact intelligence.",
            ],
            "human_review_required": True,
            "automatic_send_supported": False,
        }

    @staticmethod
    def _completion(result: dict[str, Any], status: str, eligibility: dict[str, Any], email: dict[str, Any], firewall: dict[str, Any], risk: dict[str, Any], email_routing: dict[str, Any], alternate_drafts: list[dict[str, Any]]) -> dict[str, Any]:
        fit = result.get("normalized_shipment", {}).get("product", {}).get("match_level")
        role = key(result.get("buyer_intelligence", {}).get("buyer_role"))
        no_outreach = fit not in {"EXACT", "RELATED"} or any(token in role for token in ("broker", "forwarder", "notify"))
        omission_ok = email_routing.get("omission_check_passed") is True
        sendable = (
            status in {"PREVIEW_READY", "DRAFT_READY", "SEND_REQUIRES_CONFIRMATION"}
            and email.get("mailto_status") == "ready"
            and bool(email.get("mailto_url"))
            and firewall.get("passed") is True
            and risk.get("risk_level") not in {"BLOCK", "HIGH"}
            and omission_ok
        )
        terminal_state = "NO_OUTREACH_RECOMMENDED" if no_outreach else "SENDABLE_DRAFT" if sendable else "DRAFT_BLOCKED"
        reasons = [] if sendable else list(dict.fromkeys((eligibility.get("block_reasons") or []) + (risk.get("risk_reasons") or [])))
        if no_outreach:
            reasons = ["product_or_entity_not_suitable_for_sales_outreach"]
        elif not omission_ok:
            reasons.append("email_route_omission_detected")
        action = {
            "action_id": "open-email-draft",
            "label": "一键打开邮件草稿 / Open email draft",
            "kind": "open_url",
            "url": email.get("mailto_url") if sendable else None,
            "enabled": sendable,
            "requires_human_review": True,
            "sends_message": False,
        }
        return {
            "terminal_state": terminal_state,
            "report_only_output_forbidden": True,
            "completion_contract_passed": terminal_state in {"SENDABLE_DRAFT", "DRAFT_BLOCKED", "NO_OUTREACH_RECOMMENDED"},
            "required_user_visible_sections": ["full_intelligence_dossier", "recipient_evidence", "customer_language_email", "chinese_review_translation", "draft_action_or_block_reason"],
            "action": action,
            "alternate_actions": [item.get("action") for item in alternate_drafts if item.get("action")],
            "email_route_omission_check_passed": omission_ok,
            "discovered_email_count": email_routing.get("discovered_email_count", 0),
            "accounted_email_count": email_routing.get("accounted_email_count", 0),
            "simultaneous_multi_send_prohibited": True,
            "block_reasons": reasons,
            "draft_transport": "mailto_wecom_tencent_enterprise_compatible",
            "server_side_draft_created": False,
            "provider_draft_id": None,
            "connector_receipt": None,
            "connector_next_step": "Open the reviewed UTF-8 mailto draft in the user's configured WeCom/Tencent Enterprise Mail handler. A connected mail provider may create or send only after visible review and fresh explicit confirmation. Never label a mailto link as a server-side draft receipt.",
        }

    @staticmethod
    def _buyer_ledger(enrichment: dict[str, Any]) -> list[dict[str, Any]]:
        raw = list_dicts(enrichment.get("buyer_evidence_ledger"))
        for item in list_dicts(enrichment.get("field_claims")):
            if item.get("allowed_for_external_use") is True:
                raw.append({"claim": f"{text(item.get('field'))}: {text(item.get('normalized_value') or item.get('raw_value'))}", "claim_type": item.get("claim_type") or "FACT", "source": ",".join(item.get("source_ids") or []), "source_date": item.get("source_date"), "confidence": item.get("confidence"), "verified": item.get("verified", True), "allowed_for_external_use": True, "reason": "Explicit external-use field claim."})
        return [claim_entry(item, index, seller=False) for index, item in enumerate(raw, 1) if text(item.get("claim"))]

    @staticmethod
    def _seller_ledger(enrichment: dict[str, Any]) -> list[dict[str, Any]]:
        defaults = [
            {"claim_id": "seller-identity", "claim": "Guangzhou XingHuai New Materials Co., Ltd. is represented by Mark Zhou.", "claim_type": "FACT", "status": "VERIFIED", "source": "user-approved seller profile", "source_date": "2026-08-03", "confidence": 100, "verified": True, "allowed_for_external_use": True},
            {"claim_id": "seller-pvc-board", "claim": "XingHuai manufactures PVC boards.", "claim_type": "FACT", "status": "VERIFIED", "source": "user-approved seller profile and product catalogue", "source_date": "2026-08-03", "confidence": 95, "verified": True, "allowed_for_external_use": True, "product_category": "PVC boards", "value_keys": ["additional_source", "specification_evaluation"]},
        ]
        supplied = list_dicts(enrichment.get("seller_capability_ledger")) + list_dicts(enrichment.get("seller_capabilities"))
        return [claim_entry(item, index, seller=True) for index, item in enumerate(defaults + supplied, 1) if text(item.get("claim"))]

    @staticmethod
    def _buyer_type(result: dict[str, Any], enrichment: dict[str, Any]) -> tuple[str, str]:
        profile = enrichment.get("buyer_profile") if isinstance(enrichment.get("buyer_profile"), dict) else {}
        explicit = text(profile.get("buyer_type") or enrichment.get("buyer_type"))
        if explicit:
            return explicit, text(profile.get("status") or "SUPPORTED_INFERENCE").upper()
        role = key(result.get("buyer_intelligence", {}).get("buyer_role"))
        business = key(result.get("buyer_intelligence", {}).get("business_model"))
        product = key(result.get("normalized_shipment", {}).get("product", {}).get("raw_description"))
        combined = " ".join((role, business, product))
        if any(token in combined for token in ("decorative", "wall cladding", "wallboard", "wall panel")):
            return "decorative_wall_system_supplier", "SUPPORTED_INFERENCE"
        if any(token in combined for token in ("furniture", "cabinet")):
            return "furniture_material_supplier", "SUPPORTED_INFERENCE"
        if any(token in combined for token in ("advertising", "signage", "printing")):
            return "advertising_material_supplier", "SUPPORTED_INFERENCE"
        for candidate in ("customs_broker", "freight_forwarder", "manufacturer", "importer", "distributor", "wholesaler", "retailer", "trading_company", "industrial_end_user"):
            if candidate.replace("_", " ") in combined or candidate in combined:
                return candidate, "SUPPORTED_INFERENCE"
        return "unknown", "UNVERIFIED_HYPOTHESIS"

    @staticmethod
    def _email_routing(result: dict[str, Any]) -> dict[str, Any]:
        """Account for every discovered email, then rank safe sequential routes."""
        ledger = list_dicts(result.get("contact_evidence_ledger"))
        emails = [item for item in ledger if item.get("contact_type") == "email" and text(item.get("value"))]
        routes: list[dict[str, Any]] = []
        seen: set[str] = set()
        rank_order = {"DIRECT_PROCUREMENT": 0, "FORMAL_GENERAL": 1, "ALTERNATIVE_REFERRAL": 2, "VERIFY_ONLY": 3, "DO_NOT_USE": 4}
        for index, item in enumerate(emails, 1):
            address = text(item.get("value"))
            normalized = address.casefold()
            duplicate = normalized in seen
            seen.add(normalized)
            role = key(item.get("role"))
            risks = [text(value) for value in item.get("risk_note") or [] if text(value)]
            person_current = not item.get("person_name") or item.get("position_status") == "current_confirmed"
            current_verified = item.get("verification_status") == "official_current" and item.get("evidence_grade") in {"A1", "A2"} and person_current
            hr_route = any(token in role for token in ("human resources", "recruit", "talent", " hr", "hr ")) or address.casefold().startswith(("hr@", "hrd@", "career@", "careers@", "jobs@", "recruitment@"))
            logistics_route = any(token in role for token in ("broker", "shipping", "traffic", "customs", "logistics", "freight"))
            serious_risks = [risk for risk in risks if risk != "role_not_verified_as_procurement"]
            if duplicate:
                route_class, reason = "VERIFY_ONLY", "duplicate_address_already_accounted_for"
            elif hr_route:
                route_class, reason = "DO_NOT_USE", "hr_or_recruitment_route_not_for_supplier_outreach"
            elif logistics_route:
                route_class, reason = "DO_NOT_USE", "logistics_or_broker_route_not_for_supplier_outreach"
            elif not current_verified:
                route_class, reason = "VERIFY_ONLY", "email_not_current_A1_A2_verified"
            elif serious_risks:
                route_class, reason = "VERIFY_ONLY", "contact_has_blocking_risk"
            elif item.get("procurement_authority_status") == "confirmed":
                route_class, reason = "DIRECT_PROCUREMENT", "current_verified_procurement_route"
            elif item.get("channel_use") == "official_company_general" or not role or any(token in role for token in ("general", "company", "inquiry", "enquiry", "office", "customer service")):
                route_class, reason = "FORMAL_GENERAL", "current_verified_company_route_for_internal_forwarding"
            else:
                route_class, reason = "ALTERNATIVE_REFERRAL", "current_verified_business_route_but_procurement_authority_unconfirmed"
            routes.append({
                "route_id": item.get("contact_id") or f"email-route-{index:03d}",
                "email": address,
                "person_name": item.get("person_name"),
                "role": item.get("role"),
                "route_class": route_class,
                "reason": reason,
                "eligible_for_sequential_draft": route_class in {"DIRECT_PROCUREMENT", "FORMAL_GENERAL", "ALTERNATIVE_REFERRAL"},
                "simultaneous_send_allowed": False,
                "verification_status": item.get("verification_status") or "unverified",
                "evidence_grade": item.get("evidence_grade") or "D",
                "position_status": item.get("position_status"),
                "procurement_authority_status": item.get("procurement_authority_status") or "unconfirmed",
                "channel_use": item.get("channel_use"),
                "recommended_use": item.get("recommended_use"),
                "source_reference": item.get("source_reference"),
                "source_date": item.get("source_date"),
                "risk_note": risks,
            })
        routes.sort(key=lambda item: (rank_order.get(item["route_class"], 9), item["email"].casefold()))
        eligible = [item for item in routes if item["eligible_for_sequential_draft"]]
        primary = eligible[0] if eligible else None
        alternatives = [item for item in eligible if item is not primary]
        for item in routes:
            item["selection"] = "PRIMARY" if item is primary else "ALTERNATIVE_SEQUENTIAL" if item in alternatives else item["route_class"]
        unique_count = len({item["email"].casefold() for item in routes})
        return {
            "policy": "Exhaustively display every discovered address; draft only current verified business routes; use one route at a time and never default to CC/BCC blasting.",
            "discovered_email_count": len(emails),
            "unique_email_count": unique_count,
            "accounted_email_count": len(routes),
            "omission_check_passed": len(routes) == len(emails),
            "primary_route": primary,
            "alternative_routes": alternatives,
            "verify_only_routes": [item for item in routes if item["route_class"] == "VERIFY_ONLY"],
            "do_not_use_routes": [item for item in routes if item["route_class"] == "DO_NOT_USE"],
            "all_routes": routes,
            "recommended_sequence": "Primary route first. Use one alternate only after human review, an appropriate interval, or evidence that the primary route is unsuitable. Do not send all routes simultaneously.",
        }

    @staticmethod
    def _select_contact(result: dict[str, Any], email_routing: dict[str, Any] | None = None) -> dict[str, Any]:
        ledger = list_dicts(result.get("contact_evidence_ledger"))
        routing = email_routing or OutreachExecutionEngine._email_routing(result)
        chosen = routing.get("primary_route") or {}
        usable = bool(chosen) and chosen.get("eligible_for_sequential_draft") is True
        return {
            "name": chosen.get("person_name"),
            "role": chosen.get("role"),
            "role_verified": chosen.get("position_status") == "current_confirmed",
            "procurement_authority_status": chosen.get("procurement_authority_status") or "unconfirmed",
            "email": chosen.get("email") if usable else "",
            "candidate_email": (chosen.get("email") if chosen else "") or next((item.get("email") for item in routing.get("all_routes") or []), ""),
            "phone": next((item.get("value") for item in ledger if item.get("contact_type") == "phone" and item.get("verification_status") == "official_current" and not item.get("risk_note")), ""),
            "whatsapp": next((item.get("value") for item in ledger if item.get("contact_type") == "phone" and item.get("whatsapp_status") == "confirmed_by_current_official_source"), ""),
            "source": chosen.get("source_reference"),
            "source_date": chosen.get("source_date"),
            "confidence_grade": chosen.get("evidence_grade") or "D",
            "verification_status": chosen.get("verification_status") or "NOT_YET_VERIFIED",
            "recommended_use": chosen.get("recommended_use") or "verify_before_use",
            "risk_note": chosen.get("risk_note") or ([] if usable else ["no_current_A1_A2_email"]),
            "route_class": chosen.get("route_class") or "NO_ELIGIBLE_ROUTE",
        }

    def _language(self, result: dict[str, Any], enrichment: dict[str, Any], contact: dict[str, Any]) -> dict[str, Any]:
        context = enrichment.get("outreach_context") if isinstance(enrichment.get("outreach_context"), dict) else {}
        evidence = enrichment.get("language_evidence") if isinstance(enrichment.get("language_evidence"), dict) else {}
        explicit = text(context.get("primary_language") or evidence.get("primary"))
        if explicit:
            return {"primary": explicit, "secondary": text(context.get("secondary_language") or evidence.get("secondary")) or None, "confidence": evidence.get("confidence", 90), "reason": text(evidence.get("reason") or "Explicit website/contact language evidence."), "source_ids": evidence.get("source_ids") or []}
        country = key(result.get("normalized_shipment", {}).get("buyer", {}).get("country"))
        primary, secondary = COUNTRY_LANGUAGE.get(country, ("English", None))
        return {"primary": primary, "secondary": secondary, "confidence": 60 if country in COUNTRY_LANGUAGE else 40, "reason": "Country/industry fallback only; replace with current website, social, or contact-language evidence.", "source_ids": []}

    @staticmethod
    def _buyer_city(result: dict[str, Any], enrichment: dict[str, Any]) -> str | None:
        profile = enrichment.get("buyer_profile") if isinstance(enrichment.get("buyer_profile"), dict) else {}
        return text(profile.get("city") or enrichment.get("buyer_city")) or None

    def _timezone(self, result: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
        context = enrichment.get("outreach_context") if isinstance(enrichment.get("outreach_context"), dict) else {}
        city = key(self._buyer_city(result, enrichment))
        country = key(result.get("normalized_shipment", {}).get("buyer", {}).get("country"))
        zone_name = text(context.get("buyer_timezone")) or CITY_TIMEZONE.get(city) or COUNTRY_TIMEZONE.get(country)
        now = parse_dt(context.get("current_datetime")) or datetime.now(timezone.utc)
        seller_zone, _ = timezone_or_fallback(SELLER["timezone"])
        beijing_now = now.astimezone(seller_zone)
        if not zone_name:
            return {"calculated_at_utc": now.isoformat(), "beijing_time_now": beijing_now.isoformat(), "buyer_local_time_now": None, "buyer_iana_timezone": None, "buyer_local_send_time": None, "china_send_time": None, "time_difference": None, "dst_status": "unknown", "working_day": None, "holiday_status": "not_checked", "recommended_send_window": "Tue-Thu 08:30-10:30 buyer local time after timezone verification", "recommended_call_window": "09:30-11:30 or 14:00-16:00 buyer local time after timezone verification", "beijing_equivalent_window": None, "reason": "Country has multiple timezones or city was not verified."}
        try:
            buyer_zone, used_timezone_fallback = timezone_or_fallback(zone_name)
        except ZoneInfoNotFoundError:
            return {"calculated_at_utc": now.isoformat(), "beijing_time_now": beijing_now.isoformat(), "buyer_local_time_now": None, "buyer_iana_timezone": zone_name, "buyer_local_send_time": None, "china_send_time": None, "time_difference": None, "dst_status": "unknown", "working_day": None, "holiday_status": "not_checked", "beijing_equivalent_window": None, "reason": "Invalid or unavailable IANA timezone; manual verification required."}
        local_now = now.astimezone(buyer_zone)
        window_start = local_now.replace(hour=8, minute=30, second=0, microsecond=0)
        if window_start <= local_now:
            window_start += timedelta(days=1)
        while window_start.weekday() not in {1, 2, 3}:
            window_start += timedelta(days=1)
        window_end = window_start.replace(hour=10, minute=30)
        china_start = window_start.astimezone(seller_zone)
        china_end = window_end.astimezone(seller_zone)
        diff = local_now.utcoffset() - beijing_now.utcoffset()
        dst = window_start.dst()
        return {
            "calculated_at_utc": now.isoformat(),
            "beijing_time_now": beijing_now.isoformat(),
            "buyer_local_time_now": local_now.isoformat(),
            "buyer_iana_timezone": zone_name,
            "buyer_local_send_time": window_start.isoformat(),
            "buyer_local_window_end": window_end.isoformat(),
            "china_send_time": china_start.isoformat(),
            "china_window_end": china_end.isoformat(),
            "time_difference": f"{diff.total_seconds() / 3600:+g} hours buyer minus Guangzhou",
            "dst_status": "active" if dst and dst != timedelta(0) else "not_active",
            "working_day": window_start.weekday() < 5,
            "holiday_status": "not_checked_requires_current_calendar",
            "recommended_send_window": "Tue-Thu 08:30-10:30 buyer local time",
            "beijing_equivalent_window": f"{china_start.isoformat()} to {china_end.isoformat()}",
            "recommended_call_window": "09:30-11:30 or 14:00-16:00 buyer local time",
            "reason": (
                "Built-in verified UTC-offset/DST fallback because the local IANA database is unavailable; "
                "public holidays require a current local calendar check."
                if used_timezone_fallback
                else "IANA timezone calculation; public holidays require a current local calendar check."
            ),
        }

    @staticmethod
    def _strategy(result: dict[str, Any], enrichment: dict[str, Any], buyer_type: str, type_status: str, buyer_ledger: list[dict[str, Any]], seller_ledger: list[dict[str, Any]]) -> dict[str, Any]:
        context = enrichment.get("outreach_context") if isinstance(enrichment.get("outreach_context"), dict) else {}
        strategic_route = result.get("strategic_intelligence", {}).get("development_route") or {}
        supplied = list_dicts(context.get("buyer_problem_hypotheses"))
        hypotheses = []
        for index, item in enumerate(supplied, 1):
            status = text(item.get("status") or "UNVERIFIED_HYPOTHESIS").upper()
            if status == "HYPOTHESIS":
                status = "UNVERIFIED_HYPOTHESIS"
            if status not in {"CONFIRMED", "SUPPORTED_INFERENCE", "UNVERIFIED_HYPOTHESIS"}:
                status = "UNVERIFIED_HYPOTHESIS"
            hypotheses.append({"hypothesis_id": text(item.get("hypothesis_id")) or f"problem-{index:03d}", "problem": text(item.get("problem")), "status": status, "source_ids": item.get("source_ids") or [], "external_wording_policy": "direct" if status == "CONFIRMED" and item.get("allowed_for_external_use") else "conditional_only"})
        values = [text(item) for item in context.get("value_keys") or [] if text(item)] or BUYER_TYPE_VALUES.get(buyer_type, ["additional_source", "specification_evaluation"])
        verified_values = []
        all_verified_keys = {value for item in seller_ledger if item.get("allowed_for_external_use") for value in item.get("value_keys") or []}
        for value in values:
            if value in {"additional_source", "specification_evaluation", "selected_specification", "controlled_sample", "supplier_qualification", "supply_risk_diversification"} or value in all_verified_keys:
                verified_values.append(value)
        verified_values = verified_values[:2]
        capabilities = [item for item in seller_ledger if item.get("allowed_for_external_use") and item.get("product_category")]
        requested_product = text(context.get("primary_product"))
        verified_products = {key(item.get("product_category")): item.get("product_category") for item in capabilities}
        product = verified_products.get(key(requested_product), "") if requested_product else ""
        product = product or (capabilities[0].get("product_category") if capabilities else "")
        if not hypotheses:
            hypotheses.append({"hypothesis_id": "problem-default", "problem": VALUE_TEXT.get(verified_values[0] if verified_values else "additional_source"), "status": type_status if type_status in {"CONFIRMED", "SUPPORTED_INFERENCE"} else "UNVERIFIED_HYPOTHESIS", "source_ids": [], "external_wording_policy": "conditional_only"})
        reverse_route = strategic_route.get("route_type") == "reverse_to_headquarters"
        opening_claim_id = text(context.get("opening_observation_claim_id"))
        opening_claim = next((item for item in buyer_ledger if item.get("claim_id") == opening_claim_id and item.get("claim_type") == "FACT" and item.get("verified") and item.get("allowed_for_external_use")), None)
        return {
            "buyer_problem_hypotheses": hypotheses,
            "positioning": text(context.get("positioning")) or ("OEM, controlled trial, or backup-factory qualification" if reverse_route else "additional supplier evaluation"),
            "primary_product": product,
            "primary_value": VALUE_TEXT.get(verified_values[0], "") if verified_values else "",
            "secondary_value": VALUE_TEXT.get(verified_values[1], "") if len(verified_values) > 1 else "",
            "value_keys": verified_values,
            "cta": text(context.get("cta")) or "identify the responsible category owner",
            "opening_observation": opening_claim.get("claim") if opening_claim else "",
            "opening_observation_claim_id": opening_claim_id if opening_claim else None,
            "strategic_route": strategic_route,
            "target_route_verified": bool(context.get("target_route_verified")),
            "claim_boundary": "Unconfirmed buyer problems must be phrased conditionally; no customs-derived specification may be presented as public buyer information.",
        }

    @staticmethod
    def _eligibility(result: dict[str, Any], context: dict[str, Any], contact: dict[str, Any], seller_ledger: list[dict[str, Any]], strategy: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        grade = result.get("scores", {}).get("enterprise_intelligence_grade")
        if grade not in {"A", "B"}:
            reasons.append("buyer_identity_unresolved")
        role = key(result.get("buyer_intelligence", {}).get("buyer_role"))
        if role in {"customs_broker", "freight_forwarder"} or any(token in role for token in ("broker", "forwarder", "notify")):
            reasons.append("customs_broker_only")
        fit = result.get("normalized_shipment", {}).get("product", {}).get("match_level")
        if fit not in {"EXACT", "RELATED"}:
            reasons.append("product_mismatch")
        if not contact.get("email"):
            reasons.append("only_inferred_email" if contact.get("candidate_email") else "no_verified_contact_channel")
        if contact.get("verification_status") in {"rejected", "REJECTED"}:
            reasons.append("contact_rejected")
        if not any(item.get("allowed_for_external_use") and item.get("product_category") for item in seller_ledger):
            reasons.append("capability_unverified")
        if not strategy.get("primary_product") or not strategy.get("primary_value"):
            reasons.append("capability_or_value_unresolved")
        if context.get("unsubscribed"):
            reasons.append("already_unsubscribed")
        if context.get("rejected_contact"):
            reasons.append("contact_rejected")
        if result.get("data_quality", {}).get("scoring_suspended"):
            reasons.append("legal_or_compliance_risk")
        if strategy.get("strategic_route", {}).get("route_type") == "reverse_to_headquarters" and not strategy.get("target_route_verified"):
            reasons.append("headquarters_route_contact_unverified")
        return {"eligible": not reasons, "status": "PASS" if not reasons else "BLOCK", "block_reasons": list(dict.fromkeys(reasons)), "required_conditions": ["buyer identity grade A/B", "buyer is not logistics-only", "product fit EXACT/RELATED", "current A1/A2 email", "verified externally usable seller capability", "no suppression or duplicate-contact block"]}

    @staticmethod
    def _empty_email(contact: dict[str, Any], language: dict[str, Any]) -> dict[str, Any]:
        return {"to": contact.get("email") or "", "subject": "", "body": "", "word_count": 0, "message_language": language.get("primary"), "chinese_translation": "", "mailto_url": None, "mailto_status": "not_generated", "human_style": {"passed": False, "target_word_range": [80, 110], "issues": ["draft_not_generated"]}, "human_review_required": True}

    @staticmethod
    def _empty_channels() -> dict[str, Any]:
        return {"whatsapp_first": "", "whatsapp_after_reply": "", "social_message": "", "phone_script": "", "recommended_sequence": "Email first. Use another channel only after human review and when that channel is publicly verified; no automatic same-day escalation."}

    @staticmethod
    def _human_style(subject: str, body: str, language: str) -> dict[str, Any]:
        words = word_count(body)
        questions = body.count("?") + body.count("？")
        lower = f"{subject}\n{body}".casefold()
        disclosure = any(phrase in lower for phrase in ("i reviewed your", "i analyzed your", "public catalog", "public catalogue", "public website", "according to your linkedin", "our research shows"))
        technical_terms = sum(1 for term in ("density", "weight per sheet", "flatness", "packaging", "fob", "cif", "quotation", "unit price", "lead time", "surface finish", "technical data sheet") if term in lower)
        sentences = [item.strip() for item in re.split(r"[.!?。！？]+", body) if item.strip()]
        longest_sentence_words = max((word_count(item) for item in sentences), default=0)
        issues: list[str] = []
        blocking: list[str] = []
        if words < 80:
            issues.append("first_email_below_80_word_target")
        if words > 110:
            issues.append("first_email_over_110_words")
            blocking.append("first_email_over_110_words")
        if questions != 1:
            issues.append("first_email_requires_exactly_one_low_friction_question")
            blocking.append("first_email_requires_exactly_one_low_friction_question")
        if disclosure:
            issues.append("research_process_disclosure_or_ai_style_phrase")
            blocking.append("research_process_disclosure_or_ai_style_phrase")
        if technical_terms >= 4:
            issues.append("technical_questionnaire_density")
            blocking.append("technical_questionnaire_density")
        if longest_sentence_words > 34:
            issues.append("overly_long_sentence")
        return {
            "passed": not blocking,
            "target_word_range": [80, 110],
            "word_count": words,
            "question_count": questions,
            "technical_term_count": technical_terms,
            "longest_sentence_words": longest_sentence_words,
            "research_process_disclosure": disclosure,
            "issues": issues,
            "blocking_issues": blocking,
            "principle": "Deep research stays backstage; the first email uses one verified match, one buyer value, and one low-friction question.",
            "language": language,
        }

    def _email(self, result: dict[str, Any], context: dict[str, Any], contact: dict[str, Any], language: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
        buyer_name = text(result.get("normalized_shipment", {}).get("buyer", {}).get("legal_name") or result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name")) or "Team"
        product = strategy.get("primary_product") or "PVC boards"
        values = [item for item in (strategy.get("primary_value"), strategy.get("secondary_value")) if item and item != "an additional factory-source evaluation"]
        value_phrase = values[0] if values else "supplier evaluation"
        role = key(contact.get("role"))
        procurement = contact.get("procurement_authority_status") == "confirmed"
        named = text(contact.get("name"))
        greeting = f"Dear {named}," if named else f"Dear {buyer_name} Team,"
        transfer = not procurement
        first = f"I’m Mark Zhou from {SELLER['company']}, a Chinese manufacturer of PVC boards."
        if transfer:
            first += f" Please forward this message to the person responsible for {product} sourcing and supplier evaluation."
        observation = text(strategy.get("opening_observation"))
        observation_text = (observation.rstrip(".!?") + ". ") if observation else ""
        second = f"{observation_text}We would like to see whether an additional factory source for {product}, focused on {value_phrase}, would be relevant for your team."
        if procurement:
            cta = "Could you advise which specification or supplier-evaluation step should be reviewed first?"
        elif any(token in role for token in ("technical", "product development", "engineer")):
            cta = "Could you advise the required performance criteria and sample-validation process?"
        elif any(token in role for token in ("management", "director", "president", "owner", "general manager")):
            cta = "Could you advise whether you oversee this category or who should receive the evaluation brief?"
        else:
            cta = "Could you point me to the person responsible for this category?"
        body = "\n\n".join((greeting, first, second, cta, f"Best regards,\n\n{SELLER['contact']}\n{SELLER['company']}\nMobile / WhatsApp: {SELLER['mobile_whatsapp']}\nWebsite: {SELLER['website']}"))
        subject = text(context.get("subject")) or (f"{product} for Supplier Evaluation")
        supplied_draft = context.get("draft") if isinstance(context.get("draft"), dict) else None
        if supplied_draft:
            supplied = context["draft"]
            subject = text(supplied.get("subject")) or subject
            body = str(supplied.get("body") or body).strip()
        chinese = "\n\n".join((f"尊敬的{named or buyer_name}团队：", f"我是Mark Zhou，来自{SELLER['company']}，我们是中国PVC板材制造商。" + (f"烦请将本邮件转交负责{product}采购与供应商评估的同事。" if transfer else ""), f"我们希望作为{product}的备选工厂接受评估，重点围绕{value_phrase}。", "烦请告知该品类负责人。" if transfer else "烦请告知应优先评估的规格或供应商准入步骤。", f"此中文仅供审核，不随客户邮件发送。\n\nMark Zhou\n{SELLER['company']}"))
        recipient = contact.get("email") or ""
        encoded = f"mailto:{quote(recipient)}?subject={quote(subject)}&body={quote(body)}"
        mailto = encoded if recipient and len(encoded) <= 1900 else None
        body_language = text((supplied_draft or {}).get("language")) or (language.get("primary") if supplied_draft else "English")
        language_match = key(body_language) == key(language.get("primary"))
        human_style = self._human_style(subject, body, body_language)
        return {"to": recipient, "subject": subject, "body": body, "word_count": word_count(body), "message_language": body_language, "selected_primary_language": language.get("primary"), "language_match_confirmed": language_match, "structure_attestation": (supplied_draft or {}).get("structure_attestation") or {}, "language_note": "Built-in draft is English unless a reviewed outreach_context.draft with its language is supplied; translate to the selected primary language and rerun the firewall before use." if not language_match else "Draft language matches the selected primary language.", "chinese_translation": chinese, "mailto_url": mailto, "mailto_status": "ready" if mailto else "recipient_missing" if not recipient else "too_long_use_email_draft_api", "human_style": human_style, "human_review_required": True}

    def _alternate_drafts(self, result: dict[str, Any], context: dict[str, Any], language: dict[str, Any], strategy: dict[str, Any], seller_ledger: list[dict[str, Any]], email_routing: dict[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for route in email_routing.get("alternative_routes") or []:
            contact = {
                "name": route.get("person_name"), "role": route.get("role"),
                "procurement_authority_status": route.get("procurement_authority_status") or "unconfirmed",
                "email": route.get("email"), "candidate_email": "",
                "verification_status": route.get("verification_status"), "route_class": route.get("route_class"),
            }
            email = self._email(result, context, contact, language, strategy)
            firewall = self._firewall(result, email, seller_ledger)
            reasons: list[str] = []
            if not firewall.get("passed"):
                reasons.extend(item.get("code") for item in firewall.get("blocked_items") or [])
            if email.get("language_match_confirmed") is not True:
                reasons.append("buyer_language_draft_not_reviewed")
            if not email.get("human_style", {}).get("passed"):
                reasons.extend(email.get("human_style", {}).get("blocking_issues") or [])
            if not email.get("mailto_url"):
                reasons.append("mailto_not_available")
            enabled = not reasons
            output.append({
                "route_id": route.get("route_id"), "recipient": route.get("email"),
                "role": route.get("role"), "route_class": route.get("route_class"),
                "source_reference": route.get("source_reference"), "email": email,
                "action": {"action_id": f"open-email-draft-{route.get('route_id')}", "label": f"打开备选草稿：{route.get('email')}", "kind": "open_url", "url": email.get("mailto_url") if enabled else None, "enabled": enabled, "requires_human_review": True, "sends_message": False},
                "block_reasons": list(dict.fromkeys(reason for reason in reasons if reason)),
                "sequence_policy": "Alternative route only; do not send simultaneously with the primary route.",
            })
        return output

    @staticmethod
    def _internal_fields() -> list[str]:
        return ["customs source/provider", "bill/container/declaration identifiers", "exact shipment dates/quantity/weight/value", "incumbent or historical supplier names", "purchase frequency", "inferred density/thickness/sheet count", "buyer risk score", "broker/private-person details", "internal competitive strategy"]

    def _firewall(self, result: dict[str, Any], email: dict[str, Any], seller_ledger: list[dict[str, Any]]) -> dict[str, Any]:
        combined = f"{email.get('subject', '')}\n{email.get('body', '')}"
        lower = combined.casefold()
        blocked: list[dict[str, Any]] = []
        for phrase, code in {**INTERNAL_TERMS, **HARD_BLOCK_TERMS}.items():
            if phrase.casefold() in lower:
                blocked.append({"code": code, "matched": phrase, "severity": "block"})
        for pattern, code in ((r"\[(?:your|name|email|whatsapp|website)[^\]]*\]", "signature_placeholder"), (r"\{\{[^}]+\}\}", "template_placeholder"), (r"(?i)\bTODO\b", "unfinished_draft")):
            match = re.search(pattern, combined, flags=re.IGNORECASE)
            if match:
                blocked.append({"code": code, "matched": match.group(0), "severity": "block"})
        required_signature = (SELLER["contact"], SELLER["company"], SELLER["mobile_whatsapp"], SELLER["website"])
        for required in required_signature:
            if required not in combined:
                blocked.append({"code": "incomplete_fixed_signature", "matched": required, "severity": "block"})
        shipment = result.get("normalized_shipment") or {}
        supplier_names = [shipment.get("supplier", {}).get("raw_name"), shipment.get("supplier", {}).get("legal_name")]
        for name in supplier_names:
            if len(text(name)) >= 5 and key(name) in lower:
                blocked.append({"code": "incumbent_supplier_name", "matched": text(name), "severity": "block"})
        identity = result.get("record_identity") or {}
        for item in [identity.get("master_bill"), identity.get("house_bill"), *(identity.get("container_numbers") or [])]:
            if text(item) and key(item) in lower:
                blocked.append({"code": "shipment_identifier", "matched": text(item), "severity": "block"})
        qty = shipment.get("quantity") or {}
        for item in (qty.get("weight_kg"), qty.get("gross_weight_kg"), qty.get("declared_quantity"), qty.get("package_count")):
            if item is not None and re.search(rf"(?<!\d){re.escape(str(item))}(?!\d)", combined):
                blocked.append({"code": "exact_customs_quantity_or_weight", "matched": str(item), "severity": "block"})
        return {"passed": not blocked, "blocked_items": blocked, "internal_fields_never_external": self._internal_fields(), "seller_claim_policy": "Only VERIFIED, FACT, allowed_for_external_use seller ledger entries may appear.", "external_claim_ids": [item.get("claim_id") for item in seller_ledger if item.get("allowed_for_external_use")]}

    @staticmethod
    def _risk(context: dict[str, Any], contact: dict[str, Any], email: dict[str, Any], eligibility: dict[str, Any], firewall: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = list(eligibility.get("block_reasons") or [])
        score = 0
        hard = False
        if not contact.get("email"):
            score += 80
            hard = True
        if contact.get("candidate_email") and not contact.get("email"):
            reasons.append("inferred_or_historical_email_not_allowed_in_to")
        if context.get("unsubscribed") or context.get("rejected_contact"):
            score = 100
            hard = True
        last = parse_dt(context.get("last_first_email_at"))
        now = parse_dt(context.get("current_datetime")) or datetime.now(timezone.utc)
        if last and now - last < timedelta(hours=72):
            score = max(score, 90)
            hard = True
            reasons.append("duplicate_contact_window")
        if context.get("automatic_batch_send"):
            score = 100
            hard = True
            reasons.append("automatic_batch_send_prohibited")
        if not firewall.get("passed", True):
            score = max(score, 90)
            hard = True
            reasons.extend(item.get("code") for item in firewall.get("blocked_items") or [])
        subject = text(email.get("subject"))
        body = text(email.get("body"))
        if subject and not 30 <= len(subject) <= 60:
            score += 10
            reasons.append("subject_length_outside_30_60")
        if body and email.get("word_count", 0) > 110:
            score += 20
            reasons.append("first_email_over_110_words")
        if body and email.get("word_count", 0) < 80:
            score += 5
            reasons.append("first_email_below_80_word_target")
        style = email.get("human_style") if isinstance(email.get("human_style"), dict) else {}
        style_blockers = style.get("blocking_issues") or []
        if "first_email_requires_exactly_one_low_friction_question" in style_blockers:
            score += 20
            reasons.append("first_email_requires_exactly_one_low_friction_question")
        if "research_process_disclosure_or_ai_style_phrase" in style_blockers:
            score += 15
            reasons.append("research_process_disclosure_or_ai_style_phrase")
        if "technical_questionnaire_density" in style_blockers:
            score += 20
            reasons.append("technical_questionnaire_density")
        if subject.isupper() and subject:
            score += 20
            reasons.append("all_caps_subject")
        if body.count("!") + subject.count("!") > 1:
            score += 10
            reasons.append("excess_exclamation")
        if context.get("tracking_pixel") or context.get("short_link"):
            score += 30
            reasons.append("tracking_or_short_link_not_allowed")
        if context.get("attachment_count", 0) or context.get("image_count", 0):
            score += 15
            reasons.append("first_contact_attachment_or_image")
        score = min(100, score)
        level = "BLOCK" if hard or score >= 80 else "HIGH" if score >= 60 else "REVISE" if score >= 30 else "LOW"
        return {"deliverability_contact_risk_score": score, "risk_level": level, "risk_reasons": list(dict.fromkeys(reason for reason in reasons if reason)), "heuristic_only": True, "guarantee": "No deliverability guarantee; this score only flags relevance, contact, content, and frequency risks."}

    @staticmethod
    def _quality(result: dict[str, Any], strategy: dict[str, Any], email: dict[str, Any], risk: dict[str, Any], firewall: dict[str, Any]) -> dict[str, Any]:
        body = text(email.get("body"))
        relevance = 30 if result.get("normalized_shipment", {}).get("product", {}).get("match_level") in {"EXACT", "RELATED"} and strategy.get("primary_product") else 10
        style = email.get("human_style") if isinstance(email.get("human_style"), dict) else {}
        clarity = 20 if body and 80 <= email.get("word_count", 0) <= 110 and style.get("passed") and email.get("body", "").count("\n\n") >= 2 else 15 if body and email.get("word_count", 0) <= 110 and style.get("passed") else 10 if body else 0
        credibility = 15 if body and firewall.get("passed") else 0
        buyer_value = 20 if body and strategy.get("primary_value") else 0
        attestation = email.get("structure_attestation") if isinstance(email.get("structure_attestation"), dict) else {}
        cta = 10 if (bool(attestation.get("cta")) if key(email.get("message_language")) != "english" else body.count("?") == 1) else 0
        compliance = 5 if body and risk.get("risk_level") == "LOW" and SELLER["website"] in body else 0
        total = relevance + clarity + credibility + buyer_value + cta + compliance
        answered = {
            "who_is_mark": bool(attestation.get("who")) if key(email.get("message_language")) != "english" else "Mark Zhou" in body,
            "what_xinghuai_makes": bool(attestation.get("what")) if key(email.get("message_language")) != "english" else "PVC board" in body,
            "why_relevant": bool(attestation.get("relevance")) if key(email.get("message_language")) != "english" else bool(strategy.get("primary_product") and key(strategy.get("primary_product")) in key(body)),
            "business_value": bool(attestation.get("value")) if key(email.get("message_language")) != "english" else bool(strategy.get("primary_value") and key(strategy.get("primary_value")) in key(body)),
            "exact_response_expected": bool(attestation.get("cta")) if key(email.get("message_language")) != "english" else body.count("?") == 1,
        }
        if sum(not value for value in answered.values()) >= 2:
            total = min(total, 59)
        if body and email.get("language_match_confirmed") is False:
            total = min(total, 74)
        status = "READY" if total >= 90 else "GOOD_BUT_REVIEW" if total >= 75 else "REVISE" if total >= 60 else "BLOCK"
        return {"relevance": relevance, "clarity": clarity, "credibility": credibility, "buyer_value": buyer_value, "cta": cta, "compliance": compliance, "total": total, "status": status, "five_question_check": answered, "human_style": style, "language_match_confirmed": email.get("language_match_confirmed")}

    @staticmethod
    def _state(mode: str, eligibility: dict[str, Any], risk: dict[str, Any], quality: dict[str, Any], context: dict[str, Any]) -> str:
        if mode == "RESEARCH_ONLY":
            return "RESEARCH_ONLY"
        if not eligibility.get("eligible") or risk.get("risk_level") == "BLOCK" or quality.get("status") == "BLOCK":
            return "BLOCKED"
        if mode == "OUTREACH_PREVIEW":
            return "PREVIEW_READY" if quality.get("status") in {"READY", "GOOD_BUT_REVIEW"} else "BLOCKED"
        if mode == "CREATE_DRAFT":
            return "DRAFT_READY" if quality.get("status") in {"READY", "GOOD_BUT_REVIEW"} else "BLOCKED"
        return "SEND_REQUIRES_CONFIRMATION" if context.get("user_previewed") and context.get("send_confirmed") else "BLOCKED"

    @staticmethod
    def _channels(contact: dict[str, Any], strategy: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
        if risk.get("risk_level") != "LOW":
            return OutreachExecutionEngine._empty_channels()
        product = strategy.get("primary_product") or "PVC boards"
        whatsapp = f"Hello, this is Mark Zhou from XingHuai, a PVC board manufacturer. May I confirm who handles {product} supplier evaluation?" if contact.get("whatsapp") else ""
        social = f"Hello, I’m Mark Zhou from XingHuai. Could you point me to the person responsible for {product} supplier evaluation?"
        phone = f"Hello, this is Mark Zhou from Guangzhou XingHuai New Materials. I’m calling to confirm who manages {product} supplier evaluation. Could you transfer me or share the official business contact?" if contact.get("phone") else ""
        return {"whatsapp_first": whatsapp, "whatsapp_after_reply": "Thank you. I can send a short product/specification evaluation brief to the appropriate business email.", "social_message": social, "phone_script": phone, "recommended_sequence": "Email first. No automatic same-day escalation. Use one verified secondary channel only when appropriate and after human review; do not auto-send or contact multiple people simultaneously."}

    @staticmethod
    def _follow_up(timezone_plan: dict[str, Any], email: dict[str, Any], status: str) -> dict[str, Any]:
        base = parse_dt(timezone_plan.get("buyer_local_send_time"))
        if not base or status == "BLOCKED":
            return {"first_follow_up_date": None, "first_follow_up_body": "", "second_follow_up_date": None, "second_follow_up_body": "", "final_follow_up_window": None, "max_follow_ups": 3, "rule": "No follow-up until the first contact is sent and no reply/refusal/suppression exists."}
        first = base + timedelta(days=4)
        second = base + timedelta(days=10)
        while first.weekday() >= 5:
            first += timedelta(days=1)
        while second.weekday() >= 5:
            second += timedelta(days=1)
        return {"first_follow_up_date": first.date().isoformat(), "first_follow_up_body": "Following up on my note below—could you point me to the person responsible for this category?", "second_follow_up_date": second.date().isoformat(), "second_follow_up_body": "If an additional-source evaluation is relevant, I can send a concise specification and sample-validation brief.", "final_follow_up_window": "Day 21-30, only if there was no reply or refusal", "max_follow_ups": 3, "rule": "Reply in the original thread. Stop all channels after refusal or unsubscribe. Do not follow up daily."}
