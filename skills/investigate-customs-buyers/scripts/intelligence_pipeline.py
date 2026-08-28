#!/usr/bin/env python3
"""Deterministic, evidence-controlled buyer-intelligence pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ProductMatch(str, Enum):
    EXACT = "EXACT"
    RELATED = "RELATED"
    INCIDENTAL = "INCIDENTAL"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class BuyerRole(str, Enum):
    DIRECT_IMPORTER = "DIRECT_IMPORTER"
    DISTRIBUTOR = "DISTRIBUTOR"
    RETAILER = "RETAILER"
    MANUFACTURER = "MANUFACTURER"
    END_USER = "END_USER"
    PROJECT_BUYER = "PROJECT_BUYER"
    TRADING_COMPANY = "TRADING_COMPANY"
    FREIGHT_FORWARDER = "FREIGHT_FORWARDER"
    NVOCC = "NVOCC"
    IMPORTER_OF_RECORD = "IMPORTER_OF_RECORD"
    REGISTERED_AGENT_ENTITY = "REGISTERED_AGENT_ENTITY"
    ECOMMERCE_AGGREGATOR = "ECOMMERCE_AGGREGATOR"
    UNKNOWN = "UNKNOWN"


class ContactVerification(str, Enum):
    VERIFIED = "VERIFIED"
    ASSOCIATED = "ASSOCIATED"
    UNVERIFIED = "UNVERIFIED"


class EmailStatus(str, Enum):
    OFFICIAL_COMPANY_EMAIL = "OFFICIAL_COMPANY_EMAIL"
    VERIFIED_PERSONAL_BUSINESS_EMAIL = "VERIFIED_PERSONAL_BUSINESS_EMAIL"
    HISTORICAL_EMAIL = "HISTORICAL_EMAIL"
    INFERRED_EMAIL = "INFERRED_EMAIL"
    UNVERIFIED_EMAIL = "UNVERIFIED_EMAIL"


REQUIRED_TOP_LEVEL_KEYS = (
    "status",
    "record_identity",
    "normalized_shipment",
    "data_quality",
    "entity_resolution",
    "buyer_intelligence",
    "contacts",
    "commercial_scoring",
    "facts",
    "inferences",
    "unknowns",
    "recommended_actions",
    "exclusion_reason",
    "evidence",
    "errors",
)

MODE_ALIASES = {
    "fast_scan": "fast_scan",
    "fast": "fast_scan",
    "quick": "fast_scan",
    "deep_dive": "deep_dive",
    "deep": "deep_dive",
    "standard": "deep_dive",
    "exhaustive": "deep_dive",
}


def load_rules(path: Path | None = None) -> dict[str, Any]:
    rules_path = path or (
        Path(__file__).resolve().parent.parent
        / "references"
        / "intelligence-rules.json"
    )
    return json.loads(rules_path.read_text(encoding="utf-8-sig"))


def compact_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[-_/]+", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)).strip()


def text_contains(text: str, phrase: str) -> bool:
    normalized_phrase = compact_text(phrase)
    if not normalized_phrase:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_phrase):
        return normalized_phrase.replace(" ", "") in text.replace(" ", "")
    return re.search(
        rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])",
        text,
    ) is not None


def as_number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def mapping_items(value: Any) -> list[dict[str, Any]]:
    """Return only mapping items from an untrusted list-like value."""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def normalized_string_set(value: Any) -> set[str]:
    """Normalize scalar or collection identifiers without splitting strings into characters."""
    if value in (None, "", []):
        return set()
    values = value if isinstance(value, (list, tuple, set)) else re.split(
        r"[,;\s]+", str(value)
    )
    return {
        compact_text(item).replace(" ", "")
        for item in values
        if compact_text(item)
    }


def identifier_list(value: Any) -> list[str]:
    """Preserve identifier values as an ordered JSON array."""
    if value in (None, "", []):
        return []
    values = (
        value
        if isinstance(value, (list, tuple, set))
        else re.split(r"[,;]+", str(value))
    )
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in values
            if str(item).strip()
        )
    )


def safe_snapshot_text(value: Any) -> str:
    """Serialize an untrusted raw payload without allowing snapshotting to abort the run."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        try:
            return str(value)
        except Exception:
            return "<unrepresentable raw input>"


def parse_record_date(record: dict[str, Any]) -> date | None:
    dates = record.get("dates") or {}
    if not isinstance(dates, dict):
        return None
    for key in ("arrival_date", "estimated_arrival_date", "assessment_date"):
        value = dates.get(key)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            continue
    return None


def evidence_claim(
    claim_id: str,
    text: str,
    classification: str,
    grade: str,
    confidence: float,
    source_ids: list[str],
    reason_codes: list[str],
    checked: str,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim": text,
        "classification": classification,
        "evidence_grade": grade,
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        "source_ids": source_ids,
        "date_checked": checked,
        "reason_codes": reason_codes,
    }


def blank_output(
    raw_input: str,
    mode: str,
    rules_version: Any,
    checked: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "mode": mode,
        "rules_version": rules_version,
        "generated_at": checked,
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
                "role_status": "UNKNOWN",
                "reason_codes": [],
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
                "reason_codes": [],
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
                "weight_kg": None,
                "gross_weight_kg": None,
                "package_count": None,
                "package_type": None,
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
            "field_scope": {},
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
            "reason_codes": [],
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
        },
        "facts": [],
        "inferences": [],
        "unknowns": [],
        "recommended_actions": [],
        "exclusion_reason": None,
        "evidence": [],
        "errors": [],
        "completed_sections": [],
        "missing_sections": [],
    }


class ProductSemanticClassifier:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules["product_classification"]

    def classify(
        self,
        record: dict[str, Any],
        sheet_inference: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raw_description = " | ".join(
            str(value).strip()
            for value in (
                record.get("product"),
                record.get("product_description_local"),
            )
            if value
        )
        normalized = compact_text(raw_description)
        rules = self.config["rules"]
        for level in self.config["precedence"]:
            for rule in rules:
                if rule["match_level"] != level:
                    continue
                matched = [
                    phrase
                    for phrase in rule["phrases"]
                    if text_contains(normalized, phrase)
                ]
                if not matched:
                    continue
                confidence = {
                    "EXACT": 0.97,
                    "RELATED": 0.86,
                    "INCIDENTAL": 0.92,
                    "NONE": 0.94,
                }[level]
                return self._result(
                    raw_description,
                    rule["normalized_category"],
                    level,
                    confidence,
                    [rule["id"]],
                    matched,
                    sheet_inference,
                )
        fallback = self.config["fallback"]
        return self._result(
            raw_description,
            fallback["normalized_category"],
            fallback["match_level"],
            0.25 if raw_description else 0.0,
            [fallback["reason_code"]],
            [],
            sheet_inference,
        )

    @staticmethod
    def _result(
        raw_description: str,
        category: str,
        level: str,
        confidence: float,
        reason_codes: list[str],
        matched_features: list[str],
        sheet_inference: dict[str, Any] | None,
    ) -> dict[str, Any]:
        inference = (
            sheet_inference
            if isinstance(sheet_inference, dict)
            else {}
        )
        specifications = {
            "length_mm": inference.get("length_mm"),
            "width_mm": inference.get("width_mm"),
            "thickness_mm": inference.get("thickness_mm"),
            "density_g_cm3": inference.get("density_g_cm3"),
        }
        return {
            "raw_description": raw_description or None,
            "normalized_category": category,
            "match_level": level,
            "confidence": confidence,
            "reason_codes": reason_codes,
            "matched_features": matched_features,
            "specifications": specifications,
        }


class ShipmentDataValidator:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules["data_quality"]

    def validate(
        self,
        normalized: dict[str, Any],
        product: dict[str, Any],
        related_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        record = normalized.get("record", {})
        warnings = [
            {
                "code": item.get("code", "unclassified_anomaly"),
                "severity": item.get("severity", "medium"),
                "message": item.get("message", ""),
                "source": "normalizer",
            }
            for item in mapping_items(normalized.get("anomalies"))
        ]
        codes = {item["code"] for item in warnings}
        shipment_fields = [
            key
            for key in (
                "master_bill",
                "house_bill",
                "containers",
                "teu",
                "carrier",
                "vessel",
                "port_of_lading",
                "port_of_discharge",
                "weight_kg",
                "gross_weight_kg",
                "package_count",
            )
            if record.get(key) not in (None, "", [])
        ]
        line_fields = [
            key
            for key in (
                "item_number",
                "product",
                "hs_code",
                "quantity_count",
                "quantity_unit",
                "unit_price",
                "original_amount",
            )
            if record.get(key) not in (None, "", [])
        ]
        ambiguous_fields: list[str] = []
        shipment_line_conflict = False
        if record.get("item_number") and any(
            record.get(key) not in (None, "", [])
            for key in ("teu", "containers", "package_count", "gross_weight_kg")
        ):
            shipment_line_conflict = True
            ambiguous_fields = [
                key
                for key in ("teu", "containers", "package_count", "weight_kg", "gross_weight_kg")
                if record.get(key) not in (None, "", [])
            ]
            self._add_warning(
                warnings,
                codes,
                "shipment_line_scope_ambiguous",
                "high",
                "Shipment totals coexist with an item number; do not assign TEU, total packages, containers, or total weight to this product line without allocation evidence.",
            )
        if (
            record.get("package_count") is not None
            and record.get("quantity_count") is None
        ):
            self._add_warning(
                warnings,
                codes,
                "package_count_not_product_quantity",
                "info",
                "Package count is preserved separately and was not promoted to product quantity.",
            )

        unit_conflict, unit_metrics = self._unit_consistency(record, product)
        if unit_conflict:
            self._add_warning(
                warnings,
                codes,
                "quantity_weight_spec_conflict",
                "medium",
                "Declared area, weight, and thickness imply a density outside the configured PVC foam-board range; verify unit mapping or product structure.",
            )

        origin_port_conflict = self._route_conflict(record, warnings, codes)
        cross_record_contamination = self._cross_record_checks(
            record, related_records, warnings, codes
        )
        contamination_codes = {
            "same_loading_discharge_port",
            "route_country_conflict",
            "mode_container_conflict",
            "primary_secondary_port_conflict",
            "primary_secondary_origin_conflict",
            "cross_record_house_bill_collision",
            "cross_record_container_collision",
        }
        possible_contamination = (
            cross_record_contamination
            or bool(codes & contamination_codes)
            or shipment_line_conflict
        )
        deductions = self.config["severity_deductions"]
        score = max(
            0,
            100
            - sum(
                deductions.get(item.get("severity", "medium"), 5)
                for item in warnings
            ),
        )
        scoring_suspended = bool(
            codes & set(self.config["scoring_suspend_codes"])
        )
        status = (
            "critical"
            if scoring_suspended
            else "warning"
            if warnings
            else "pass"
        )
        receipt = str(record.get("place_of_receipt") or "").strip()
        origin = str(record.get("origin") or "").strip()
        origin_interpretation = "declared_manufacturing_origin"
        if receipt and origin and compact_text(receipt) != compact_text(origin):
            origin_interpretation = "route_or_transshipment_field_possible"
        return {
            "status": status,
            "score": score,
            "possible_contamination": possible_contamination,
            "shipment_line_conflict": shipment_line_conflict,
            "unit_conflict": unit_conflict,
            "origin_port_conflict": origin_port_conflict,
            "origin_field_interpretation": origin_interpretation,
            "scoring_suspended": scoring_suspended,
            "warnings": warnings,
            "field_scope": {
                "shipment_level": shipment_fields,
                "line_item": line_fields,
                "ambiguous": ambiguous_fields,
            },
            "unit_consistency_metrics": unit_metrics,
        }

    @staticmethod
    def _add_warning(
        warnings: list[dict[str, Any]],
        codes: set[str],
        code: str,
        severity: str,
        message: str,
    ) -> None:
        if code in codes:
            return
        warnings.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
                "source": "intelligence_pipeline",
            }
        )
        codes.add(code)

    def _unit_consistency(
        self,
        record: dict[str, Any],
        product: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        quantity = as_number(record.get("quantity_count"))
        unit = str(record.get("quantity_unit") or "").upper()
        weight = as_number(record.get("weight_kg"))
        thickness = product.get("specifications", {}).get("thickness_mm")
        if thickness is None:
            match = re.search(
                r"(?<!\d)(\d+(?:\.\d+)?)\s*mm\b",
                str(product.get("raw_description") or ""),
                re.I,
            )
            thickness = float(match.group(1)) if match else None
        area_units = {"M2", "M²", "SQM", "SQUAREMETER", "SQUAREMETERS"}
        if (
            quantity in (None, 0)
            or weight is None
            or thickness in (None, 0)
            or unit.replace(" ", "") not in area_units
        ):
            return False, {}
        areal_mass = weight / quantity
        implied_density = weight / (quantity * (float(thickness) / 1000)) / 1000
        low, high = self.config["foam_density_range_g_cm3"]
        conflict = (
            product.get("match_level") == ProductMatch.EXACT.value
            and not low <= implied_density <= high
        )
        return conflict, {
            "declared_area_m2": quantity,
            "areal_mass_kg_m2": round(areal_mass, 4),
            "implied_density_g_cm3": round(implied_density, 4),
            "calculation_status": "estimate",
        }

    def _route_conflict(
        self,
        record: dict[str, Any],
        warnings: list[dict[str, Any]],
        codes: set[str],
    ) -> bool:
        destination = compact_text(
            " ".join(
                str(value or "")
                for value in (
                    record.get("destination_country"),
                    record.get("buyer_address"),
                )
            )
        )
        port_map = self.config["port_country_map"]
        conflict = False
        for field_name in ("port_of_discharge", "port_of_entry"):
            port = compact_text(record.get(field_name))
            if not port:
                continue
            port_country = next(
                (
                    country
                    for marker, country in port_map.items()
                    if compact_text(marker) in port
                ),
                None,
            )
            if not port_country:
                continue
            country_key = compact_text(port_country)
            equivalents = {
                "puerto rico": {"puerto rico", "united states", "usa", "us"},
                "us virgin islands": {
                    "us virgin islands",
                    "virgin islands",
                    "united states",
                    "usa",
                    "us",
                },
            }
            accepted = equivalents.get(country_key, {country_key})
            if destination and not any(
                text_contains(destination, item) for item in accepted
            ):
                conflict = True
                self._add_warning(
                    warnings,
                    codes,
                    "route_country_conflict",
                    "high",
                    f"{field_name} appears to be in {port_country}, which conflicts with the stated destination context; possible field contamination or transshipment labeling.",
                )
        return conflict

    def _cross_record_checks(
        self,
        record: dict[str, Any],
        related_records: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        codes: set[str],
    ) -> bool:
        current_buyer = compact_text(record.get("buyer"))
        current_destination = compact_text(record.get("destination_country"))
        current_house = compact_text(record.get("house_bill"))
        current_master = compact_text(record.get("master_bill"))
        current_containers = normalized_string_set(record.get("containers"))
        current_date = parse_record_date(record)
        contaminated = False
        for related in related_records:
            if not isinstance(related, dict):
                continue
            other = related.get("record", related)
            if not isinstance(other, dict):
                continue
            other_buyer = compact_text(other.get("buyer"))
            other_destination = compact_text(other.get("destination_country"))
            different_context = (
                current_buyer
                and other_buyer
                and current_buyer != other_buyer
            ) or (
                current_destination
                and other_destination
                and current_destination != other_destination
            )
            if not different_context:
                continue
            other_house = compact_text(other.get("house_bill"))
            if current_house and other_house == current_house:
                contaminated = True
                self._add_warning(
                    warnings,
                    codes,
                    "cross_record_house_bill_collision",
                    "high",
                    "The same house bill appears in a different buyer or destination context.",
                )
            other_master = compact_text(other.get("master_bill"))
            if current_master and other_master == current_master:
                self._add_warning(
                    warnings,
                    codes,
                    "cross_record_master_bill_shared",
                    "medium",
                    "The same master bill appears in another buyer/destination context; this can be legitimate consolidation and requires house-bill review.",
                )
            shared = current_containers & normalized_string_set(
                other.get("containers")
            )
            if not shared:
                continue
            other_date = parse_record_date(other)
            within_window = (
                current_date is None
                or other_date is None
                or abs((current_date - other_date).days)
                <= int(self.config["container_collision_window_days"])
            )
            if within_window:
                contaminated = True
                self._add_warning(
                    warnings,
                    codes,
                    "cross_record_container_collision",
                    "high",
                    "A container identifier appears within the configured time window under a different buyer or destination.",
                )
        return contaminated


class EntityResolver:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules["entity_resolution"]

    def resolve(
        self,
        record: dict[str, Any],
        enrichment: dict[str, Any],
    ) -> dict[str, Any]:
        entity = enrichment.get("entity") or {}
        if not isinstance(entity, dict):
            entity = {}
        evidence = mapping_items(entity.get("match_evidence"))
        bases = {
            str(item.get("basis") or "")
            for item in evidence
        }
        confirmed = bool(bases & set(self.config["confirmed_bases"]))
        complementary = bases & set(self.config["complementary_bases"])
        strong_complementary = [
            item
            for item in evidence
            if item.get("basis") in complementary
            and item.get("evidence_grade") in {"A", "B"}
        ]
        if len({item.get("basis") for item in strong_complementary}) >= 2:
            confirmed = True
        prohibited = sorted(bases & set(self.config["prohibited_bases"]))
        trusted_bases = bases & (
            set(self.config["confirmed_bases"])
            | set(self.config["complementary_bases"])
        )
        confidence = (
            min(0.98, 0.78 + 0.06 * len(trusted_bases))
            if confirmed
            else min(0.65, 0.2 + 0.08 * len(complementary))
        )
        possible_affiliates = []
        for affiliate in mapping_items(entity.get("possible_affiliates")):
            affiliate_bases = set(affiliate.get("match_basis") or [])
            affiliate_confirmed = bool(
                affiliate_bases & set(self.config["confirmed_bases"])
            )
            possible_affiliates.append(
                {
                    "name": affiliate.get("name"),
                    "relationship": (
                        affiliate.get("relationship", "confirmed")
                        if affiliate_confirmed
                        else "unverified"
                    ),
                    "match_basis": sorted(affiliate_bases),
                    "do_not_merge": not affiliate_confirmed,
                }
            )
        legal_name = entity.get("legal_name") if confirmed else None
        status = "MATCHED" if confirmed else "UNVERIFIED" if evidence else "UNKNOWN"
        return {
            "status": status,
            "legal_name": legal_name,
            "matched": confirmed,
            "confidence": round(confidence, 2),
            "match_basis": sorted(bases),
            "prohibited_or_weak_bases": prohibited,
            "legal_registration": (
                entity.get("legal_registration") or {}
                if confirmed
                else {}
            ),
            "address_type": (
                entity.get("address_type", "unknown")
                if confirmed
                else "unknown"
            ),
            "official_channels": (
                mapping_items(entity.get("official_channels"))
                if confirmed
                else []
            ),
            "possible_affiliates": possible_affiliates,
        }


class BuyerRoleClassifier:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules["buyer_roles"]
        self.allowed = set(self.config["allowed"])

    def classify(
        self,
        record: dict[str, Any],
        product: dict[str, Any],
        entity: dict[str, Any],
        enrichment: dict[str, Any],
    ) -> dict[str, Any]:
        business = enrichment.get("business") or {}
        trade = enrichment.get("trade_summary") or {}
        if not isinstance(business, dict):
            business = {}
        if not isinstance(trade, dict):
            trade = {}
        raw_role_signals = business.get("role_signals") or []
        role_signals = (
            raw_role_signals
            if isinstance(raw_role_signals, (list, tuple))
            else [raw_role_signals]
        )
        description = compact_text(
            " ".join(
                str(value or "")
                for value in (
                    business.get("official_description"),
                    business.get("business_model"),
                    " ".join(str(item) for item in role_signals),
                )
            )
        )
        source_grade = str(business.get("evidence_grade") or "D").upper()
        explicit = str(business.get("verified_role") or "").upper()
        reasons: list[str] = []
        candidates: list[dict[str, Any]] = []

        entity_matched = bool(entity.get("matched"))
        if (
            explicit in self.allowed
            and source_grade in {"A", "B"}
            and entity_matched
        ):
            role = explicit
            confidence = 0.93 if source_grade == "A" else 0.86
            reasons.append("verified_role_from_strong_source")
        else:
            role, confidence = self._from_signals(
                description,
                source_grade,
                product,
                entity,
                trade,
                reasons,
            )
        if (
            explicit in self.allowed
            and source_grade in {"A", "B"}
            and not entity_matched
        ):
            candidates.append(
                {
                    "role": explicit,
                    "confidence": 0.55,
                    "reason_codes": [
                        "strong_role_source_but_entity_match_unverified"
                    ],
                }
            )

        if role == BuyerRole.UNKNOWN.value:
            if product.get("match_level") == ProductMatch.EXACT.value:
                candidates.append(
                    {
                        "role": BuyerRole.DIRECT_IMPORTER.value,
                        "confidence": 0.55,
                        "reason_codes": ["exact_product_customs_record_only"],
                    }
                )
            name = compact_text(record.get("buyer"))
            if any(text_contains(name, phrase) for phrase in self.config["ior_phrases"]):
                candidates.append(
                    {
                        "role": BuyerRole.IMPORTER_OF_RECORD.value,
                        "confidence": 0.35,
                        "reason_codes": ["weak_name_pattern_only"],
                    }
                )
        secondary: list[str] = []
        if role == BuyerRole.DISTRIBUTOR.value and any(
            text_contains(description, phrase)
            for phrase in self.config["retail_phrases"]
        ):
            secondary.append(BuyerRole.RETAILER.value)
        direct_probability = {
            BuyerRole.DIRECT_IMPORTER.value: 0.9,
            BuyerRole.DISTRIBUTOR.value: 0.85,
            BuyerRole.MANUFACTURER.value: 0.8,
            BuyerRole.RETAILER.value: 0.55,
            BuyerRole.TRADING_COMPANY.value: 0.55,
            BuyerRole.END_USER.value: 0.45,
            BuyerRole.IMPORTER_OF_RECORD.value: 0.25,
            BuyerRole.ECOMMERCE_AGGREGATOR.value: 0.2,
            BuyerRole.FREIGHT_FORWARDER.value: 0.05,
            BuyerRole.NVOCC.value: 0.02,
            BuyerRole.UNKNOWN.value: 0.25,
        }.get(role, 0.25)
        return {
            "buyer_role": role,
            "secondary_roles": secondary,
            "candidate_roles": candidates,
            "role_confidence": round(confidence, 2),
            "role_status": "VERIFIED" if confidence >= 0.85 else "PROVISIONAL",
            "reason_codes": reasons or ["insufficient_role_evidence"],
            "business_model": business.get("business_model"),
            "company_scale": business.get("company_scale"),
            "purchase_pattern": trade.get("purchase_pattern", "not_verified"),
            "current_supplier": record.get("supplier"),
            "direct_import_probability": direct_probability,
        }

    def _from_signals(
        self,
        description: str,
        source_grade: str,
        product: dict[str, Any],
        entity: dict[str, Any],
        trade: dict[str, Any],
        reasons: list[str],
    ) -> tuple[str, float]:
        strong = source_grade in {"A", "B"} and bool(entity.get("matched"))
        if strong:
            if any(text_contains(description, phrase) for phrase in self.config["logistics_phrases"]):
                reasons.append("official_logistics_business_description")
                return (
                    BuyerRole.NVOCC.value
                    if text_contains(description, "nvocc")
                    else BuyerRole.FREIGHT_FORWARDER.value,
                    0.9,
                )
            for role, key in (
                (BuyerRole.DISTRIBUTOR.value, "distribution_phrases"),
                (BuyerRole.MANUFACTURER.value, "manufacturing_phrases"),
                (BuyerRole.RETAILER.value, "retail_phrases"),
                (BuyerRole.TRADING_COMPANY.value, "trading_phrases"),
            ):
                if any(text_contains(description, phrase) for phrase in self.config[key]):
                    reasons.append(f"official_description_supports_{role.casefold()}")
                    return role, 0.86
            if any(text_contains(description, phrase) for phrase in self.config["ior_phrases"]):
                reasons.append("official_description_supports_importer_of_record")
                return BuyerRole.IMPORTER_OF_RECORD.value, 0.86

        concentration = as_number(trade.get("product_concentration"))
        unrelated = as_number(trade.get("unrelated_product_categories"))
        consolidator = as_number(trade.get("top_consolidator_share"))
        if (
            entity.get("address_type") == "registered_agent"
            and concentration is not None
            and concentration < 0.2
            and unrelated is not None
            and unrelated >= 5
            and consolidator is not None
            and consolidator >= 0.7
        ):
            reasons.extend(
                [
                    "registered_agent_address",
                    "low_product_concentration",
                    "high_unrelated_product_diversity",
                    "single_consolidator_concentration",
                ]
            )
            return BuyerRole.IMPORTER_OF_RECORD.value, 0.82
        if (
            product.get("match_level") == ProductMatch.INCIDENTAL.value
            and strong
            and description
        ):
            reasons.append("finished_display_or_fixture_for_business_use")
            return BuyerRole.END_USER.value, 0.75
        return BuyerRole.UNKNOWN.value, 0.25


class ContactVerifier:
    EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules["contacts"]

    def verify(
        self,
        normalized: dict[str, Any],
        entity: dict[str, Any],
        enrichment: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        contacts: list[dict[str, Any]] = []
        for raw in mapping_items(enrichment.get("contacts")):
            contacts.append(self._verify_one(raw))
        for channel in mapping_items(entity.get("official_channels")):
            if str(channel.get("type") or "").casefold() != "email":
                continue
            email = str(channel.get("value") or "").strip()
            contacts.append(
                {
                    "name": None,
                    "title": None,
                    "decision_role": "GENERAL_COMPANY_CHANNEL",
                    "verification": ContactVerification.ASSOCIATED.value,
                    "email": email if self.EMAIL_RE.match(email) else None,
                    "email_status": (
                        EmailStatus.OFFICIAL_COMPANY_EMAIL.value
                        if self.EMAIL_RE.match(email)
                        else EmailStatus.UNVERIFIED_EMAIL.value
                    ),
                    "phone": None,
                    "social": None,
                    "evidence_grade": channel.get("evidence_grade", "A"),
                    "source_ids": channel.get("source_ids") or [],
                    "usable_for_outreach": bool(self.EMAIL_RE.match(email)),
                    "reason_codes": ["official_general_channel"],
                }
            )
        candidate_map = normalized.get("contact_candidates") or {}
        if not isinstance(candidate_map, dict):
            candidate_map = {}
        for candidate in candidate_map.values():
            if not isinstance(candidate, dict):
                continue
            contacts.append(
                {
                    "name": None,
                    "title": None,
                    "decision_role": "CUSTOMS_OPERATIONAL_LEAD",
                    "verification": ContactVerification.UNVERIFIED.value,
                    "email": candidate.get("value"),
                    "email_status": (
                        EmailStatus.INFERRED_EMAIL.value
                        if candidate.get("status") == "candidate_unverified"
                        else EmailStatus.HISTORICAL_EMAIL.value
                    ),
                    "phone": None,
                    "social": None,
                    "evidence_grade": "C",
                    "source_ids": ["src-customs-record"],
                    "usable_for_outreach": False,
                    "reason_codes": ["customs_text_not_independently_verified"],
                }
            )
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, ...]] = set()
        for item in contacts:
            key = (
                str(item.get("email") or "").casefold(),
                str(item.get("name") or "").casefold(),
                compact_text(item.get("phone")),
                compact_text(item.get("social")),
                compact_text(item.get("title")),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        procurement = any(
            item.get("verification") == ContactVerification.VERIFIED.value
            and item.get("decision_role") == "PROCUREMENT"
            for item in deduped
        )
        general = any(
            item.get("email_status")
            == EmailStatus.OFFICIAL_COMPANY_EMAIL.value
            and item.get("usable_for_outreach")
            for item in deduped
        )
        return deduped, {
            "verified_procurement_contact": procurement,
            "official_general_channel": general,
            "message": (
                "已找到经验证采购负责人"
                if procurement
                else "未找到已验证采购负责人"
            ),
        }

    def _verify_one(self, raw: dict[str, Any]) -> dict[str, Any]:
        grade = str(raw.get("evidence_grade") or "D").upper()
        company_verified = bool(raw.get("company_verified"))
        title_verified = bool(raw.get("title_verified"))
        if company_verified and title_verified and grade in {"A", "B"}:
            verification = ContactVerification.VERIFIED.value
        elif company_verified and grade in {"A", "B", "C"}:
            verification = ContactVerification.ASSOCIATED.value
        else:
            verification = ContactVerification.UNVERIFIED.value
        title = str(raw.get("title") or "")
        lowered_title = compact_text(title)
        if any(
            token in lowered_title
            for token in ("procurement", "purchasing", "buyer", "sourcing")
        ) and title_verified:
            decision_role = "PROCUREMENT"
        elif any(
            token in lowered_title
            for token in ("chief executive", "ceo", "president", "founder")
        ) and title_verified:
            decision_role = "EXECUTIVE_DECISION"
        elif any(
            token in lowered_title
            for token in ("broker", "registered agent", "notify", "sales")
        ):
            decision_role = "NON_PROCUREMENT_OR_OPERATIONAL"
        else:
            decision_role = "UNKNOWN"
        email = str(raw.get("email") or "").strip()
        requested_status = str(
            raw.get("email_status") or EmailStatus.UNVERIFIED_EMAIL.value
        ).upper()
        if requested_status not in self.config["email_statuses"]:
            requested_status = EmailStatus.UNVERIFIED_EMAIL.value
        if not self.EMAIL_RE.match(email):
            email = ""
            requested_status = EmailStatus.UNVERIFIED_EMAIL.value
        formal = requested_status in self.config["formal_email_statuses"]
        usable = (
            bool(email)
            and formal
            and verification
            in {
                ContactVerification.VERIFIED.value,
                ContactVerification.ASSOCIATED.value,
            }
        )
        return {
            "name": raw.get("name"),
            "title": raw.get("title"),
            "decision_role": decision_role,
            "verification": verification,
            "email": email or None,
            "email_status": requested_status,
            "phone": raw.get("phone"),
            "social": raw.get("social"),
            "evidence_grade": grade if grade in {"A", "B", "C", "D"} else "D",
            "source_ids": raw.get("source_ids") or [],
            "usable_for_outreach": usable,
            "reason_codes": (
                ["company_and_title_verified"]
                if verification == ContactVerification.VERIFIED.value
                else ["contact_not_fully_verified"]
            ),
        }


class CommercialScorer:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules["scoring"]

    def score(
        self,
        record: dict[str, Any],
        product: dict[str, Any],
        quality: dict[str, Any],
        entity: dict[str, Any],
        role: dict[str, Any],
        contacts: list[dict[str, Any]],
        contact_status: dict[str, Any],
        enrichment: dict[str, Any],
    ) -> dict[str, Any]:
        if quality.get("scoring_suspended"):
            return {
                "status": "suspended",
                "components": {},
                "risk_penalties": [],
                "observed_score": None,
                "total_score": None,
                "score_range": [None, None],
                "score_completeness": 0.0,
                "provisional": True,
                "grade": "UNSCORABLE",
                "buyer_authenticity": "UNKNOWN",
                "product_fit": product.get("match_level", "UNKNOWN"),
                "sales_priority": "UNSCORABLE",
                "deep_dive_eligible": False,
                "reason_codes": ["data_quality_scoring_suspended"],
            }
        weights = self.config["weights"]
        components: dict[str, dict[str, Any]] = {}

        if entity.get("matched"):
            authenticity, auth_status, auth_reasons = 15, "observed", ["strong_entity_match"]
        elif entity.get("official_channels"):
            authenticity, auth_status, auth_reasons = 10, "observed", ["official_business_channel"]
        elif record.get("buyer") and record.get("buyer_address"):
            authenticity, auth_status, auth_reasons = 6, "partial", ["customs_name_and_address_only"]
        elif record.get("buyer"):
            authenticity, auth_status, auth_reasons = 4, "partial", ["customs_name_only"]
        else:
            authenticity, auth_status, auth_reasons = 0, "unknown", ["buyer_identity_missing"]
        components["buyer_authenticity"] = self._component(
            authenticity, weights["buyer_authenticity"], auth_status, auth_reasons
        )

        product_scores = {
            ProductMatch.EXACT.value: 25,
            ProductMatch.RELATED.value: 15,
            ProductMatch.INCIDENTAL.value: 5,
            ProductMatch.NONE.value: 0,
            ProductMatch.UNKNOWN.value: 0,
        }
        product_status = (
            "unknown"
            if product.get("match_level") == ProductMatch.UNKNOWN.value
            else "observed"
        )
        components["product_fit"] = self._component(
            product_scores.get(product.get("match_level"), 0),
            weights["product_fit"],
            product_status,
            product.get("reason_codes") or [],
        )

        weight = as_number(record.get("weight_kg")) or 0
        teu = as_number(record.get("teu")) or 0
        if quality.get("shipment_line_conflict"):
            scale_score = 0
            scale_reason = "shipment_total_not_allocated_to_product_line"
            scale_status = "unknown"
        elif teu >= 1 or weight >= 20000:
            scale_score, scale_reason = 15, "container_scale_or_20t"
            scale_status = "observed"
        elif weight >= 5000:
            scale_score, scale_reason = 12, "large_partial_shipment"
            scale_status = "observed"
        elif weight >= 1000:
            scale_score, scale_reason = 8, "medium_shipment"
            scale_status = "observed"
        elif weight >= 100:
            scale_score, scale_reason = 4, "small_commercial_shipment"
            scale_status = "observed"
        elif weight > 0:
            scale_score, scale_reason = 2, "sample_or_very_small_shipment"
            scale_status = "observed"
        else:
            scale_score, scale_reason = 0, "shipment_scale_unknown"
            scale_status = "unknown"
        components["purchase_scale"] = self._component(
            scale_score,
            weights["purchase_scale"],
            scale_status,
            [scale_reason],
        )

        trade = enrichment.get("trade_summary") or {}
        if not isinstance(trade, dict):
            trade = {}
        repeat_count = as_number(trade.get("product_specific_shipments"))
        if repeat_count is None and product.get("match_level") in {
            ProductMatch.EXACT.value,
            ProductMatch.RELATED.value,
            ProductMatch.INCIDENTAL.value,
        }:
            repeat_count = 1
        if repeat_count is None:
            repeat_score, repeat_status, repeat_reason = 0, "unknown", "repeat_purchase_not_verified"
        elif repeat_count >= 3:
            repeat_score, repeat_status, repeat_reason = 15, "observed", "three_or_more_product_shipments"
        elif repeat_count >= 2:
            repeat_score, repeat_status, repeat_reason = 10, "observed", "two_product_shipments"
        else:
            repeat_score, repeat_status, repeat_reason = 5, "observed", "single_product_shipment"
        components["repeat_purchase"] = self._component(
            repeat_score,
            weights["repeat_purchase"],
            repeat_status,
            [repeat_reason],
        )

        primary_role = role.get("buyer_role")
        channel_scores = {
            BuyerRole.DISTRIBUTOR.value: 10,
            BuyerRole.MANUFACTURER.value: 10,
            BuyerRole.RETAILER.value: 8,
            BuyerRole.PROJECT_BUYER.value: 7,
            BuyerRole.END_USER.value: 6,
            BuyerRole.TRADING_COMPANY.value: 5,
            BuyerRole.DIRECT_IMPORTER.value: 7,
            BuyerRole.IMPORTER_OF_RECORD.value: 1,
            BuyerRole.ECOMMERCE_AGGREGATOR.value: 2,
            BuyerRole.FREIGHT_FORWARDER.value: 0,
            BuyerRole.NVOCC.value: 0,
            BuyerRole.UNKNOWN.value: 0,
        }
        role_unknown = primary_role == BuyerRole.UNKNOWN.value
        components["channel_value"] = self._component(
            channel_scores.get(primary_role, 0),
            weights["channel_value"],
            "unknown" if role_unknown else "observed",
            role.get("reason_codes") or [],
        )

        direct_score = round(
            float(role.get("direct_import_probability") or 0)
            * weights["direct_import_probability"]
        )
        components["direct_import_probability"] = self._component(
            direct_score,
            weights["direct_import_probability"],
            "unknown" if role_unknown else "inferred",
            ["role_based_direct_import_probability"],
        )

        if contact_status.get("verified_procurement_contact"):
            reachability, reach_status, reach_reason = 5, "observed", "verified_procurement_contact"
        elif contact_status.get("official_general_channel"):
            reachability, reach_status, reach_reason = 3, "observed", "official_general_channel"
        elif any(item.get("verification") == ContactVerification.ASSOCIATED.value for item in contacts):
            reachability, reach_status, reach_reason = 2, "partial", "associated_contact_only"
        else:
            reachability, reach_status, reach_reason = 0, "unknown", "no_verified_contact"
        components["reachability"] = self._component(
            reachability,
            weights["reachability"],
            reach_status,
            [reach_reason],
        )

        quality_score = int(quality.get("score") or 0)
        data_points = 5 if quality_score >= 90 else 4 if quality_score >= 75 else 2 if quality_score >= 50 else 0
        components["data_quality"] = self._component(
            data_points,
            weights["data_quality"],
            "observed",
            [f"data_quality_score_{quality_score}"],
        )

        penalties: list[dict[str, Any]] = []
        address_type = entity.get("address_type")
        business = enrichment.get("business") or {}
        if not isinstance(business, dict):
            business = {}
        if address_type == "registered_agent":
            penalties.append(self._penalty("registered_agent_address"))
        if business.get("no_visible_business_channel_confirmed") is True:
            penalties.append(self._penalty("no_visible_business_channel"))
        if primary_role in {
            BuyerRole.IMPORTER_OF_RECORD.value,
            BuyerRole.ECOMMERCE_AGGREGATOR.value,
        } and float(role.get("role_confidence") or 0) >= 0.7:
            penalties.append(self._penalty("probable_ior_or_aggregator"))
        if primary_role in {
            BuyerRole.FREIGHT_FORWARDER.value,
            BuyerRole.NVOCC.value,
        }:
            penalties.append(self._penalty("freight_forwarder_or_nvocc"))

        observed_score = sum(item["score"] for item in components.values())
        penalty_total = sum(item["points"] for item in penalties)
        total = max(0, min(100, observed_score + penalty_total))
        unknown_max = sum(
            item["maximum"]
            for item in components.values()
            if item["status"] == "unknown"
        )
        upper = max(total, min(100, total + unknown_max))
        known_max = sum(
            item["maximum"]
            for item in components.values()
            if item["status"] != "unknown"
        )
        configured_total = sum(int(value) for value in weights.values()) or 100
        completeness = known_max / configured_total
        insufficient_core_evidence = (
            not record.get("buyer")
            or product.get("match_level") == ProductMatch.UNKNOWN.value
        )
        grade = "UNSCORABLE" if insufficient_core_evidence else self.grade(total)
        provisional = completeness < 1 or not entity.get("matched")
        deep_eligible = (
            not insufficient_core_evidence
            and total >= int(self.config["deep_dive_minimum_score"])
            and product.get("match_level") == ProductMatch.EXACT.value
            and primary_role
            in {
                BuyerRole.DIRECT_IMPORTER.value,
                BuyerRole.DISTRIBUTOR.value,
                BuyerRole.RETAILER.value,
                BuyerRole.MANUFACTURER.value,
                BuyerRole.PROJECT_BUYER.value,
            }
        )
        return {
            "status": (
                "insufficient_evidence"
                if insufficient_core_evidence
                else "scored"
            ),
            "components": components,
            "risk_penalties": penalties,
            "observed_score": observed_score,
            "total_score": total,
            "score_range": [total, upper],
            "score_completeness": round(completeness, 2),
            "provisional": provisional,
            "grade": grade,
            "buyer_authenticity": self._authenticity_label(authenticity),
            "product_fit": product.get("match_level", "UNKNOWN"),
            "sales_priority": grade,
            "deep_dive_eligible": deep_eligible,
            "reason_codes": [
                "provisional_due_to_unknown_components"
                if provisional
                else "all_scoring_components_observed"
            ],
        }

    @staticmethod
    def _component(
        score: int,
        maximum: int,
        status: str,
        reason_codes: list[str],
    ) -> dict[str, Any]:
        return {
            "score": int(score),
            "maximum": int(maximum),
            "status": status,
            "reason_codes": reason_codes,
            "evidence_refs": [],
        }

    def _penalty(self, name: str) -> dict[str, Any]:
        return {
            "code": name,
            "points": int(self.config["risk_penalties"][name]),
        }

    def grade(self, score: int) -> str:
        for band in self.config["grade_boundaries"]:
            if score >= int(band["minimum"]):
                return str(band["grade"])
        return "D"

    @staticmethod
    def _authenticity_label(score: int) -> str:
        return "HIGH" if score >= 12 else "MEDIUM" if score >= 7 else "LOW"


@dataclass
class PipelineContext:
    normalized: dict[str, Any]
    raw_input: str
    enrichment: dict[str, Any]
    related_records: list[dict[str, Any]]
    mode: str
    checked: str
    output: dict[str, Any]
    stage_values: dict[str, Any] = field(default_factory=dict)


class IntelligencePipeline:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.product_classifier = ProductSemanticClassifier(rules)
        self.data_validator = ShipmentDataValidator(rules)
        self.entity_resolver = EntityResolver(rules)
        self.role_classifier = BuyerRoleClassifier(rules)
        self.contact_verifier = ContactVerifier(rules)
        self.scorer = CommercialScorer(rules)

    def run(
        self,
        normalized: dict[str, Any],
        raw_input: str,
        enrichment: dict[str, Any] | None = None,
        related_records: list[dict[str, Any]] | None = None,
        mode: str = "fast_scan",
    ) -> dict[str, Any]:
        checked = date.today().isoformat()
        raw_text = safe_snapshot_text(raw_input)
        requested_mode = compact_text(mode).replace(" ", "_")
        normalized_mode = MODE_ALIASES.get(requested_mode)
        output = blank_output(
            raw_text,
            normalized_mode or requested_mode or "invalid",
            self.rules.get("version"),
            checked,
        )
        if normalized_mode is None:
            output["errors"].append(
                {
                    "stage": "input_validation",
                    "code": "unsupported_mode",
                    "message": (
                        "Unsupported mode. Use fast_scan or deep_dive "
                        "(quick/standard aliases are accepted)."
                    ),
                    "retry_count": 0,
                    "retryable": False,
                }
            )
            output["missing_sections"].append("input_validation")
            context = PipelineContext(
                normalized={},
                raw_input=raw_text,
                enrichment={},
                related_records=[],
                mode=output["mode"],
                checked=checked,
                output=output,
            )
            self._finalize(context)
            return output
        if not isinstance(normalized, dict):
            output["errors"].append(
                {
                    "stage": "input_validation",
                    "code": "normalized_input_not_object",
                    "message": "Normalized input must be a JSON object.",
                    "retry_count": 0,
                    "retryable": False,
                }
            )
            output["missing_sections"].append("shipment_normalization")
            context = PipelineContext(
                normalized={},
                raw_input=raw_text,
                enrichment={},
                related_records=[],
                mode=normalized_mode,
                checked=checked,
                output=output,
            )
            self._finalize(context)
            return output
        record = normalized.get("record")
        if not isinstance(record, dict) or not any(
            value not in (None, "", [])
            for value in (record or {}).values()
        ):
            output["errors"].append(
                {
                    "stage": "input_validation",
                    "code": "normalized_record_missing",
                    "message": "No usable normalized customs record was supplied.",
                    "retry_count": 0,
                    "retryable": False,
                }
            )
            output["missing_sections"].append("shipment_normalization")
            context = PipelineContext(
                normalized=normalized,
                raw_input=raw_text,
                enrichment={},
                related_records=[],
                mode=normalized_mode,
                checked=checked,
                output=output,
            )
            self._finalize(context)
            return output
        safe_enrichment = enrichment if isinstance(enrichment, dict) else {}
        safe_related_records = (
            [item for item in related_records if isinstance(item, dict)]
            if isinstance(related_records, list)
            else []
        )
        context = PipelineContext(
            normalized=normalized,
            raw_input=raw_text,
            enrichment=safe_enrichment,
            related_records=safe_related_records,
            mode=normalized_mode,
            checked=checked,
            output=output,
        )
        if enrichment is not None and not isinstance(enrichment, dict):
            output["errors"].append(
                {
                    "stage": "external_enrichment",
                    "code": "external_enrichment_not_object",
                    "message": "External enrichment was ignored because it is not a JSON object.",
                    "retry_count": 0,
                    "retryable": False,
                }
            )
            output["missing_sections"].append("external_enrichment")
        if related_records is not None and not isinstance(related_records, list):
            output["errors"].append(
                {
                    "stage": "related_records",
                    "code": "related_records_not_array",
                    "message": "Related records were ignored because they are not an array.",
                    "retry_count": 0,
                    "retryable": False,
                }
            )
            output["missing_sections"].append("cross_record_data_quality")
        self._stage(context, "shipment_normalization", self._shipment)
        self._stage(context, "product_classification", self._product)
        self._stage(context, "data_quality", self._quality)
        self._stage(context, "entity_resolution", self._entity)
        self._stage(context, "buyer_role", self._role)
        self._stage(context, "contact_verification", self._contacts)
        self._stage(context, "commercial_scoring", self._scoring)
        self._stage(context, "evidence_and_actions", self._evidence_and_actions)
        self._ingest_external_errors(context)
        self._finalize(context)
        return output

    def _stage(
        self,
        context: PipelineContext,
        name: str,
        function: Callable[[PipelineContext], Any],
    ) -> None:
        try:
            context.stage_values[name] = function(context)
            context.output["completed_sections"].append(name)
        except Exception as exc:  # intentional stage isolation
            context.output["errors"].append(
                {
                    "stage": name,
                    "code": f"{name}_failed",
                    "message": str(exc) or exc.__class__.__name__,
                    "retry_count": 0,
                    "retryable": False,
                }
            )
            context.output["missing_sections"].append(name)

    def _shipment(self, context: PipelineContext) -> dict[str, Any]:
        record = context.normalized.get("record") or {}
        output = context.output
        record_date = parse_record_date(record)
        output["record_identity"] = {
            "data_source": record.get("data_source"),
            "record_date": record_date.isoformat() if record_date else None,
            "master_bill": record.get("master_bill"),
            "house_bill": record.get("house_bill"),
            "container_numbers": identifier_list(record.get("containers")),
        }
        supplier_name = record.get("supplier")
        supplier_enrichment = context.enrichment.get("supplier") or {}
        if not isinstance(supplier_enrichment, dict):
            supplier_enrichment = {}
        supplier_role_candidate = str(
            supplier_enrichment.get("verified_role") or ""
        ).upper()
        supplier_grade = str(
            supplier_enrichment.get("evidence_grade") or ""
        ).upper()
        allowed_supplier_roles = {
            "MANUFACTURER",
            "TRADING_COMPANY",
            "LOGISTICS_PROVIDER",
        }
        supplier_role_verified = (
            supplier_role_candidate in allowed_supplier_roles
            and supplier_grade in {"A", "B"}
        )
        supplier_role = (
            supplier_role_candidate
            if supplier_role_verified
            else "UNKNOWN"
        )
        inference = context.normalized.get("pvc_sheet_inference") or {}
        if not isinstance(inference, dict):
            inference = {}
        quantity_estimate = None
        if inference.get("estimated_sheet_count") is not None:
            quantity_estimate = {
                "estimated_sheets": inference.get("nearest_full_sheet_count"),
                "raw_estimate": inference.get("estimated_sheet_count"),
                "calculation_basis": "dimensions × thickness × density",
                "confidence": "medium"
                if inference.get("plausible_for_sheet_count")
                else "low",
                "warning": "Gross/net weight, packaging and shorthand density may affect the result.",
                "status": "estimate",
            }
        origin = record.get("origin")
        origin_code = compact_text(
            " ".join(
                str(value or "")
                for value in (
                    record.get("country_origin_code"),
                    record.get("origin_code"),
                    record.get("coo_code"),
                )
            )
        )
        origin_text = compact_text(origin)
        if "cn" in origin_code.split() or "china" in origin_text:
            manufacturing_origin = "China"
            manufacturing_status = "DECLARED"
        else:
            manufacturing_origin = None
            manufacturing_status = "UNKNOWN"
        route_enrichment = context.enrichment.get("route") or {}
        if not isinstance(route_enrichment, dict):
            route_enrichment = {}
        output["normalized_shipment"] = {
            "supplier": {
                "raw_name": supplier_name,
                "legal_name": (
                    supplier_enrichment.get("legal_name")
                    if supplier_role_verified
                    else None
                ),
                "role": supplier_role,
                "role_status": (
                    "VERIFIED" if supplier_role_verified else "UNKNOWN"
                ),
                "reason_codes": (
                    ["strong_supplier_role_evidence"]
                    if supplier_role_verified
                    else ["supplier_role_not_verified"]
                ),
            },
            "buyer": {
                "raw_name": record.get("buyer"),
                "legal_name": None,
                "country": record.get("destination_country"),
                "role": "UNKNOWN",
            },
            "product": output["normalized_shipment"]["product"],
            "quantity": {
                "declared_quantity": record.get("quantity_count"),
                "declared_unit": record.get("quantity_unit"),
                "quantity_scope": record.get("quantity_scope", "not_declared"),
                "weight_kg": record.get("weight_kg"),
                "gross_weight_kg": record.get("gross_weight_kg"),
                "package_count": record.get("package_count"),
                "package_type": record.get("package_type"),
                "package_count_is_product_quantity": False,
                "estimated_sheets": (
                    quantity_estimate.get("estimated_sheets")
                    if quantity_estimate
                    else None
                ),
                "estimate": quantity_estimate,
            },
            "route": {
                "declared_origin": origin,
                "manufacturing_origin": manufacturing_origin,
                "manufacturing_origin_status": manufacturing_status,
                "place_of_receipt": record.get("place_of_receipt"),
                "port_of_lading": record.get("port_of_lading"),
                "transshipment_ports": identifier_list(
                    route_enrichment.get("transshipment_ports")
                ),
                "port_of_discharge": record.get("port_of_discharge"),
                "final_delivery_location": (
                    route_enrichment.get("final_delivery_location")
                    or record.get("buyer_address")
                ),
            },
            "field_scope": {
                "shipment_level": [],
                "line_item": [],
                "ambiguous": [],
            },
        }
        return output["normalized_shipment"]

    def _product(self, context: PipelineContext) -> dict[str, Any]:
        record = context.normalized.get("record") or {}
        result = self.product_classifier.classify(
            record,
            context.normalized.get("pvc_sheet_inference"),
        )
        context.output["normalized_shipment"]["product"] = result
        return result

    def _quality(self, context: PipelineContext) -> dict[str, Any]:
        product = context.output["normalized_shipment"]["product"]
        result = self.data_validator.validate(
            context.normalized,
            product,
            context.related_records,
        )
        context.output["data_quality"] = result
        context.output["normalized_shipment"]["field_scope"] = result["field_scope"]
        return result

    def _entity(self, context: PipelineContext) -> dict[str, Any]:
        record = context.normalized.get("record") or {}
        result = self.entity_resolver.resolve(record, context.enrichment)
        context.output["entity_resolution"] = result
        context.output["normalized_shipment"]["buyer"]["legal_name"] = result.get(
            "legal_name"
        )
        return result

    def _role(self, context: PipelineContext) -> dict[str, Any]:
        record = context.normalized.get("record") or {}
        result = self.role_classifier.classify(
            record,
            context.output["normalized_shipment"]["product"],
            context.output["entity_resolution"],
            context.enrichment,
        )
        context.output["buyer_intelligence"] = result
        context.output["normalized_shipment"]["buyer"]["role"] = result["buyer_role"]
        return result

    def _contacts(self, context: PipelineContext) -> list[dict[str, Any]]:
        contacts, status = self.contact_verifier.verify(
            context.normalized,
            context.output["entity_resolution"],
            context.enrichment,
        )
        context.output["contacts"] = contacts
        context.output["contact_status"] = status
        return contacts

    def _scoring(self, context: PipelineContext) -> dict[str, Any]:
        record = context.normalized.get("record") or {}
        score = self.scorer.score(
            record,
            context.output["normalized_shipment"]["product"],
            context.output["data_quality"],
            context.output["entity_resolution"],
            context.output["buyer_intelligence"],
            context.output["contacts"],
            context.output["contact_status"],
            context.enrichment,
        )
        context.output["commercial_scoring"] = score
        return score

    def _evidence_and_actions(self, context: PipelineContext) -> dict[str, Any]:
        output = context.output
        record = context.normalized.get("record") or {}
        source = {
            "source_id": "src-customs-record",
            "type": "customs_or_trade_record",
            "evidence_grade": "C",
            "source": record.get("data_source") or "user-provided customs record",
            "date_checked": context.checked,
        }
        evidence = [source]
        for index, item in enumerate(
            mapping_items(context.enrichment.get("evidence")),
            start=1,
        ):
            grade = str(item.get("evidence_grade") or "D").upper()
            if grade not in {"A", "B", "C", "D"}:
                grade = "D"
            evidence.append(
                {
                    "source_id": item.get("source_id") or f"src-enrichment-{index}",
                    "type": item.get("type", "external_enrichment"),
                    "evidence_grade": grade,
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "date_checked": item.get("date_checked") or context.checked,
                }
            )
        output["evidence"] = evidence
        facts = []
        if record.get("buyer"):
            facts.append(
                evidence_claim(
                    "fact-buyer",
                    f"Customs record names buyer: {record['buyer']}",
                    "fact",
                    "C",
                    0.75,
                    ["src-customs-record"],
                    ["buyer_name_observed_in_customs_record"],
                    context.checked,
                )
            )
        if record.get("product"):
            facts.append(
                evidence_claim(
                    "fact-product-description",
                    f"Customs product description: {record['product']}",
                    "fact",
                    "C",
                    0.75,
                    ["src-customs-record"],
                    ["product_text_observed_in_customs_record"],
                    context.checked,
                )
            )
        output["facts"] = facts
        product = output["normalized_shipment"]["product"]
        role = output["buyer_intelligence"]
        score = output["commercial_scoring"]
        output["inferences"] = [
            evidence_claim(
                "inference-product-classification",
                f"Product match classified as {product['match_level']} ({product['normalized_category']}).",
                "inference",
                "D",
                float(product.get("confidence") or 0),
                ["src-customs-record"],
                product.get("reason_codes") or [],
                context.checked,
            ),
            evidence_claim(
                "inference-buyer-role",
                f"Buyer role assessed as {role['buyer_role']}.",
                "inference",
                "D",
                float(role.get("role_confidence") or 0),
                ["src-customs-record"],
                role.get("reason_codes") or [],
                context.checked,
            ),
            evidence_claim(
                "inference-sales-priority",
                f"Provisional sales priority is {score.get('sales_priority')}.",
                "inference",
                "D",
                min(0.75, float(score.get("score_completeness") or 0)),
                ["src-customs-record"],
                score.get("reason_codes") or [],
                context.checked,
            ),
        ]
        unknowns: list[dict[str, Any]] = []
        if not output["entity_resolution"].get("matched"):
            unknowns.append(
                {
                    "field": "current_legal_identity",
                    "status": "未显示/待核验",
                    "reason_code": "strong_entity_match_not_available",
                }
            )
        trade = context.enrichment.get("trade_summary") or {}
        if not isinstance(trade, dict):
            trade = {}
        if trade.get("product_specific_shipments") is None:
            unknowns.append(
                {
                    "field": "repeat_purchase",
                    "status": "未显示/待核验",
                    "reason_code": "product_specific_history_not_supplied",
                }
            )
        if not output["contact_status"]["verified_procurement_contact"]:
            unknowns.append(
                {
                    "field": "verified_procurement_contact",
                    "status": "未找到已验证采购负责人",
                    "reason_code": "verified_procurement_contact_not_found",
                }
            )
        output["unknowns"] = unknowns
        actions: list[dict[str, Any]] = []
        exclusion = None
        if output["data_quality"].get("scoring_suspended"):
            actions.append(
                {
                    "priority": 1,
                    "action": "Reconcile bill/container collisions before customer grading.",
                    "reason_code": "data_quality_scoring_suspended",
                }
            )
            exclusion = "record_contamination_requires_reconciliation"
        elif role.get("buyer_role") in {
            BuyerRole.FREIGHT_FORWARDER.value,
            BuyerRole.NVOCC.value,
        }:
            exclusion = "logistics_intermediary_not_end_buyer"
            actions.append(
                {
                    "priority": 1,
                    "action": "Do not treat the logistics intermediary as the PVC purchasing buyer.",
                    "reason_code": "logistics_role",
                }
            )
        elif product.get("match_level") == ProductMatch.NONE.value:
            exclusion = "non_target_product"
            actions.append(
                {
                    "priority": 1,
                    "action": "Exclude from standard PVC foam-board outreach unless a separate target-product record exists.",
                    "reason_code": "non_target_product",
                }
            )
        elif product.get("match_level") == ProductMatch.INCIDENTAL.value:
            exclusion = "finished_item_or_incidental_material_use"
            actions.append(
                {
                    "priority": 1,
                    "action": "Treat as a finished-display/end-use lead, not proof of regular board purchasing.",
                    "reason_code": "incidental_product_use",
                }
            )
        elif score.get("deep_dive_eligible"):
            actions.append(
                {
                    "priority": 1,
                    "action": "Run Deep Dive for entity, repeat-purchase and procurement-contact verification.",
                    "reason_code": "deep_dive_gate_passed",
                }
            )
        else:
            actions.append(
                {
                    "priority": 1,
                    "action": "Verify unresolved product, role or repeat-purchase evidence before Deep Dive.",
                    "reason_code": "fast_scan_requires_more_evidence",
                }
            )
        output["recommended_actions"] = actions
        output["exclusion_reason"] = exclusion
        return {"facts": facts, "unknowns": unknowns, "actions": actions}

    def _ingest_external_errors(self, context: PipelineContext) -> None:
        raw_errors = context.enrichment.get("errors")
        if raw_errors not in (None, []) and not isinstance(
            raw_errors, (list, tuple)
        ):
            raw_errors = [raw_errors]
        for item in raw_errors or []:
            if not isinstance(item, dict):
                context.output["errors"].append(
                    {
                        "stage": "external_company_search",
                        "code": "malformed_external_error",
                        "message": str(item) or "Malformed external error entry.",
                        "retry_count": 0,
                        "retryable": False,
                    }
                )
                continue
            try:
                retry_count = max(0, int(item.get("retry_count") or 0))
            except (TypeError, ValueError):
                retry_count = 0
            context.output["errors"].append(
                {
                    "stage": item.get("stage", "external_company_search"),
                    "code": item.get("code", "external_search_failed"),
                    "message": item.get("message", "External search did not return a usable result."),
                    "retry_count": retry_count,
                    "retryable": bool(item.get("retryable", False)),
                }
            )
        enrichment_status = compact_text(
            context.enrichment.get("status")
        ).replace(" ", "_")
        deep_dive_failed = (
            context.mode == "deep_dive"
            and (
                not context.enrichment
                or enrichment_status in {"failed", "partial"}
            )
        )
        if deep_dive_failed:
            if not context.output["errors"]:
                context.output["errors"].append(
                    {
                        "stage": "deep_dive_enrichment",
                        "code": (
                            "deep_dive_enrichment_missing"
                            if not context.enrichment
                            else f"deep_dive_enrichment_{enrichment_status}"
                        ),
                        "message": (
                            "Deep Dive was requested without verified external enrichment."
                            if not context.enrichment
                            else "Deep Dive enrichment did not complete successfully."
                        ),
                        "retry_count": 0,
                        "retryable": True,
                    }
                )
            context.output["missing_sections"].extend(
                ["current_legal_status", "decision_makers", "verified_contacts"]
            )

    @staticmethod
    def _finalize(context: PipelineContext) -> None:
        output = context.output
        output["completed_sections"] = list(
            dict.fromkeys(output.get("completed_sections") or [])
        )
        output["missing_sections"] = list(
            dict.fromkeys(output.get("missing_sections") or [])
        )
        defaults: dict[str, Any] = {
            "status": "failed",
            "record_identity": {},
            "normalized_shipment": {},
            "data_quality": {},
            "entity_resolution": {},
            "buyer_intelligence": {},
            "contacts": [],
            "commercial_scoring": {},
            "facts": [],
            "inferences": [],
            "unknowns": [],
            "recommended_actions": [],
            "exclusion_reason": None,
            "evidence": [],
            "errors": [],
        }
        for key in REQUIRED_TOP_LEVEL_KEYS:
            if key not in output or output[key] is None:
                output[key] = defaults[key]
        if output["errors"] or output["missing_sections"]:
            output["status"] = (
                "partial" if output["completed_sections"] else "failed"
            )
        else:
            output["status"] = "complete"


def render_chinese_report(result: dict[str, Any]) -> str:
    product = result.get("normalized_shipment", {}).get("product", {})
    buyer = result.get("normalized_shipment", {}).get("buyer", {})
    quantity = result.get("normalized_shipment", {}).get("quantity", {})
    quality = result.get("data_quality", {})
    role = result.get("buyer_intelligence", {})
    score = result.get("commercial_scoring", {})
    contact_status = result.get("contact_status", {})
    role_confidence = as_number(role.get("role_confidence")) or 0.0
    lines = [
        "# 海关买家情报报告",
        "",
        f"- 运行状态：{result.get('status', 'failed')}",
        f"- 买家：{buyer.get('raw_name') or '未显示/待核验'}",
        f"- 产品匹配：{product.get('match_level', 'UNKNOWN')} / {product.get('normalized_category', '未显示/待核验')}",
        f"- 买家角色：{role.get('buyer_role', 'UNKNOWN')}（置信度 {role_confidence:.2f}）",
        f"- 销售优先级：{score.get('sales_priority', 'UNSCORABLE')}（{'暂定' if score.get('provisional', True) else '已完成'}）",
        "",
        "## 1. 数据质量",
        "",
        f"- 状态：{quality.get('status', 'unknown')}；评分：{quality.get('score', 0)}/100",
        f"- 疑似串单或字段污染：{'是' if quality.get('possible_contamination') else '否'}",
    ]
    for warning in quality.get("warnings", [])[:8]:
        lines.append(
            f"- [{warning.get('severity', 'medium')}] {warning.get('code')}: {warning.get('message')}"
        )
    lines.extend(
        [
            "",
            "## 2. 货物与数量",
            "",
            f"- 海关申报数量：{quantity.get('declared_quantity') if quantity.get('declared_quantity') is not None else '未显示/待核验'} {quantity.get('declared_unit') or ''}".rstrip(),
            f"- 包装数量：{quantity.get('package_count') if quantity.get('package_count') is not None else '未显示/待核验'}（不得视为商品件数）",
            f"- 重量：{quantity.get('weight_kg') if quantity.get('weight_kg') is not None else '未显示/待核验'} kg",
            f"- 估算张数：{quantity.get('estimated_sheets') if quantity.get('estimated_sheets') is not None else '未显示/待核验'}（仅为估算）",
            "",
            "## 3. 企业、角色与评分",
            "",
            f"- 实体匹配：{result.get('entity_resolution', {}).get('status', 'UNKNOWN')}",
            f"- 买家真实性：{score.get('buyer_authenticity', 'UNKNOWN')}",
            f"- 产品匹配：{score.get('product_fit', 'UNKNOWN')}",
            f"- 总分：{score.get('total_score') if score.get('total_score') is not None else '暂停评分'}",
            f"- 分数范围：{score.get('score_range')}",
            "",
            "## 4. 联系人",
            "",
            f"- {contact_status.get('message', '未找到已验证采购负责人')}",
        ]
    )
    formal_contacts = [
        item
        for item in result.get("contacts", [])
        if item.get("usable_for_outreach")
    ]
    if formal_contacts:
        for item in formal_contacts:
            lines.append(
                f"- {item.get('name') or '公司通用渠道'} | {item.get('title') or item.get('decision_role')} | {item.get('email') or item.get('phone') or item.get('social')}"
            )
    else:
        lines.append("- 未显示/待核验")
    lines.extend(["", "## 5. 事实、推断与未知", ""])
    for item in result.get("facts", []):
        lines.append(f"- 事实：{item.get('claim')}")
    for item in result.get("inferences", []):
        lines.append(
            f"- 推断：{item.get('claim')}（{item.get('evidence_grade')}/{item.get('confidence')}）"
        )
    for item in result.get("unknowns", []):
        lines.append(f"- 未知：{item.get('field')} — {item.get('status')}")
    lines.extend(["", "## 6. 下一步", ""])
    for item in result.get("recommended_actions", []):
        lines.append(f"- {item.get('action')}")
    if result.get("errors"):
        lines.extend(["", "## 错误与未完成项", ""])
        for item in result["errors"]:
            lines.append(
                f"- {item.get('stage')}: {item.get('message')}（重试 {item.get('retry_count', 0)} 次）"
            )
    return "\n".join(lines).rstrip() + "\n"
