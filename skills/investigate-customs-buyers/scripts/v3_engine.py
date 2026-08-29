#!/usr/bin/env python3
"""V3 audit, CRM, scenario, source-ledger, and contamination layer."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCHEMA_VERSION = "4.2.0"
CLAIM_CLASSES = {"FACT", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION", "UNKNOWN"}
FIELD_STATUSES = {
    "confirmed",
    "plausible",
    "inferred",
    "contaminated",
    "contradictory",
    "unresolved",
}

RESEARCH_STEPS = (
    "customs_consignee_notify_notes",
    "official_homepage",
    "official_contact_page",
    "official_footer",
    "official_mobile_page",
    "official_images_pdfs_catalogs",
    "instagram_bio",
    "instagram_contact_and_recent_images",
    "facebook_about",
    "facebook_posts_and_images",
    "linkedin_company",
    "linkedin_people",
    "google_business_profile",
    "youtube_about",
    "recruitment_sites",
    "industry_associations",
    "trade_show_pages",
    "local_business_directories",
    "government_registry_tax",
    "historical_bills",
    "packaging_marks_and_promotional_images",
)

SOURCE_GRADE_BY_TYPE = {
    "government_registry": "A1",
    "official_customs": "A1",
    "official_domain": "A2",
    "official_social": "A2",
    "official_directory": "A2",
    "official_pdf": "A2",
    "trade_database": "B1",
    "professional_profile": "B2",
    "google_business_profile": "C1",
    "local_business_directory": "C1",
    "recruitment_site": "C1",
    "marketplace": "C2",
    "third_party_directory": "C2",
    "unverified_site": "C2",
    "customs_or_trade_record": "B1",
    "calculation": "D",
    "user_supplied": "D",
}


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def key_text(value: Any) -> str:
    text = clean_text(value).casefold()
    text = re.sub(r"\b(?:incorporated|corporation|company|limited|ltd|inc|corp|llc|pvt|s\.?a\.?c\.?)\b", " ", text)
    return re.sub(r"[^a-z0-9\u00c0-\u024f\u4e00-\u9fff]+", " ", text).strip()


def stable_hash(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    match = re.search(r"[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def normalize_email(value: Any) -> str | None:
    text = clean_text(value).casefold().replace(" ", "")
    match = re.search(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", text)
    return match.group(0) if match else None


def normalize_phone(value: Any) -> str | None:
    text = clean_text(value)
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return None
    return ("+" if plus else "") + digits


def iter_contact_candidates(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from iter_contact_candidates(item)
    elif isinstance(value, dict):
        if any(key in value for key in ("email", "phone", "value", "social")):
            yield value
        else:
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    yield from iter_contact_candidates(item)
                elif normalize_email(item):
                    yield {"contact_type": "email", "email": item, "field": key}


def classify_source(url: Any, declared_type: Any = None) -> str:
    declared = clean_text(declared_type).casefold().replace(" ", "_")
    if declared in SOURCE_GRADE_BY_TYPE:
        return declared
    host = urlparse(clean_text(url)).netloc.casefold().removeprefix("www.")
    if not host:
        return "user_supplied"
    if host.endswith((".gov", ".gov.ph", ".gov.vn", ".gov.cn")):
        return "government_registry"
    if host in {"dnb.com", "www.dnb.com"} or host.endswith(".dnb.com"):
        return "third_party_directory"
    if "google." in host or host in {"maps.app.goo.gl", "goo.gl"}:
        return "google_business_profile"
    if host.endswith(("instagram.com", "facebook.com", "linkedin.com", "youtube.com")):
        return "unverified_site"
    if any(token in host for token in ("alibaba", "made-in-china", "globalsources")):
        return "marketplace"
    return "unverified_site"


def evidence_grade(source_type: str, declared_grade: Any = None) -> str:
    grade = clean_text(declared_grade).upper()
    if grade in {"A1", "A2", "B1", "B2", "C1", "C2", "D"}:
        return grade
    if grade in {"A", "B", "C"}:
        return {"A": "A1", "B": "B1", "C": "C2"}[grade]
    return SOURCE_GRADE_BY_TYPE.get(source_type, "D")


def parse_iso_date(value: Any) -> date | None:
    text = clean_text(value)
    match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def source_freshness(source: dict[str, Any], *, target_days: int = 30) -> str:
    observed = parse_iso_date(source.get("checked_at") or source.get("last_verified"))
    if observed is None:
        return "unknown"
    age = (date.today() - observed).days
    if age < 0:
        return "future_date_invalid"
    return "current" if age <= target_days else "stale"


def link_type(source_type: str, url: Any, page_kind: Any = None) -> str:
    url_text = clean_text(url)
    page = clean_text(page_kind).casefold()
    if source_type == "government_registry":
        return "工商/政府查询入口"
    if source_type == "trade_database" or source_type == "customs_or_trade_record":
        return "贸易数据库"
    if source_type == "google_business_profile":
        if any(token in url_text.casefold() for token in ("/search", "?q=", "maps/search")):
            return "地图搜索入口"
        return "Google Business企业档案"
    if source_type == "official_social":
        return "官方社媒"
    if source_type == "official_domain":
        return "官方品牌官网" if "brand" in page else "官方官网"
    if source_type in {"third_party_directory", "local_business_directory", "professional_profile"}:
        return "第三方商业目录"
    if source_type in {"unverified_site", "marketplace"}:
        return "疑似官方，待验证"
    return "人工检查入口" if not url_text else "其他来源"


def independent_source_groups(sources: Iterable[dict[str, Any]]) -> set[str]:
    groups: set[str] = set()
    for source in sources:
        url = clean_text(source.get("url") or source.get("source_reference"))
        host = urlparse(url).netloc.casefold().removeprefix("www.")
        provider = clean_text(source.get("provider") or source.get("source")).casefold()
        groups.add(host or provider or str(source.get("source_id") or "unknown"))
    return groups


class ProductTaxonomy:
    """Use specific structural signals before generic PVC/foam tokens."""

    def classify(self, record: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        raw = " | ".join(
            clean_text(value)
            for value in (record.get("product"), record.get("product_description_local"))
            if value
        )
        text = raw.casefold().replace("×", "x")
        compact = re.sub(r"\s+", " ", text)
        result = dict(current)
        category = None
        level = None
        reason = None
        confidence = 0.9

        thin_edge = bool(
            re.search(r"(?:0[.,]?\d+|1(?:\.\d+)?)\s*(?:mm)?\s*x\s*(?:1\d|2\d|3\d)\s*mm", compact)
        ) and any(token in compact for token in ("non foam", "non-foam", "no adhesive", "not self adhesive", "edge band", "edgeband"))
        ps_signal = any(token in compact for token in ("polystyrene", "ps foam", "kt board")) or bool(re.search(r"\bps\b.*\bfoam\b|\bfoam\b.*\bps\b", compact))
        paper_ps = ps_signal and any(
            token in compact for token in ("paper", "carton", "g/m2", "g/m²", "gsm", "202g")
        )

        checks = (
            (paper_ps, "PAPER_FACED_PS_OR_KT_BOARD", "NONE", "paper_faced_ps_board_signals", 0.98),
            (thin_edge or "pvc edge band" in compact or "pvc edging" in compact, "PVC_EDGE_BAND", "NONE", "thin_nonfoam_edge_band_signals", 0.97),
            (any(x in compact for x in ("structural pvc foam core", "marine foam core", "cross linked pvc core", "cross-linked pvc core")), "STRUCTURAL_CROSSLINKED_PVC_MARINE_CORE", "NONE", "structural_marine_core_signals", 0.98),
            (any(x in compact for x in ("outer corner", "inside corner", "metal line", "decorative trim", "wall panel trim", "outside angle", "external angle")), "WALL_PANEL_TRIM_ACCESSORY", "RELATED", "wall_panel_trim_accessory_signals", 0.96),
            ("wpc" in compact or "wood plastic composite" in compact, "WPC_BOARD", "RELATED", "wpc_board_signals", 0.95),
            ("co extruded pvc" in compact or "co-extruded pvc" in compact or "pvc coextruded" in compact, "PVC_COEXTRUDED_BOARD", "EXACT", "coextruded_board_signals", 0.97),
            ("celuka" in compact or "pvc crust board" in compact or "结皮" in compact, "PVC_CELUKA_BOARD", "EXACT", "celuka_board_signals", 0.97),
            ("free foam" in compact or "自由发泡" in compact, "PVC_FREE_FOAM_BOARD", "EXACT", "free_foam_signals", 0.97),
            (any(x in compact for x in ("petg laminated", "pvc laminated", "decorative film", "覆膜")), "PETG_OR_PVC_LAMINATED_BOARD", "RELATED", "laminated_board_signals", 0.9),
            (any(x in compact for x in ("solid pvc sheet", "rigid pvc sheet", "non porous pvc plate", "non-porous pvc plate")), "SOLID_OR_RIGID_PVC_SHEET", "RELATED", "solid_pvc_sheet_signals", 0.93),
            (any(x in compact for x in ("aluminum composite panel", "acrylic sheet", "acp sheet")) and "pvc" in compact, "MIXED_BOARD_CARGO", "RELATED", "mixed_board_cargo_signals", 0.88),
            ("pvc foam board" in compact or "foamed pvc board" in compact or "expanded pvc sheet" in compact, "PVC_FOAM_BOARD_UNSPECIFIED_PROCESS", "EXACT", "generic_pvc_foam_board_signals", 0.97),
        )
        for matched, candidate, match_level, code, candidate_confidence in checks:
            if matched:
                category, level, reason, confidence = candidate, match_level, code, candidate_confidence
                break
        if category:
            result.update(
                {
                    "normalized_category": category,
                    "match_level": level,
                    "confidence": confidence,
                    "reason_codes": [reason],
                    "classification_basis": "semantic_signals_not_hs_title",
                }
            )
        result["claim_class"] = "INFERENCE"
        result["requires_spec_verification"] = category in {
            "PVC_FOAM_BOARD_UNSPECIFIED_PROCESS",
            "PETG_OR_PVC_LAMINATED_BOARD",
            "MIXED_BOARD_CARGO",
            "WALL_PANEL_TRIM_ACCESSORY",
        } or not category
        return result


class ScenarioEngine:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.config = rules.get("scenario_engine") or rules.get("v3", {}).get("scenario_engine", {})

    def generate(
        self,
        record: dict[str, Any],
        product: dict[str, Any],
        data_quality: dict[str, Any],
        enrichment: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        calculations: list[dict[str, Any]] = []
        scenarios: list[dict[str, Any]] = []
        specs = product.get("specifications") or {}
        length_mm = as_number(specs.get("length_mm"))
        width_mm = as_number(specs.get("width_mm"))
        thickness_mm = as_number(specs.get("thickness_mm"))
        density_g_cm3 = as_number(specs.get("density_g_cm3"))
        quantity = as_number(record.get("quantity_count"))
        package_count = as_number(record.get("package_count"))
        weight_kg = as_number(record.get("weight_kg"))
        measurement_m3 = as_number(record.get("measurement_m3"))
        amount = as_number(record.get("original_amount"))

        if record.get("weight_lb") is not None:
            pounds = as_number(record.get("weight_lb"))
            if pounds is not None:
                calculations.append(self._calc("lb_to_kg", "lb × 0.45359237", {"lb": pounds}, pounds * 0.45359237, "kg"))
        if record.get("measurement_cuft") is not None:
            cuft = as_number(record.get("measurement_cuft"))
            if cuft is not None:
                calculations.append(self._calc("cubic_feet_to_m3", "ft³ × 0.0283168466", {"ft3": cuft}, cuft * 0.0283168466, "m3"))

        if length_mm and width_mm:
            area = length_mm / 1000 * width_mm / 1000
            calculations.append(self._calc("sheet_area", "length_m × width_m", {"length_mm": length_mm, "width_mm": width_mm}, area, "m2"))
            if thickness_mm:
                volume = area * thickness_mm / 1000
                calculations.append(self._calc("sheet_volume", "area_m2 × thickness_m", {"area_m2": area, "thickness_mm": thickness_mm}, volume, "m3"))
                if density_g_cm3:
                    sheet_weight = volume * density_g_cm3 * 1000
                    calculations.append(self._calc("weight_per_sheet", "volume_m3 × density_kg_m3", {"volume_m3": volume, "density_g_cm3": density_g_cm3}, sheet_weight, "kg"))
        if amount not in (None, 0) and quantity not in (None, 0):
            calculations.append(self._calc("price_per_declared_unit", "amount ÷ quantity", {"amount": amount, "quantity": quantity}, amount / quantity, f"currency/{record.get('quantity_unit') or 'unit'}"))
        if amount not in (None, 0) and weight_kg not in (None, 0) and not data_quality.get("shipment_line_conflict"):
            calculations.append(self._calc("price_per_kg", "amount ÷ allocated_weight_kg", {"amount": amount, "weight_kg": weight_kg}, amount / weight_kg, "currency/kg"))
        elif amount not in (None, 0) and weight_kg not in (None, 0):
            calculations.append({
                "calculation_id": "price_per_kg",
                "status": "blocked",
                "claim_class": "UNKNOWN",
                "formula": "amount ÷ allocated_weight_kg",
                "inputs": {"amount": amount, "weight_kg": weight_kg},
                "result": None,
                "unit": "currency/kg",
                "reason_code": "shipment_total_not_allocated_to_line_item",
            })
        if weight_kg not in (None, 0) and measurement_m3 not in (None, 0):
            calculations.append(self._calc("shipment_bulk_density", "weight_kg ÷ volume_m3", {"weight_kg": weight_kg, "volume_m3": measurement_m3}, weight_kg / measurement_m3, "kg/m3"))
        packing_text = clean_text(record.get("product") or record.get("product_description_local")).casefold()
        pieces_per_box_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:pcs?|pieces?)\s*(?:/|per)\s*(?:box|ctn|carton)", packing_text)
        if quantity not in (None, 0) and pieces_per_box_match:
            pieces_per_box = float(pieces_per_box_match.group(1))
            implied_boxes = quantity / pieces_per_box
            calculation = self._calc("implied_inner_box_count", "declared_piece_quantity ÷ stated_pieces_per_box", {"quantity": quantity, "pieces_per_box": pieces_per_box, "declared_package_count": package_count, "declared_package_type": record.get("package_type")}, implied_boxes, "box")
            calculation["package_level_interpretation"] = "different_level_or_conflict" if package_count not in (None, 0) and abs(implied_boxes - package_count) > 1e-9 else "consistent"
            calculation["warning"] = "A different declared package count may describe outer packages, not an error. Confirm the packing list before replacing either count."
            calculations.append(calculation)

        assumptions = enrichment.get("calculation_assumptions") or {}
        if not isinstance(assumptions, dict):
            assumptions = {}
        if product.get("normalized_category") == "WALL_PANEL_TRIM_ACCESSORY":
            accessory_calculations, accessory_scenarios = self._accessory_material_scenarios(
                record,
                product,
                assumptions,
                quantity=quantity,
                weight_kg=weight_kg,
            )
            calculations.extend(accessory_calculations)
            return calculations, accessory_scenarios
        length_candidates = self._candidates(length_mm, assumptions.get("length_mm"), [1220])
        width_candidates = self._candidates(width_mm, assumptions.get("width_mm"), [2440])
        thickness_candidates = self._candidates(thickness_mm, assumptions.get("thickness_mm"), self.config.get("thickness_mm_candidates", [5, 8, 10, 15, 18]))
        density_candidates = self._candidates(density_g_cm3, assumptions.get("density_g_cm3"), self.config.get("density_g_cm3_candidates", [0.45, 0.5, 0.55, 0.6, 0.65]))
        sheets_per_package = self._candidates(None, assumptions.get("sheets_per_package"), self.config.get("sheets_per_package_candidates", [20, 30, 40, 50]))
        scenario_package_count = as_number(assumptions.get("package_count")) or package_count
        actual_weight = as_number(assumptions.get("actual_weight_kg")) or weight_kg
        if (
            actual_weight not in (None, 0)
            and scenario_package_count not in (None, 0)
            and not data_quality.get("shipment_line_conflict")
        ):
            for length in length_candidates:
                for width in width_candidates:
                    for thickness in thickness_candidates:
                        for density in density_candidates:
                            for spp in sheets_per_package:
                                sheet_count = scenario_package_count * spp
                                theoretical = (length / 1000) * (width / 1000) * (thickness / 1000) * (density * 1000) * sheet_count
                                diff = abs(theoretical - actual_weight) / actual_weight * 100
                                scenarios.append(
                                    {
                                        "scenario_id": "",
                                        "rank": 0,
                                        "claim_class": "HYPOTHESIS",
                                        "inputs": {
                                            "length_mm": length,
                                            "width_mm": width,
                                            "thickness_mm": thickness,
                                            "density_g_cm3": density,
                                            "package_count": scenario_package_count,
                                            "sheets_per_package": spp,
                                            "sheet_count": sheet_count,
                                        },
                                        "theoretical_weight_kg": round(theoretical, 3),
                                        "actual_weight_kg": actual_weight,
                                        "difference_percent": round(diff, 3),
                                        "confidence": round(max(0.05, min(0.85, 0.85 - diff / 100)), 2),
                                        "unresolved_fields": ["packing_list", "line_item_weight_allocation", "confirmed_density_and_sheet_count"],
                                        "warning": "Mathematical fit does not confirm the physical specification.",
                                    }
                                )
            scenarios.sort(key=lambda item: (item["difference_percent"], -item["confidence"]))
            scenarios = scenarios[:3]
            labels = ("best_fit", "alternative_1", "alternative_2")
            for index, scenario in enumerate(scenarios):
                scenario["rank"] = index + 1
                scenario["scenario_id"] = labels[index]
        return calculations, scenarios

    def _accessory_material_scenarios(
        self,
        record: dict[str, Any],
        product: dict[str, Any],
        assumptions: dict[str, Any],
        *,
        quantity: float | None,
        weight_kg: float | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        calculations: list[dict[str, Any]] = []
        raw = clean_text(record.get("product") or product.get("raw_description")).casefold().replace("×", "x")
        specs = product.get("specifications") or {}
        length_mm = as_number(assumptions.get("length_mm")) or as_number(specs.get("length_mm"))
        thickness_mm = as_number(assumptions.get("thickness_mm")) or as_number(specs.get("thickness_mm"))
        dimension = re.search(r"(\d{3,4}(?:\.\d+)?)\s*(?:mm)?\s*x\s*(0?\.\d+|\d+(?:\.\d+)?)\s*mm", raw)
        if dimension:
            length_mm = length_mm or float(dimension.group(1))
            thickness_mm = thickness_mm or float(dimension.group(2))
        if length_mm is None:
            candidates = [float(item) for item in re.findall(r"\b(\d{3,4})\b", raw) if 1000 <= float(item) <= 6000]
            length_mm = candidates[0] if candidates else None
        unit_weight = weight_kg / quantity if weight_kg not in (None, 0) and quantity not in (None, 0) else None
        if unit_weight is not None:
            calculations.append(self._calc("observed_weight_per_piece", "allocated_weight_kg ÷ declared_piece_quantity", {"weight_kg": weight_kg, "quantity": quantity}, unit_weight, "kg/piece"))

        material_candidates = [
            ("aluminum_alloy", 2700.0, ("aluminum", "aluminium", "铝")),
            ("stainless_steel", 8000.0, ("stainless", "不锈钢")),
            ("coated_or_galvanized_steel", 7850.0, ("galvanized", "coated steel", "镀锌", "steel")),
            ("pvc_or_metalized_pvc", 1400.0, ("pvc", "plastic")),
        ]
        explicit = [item for item in material_candidates if any(token in raw for token in item[2])]
        ordered = explicit + [item for item in material_candidates if item not in explicit]
        cross_section = as_number(assumptions.get("cross_section_area_mm2"))
        scenarios: list[dict[str, Any]] = []
        for index, (material, density, _tokens) in enumerate(ordered[:3], 1):
            theoretical = None
            difference = None
            required_area = None
            implied_flat_width = None
            if length_mm and cross_section:
                theoretical = density * (cross_section / 1_000_000) * (length_mm / 1000)
                if unit_weight:
                    difference = abs(theoretical - unit_weight) / unit_weight * 100
            elif length_mm and unit_weight:
                required_area = unit_weight / (density * (length_mm / 1000)) * 1_000_000
                if thickness_mm:
                    implied_flat_width = required_area / thickness_mm
            scenarios.append(
                {
                    "scenario_id": "best_fit" if explicit and index == 1 else f"alternative_{index if explicit else index}",
                    "rank": index if explicit else None,
                    "ranking_status": "explicit_material_token" if explicit else "insufficient_evidence_to_rank",
                    "claim_class": "HYPOTHESIS",
                    "material": material,
                    "inputs": {"density_kg_m3": density, "length_mm": length_mm, "thickness_mm": thickness_mm, "cross_section_area_mm2": cross_section, "observed_unit_weight_kg": unit_weight},
                    "theoretical_weight_kg": round(theoretical, 6) if theoretical is not None else None,
                    "difference_percent": round(difference, 3) if difference is not None else None,
                    "required_cross_section_area_mm2": round(required_area, 4) if required_area is not None else None,
                    "implied_flat_width_mm": round(implied_flat_width, 3) if implied_flat_width is not None else None,
                    "confidence": 0.65 if explicit and index == 1 else 0.35,
                    "unresolved_fields": ["material_declaration", "hs_code", "profile_cross_section_drawing", "allocated_line_weight"],
                    "falsification_test": "Verify material declaration, HS code, section drawing, wall thickness meaning, and line-item allocated weight.",
                    "warning": "Required section geometry is a reverse calculation, not proof of material. A 0.5 mm value may not be wall thickness.",
                }
            )
        return calculations, scenarios

    @staticmethod
    def _candidates(primary: float | None, supplied: Any, defaults: list[Any]) -> list[float]:
        values: list[float] = []
        for value in ([primary] if primary is not None else []) + (supplied if isinstance(supplied, list) else [supplied]) + list(defaults):
            number = as_number(value)
            if number and number > 0 and number not in values:
                values.append(number)
        return values[:8]

    @staticmethod
    def _calc(calculation_id: str, formula: str, inputs: dict[str, Any], result: float, unit: str) -> dict[str, Any]:
        return {
            "calculation_id": calculation_id,
            "status": "computed",
            "claim_class": "INFERENCE",
            "formula": formula,
            "inputs": inputs,
            "result": round(result, 6) if math.isfinite(result) else None,
            "unit": unit,
            "reproducible": True,
        }


class CrossRecordStore:
    """Persistent, local, append-only-ish collision index using SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=20)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS identifiers (
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                buyer TEXT,
                country TEXT,
                source_hash TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                record_json TEXT NOT NULL,
                PRIMARY KEY(kind, value, entity_key, source_hash)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_lookup ON identifiers(kind, value)")
        self.connection.commit()

    def check_and_store(self, normalized: dict[str, Any], raw_hash: str) -> list[dict[str, Any]]:
        record = normalized.get("record") or {}
        buyer = clean_text(record.get("buyer"))
        country = clean_text(record.get("destination_country") or record.get("country_code"))
        entity_key = key_text(buyer) or "unknown"
        identifiers: list[tuple[str, str]] = []
        for kind, value in (
            ("master_bill", record.get("master_bill")),
            ("house_bill", record.get("house_bill")),
            ("address", record.get("buyer_address")),
        ):
            normalized_value = key_text(value) if kind == "address" else clean_text(value).upper()
            if normalized_value:
                identifiers.append((kind, normalized_value))
        containers = record.get("containers") or []
        if isinstance(containers, str):
            containers = re.split(r"[,;/\s]+", containers)
        identifiers.extend(("container", clean_text(value).upper()) for value in containers if clean_text(value))
        for candidate in iter_contact_candidates(normalized.get("contact_candidates")):
            email = normalize_email(candidate.get("email") or candidate.get("value"))
            if email:
                identifiers.append(("email", email))

        conflicts: list[dict[str, Any]] = []
        payload = json.dumps({"buyer": buyer, "country": country, "record_identity": {k: record.get(k) for k in ("master_bill", "house_bill", "containers")}}, ensure_ascii=False, sort_keys=True)
        today = date.today().isoformat()
        for kind, value in identifiers:
            rows = self.connection.execute(
                "SELECT entity_key,buyer,country,source_hash,record_json FROM identifiers WHERE kind=? AND value=?",
                (kind, value),
            ).fetchall()
            for old_entity, old_buyer, old_country, old_hash, old_record in rows:
                unrelated = old_entity != entity_key and old_hash != raw_hash
                country_conflict = bool(country and old_country and key_text(country) != key_text(old_country))
                if unrelated and (kind in {"master_bill", "house_bill", "container", "email"} or country_conflict):
                    conflicts.append(
                        {
                            "kind": kind,
                            "value": value,
                            "severity": "high" if kind in {"master_bill", "house_bill", "container"} else "medium",
                            "current_entity": buyer or None,
                            "current_country": country or None,
                            "known_original_record": json.loads(old_record),
                            "reason_code": f"persistent_{kind}_collision",
                        }
                    )
            self.connection.execute(
                "INSERT OR IGNORE INTO identifiers(kind,value,entity_key,buyer,country,source_hash,first_seen,record_json) VALUES(?,?,?,?,?,?,?,?)",
                (kind, value, entity_key, buyer, country, raw_hash, today, payload),
            )
        self.connection.commit()
        return conflicts

    def close(self) -> None:
        self.connection.close()


class V3Assembler:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.taxonomy = ProductTaxonomy()
        self.scenarios = ScenarioEngine(rules)

    def assemble(
        self,
        result: dict[str, Any],
        normalized: dict[str, Any],
        raw_input: str,
        *,
        mode: str,
        enrichment: dict[str, Any] | None = None,
        related_records: list[dict[str, Any]] | None = None,
        evidence_bundle: dict[str, Any] | None = None,
        source_images: list[str] | None = None,
        contamination_db: Path | None = None,
        feedback_db: Path | None = None,
    ) -> dict[str, Any]:
        enrichment = enrichment if isinstance(enrichment, dict) else {}
        evidence_bundle = evidence_bundle if isinstance(evidence_bundle, dict) else {}
        related_records = [item for item in (related_records or []) if isinstance(item, dict)]
        source_images = [str(item) for item in (source_images or [])]
        record = normalized.get("record") or {}

        product = self.taxonomy.classify(record, result.get("normalized_shipment", {}).get("product") or {})
        result.setdefault("normalized_shipment", {})["product"] = product
        result["products"] = [product]

        contamination_matches: list[dict[str, Any]] = []
        if contamination_db:
            store = CrossRecordStore(contamination_db)
            try:
                contamination_matches = store.check_and_store(normalized, stable_hash(raw_input))
            finally:
                store.close()
        self._apply_contamination(result, contamination_matches)

        calculations, scenarios = self.scenarios.generate(record, product, result.get("data_quality") or {}, enrichment)
        result["calculations"] = calculations
        result["calculation_scenarios"] = scenarios
        result["route"] = self._route(result, record)
        result["sources"] = self._sources(result, enrichment, evidence_bundle)
        result["research_coverage"], result["manual_checks"] = self._coverage(enrichment, evidence_bundle, source_images, mode)
        result["contact_evidence_ledger"] = self._contact_ledger(result, enrichment, related_records, result["sources"])
        result["contacts"] = self._compatible_contacts(result["contact_evidence_ledger"])
        result["entities"] = self._entities(result, record, enrichment)
        result["supplier_intelligence"] = self._supplier(result, enrichment)
        result["trade_history"], result["trade_history_summary"] = self._trade_history(result, enrichment)
        result["field_audit"] = self._field_audit(result, normalized, enrichment, contamination_matches)
        result["review_ledger"] = self._review_ledger(result, enrichment)
        result["competition_matrix"] = self._competition_matrix(result, enrichment)
        result["evidence_binding_summary"] = self._evidence_binding_summary(result)
        result["hypotheses"] = self._hypotheses(result)
        result["scores"] = self._scores(result, enrichment)
        from strategic_engine import StrategicDecisionEngine, build_decision_layers
        result["strategic_intelligence"], result["learning_ledger"] = StrategicDecisionEngine(feedback_db).build(result, enrichment)
        from outreach_engine import OutreachExecutionEngine
        result["outreach"] = OutreachExecutionEngine().build(result, enrichment)
        result["outreach_status"] = result["outreach"].get("outreach_status")
        result["crm"] = self._crm(result)
        result["next_actions"] = self._actions(result)
        result["unresolved"] = self._unresolved(result)
        result["claim_ledger"] = self._claim_ledger(result)
        result["intelligence_dossier"] = self._intelligence_dossier(result, enrichment, mode)
        result["decision_layers"] = build_decision_layers(result, enrichment)
        result["quality_gate"] = self._quality_gate(result, mode)
        result["research_status"] = result["quality_gate"]["research_status"]
        result["audit_trail"] = self._audit_trail(result)
        result["provenance"] = {
            "schema_version": SCHEMA_VERSION,
            "rules_version": self.rules.get("version"),
            "input_sha256": stable_hash(raw_input),
            "rules_sha256": stable_hash(self.rules),
            "generated_at": result.get("generated_at") or date.today().isoformat(),
            "deterministic_fast_scan": mode.replace("-", "_") == "fast_scan",
        }
        result["schema_version"] = SCHEMA_VERSION
        return result

    @staticmethod
    def _apply_contamination(result: dict[str, Any], conflicts: list[dict[str, Any]]) -> None:
        if not conflicts:
            result["cross_record_contamination"] = {"matches": [], "status": "clear_in_available_index"}
            return
        quality = result.setdefault("data_quality", {})
        quality["possible_contamination"] = True
        quality["scoring_suspended"] = any(item.get("severity") == "high" for item in conflicts)
        warnings = quality.setdefault("warnings", [])
        for conflict in conflicts:
            warnings.append({"code": conflict["reason_code"], "severity": conflict["severity"], "message": f"Persistent index found {conflict['kind']} attached to another entity or country.", "source": "cross_record_store"})
        result["cross_record_contamination"] = {"matches": conflicts, "status": "conflict"}
        if quality["scoring_suspended"]:
            score = result.setdefault("commercial_scoring", {})
            score.update({"status": "suspended", "total_score": None, "observed_score": None, "grade": "UNSCORABLE", "sales_priority": "UNSCORABLE", "provisional": True})

    @staticmethod
    def _route(result: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        route = dict(result.get("normalized_shipment", {}).get("route") or {})
        route.update(
            {
                "country_of_export": record.get("export_country"),
                "foreign_port_of_lading": record.get("port_of_lading"),
                "frob_status": record.get("frob") or "UNKNOWN",
                "on_the_spot_export": record.get("on_the_spot_export") or "UNKNOWN",
                "bonded_zone": record.get("bonded_zone") or "UNKNOWN",
                "trade_regime": record.get("import_type") or record.get("type_of_import"),
                "claim_class": "FACT" if record.get("country_origin_code") or record.get("coo_code") else "INFERENCE",
                "interpretation_warning": "Ports and receipt locations do not establish manufacturing origin.",
            }
        )
        return route

    def _sources(self, result: dict[str, Any], enrichment: dict[str, Any], evidence_bundle: dict[str, Any]) -> list[dict[str, Any]]:
        raw_sources = list_of_dicts(result.get("evidence")) + list_of_dicts(enrichment.get("evidence")) + list_of_dicts(enrichment.get("sources")) + list_of_dicts(evidence_bundle.get("sources"))
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_sources, 1):
            url = clean_text(raw.get("url") or raw.get("source_reference")) or None
            source_type = classify_source(url, raw.get("source_type") or raw.get("type"))
            official_asserted = bool(raw.get("official"))
            host = urlparse(url or "").netloc.casefold()
            if official_asserted and source_type == "unverified_site":
                if any(domain in host for domain in ("instagram.com", "facebook.com", "linkedin.com", "youtube.com")):
                    source_type = "official_social"
                elif host:
                    source_type = "official_domain"
            source_id = clean_text(raw.get("source_id")) or f"src-v3-{index:03d}"
            dedupe = stable_hash((url, source_type, raw.get("source_date"), raw.get("claim")))
            if dedupe in seen:
                continue
            seen.add(dedupe)
            checked_at = raw.get("date_checked") or raw.get("checked_at") or date.today().isoformat()
            source_entry = {
                    "source_id": source_id,
                    "source_type": source_type,
                    "evidence_grade": evidence_grade(source_type, raw.get("evidence_grade")),
                    "source_reference": url or raw.get("source"),
                    "source_date": raw.get("source_date"),
                    "publication_date": raw.get("publication_date") or raw.get("source_date"),
                    "checked_at": checked_at,
                    "officiality_status": "verified" if source_type.startswith("official_") or source_type == "government_registry" else "not_official",
                    "independence_group": urlparse(url or "").netloc.casefold() or clean_text(raw.get("provider") or raw.get("source")) or source_id,
                    "page_kind": raw.get("page_kind"),
                    "claim_ids": raw.get("claim_ids") or [],
                    "quoted_or_visible_text": raw.get("quoted_or_visible_text") or raw.get("raw_text") or raw.get("claim"),
                    "negative_or_conflicting_evidence": raw.get("negative_or_conflicting_evidence") or [],
                    "link_type": link_type(source_type, url, raw.get("page_kind")),
                    "is_search_entry": link_type(source_type, url, raw.get("page_kind")) in {"地图搜索入口", "人工检查入口"},
                }
            source_entry["freshness_status"] = source_freshness(source_entry, target_days=30)
            output.append(source_entry)
        if not output:
            output.append({"source_id": "src-customs-record", "source_type": "customs_or_trade_record", "evidence_grade": "B1", "source_reference": result.get("record_identity", {}).get("data_source"), "source_date": result.get("record_identity", {}).get("record_date"), "publication_date": None, "checked_at": date.today().isoformat(), "officiality_status": "not_independently_verified", "independence_group": "user-supplied-customs-record", "page_kind": None, "claim_ids": [], "quoted_or_visible_text": None, "negative_or_conflicting_evidence": [], "link_type": "贸易数据库", "is_search_entry": False, "freshness_status": "current"})
        return output

    @staticmethod
    def _coverage(enrichment: dict[str, Any], evidence_bundle: dict[str, Any], source_images: list[str], mode: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        supplied = {clean_text(item.get("step")): item for item in list_of_dicts(enrichment.get("research_coverage"))}
        manual: list[dict[str, Any]] = list_of_dicts(evidence_bundle.get("manual_checks"))
        coverage: list[dict[str, Any]] = []
        fast = mode.replace("-", "_") == "fast_scan"
        for step in RESEARCH_STEPS:
            raw = supplied.get(step, {})
            status = clean_text(raw.get("status")) or ("not_applicable_fast_scan" if fast else "not_checked")
            if status in {"blocked", "login_required", "dynamic_unreadable"} and (step.startswith(("instagram", "facebook")) or step == "google_business_profile"):
                manual.append({"check_id": f"manual-{step}", "type": "manual_visual_check_required", "target": raw.get("url"), "instructions": "Inspect bio/About, Contact button, visible email/WhatsApp, and recent post images.", "status": "pending", "reason_code": status})
            target_url = raw.get("url") or raw.get("target_url")
            declared_type = raw.get("source_type") or ("google_business_profile" if step == "google_business_profile" else None)
            coverage.append({"step": step, "checked": status not in {"not_checked", "not_applicable_fast_scan"}, "status": status, "result_summary": raw.get("result_summary") or raw.get("result") or raw.get("note"), "target_url": target_url, "link_type": link_type(classify_source(target_url, declared_type), target_url, raw.get("page_kind")), "source_ids": raw.get("source_ids") or [], "checked_at": raw.get("checked_at"), "note": raw.get("note")})
        observed_images = {clean_text(item.get("path")) for item in list_of_dicts(evidence_bundle.get("image_observations"))}
        for image_path in source_images:
            if clean_text(image_path) not in observed_images:
                manual.append({"check_id": f"manual-image-{stable_hash(image_path)[:10]}", "type": "manual_visual_check_required", "target": image_path, "instructions": "Use visual inspection to extract only visible company, contact, channel, and date evidence; record crop/page coordinates.", "status": "pending", "reason_code": "image_not_yet_observed"})
        return coverage, manual

    def _contact_ledger(self, result: dict[str, Any], enrichment: dict[str, Any], related_records: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raw_contacts = list_of_dicts(enrichment.get("contacts")) + list_of_dicts(result.get("contacts"))
        source_by_id = {item["source_id"]: item for item in sources}
        related_emails: dict[str, set[str]] = {}
        current_entity = key_text(result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name"))
        for related in related_records:
            entity = key_text((related.get("record") or {}).get("buyer"))
            for candidate in iter_contact_candidates(related.get("contact_candidates")):
                email = normalize_email(candidate.get("email") or candidate.get("value"))
                if email:
                    related_emails.setdefault(email, set()).add(entity)
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for index, raw in enumerate(raw_contacts, 1):
            email = normalize_email(raw.get("email") or raw.get("value"))
            phone = normalize_phone(raw.get("phone") or (raw.get("value") if not email else None))
            social = clean_text(raw.get("social")) or None
            value = email or phone or social
            contact_type = "email" if email else "phone" if phone else "social" if social else clean_text(raw.get("contact_type")) or "unknown"
            if not value or (contact_type, value) in seen:
                continue
            seen.add((contact_type, value))
            source_ids = [str(item) for item in (raw.get("source_ids") or []) if item]
            source = source_by_id.get(source_ids[0], {}) if source_ids else {}
            source_type = clean_text(raw.get("source_type") or source.get("source_type")) or "user_supplied"
            grade = evidence_grade(source_type, raw.get("evidence_grade") or source.get("evidence_grade"))
            requested_verification = clean_text(raw.get("verification_status") or raw.get("verification")).casefold()
            if requested_verification in {"verified", "official_company_email"}:
                requested_verification = "official_current"
            elif requested_verification == "associated":
                requested_verification = "unverified"
            source_reference = raw.get("source_reference") or source.get("source_reference")
            evidence_view = {**source, "checked_at": raw.get("last_verified") or source.get("checked_at")}
            freshness = source_freshness(evidence_view, target_days=30)
            official_source = source_type in {"official_domain", "official_social", "official_directory", "government_registry"} and bool(source_reference)
            directory_source = source_type in {"google_business_profile", "local_business_directory", "third_party_directory", "professional_profile"}
            if requested_verification == "official_current" and official_source and freshness == "current":
                verification = "official_current"
            elif requested_verification.startswith("official") and official_source:
                verification = "official_historical"
            elif directory_source and freshness == "current":
                verification = "directory_current"
            elif directory_source:
                verification = "directory_historical"
            elif source_type in {"trade_database", "customs_or_trade_record"}:
                verification = "customs_historical"
            elif requested_verification in {"inferred", "rejected"}:
                verification = requested_verification
            else:
                verification = "unverified"
            role = clean_text(raw.get("role") or raw.get("title") or raw.get("decision_role")) or None
            person = clean_text(raw.get("person_name") or raw.get("name")) or None
            risks: list[str] = []
            contact_entity = key_text(raw.get("company")) or current_entity
            if email and len(related_emails.get(email, set()) - {contact_entity}) > 0:
                risks.append("shared_logistics_or_customs_email")
            if any(token in clean_text(role).casefold() for token in ("hr", "account", "sales", "shipping", "broker", "traffic")):
                risks.append("role_not_verified_as_procurement")
            procurement_status = clean_text(raw.get("procurement_authority_status")).casefold()
            if procurement_status not in {"confirmed", "unconfirmed", "not_applicable", "rejected"}:
                procurement_status = "confirmed" if role and any(token in role.casefold() for token in ("procurement", "purchasing", "buyer", "sourcing")) and verification == "official_current" else "unconfirmed"
            position_status = "current_confirmed" if person and role and verification == "official_current" else "historical_or_unverified" if person else "not_applicable"
            generic_role = not role or any(token in clean_text(role).casefold() for token in ("general", "company", "sales", "inquiry", "enquiry", "office", "customer service"))
            channel_use = "official_company_general" if verification == "official_current" and generic_role else "direct_procurement" if verification == "official_current" and procurement_status == "confirmed" else "historical_or_verification_lead"
            whatsapp_status = "confirmed_by_current_official_source" if raw.get("whatsapp_verified") is True and verification == "official_current" else "click_or_registration_not_verified" if raw.get("whatsapp") or raw.get("whatsapp_url") else "not_claimed"
            recommended_use = "direct_procurement_outreach" if channel_use == "direct_procurement" else "formal_company_outreach" if channel_use == "official_company_general" else "company_switchboard" if phone and verification in {"official_current", "directory_current"} else "verify_before_use"
            if risks:
                recommended_use = "secondary_or_verification_only"
            output.append({"contact_id": f"contact-{index:03d}", "contact_type": contact_type, "value": value, "person_name": person, "role": role, "company": raw.get("company"), "source_type": source_type, "source_reference": source_reference, "source_date": raw.get("source_date") or source.get("source_date"), "discovered_at": raw.get("discovered_at") or date.today().isoformat(), "last_verified": raw.get("last_verified") or source.get("checked_at"), "freshness_status": freshness, "confidence": as_number(raw.get("confidence")) or (0.9 if grade.startswith("A") else 0.7 if grade.startswith("B") else 0.5), "verification_status": verification, "position_status": position_status, "procurement_authority_status": procurement_status, "channel_use": channel_use, "whatsapp_status": whatsapp_status, "recommended_use": recommended_use, "risk_note": risks, "evidence_grade": grade, "source_ids": source_ids, "cross_validation_source_ids": raw.get("cross_validation_source_ids") or [], "negative_or_conflicting_evidence": raw.get("negative_or_conflicting_evidence") or []})
        return output

    @staticmethod
    def _compatible_contacts(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contacts: list[dict[str, Any]] = []
        for item in ledger:
            formal = item.get("verification_status") == "official_current" and not item.get("risk_note")
            procurement = item.get("procurement_authority_status") == "confirmed"
            contacts.append({"name": item.get("person_name"), "title": item.get("role"), "decision_role": "PROCUREMENT" if procurement else None, "verification": "VERIFIED_COMPANY_CHANNEL" if formal else "UNVERIFIED", "email": item.get("value") if item.get("contact_type") == "email" else None, "email_status": "OFFICIAL_COMPANY_EMAIL" if formal and item.get("contact_type") == "email" else "UNVERIFIED_EMAIL", "phone": item.get("value") if item.get("contact_type") == "phone" else None, "social": item.get("value") if item.get("contact_type") == "social" else None, "usable_for_outreach": formal, "procurement_authority_confirmed": procurement, "channel_use": item.get("channel_use"), "evidence_grade": item.get("evidence_grade", "D")[0], "source_ids": item.get("source_ids") or []})
        return contacts

    @staticmethod
    def _entities(result: dict[str, Any], record: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
        entity = enrichment.get("entity") if isinstance(enrichment.get("entity"), dict) else {}
        buyer_raw = clean_text(record.get("buyer"))
        confirmed = result.get("entity_resolution", {}).get("status") == "MATCHED"
        legal_name = result.get("entity_resolution", {}).get("legal_name") if confirmed else None
        aliases = [buyer_raw] if buyer_raw else []
        for value in (entity.get("trade_names") or []) + (entity.get("aliases") or []):
            cleaned = clean_text(value)
            if cleaned and cleaned not in aliases:
                aliases.append(cleaned)
        buyer = {"entity_id": f"ent-{stable_hash((legal_name or buyer_raw, record.get('destination_country')))[:16]}", "legal_name": legal_name, "customs_name": buyer_raw or None, "trade_names": entity.get("trade_names") or [], "aliases": aliases, "related_entities": result.get("entity_resolution", {}).get("possible_affiliates") or [], "relationship_type": "self" if confirmed else "unverified_customs_identity", "relationship_confidence": result.get("entity_resolution", {}).get("confidence", 0), "relationship_evidence": result.get("entity_resolution", {}).get("match_basis") or [], "do_not_merge": not confirmed}
        supplier_name = clean_text(record.get("supplier"))
        source_by_id = {item.get("source_id"): item for item in result.get("sources") or []}
        relationships: list[dict[str, Any]] = []
        for index, raw in enumerate(list_of_dicts(enrichment.get("entity_relationships")), 1):
            source_ids = [str(item) for item in raw.get("source_ids") or [] if item]
            sources = [source_by_id[item] for item in source_ids if item in source_by_id]
            grades = {item.get("evidence_grade") for item in sources}
            groups = independent_source_groups(sources)
            legal_basis = bool("A1" in grades or (raw.get("official_legal_disclosure") and "A2" in grades))
            cross_link = bool(raw.get("official_cross_link")) and any(item.get("officiality_status") == "verified" for item in sources)
            if legal_basis and source_ids:
                status, confidence, merge_allowed = "legally_confirmed", max(0.95, as_number(raw.get("confidence")) or 0), True
            elif cross_link or len(groups) >= 2:
                status, confidence, merge_allowed = "strongly_supported_not_legally_confirmed", min(0.89, as_number(raw.get("confidence")) or 0.82), False
            else:
                status, confidence, merge_allowed = "unverified", min(0.6, as_number(raw.get("confidence")) or 0.45), False
            relationships.append({"relationship_id": raw.get("relationship_id") or f"rel-{index:03d}", "entity_a": raw.get("entity_a"), "entity_b": raw.get("entity_b"), "relationship_type": raw.get("relationship_type") or "possible_affiliate", "relationship_status": status, "confidence": confidence, "relationship_evidence": raw.get("relationship_evidence") or raw.get("evidence") or [], "source_ids": source_ids, "independent_source_count": len(groups), "missing_evidence": raw.get("missing_evidence") or ([] if merge_allowed else ["official legal disclosure, registry relationship, or trademark owner"]), "merge_allowed": merge_allowed, "do_not_merge": not merge_allowed})
        return {"buyer": buyer, "supplier": {"entity_id": f"ent-{stable_hash((supplier_name, 'supplier'))[:16]}" if supplier_name else None, "legal_name": result.get("normalized_shipment", {}).get("supplier", {}).get("legal_name"), "customs_name": supplier_name or None, "aliases": [supplier_name] if supplier_name else [], "do_not_merge": True}, "notify": {"entity_id": None, "legal_name": None, "customs_name": record.get("notify_party"), "aliases": [], "do_not_merge": True}, "relationships": relationships}

    @staticmethod
    def _supplier(result: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
        supplier = enrichment.get("supplier") if isinstance(enrichment.get("supplier"), dict) else {}
        declared = clean_text(supplier.get("classification") or supplier.get("verified_role")).upper()
        allowed = {"VERIFIED_FACTORY", "FACTORY_AFFILIATED_EXPORTER", "SOURCING_INTEGRATOR", "TRADER", "LOGISTICS_EXPORTER"}
        grade = evidence_grade(classify_source(supplier.get("url"), supplier.get("source_type")), supplier.get("evidence_grade"))
        strong = declared in allowed and grade in {"A1", "A2"} and bool(supplier.get("source_ids") or supplier.get("url"))
        candidate = declared if declared in allowed else "UNVERIFIED"
        factory_owned = clean_text(supplier.get("factory_ownership_status")).upper()
        if candidate == "VERIFIED_FACTORY" and factory_owned not in {"CONFIRMED", "OWNED", "LEASED_AND_CONTROLLED"}:
            strong = False
        return {"classification": candidate if strong else "UNVERIFIED", "candidate_classification": candidate, "classification_status": "confirmed" if strong else "candidate_only", "company_claim": supplier.get("company_claim"), "verified_evidence": supplier.get("verified_evidence") or [], "source_ids": supplier.get("source_ids") or [], "legal_entity_relationship": supplier.get("legal_entity_relationship"), "factory_ownership_status": factory_owned if strong else "UNVERIFIED", "buyer_relationship_history": supplier.get("buyer_relationship_history") or [], "replacement_difficulty": supplier.get("replacement_difficulty") or "UNKNOWN", "evidence_grade": grade, "missing_checks": supplier.get("missing_checks") or ["official registration and establishment date", "registered address and workforce indicators", "platform-to-legal-entity match", "factory ownership or controlled-production evidence", "certificate holder and packaging/factory-image provenance"]}

    @staticmethod
    def _trade_history(result: dict[str, Any], enrichment: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = list_of_dicts(enrichment.get("trade_history"))
        output: list[dict[str, Any]] = []
        seen: dict[str, str] = {}
        for index, row in enumerate(rows, 1):
            shipment_id = clean_text(row.get("shipment_id") or row.get("master_bill") or row.get("house_bill") or row.get("declaration_number")) or None
            item_id = clean_text(row.get("item_number")) or None
            key = stable_hash((row.get("date"), shipment_id, item_id, key_text(row.get("buyer")), key_text(row.get("supplier")), clean_text(row.get("product_raw") or row.get("product")), row.get("quantity"), row.get("uom"), row.get("weight_kg"), row.get("provider")))
            duplicate_of = seen.get(key)
            record_id = row.get("record_id") or f"trade-{index:04d}"
            if duplicate_of is None:
                seen[key] = record_id
            source_ids = [str(item) for item in row.get("source_ids") or [] if item]
            data_level = clean_text(row.get("data_level")).casefold()
            if data_level not in {"shipment", "declaration", "item", "container", "provider_aggregate", "unknown"}:
                data_level = "unknown"
            status = "duplicate" if duplicate_of else "auditable" if row.get("date") and (shipment_id or row.get("declaration_number")) and row.get("product_raw") and source_ids else "incomplete_row"
            output.append({"record_id": record_id, "date": row.get("date"), "master_bill": row.get("master_bill"), "house_bill": row.get("house_bill"), "declaration_number": row.get("declaration_number"), "item_number": row.get("item_number"), "supplier": row.get("supplier"), "buyer": row.get("buyer"), "product_raw": row.get("product_raw") or row.get("product"), "hs_code": row.get("hs_code"), "quantity": row.get("quantity"), "uom": row.get("uom"), "weight_kg": row.get("weight_kg"), "data_level": data_level, "provider": row.get("provider"), "provider_count_unit": row.get("provider_count_unit") or "unknown", "source_ids": source_ids, "duplicate_of": duplicate_of, "status": status, "claim_class": "FACT" if status == "auditable" else "UNKNOWN", "notes": row.get("notes")})
        auditable = [row for row in output if row["status"] == "auditable"]
        dated = sorted({clean_text(row.get("date")) for row in auditable if clean_text(row.get("date"))})
        product_rows = [row for row in auditable if clean_text(row.get("product_raw"))]
        repeat_status = "repeat_purchase_observed" if len(product_rows) >= 2 and len(dated) >= 2 else "single_purchase_observed" if product_rows else "not_verified"
        summary = {"raw_row_count": len(rows), "deduplicated_row_count": len([row for row in output if not row.get("duplicate_of")]), "auditable_row_count": len(auditable), "duplicate_count": len([row for row in output if row.get("duplicate_of")]), "visible_date_range": [dated[0], dated[-1]] if dated else [None, None], "repeat_purchase_status": repeat_status, "provider_counts_comparable": False, "warning": "Provider shipment counts may represent bills, declarations, item rows, containers, or duplicates and must not be added across providers."}
        return output, summary

    @staticmethod
    def _review_ledger(result: dict[str, Any], enrichment: dict[str, Any]) -> list[dict[str, Any]]:
        supplied = enrichment.get("assistant_reviews")
        if isinstance(supplied, dict):
            reviews = {clean_text(key): value for key, value in supplied.items() if isinstance(value, dict)}
        else:
            reviews = {clean_text(item.get("field")): item for item in list_of_dicts(supplied)}
        ledger: list[dict[str, Any]] = []
        for item in result.get("field_audit") or []:
            field = clean_text(item.get("field"))
            review = reviews.get(field, {})
            decision = clean_text(review.get("decision")).casefold()
            has_review = bool(review)
            if decision == "rejected":
                final_value, final_status = None, "rejected"
            elif decision in {"corrected", "accepted"}:
                final_value = review.get("final_value", item.get("normalized_value"))
                final_status = review.get("final_status") or item.get("status")
            else:
                final_value, final_status = item.get("normalized_value"), item.get("status")
            changed = final_value != item.get("normalized_value") or final_status != item.get("status")
            ledger.append({"field": field, "plugin_output": {"value": item.get("normalized_value"), "status": item.get("status"), "confidence": item.get("confidence"), "source_ids": item.get("evidence") or []}, "assistant_review": review.get("review") or review.get("assistant_review") if has_review else None, "review_decision": decision or "not_reviewed", "final_decision": {"value": final_value, "status": final_status, "crm_eligible": bool(item.get("crm_eligible")) and final_status not in {"rejected", "unresolved", "contradictory", "contaminated"}}, "changed": changed, "change_reason": review.get("change_reason") if has_review else None, "reviewer_source_ids": review.get("source_ids") or [], "review_status": "reviewed" if has_review else "not_reviewed"})
        return ledger

    @staticmethod
    def _competition_matrix(result: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
        competition = enrichment.get("competition") if isinstance(enrichment.get("competition"), dict) else {}
        raw_rows = list_of_dicts(competition.get("rows"))
        if not raw_rows:
            raw_rows = [{"capability": capability} for capability in ("core_board_specification", "decorative_finish_and_color", "matching_trim_accessories", "mixed_sku_loading", "private_label_packaging", "container_delivery_execution")]
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(raw_rows, 1):
            incumbent = clean_text(row.get("incumbent_status") or row.get("competitor_status")).upper() or "UNKNOWN"
            own = clean_text(row.get("our_status") or row.get("company_status")).upper() or "UNKNOWN"
            source_ids = [str(item) for item in row.get("source_ids") or [] if item]
            supported = bool(source_ids)
            gap = row.get("gap") or ("UNKNOWN" if "UNKNOWN" in {incumbent, own} else "NONE" if incumbent == own else "REQUIRES_VALIDATION")
            rows.append({"row_id": f"cap-{index:03d}", "capability": row.get("capability"), "incumbent_status": incumbent, "our_status": own, "gap": gap, "source_ids": source_ids, "evidence_status": "supported" if supported else "unverified", "claim_class": "FACT" if supported and "UNKNOWN" not in {incumbent, own} else "UNKNOWN", "acceptance_criteria": row.get("acceptance_criteria") or "Provide dated evidence, specification/sample requirement, responsible owner, and pass/fail threshold.", "recommended_action": row.get("recommended_action") or "Collect comparable evidence before assigning a score."})
        scoreable = [row for row in rows if row["evidence_status"] == "supported" and row["claim_class"] == "FACT"]
        return {"status": "scoreable" if len(scoreable) == len(rows) and rows else "incomplete_evidence", "rows": rows, "score": competition.get("score") if len(scoreable) == len(rows) and rows else None, "score_status": "accepted" if competition.get("score") is not None and len(scoreable) == len(rows) else "withheld", "warning": "A numeric competitive-fit score is withheld until every scored capability has evidence and acceptance criteria."}

    @staticmethod
    def _evidence_binding_summary(result: dict[str, Any]) -> dict[str, Any]:
        fields = result.get("field_audit") or []
        external = [item for item in fields if item.get("scope") == "external_company_field"]
        missing = [item.get("field") for item in external if not item.get("evidence")]
        weak_current = [item.get("field") for item in external if item.get("rejection_reason") == "current_validity_not_recently_verified"]
        return {"external_field_count": len(external), "source_bound_count": len(external) - len(missing), "missing_source_fields": missing, "current_status_without_recent_verification": weak_current, "all_external_fields_source_bound": not missing}

    @staticmethod
    def _field_audit(result: dict[str, Any], normalized: dict[str, Any], enrichment: dict[str, Any], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        record = normalized.get("record") or {}
        confirmations = enrichment.get("field_confirmations") if isinstance(enrichment.get("field_confirmations"), dict) else {}
        ambiguous = set(result.get("data_quality", {}).get("field_scope", {}).get("ambiguous") or [])
        warning_codes = {item.get("code") for item in result.get("data_quality", {}).get("warnings") or [] if isinstance(item, dict)}
        contaminated_fields = {"master_bill" if item.get("kind") == "master_bill" else "house_bill" if item.get("kind") == "house_bill" else "containers" if item.get("kind") == "container" else "buyer_address" if item.get("kind") == "address" else "contact_candidates" for item in conflicts}
        contradiction_map = {
            "port_of_lading": {"same_loading_discharge_port", "route_country_conflict", "primary_secondary_port_conflict"},
            "port_of_discharge": {"same_loading_discharge_port", "route_country_conflict", "primary_secondary_port_conflict"},
            "origin": {"primary_secondary_origin_conflict"},
            "gross_weight_kg": {"gross_weight_below_net_weight"},
            "containers": {"mode_container_conflict", "declared_container_count_conflict"},
            "teu": {"declared_container_count_conflict"},
            "product": {"product_structure_conflict"},
            "original_amount": {"financial_reconciliation_mismatch"},
        }
        fields = ("data_source", "arrival_date", "master_bill", "house_bill", "supplier", "supplier_address", "buyer", "buyer_address", "notify_party", "product", "hs_code", "quantity_count", "quantity_unit", "package_count", "package_type", "weight_kg", "gross_weight_kg", "measurement_m3", "teu", "containers", "origin", "export_country", "place_of_receipt", "port_of_lading", "port_of_discharge", "vessel", "carrier", "transport_mode", "unit_price", "original_amount", "currency")
        output: list[dict[str, Any]] = []
        for field in fields:
            value = record.get(field)
            confirmation = confirmations.get(field) if isinstance(confirmations.get(field), dict) else {}
            if field in contaminated_fields:
                status, confidence, rejection = "contaminated", 0.05, "cross_record_collision"
            elif warning_codes & contradiction_map.get(field, set()):
                status, confidence, rejection = "contradictory", 0.2, "conflicting_record_signals"
            elif field in ambiguous:
                status, confidence, rejection = "unresolved", 0.35, "shipment_or_line_scope_unresolved"
            elif confirmation.get("evidence_grade") in {"A1", "A2"}:
                status, confidence, rejection = "confirmed", min(0.99, as_number(confirmation.get("confidence")) or 0.95), None
            elif value in (None, "", []):
                status, confidence, rejection = "unresolved", 0.0, "not_present_in_supplied_record"
            else:
                status, confidence, rejection = "plausible", 0.72, None
            evidence_refs = confirmation.get("source_ids") or (["src-customs-record"] if value not in (None, "", []) else [])
            output.append({"field": field, "raw_value": value, "normalized_value": value, "confidence": confidence, "status": status, "evidence": evidence_refs, "rejection_reason": rejection, "scope": "ambiguous" if field in ambiguous else "line_item" if field in {"product", "hs_code", "quantity_count", "quantity_unit", "unit_price", "original_amount"} else "shipment_or_party", "crm_eligible": status in {"confirmed", "plausible"} and field not in ambiguous})
        source_by_id = {item.get("source_id"): item for item in result.get("sources") or []}
        for index, claim in enumerate(list_of_dicts(enrichment.get("field_claims")), 1):
            field = clean_text(claim.get("field") or claim.get("field_path")) or f"external_claim_{index}"
            source_ids = [str(item) for item in claim.get("source_ids") or [] if item]
            sources = [source_by_id[item] for item in source_ids if item in source_by_id]
            grades = {item.get("evidence_grade") for item in sources}
            groups = independent_source_groups(sources)
            freshness = {item.get("freshness_status") for item in sources}
            legal_identifier = any(token in field.casefold() for token in ("registration", "sec_number", "tax_id", "legal_status", "lawsuit", "court"))
            negative = claim.get("negative_or_conflicting_evidence") or [item for source in sources for item in source.get("negative_or_conflicting_evidence") or []]
            if negative:
                status, confidence, rejection = "contradictory", min(0.45, as_number(claim.get("confidence")) or 0.35), "negative_or_conflicting_evidence_present"
            elif not sources:
                status, confidence, rejection = "unresolved", 0.0, "no_source_bound_to_external_field"
            elif legal_identifier and "A1" not in grades:
                status, confidence, rejection = "plausible", min(0.79, as_number(claim.get("confidence")) or 0.7), "official_registry_confirmation_missing"
            elif claim.get("current_status_claim") and "current" not in freshness:
                status, confidence, rejection = "plausible", min(0.69, as_number(claim.get("confidence")) or 0.6), "current_validity_not_recently_verified"
            elif grades & {"A1", "A2"}:
                status, confidence, rejection = "confirmed", min(0.99, as_number(claim.get("confidence")) or 0.93), None
            else:
                status, confidence, rejection = "plausible", min(0.82, as_number(claim.get("confidence")) or 0.68), None
            output.append({"field": field, "raw_value": claim.get("raw_value"), "normalized_value": claim.get("normalized_value", claim.get("raw_value")), "confidence": confidence, "status": status, "evidence": source_ids, "evidence_details": [{key: source.get(key) for key in ("source_id", "source_type", "evidence_grade", "source_reference", "publication_date", "checked_at", "freshness_status", "link_type", "quoted_or_visible_text")} for source in sources], "source_type": sources[0].get("source_type") if len(sources) == 1 else "multiple" if sources else None, "source_url": sources[0].get("source_reference") if len(sources) == 1 else None, "source_date": sources[0].get("source_date") if len(sources) == 1 else None, "last_verified": max((clean_text(item.get("checked_at")) for item in sources), default=None), "official_confirmation": bool("A1" in grades or (not legal_identifier and "A2" in grades)), "independent_source_count": len(groups), "negative_or_conflicting_evidence": negative, "rejection_reason": rejection, "scope": claim.get("scope") or "external_company_field", "crm_eligible": status == "confirmed" or (status == "plausible" and not legal_identifier and not claim.get("current_status_claim"))})
        for item in output:
            if "evidence_details" in item:
                continue
            bound = [source_by_id[source_id] for source_id in item.get("evidence") or [] if source_id in source_by_id]
            item["evidence_details"] = [{key: source.get(key) for key in ("source_id", "source_type", "evidence_grade", "source_reference", "publication_date", "checked_at", "freshness_status", "link_type", "quoted_or_visible_text")} for source in bound]
            item["official_confirmation"] = any(source.get("evidence_grade") in {"A1", "A2"} for source in bound)
            item["independent_source_count"] = len(independent_source_groups(bound))
            item["negative_or_conflicting_evidence"] = []
        return output

    @staticmethod
    def _hypotheses(result: dict[str, Any]) -> list[dict[str, Any]]:
        hypotheses = []
        for scenario in result.get("calculation_scenarios") or []:
            statement = f"Possible {scenario.get('material')} material scenario" if scenario.get("material") else f"Possible specification scenario {scenario.get('scenario_id')}"
            hypotheses.append({"hypothesis_id": f"hyp-{scenario.get('scenario_id')}", "statement": statement, "claim_class": "HYPOTHESIS", "confidence": scenario.get("confidence"), "evidence_refs": ["src-customs-record"], "assumptions": scenario.get("inputs"), "falsification_test": scenario.get("falsification_test") or "Verify packing list, allocated line weight, density, thickness, and sheets per package."})
        return hypotheses

    @staticmethod
    def _scores(result: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
        commercial = result.get("commercial_scoring") or {}
        entity_matched = result.get("entity_resolution", {}).get("status") == "MATCHED"
        exact = result.get("normalized_shipment", {}).get("product", {}).get("match_level") == "EXACT"
        official_contacts = [item for item in result.get("contact_evidence_ledger") or [] if item.get("verification_status") == "official_current" and not item.get("risk_note")]
        trade_rows = [row for row in result.get("trade_history") or [] if row.get("status") == "auditable"]
        enterprise_grade = "A" if entity_matched else "B" if result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name") else "D"
        demand_grade = commercial.get("grade", "UNSCORABLE") if exact else "C" if result.get("normalized_shipment", {}).get("product", {}).get("match_level") == "RELATED" else "D"
        outreach_grade = "A" if any(item.get("procurement_authority_status") == "confirmed" for item in official_contacts) else "B" if official_contacts else "C"
        if result.get("data_quality", {}).get("scoring_suspended"):
            enterprise_grade = demand_grade = outreach_grade = "UNSCORABLE"
        stage = "S0"
        stage_modifier = None
        if result.get("normalized_shipment", {}).get("buyer", {}).get("raw_name") and exact:
            stage = "S1"
        if entity_matched and (official_contacts or len(trade_rows) >= 2):
            stage = "S2"
        engagement = enrichment.get("engagement") if isinstance(enrichment.get("engagement"), dict) else {}
        if any(engagement.get(key) for key in ("contacted", "quoted", "sample_sent", "project_active")):
            stage = "S3"
        elif stage == "S2" and official_contacts and len(trade_rows) >= 2:
            stage_modifier = "advanced"
        calibrated = enrichment.get("calibrated_conversion_model") if isinstance(enrichment.get("calibrated_conversion_model"), dict) else {}
        conversion = calibrated.get("point_estimate") if calibrated.get("validation_status") == "validated" and calibrated.get("model_version") and calibrated.get("calibration_dataset") else None
        conversion_range = calibrated.get("range") if conversion is not None else [None, None]
        return {"enterprise_intelligence_grade": enterprise_grade, "product_demand_grade": demand_grade, "direct_outreach_grade": outreach_grade, "conversion_probability": {"point_estimate": conversion, "range": conversion_range, "status": "calibrated_model" if conversion is not None else "withheld_no_calibrated_model", "model_version": calibrated.get("model_version") if conversion is not None else None, "warning": "Do not convert a rule score into a sales probability. A probability is published only from a documented, validated and calibrated model."}, "supplier_lock_in": "UNKNOWN" if not trade_rows else "HIGH" if len({row.get('supplier') for row in trade_rows if row.get('supplier')}) == 1 and len(trade_rows) >= 3 else "MEDIUM", "contact_completeness": round(min(100, len(official_contacts) * 35 + (25 if any(item.get('role') for item in official_contacts) else 0))), "data_quality": result.get("data_quality", {}).get("score"), "product_fit": result.get("normalized_shipment", {}).get("product", {}).get("match_level"), "stage": stage, "stage_modifier": stage_modifier, "upgrade_conditions": ["Confirm legal entity with A1/A2 evidence", "Confirm repeat product-specific purchasing", "Verify procurement decision-maker and current channel"], "downgrade_conditions": ["Persistent bill/container contamination", "Product reclassified as non-target", "Buyer shown to be logistics-only or IOR"]}

    @staticmethod
    def _crm(result: dict[str, Any]) -> dict[str, Any]:
        audit = {item["field"]: item for item in result.get("field_audit") or []}
        reviews = {item.get("field"): item for item in result.get("review_ledger") or []}
        def accepted(field: str) -> Any:
            item = audit.get(field, {})
            review = reviews.get(field, {}).get("final_decision") or {}
            if review:
                return review.get("value") if review.get("crm_eligible") else None
            return item.get("normalized_value") if item.get("crm_eligible") else None
        official_channels = [item["value"] for item in result.get("contact_evidence_ledger") or [] if item.get("verification_status") == "official_current" and not item.get("risk_note")]
        blocked = [{"field": item["field"], "reason": item.get("rejection_reason") or item.get("status")} for item in result.get("field_audit") or [] if accepted(item["field"]) is None]
        country = result.get("normalized_shipment", {}).get("buyer", {}).get("country")
        procurement_contacts = [item["value"] for item in result.get("contact_evidence_ledger") or [] if item.get("verification_status") == "official_current" and item.get("procurement_authority_status") == "confirmed" and not item.get("risk_note")]
        return {"crm_status": "ready_with_limits" if accepted("buyer") else "blocked", "account_name": accepted("buyer"), "legal_name": accepted("legal_name") or result.get("entities", {}).get("buyer", {}).get("legal_name"), "country": country, "address": accepted("buyer_address"), "buyer_role": result.get("buyer_intelligence", {}).get("buyer_role"), "product_category": result.get("normalized_shipment", {}).get("product", {}).get("normalized_category"), "product_fit": result.get("normalized_shipment", {}).get("product", {}).get("match_level"), "sales_priority": result.get("commercial_scoring", {}).get("sales_priority"), "enterprise_grade": result.get("scores", {}).get("enterprise_intelligence_grade"), "demand_grade": result.get("scores", {}).get("product_demand_grade"), "outreach_grade": result.get("scores", {}).get("direct_outreach_grade"), "stage": result.get("scores", {}).get("stage"), "official_channels": official_channels, "verified_procurement_contacts": procurement_contacts, "next_action": (result.get("recommended_actions") or [{}])[0].get("action"), "risk_flags": [item.get("code") for item in result.get("data_quality", {}).get("warnings") or [] if isinstance(item, dict)], "blocked_fields": blocked, "export_policy": "Only final reviewed/eligible, non-ambiguous, non-contaminated fields and explicitly verified current channels are exportable."}

    @staticmethod
    def _actions(result: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        strategic_route = result.get("strategic_intelligence", {}).get("development_route") or {}
        for step in strategic_route.get("next_steps") or []:
            actions.append({"priority": len(actions) + 1, "action": step, "reason_code": strategic_route.get("route_type") or "strategic_route", "claim_class": "RECOMMENDATION", "acceptance_criteria": strategic_route.get("first_objective") or "Record source-linked evidence and an explicit assistant review decision."})
        for item in result.get("recommended_actions") or []:
            if isinstance(item, dict):
                actions.append({**item, "claim_class": "RECOMMENDATION", "acceptance_criteria": item.get("acceptance_criteria") or "Capture a dated source and update the affected claim/field status."})
        for check in result.get("manual_checks") or []:
            actions.append({"priority": len(actions) + 1, "action": check.get("instructions"), "reason_code": check.get("reason_code"), "claim_class": "RECOMMENDATION", "acceptance_criteria": "Record visible evidence, source image/page, crop or coordinates, and verification date."})
        return actions[:12]

    @staticmethod
    def _unresolved(result: dict[str, Any]) -> list[dict[str, Any]]:
        unresolved = []
        for item in result.get("field_audit") or []:
            if item.get("status") in {"unresolved", "contaminated", "contradictory"}:
                unresolved.append({"field": item.get("field"), "status": item.get("status"), "reason_code": item.get("rejection_reason"), "verification_method": "Obtain original declaration/packing list or an authoritative current source.", "claim_class": "UNKNOWN"})
        return unresolved

    @staticmethod
    def _quality_gate(result: dict[str, Any], mode: str) -> dict[str, Any]:
        coverage = {item.get("step"): item.get("status") for item in result.get("research_coverage") or []}
        manual_social = any(item.get("type") == "manual_visual_check_required" and any(token in clean_text(item.get("check_id")) for token in ("instagram", "facebook", "google_business")) for item in result.get("manual_checks") or [])
        contacts_have_sources = all((item.get("source_reference") or item.get("source_ids")) and item.get("recommended_use") for item in result.get("contact_evidence_ledger") or [])
        no_unsupported_procurement = all(item.get("procurement_authority_status") != "confirmed" or (item.get("position_status") == "current_confirmed" and item.get("verification_status") == "official_current") for item in result.get("contact_evidence_ledger") or [])
        current_contacts_strict = all(item.get("verification_status") != "official_current" or (item.get("source_type") in {"official_domain", "official_social", "official_directory", "government_registry"} and item.get("freshness_status") == "current") for item in result.get("contact_evidence_ledger") or [])
        entity_merges_safe = all(not item.get("merge_allowed") or item.get("relationship_status") == "legally_confirmed" for item in result.get("entities", {}).get("relationships") or [])
        trade_summary = result.get("trade_history_summary") or {}
        trade_claims_auditable = trade_summary.get("repeat_purchase_status") not in {"repeat_purchase_observed", "single_purchase_observed"} or trade_summary.get("auditable_row_count", 0) > 0
        coverage_results_recorded = all(item.get("status") in {"not_checked", "not_applicable_fast_scan"} or item.get("result_summary") or item.get("source_ids") for item in result.get("research_coverage") or [])
        all_applicable_coverage_receipted = all(
            item.get("status") not in {None, "not_checked", "not_applicable_fast_scan"}
            and bool(item.get("result_summary") or item.get("source_ids"))
            for item in result.get("research_coverage") or []
        )
        unified_closure = result.get("unified_runtime_closure") or {}
        unified_runtime_closed = (
            unified_closure.get("closed") is True
            and unified_closure.get("status") in {"COMPLETE_POSITIVE", "COMPLETE_NEGATIVE_ENTITLED"}
            and bool(unified_closure.get("closure_id"))
        )
        review_changes_explained = all(not item.get("changed") or item.get("change_reason") for item in result.get("review_ledger") or [])
        strategic = result.get("strategic_intelligence") or {}
        relationship = strategic.get("relationship_resolution") or {}
        legal_relationship_safe = relationship.get("legal_relationship") == "confirmed" or not relationship.get("entity_merge_allowed")
        categorical_values = strategic.get("commercial_value_portfolio", {}).get("numeric_score") is None
        related_price_safe = not strategic.get("related_party_pricing", {}).get("related_party_pricing_risk") or not strategic.get("related_party_pricing", {}).get("market_price_benchmark_eligible")
        learning = result.get("learning_ledger") or {}
        learning_bounded = learning.get("automatic_rule_promotion") is False and learning.get("automatic_code_modification") is False and learning.get("online_model_weight_update") is False
        final_crm = result.get("decision_layers", {}).get("final_crm") or {}
        crm_review_gated = not final_crm.get("export_allowed") or bool(final_crm.get("record"))
        outreach_completion = result.get("outreach", {}).get("completion") or {}
        outreach_completion_forced = outreach_completion.get("completion_contract_passed") is True and outreach_completion.get("terminal_state") in {"SENDABLE_DRAFT", "DRAFT_BLOCKED", "NO_OUTREACH_RECOMMENDED"} and outreach_completion.get("report_only_output_forbidden") is True
        email_routing = result.get("outreach", {}).get("email_routing") or {}
        email_route_complete = email_routing.get("omission_check_passed") is True and email_routing.get("discovered_email_count", 0) == email_routing.get("accounted_email_count", 0)
        sendable_terminal = outreach_completion.get("terminal_state") == "SENDABLE_DRAFT"
        sendable_mailto_visible = not sendable_terminal or bool((outreach_completion.get("action") or {}).get("url"))
        human_style_passed = not sendable_terminal or bool((result.get("outreach", {}).get("email", {}).get("human_style") or {}).get("passed"))
        intelligence_value_ready = bool(((result.get("intelligence_dossier") or {}).get("value_gate") or {}).get("passed"))
        manual_queue_resolved = all(item.get("status") not in {None, "pending"} for item in result.get("manual_checks") or [])
        checks = [
            ("official_homepage_checked", coverage.get("official_homepage") not in {None, "not_checked"}),
            ("official_contact_checked", coverage.get("official_contact_page") not in {None, "not_checked"}),
            ("official_footer_checked", coverage.get("official_footer") not in {None, "not_checked"}),
            ("social_checked_or_manual_queued", any(coverage.get(step) not in {None, "not_checked", "not_applicable_fast_scan"} for step in ("instagram_bio", "facebook_about", "linkedin_company")) or manual_social),
            ("google_business_checked_or_manual_queued", coverage.get("google_business_profile") not in {None, "not_checked", "not_applicable_fast_scan"} or manual_social),
            ("checked_channels_have_result_or_sources", coverage_results_recorded),
            ("all_applicable_source_families_have_execution_receipts", all_applicable_coverage_receipted),
            ("unified_runtime_issued_closure", unified_runtime_closed),
            ("contacts_have_sources_and_use", contacts_have_sources),
            ("no_unsupported_procurement_person", no_unsupported_procurement),
            ("official_current_contacts_are_recent_official", current_contacts_strict),
            ("entity_merges_have_legal_basis", entity_merges_safe),
            ("commercial_and_legal_relationships_separated", legal_relationship_safe),
            ("commercial_value_numeric_score_withheld", categorical_values),
            ("related_party_price_not_market_benchmark", related_price_safe),
            ("controlled_learning_cannot_self_modify", learning_bounded),
            ("final_crm_requires_reviewed_record", crm_review_gated),
            ("outreach_has_mandatory_terminal_state", outreach_completion_forced),
            ("every_discovered_email_has_route", email_route_complete),
            ("sendable_draft_has_visible_mailto", sendable_mailto_visible),
            ("sendable_first_email_passes_human_style", human_style_passed),
            ("intelligence_dossier_has_substantive_value", intelligence_value_ready),
            ("external_fields_are_source_bound", (result.get("evidence_binding_summary") or {}).get("all_external_fields_source_bound", True)),
            ("trade_continuity_is_row_auditable", trade_claims_auditable),
            ("review_changes_have_reason", review_changes_explained),
            ("manual_visual_queue_resolved", manual_queue_resolved),
            ("hypotheses_labeled", all(item.get("claim_class") == "HYPOTHESIS" for item in result.get("hypotheses") or [])),
            ("line_and_declaration_scope_separated", bool(result.get("data_quality", {}).get("field_scope"))),
            ("route_conflicts_explained", all(item.get("message") for item in result.get("data_quality", {}).get("warnings") or [] if isinstance(item, dict))),
            ("calculations_reproducible_or_blocked", all(item.get("reproducible") or item.get("status") == "blocked" for item in result.get("calculations") or [])),
            ("crm_excludes_contaminated_fields", all(not item.get("crm_eligible") for item in result.get("field_audit") or [] if item.get("status") == "contaminated")),
            ("competitive_score_withheld_without_evidence", result.get("competition_matrix", {}).get("score_status") != "accepted" or result.get("competition_matrix", {}).get("status") == "scoreable"),
            ("has_executable_next_action", bool(result.get("next_actions"))),
        ]
        fast = mode.replace("-", "_") == "fast_scan"
        passed = all(value for _, value in checks)
        research_status = "fast_scan_complete" if fast else "research_complete" if passed else "incomplete_research"
        return {"research_status": research_status, "passed": passed if not fast else None, "checks": [{"gate": name, "passed": value} for name, value in checks], "failed_gates": [name for name, value in checks if not value], "note": "Operational status and research completeness are intentionally separate."}

    @staticmethod
    def _claim_ledger(result: dict[str, Any]) -> list[dict[str, Any]]:
        ledger: list[dict[str, Any]] = []
        for collection, claim_class in ((result.get("facts"), "FACT"), (result.get("inferences"), "INFERENCE"), (result.get("hypotheses"), "HYPOTHESIS"), (result.get("next_actions"), "RECOMMENDATION"), (result.get("unresolved"), "UNKNOWN")):
            for index, item in enumerate(collection or [], 1):
                if not isinstance(item, dict):
                    continue
                statement = item.get("claim") or item.get("statement") or item.get("action") or f"Unresolved field: {item.get('field')}"
                reason_codes = item.get("reason_codes") or ([item.get("reason_code")] if item.get("reason_code") else [])
                ledger.append({"claim_id": item.get("claim_id") or item.get("hypothesis_id") or f"{claim_class.lower()}-{index:03d}", "claim_class": claim_class, "statement": statement, "confidence": item.get("confidence"), "evidence_grade": item.get("evidence_grade") or ("D" if claim_class != "FACT" else "B1"), "source_ids": item.get("source_ids") or item.get("evidence_refs") or [], "reason_codes": reason_codes, "acceptance_criteria": item.get("acceptance_criteria") or item.get("verification_method")})
        return ledger

    @staticmethod
    def _intelligence_dossier(result: dict[str, Any], enrichment: dict[str, Any], mode: str) -> dict[str, Any]:
        """Build the human-analysis layer independently from outreach eligibility."""
        allowed_classes = {"FACT", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION", "UNKNOWN"}
        findings: list[dict[str, Any]] = []

        for index, item in enumerate(list_of_dicts(enrichment.get("intelligence_findings")), 1):
            statement = clean_text(item.get("statement") or item.get("finding") or item.get("claim"))
            if not statement:
                continue
            classification = clean_text(item.get("classification") or item.get("claim_class")).upper() or "INFERENCE"
            if classification not in allowed_classes:
                classification = "INFERENCE"
            findings.append(
                {
                    "finding_id": clean_text(item.get("finding_id")) or f"finding-{index:03d}",
                    "classification": classification,
                    "statement": statement,
                    "reasoning": clean_text(item.get("reasoning")) or None,
                    "business_impact": clean_text(item.get("business_impact")) or None,
                    "counter_explanation": clean_text(item.get("counter_explanation")) or None,
                    "source_ids": item.get("source_ids") or [],
                    "verification_method": clean_text(item.get("verification_method")) or None,
                }
            )

        contamination = result.get("cross_record_contamination") or {}
        for item in list_of_dicts(contamination.get("matches")):
            findings.append(
                {
                    "finding_id": f"contamination-{len(findings) + 1:03d}",
                    "classification": "FACT",
                    "statement": f"字段 {clean_text(item.get('kind')) or '未知'}={clean_text(item.get('value')) or '未显示'} 与其他实体或国家记录发生冲突，不能进入CRM。",
                    "reasoning": clean_text(item.get("reason_code")) or None,
                    "business_impact": "暂停使用受污染字段进行规格、金额、路线或客户评级判断。",
                    "counter_explanation": None,
                    "source_ids": [],
                    "verification_method": "核对原始提单、报关商品行和对应集装箱清单。",
                }
            )

        product = (result.get("normalized_shipment") or {}).get("product") or {}
        if not any(item.get("finding_id") == "product-classification" for item in findings):
            findings.append(
                {
                    "finding_id": "product-classification",
                    "classification": "INFERENCE",
                    "statement": f"产品暂分类为 {clean_text(product.get('normalized_category')) or 'UNCLASSIFIED'}，匹配等级为 {clean_text(product.get('match_level')) or 'UNKNOWN'}。",
                    "reasoning": "；".join(product.get("reason_codes") or []) or "原始描述不足。",
                    "business_impact": "只有产品结构和规格与兴怀能力相符时才进入正式开发。",
                    "counter_explanation": "海关品名可能描述成品、配件、非发泡板或其他PVC制品。",
                    "source_ids": ["src-customs-record"],
                    "verification_method": "取得Packing List、产品照片、尺寸、厚度、密度和结构说明。",
                }
            )

        trade_summary = result.get("trade_history_summary") or {}
        repeat_status = clean_text(trade_summary.get("repeat_purchase_status")) or "not_established"
        findings.append(
            {
                "finding_id": "trade-continuity-boundary",
                "classification": "FACT" if repeat_status == "repeat_purchase_observed" else "UNKNOWN",
                "statement": "已存在逐票、去重的相关产品重复采购证据。" if repeat_status == "repeat_purchase_observed" else "当前资料不能证明持续采购、唯一供应商或稳定月度需求。",
                "reasoning": f"repeat_purchase_status={repeat_status}; auditable_rows={trade_summary.get('auditable_row_count', 0)}",
                "business_impact": "禁止仅凭一票记录评为A级或声称客户存在单一供应来源风险。",
                "counter_explanation": "同一平台可能按提单、商品行或重复记录统计。",
                "source_ids": [],
                "verification_method": "列出至少三条带日期、产品原文、数量/重量、供应商、数据层级和去重状态的记录。",
            }
        )

        buyer_intelligence = result.get("buyer_intelligence") or {}
        buyer_role_scenarios = list_of_dicts(enrichment.get("buyer_role_scenarios"))
        if not buyer_role_scenarios:
            primary = clean_text(buyer_intelligence.get("buyer_role")) or "UNKNOWN"
            buyer_role_scenarios = [
                {
                    "scenario": "current_best_supported",
                    "role": primary,
                    "status": clean_text(buyer_intelligence.get("role_status")) or "UNVERIFIED",
                    "evidence": buyer_intelligence.get("reason_codes") or [],
                    "falsification_test": "核验官网经营范围、工商目的、仓库/门店、产品页和逐票采购记录。",
                },
                {
                    "scenario": "reverse_possibility",
                    "role": "IMPORTER_OF_RECORD / TRADING_COMPANY / downstream buyer not disclosed",
                    "status": "HYPOTHESIS",
                    "evidence": ["Consignee名称本身不能证明最终采购和销售渠道。"],
                    "falsification_test": "确认付款、库存、供应商准入和最终销售主体。",
                },
            ]

        product_form_scenarios = list_of_dicts(enrichment.get("product_form_scenarios")) or list_of_dicts(result.get("calculation_scenarios"))
        decision = enrichment.get("business_decision") if isinstance(enrichment.get("business_decision"), dict) else {}
        strategic_route = (result.get("strategic_intelligence") or {}).get("development_route") or {}
        if not decision:
            decision = {
                "current_judgment": clean_text(strategic_route.get("positioning")) or "先核验买家角色、产品形态和决策路线，再决定开发投入。",
                "recommended_target": clean_text(strategic_route.get("recommended_target")) or "已验证采购或品类负责人",
                "first_objective": clean_text(strategic_route.get("first_objective")) or "确认真实业务角色和一个优先规格",
                "stop_condition": "若买家仅为物流/IOR、产品不匹配或决策权在未披露第三方，则停止直接报价。",
            }

        checks = {
            "material_findings_present": bool(findings),
            "buyer_role_has_reverse_possibility": len(buyer_role_scenarios) >= 2,
            "product_boundary_present": bool(product),
            "continuity_boundary_present": any(item.get("finding_id") == "trade-continuity-boundary" for item in findings),
            "prioritized_actions_present": bool(result.get("next_actions")),
            "outreach_is_separate": True,
        }
        return {
            "version": SCHEMA_VERSION,
            "mode": mode,
            "primary_product": "full_intelligence_dossier",
            "outreach_appendix_only": True,
            "material_findings": findings,
            "buyer_role_scenarios": buyer_role_scenarios,
            "product_form_scenarios": product_form_scenarios,
            "business_decision": decision,
            "value_gate": {
                "passed": all(checks.values()),
                "checks": [{"gate": key, "passed": value} for key, value in checks.items()],
                "failed_gates": [key for key, value in checks.items() if not value],
                "rule": "A blocked outreach route never shortens the intelligence dossier; raw JSON is not a human-facing report.",
            },
        }

    @staticmethod
    def _audit_trail(result: dict[str, Any]) -> list[dict[str, Any]]:
        events = [
            ("input", result.get("input_snapshot", {}).get("sha256")),
            ("field_audit", stable_hash(result.get("field_audit"))),
            ("product_taxonomy", stable_hash(result.get("products"))),
            ("contamination", stable_hash(result.get("cross_record_contamination"))),
            ("calculations", stable_hash(result.get("calculations"))),
            ("contacts", stable_hash(result.get("contact_evidence_ledger"))),
            ("trade_history", stable_hash(result.get("trade_history"))),
            ("review_ledger", stable_hash(result.get("review_ledger"))),
            ("competition_matrix", stable_hash(result.get("competition_matrix"))),
            ("strategic_intelligence", stable_hash(result.get("strategic_intelligence"))),
            ("learning_ledger", stable_hash(result.get("learning_ledger"))),
            ("decision_layers", stable_hash(result.get("decision_layers"))),
            ("crm", stable_hash(result.get("crm"))),
            ("quality_gate", stable_hash(result.get("quality_gate"))),
            ("outreach", stable_hash(result.get("outreach"))),
        ]
        previous = "GENESIS"
        output = []
        for index, (stage, digest) in enumerate(events, 1):
            chain = stable_hash({"sequence": index, "stage": stage, "digest": digest, "previous": previous})
            output.append({"sequence": index, "stage": stage, "payload_sha256": digest, "previous_hash": previous, "chain_hash": chain})
            previous = chain
        return output


def render_crm_csv_row(result: dict[str, Any]) -> dict[str, str]:
    final = result.get("decision_layers", {}).get("final_crm") or {}
    reviewed = final.get("record") if final.get("export_allowed") and isinstance(final.get("record"), dict) else {}
    value_summary = reviewed.get("commercial_value_dimensions") or []
    return {
        "account_name": clean_text(reviewed.get("buyer")),
        "legal_name": clean_text(reviewed.get("legal_name")),
        "country": clean_text(reviewed.get("buyer_country") or reviewed.get("destination_country")),
        "address": clean_text(reviewed.get("buyer_address")),
        "buyer_role": clean_text(reviewed.get("buyer_role")),
        "product_category": clean_text(reviewed.get("product")),
        "product_fit": clean_text(reviewed.get("product_fit")),
        "sales_priority": clean_text(reviewed.get("sales_priority")),
        "enterprise_grade": clean_text(reviewed.get("enterprise_grade")),
        "demand_grade": clean_text(reviewed.get("demand_grade")),
        "outreach_grade": clean_text(reviewed.get("outreach_grade")),
        "stage": clean_text(reviewed.get("stage")),
        "official_channels": " | ".join(str(item) for item in reviewed.get("official_channels") or []),
        "next_action": clean_text(reviewed.get("next_action")),
        "risk_flags": " | ".join(str(item) for item in reviewed.get("risk_flags") or []),
        "relationship_type": clean_text(reviewed.get("relationship_type")),
        "development_route": clean_text(reviewed.get("development_route")),
        "commercial_value_dimensions": " | ".join(str(item) for item in value_summary) if isinstance(value_summary, list) else clean_text(value_summary),
        "crm_status": clean_text(final.get("status")),
        "blocked_field_count": str(len(final.get("pending_fields") or []) + len(final.get("rejected_fields") or [])),
    }


def render_v3_report(result: dict[str, Any]) -> str:
    """Render an intelligence-first Chinese dossier; structured JSON stays in audit artifacts."""

    labels = {
        "status": "状态", "research_status": "研究状态", "raw_name": "原始名称", "legal_name": "法律名称",
        "country": "国家/地区", "role": "角色", "role_status": "角色状态", "business_model": "经营模式",
        "purchase_pattern": "采购模式", "match_level": "匹配等级", "normalized_category": "产品分类",
        "declared_origin": "申报原产地", "manufacturing_origin": "制造原产地", "manufacturing_origin_status": "原产地状态",
        "place_of_receipt": "收货地", "port_of_lading": "装货港", "foreign_port_of_lading": "外国装货港",
        "transshipment_ports": "中转港", "port_of_discharge": "卸货港", "final_delivery_location": "最终目的地",
        "country_of_export": "出口国", "frob_status": "FROB", "trade_regime": "贸易方式",
        "enterprise_intelligence_grade": "企业情报等级", "product_demand_grade": "产品需求等级",
        "direct_outreach_grade": "直接开发等级", "supplier_lock_in": "供应链锁定", "contact_completeness": "联系方式完整度",
        "data_quality": "数据质量", "product_fit": "产品匹配", "stage": "阶段", "stage_modifier": "阶段修正",
        "current_judgment": "当前判断", "recommended_target": "推荐目标", "first_objective": "首要目标", "stop_condition": "停止条件",
        "terminal_state": "外联终止状态", "primary": "主要语言", "secondary": "备用语言", "confidence": "可信度",
        "buyer_iana_timezone": "客户时区", "buyer_local_time_now": "客户当地时间", "beijing_time_now": "北京时间",
        "buyer_local_send_time": "客户建议发送时间", "beijing_equivalent_window": "北京时间对应窗口", "dst_status": "夏令时",
        "holiday_status": "节假日核验", "working_day": "是否工作日", "crm_status": "CRM状态",
    }

    def value(item: Any, fallback: str = "未显示/待完整资料核验") -> str:
        if item is None or item == "":
            return fallback
        if isinstance(item, bool):
            return "是" if item else "否"
        if isinstance(item, float):
            return f"{item:,.4f}".rstrip("0").rstrip(".")
        if isinstance(item, int):
            return f"{item:,}"
        if isinstance(item, list):
            return "；".join(value(x, "") for x in item if x not in (None, "")) or fallback
        if isinstance(item, dict):
            parts = [f"{labels.get(str(k), str(k))}={value(v, '未显示')}" for k, v in item.items() if v not in (None, "", [], {})]
            return "；".join(parts) or fallback
        return clean_text(item) or fallback

    def cell(item: Any) -> str:
        return value(item).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")

    def table(headers: list[str], rows: list[list[Any]], empty: str) -> list[str]:
        if not rows:
            return [f"- {empty}"]
        output = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        output.extend("| " + " | ".join(cell(item) for item in row) + " |" for row in rows)
        return output

    def kv_rows(mapping: dict[str, Any], keys: list[str] | None = None) -> list[list[Any]]:
        selected = keys or list(mapping)
        return [[labels.get(key, key), mapping.get(key)] for key in selected if mapping.get(key) not in (None, "", [], {})]

    def source_link(item: dict[str, Any]) -> str:
        url = clean_text(item.get("source_reference") or item.get("url") or item.get("target_url"))
        label = clean_text(item.get("link_type") or item.get("source_id") or item.get("step")) or "来源"
        return f"[{label}]({url})" if url.startswith(("http://", "https://")) else (url or "未显示")

    shipment = result.get("normalized_shipment") or {}
    identity = result.get("record_identity") or {}
    buyer = shipment.get("buyer") or {}
    supplier = shipment.get("supplier") or {}
    product = shipment.get("product") or {}
    quantity = shipment.get("quantity") or {}
    route = result.get("route") or shipment.get("route") or {}
    data_quality = result.get("data_quality") or {}
    contamination = result.get("cross_record_contamination") or {}
    dossier = result.get("intelligence_dossier") or {}
    buyer_intelligence = result.get("buyer_intelligence") or {}
    supplier_intelligence = result.get("supplier_intelligence") or {}
    scores = result.get("scores") or {}
    quality = result.get("quality_gate") or {}
    outreach = result.get("outreach") or {}
    completion = outreach.get("completion") or {}
    email = outreach.get("email") or {}
    email_routing = outreach.get("email_routing") or {}
    decision_layers = result.get("decision_layers") or {}
    final_crm = decision_layers.get("final_crm") or {}

    verified_procurement = [item for item in result.get("contact_evidence_ledger") or [] if item.get("procurement_authority_status") == "confirmed" and item.get("verification_status") == "official_current"]
    findings_rows = [[item.get("classification"), item.get("statement"), item.get("business_impact"), item.get("counter_explanation"), item.get("verification_method")] for item in dossier.get("material_findings") or []]
    warning_rows = [[item.get("severity"), item.get("code"), item.get("message"), item.get("source")] for item in data_quality.get("warnings") or [] if isinstance(item, dict)]
    contamination_rows = [[item.get("kind"), item.get("value"), item.get("severity"), item.get("reason_code"), "隔离，不进入CRM"] for item in contamination.get("matches") or [] if isinstance(item, dict)]
    audit_rows = [[item.get("field"), item.get("raw_value"), item.get("normalized_value"), item.get("status"), item.get("confidence"), item.get("rejection_reason"), item.get("evidence") or item.get("source_ids")] for item in result.get("field_audit") or [] if isinstance(item, dict)]
    calculation_rows = [[item.get("calculation_id"), item.get("formula"), item.get("inputs"), item.get("result"), item.get("unit"), item.get("status"), item.get("warning") or item.get("interpretation")] for item in result.get("calculations") or [] if isinstance(item, dict)]
    scenario_rows = [[item.get("scenario_id") or item.get("scenario"), item.get("material") or item.get("product_form"), item.get("inputs") or item.get("assumptions"), item.get("theoretical_weight_kg"), item.get("difference_percent"), item.get("ranking_status") or item.get("status"), item.get("falsification_test") or item.get("verification_method")] for item in (dossier.get("product_form_scenarios") or []) if isinstance(item, dict)]
    role_rows = [[item.get("scenario"), item.get("role"), item.get("status"), item.get("evidence"), item.get("falsification_test")] for item in dossier.get("buyer_role_scenarios") or [] if isinstance(item, dict)]
    trade_rows = [[item.get("date"), item.get("supplier"), item.get("product_raw"), item.get("quantity"), item.get("uom"), item.get("weight_kg"), item.get("data_level"), item.get("duplicate_status") or item.get("is_duplicate"), item.get("source_ids")] for item in result.get("trade_history") or [] if isinstance(item, dict)]
    source_rows = [[item.get("source_id"), source_link(item), item.get("source_type"), item.get("evidence_grade"), item.get("publication_date") or item.get("source_date"), item.get("checked_at"), item.get("freshness_status"), item.get("quoted_or_visible_text")] for item in result.get("sources") or [] if isinstance(item, dict)]
    coverage_rows = [[item.get("step"), item.get("status"), item.get("result_summary"), source_link(item), item.get("link_type")] for item in result.get("research_coverage") or [] if isinstance(item, dict)]
    contact_rows = [[item.get("value"), item.get("person_name"), item.get("role"), item.get("procurement_authority_status"), item.get("verification_status"), item.get("recommended_use") or item.get("channel_use"), item.get("evidence_grade"), item.get("source_date") or item.get("last_verified"), source_link(item)] for item in result.get("contact_evidence_ledger") or [] if isinstance(item, dict)]
    email_route_rows = [[item.get("email"), item.get("person_name"), item.get("role"), item.get("route_class"), item.get("verification_status"), item.get("recommended_use"), item.get("reason") or item.get("risk_note"), item.get("source_date")] for item in email_routing.get("all_routes") or [] if isinstance(item, dict)]
    action_rows = [[item.get("priority"), item.get("action"), item.get("reason_code"), item.get("acceptance_criteria")] for item in result.get("next_actions") or [] if isinstance(item, dict)]
    unresolved_rows = [[item.get("field"), item.get("status"), item.get("reason") or item.get("reason_code"), item.get("verification_method")] for item in result.get("unresolved") or [] if isinstance(item, dict)]
    manual_rows = [[item.get("check_id"), item.get("type"), item.get("reason") or item.get("reason_code"), item.get("instructions"), item.get("status")] for item in result.get("manual_checks") or [] if isinstance(item, dict)]
    competition_rows = [[item.get("capability"), item.get("incumbent_status"), item.get("our_status"), item.get("gap"), item.get("acceptance_criteria"), item.get("source_ids")] for item in (result.get("competition_matrix") or {}).get("rows") or [] if isinstance(item, dict)]
    review_rows = [[item.get("field"), item.get("plugin_output"), item.get("assistant_review"), item.get("final_decision"), item.get("changed"), item.get("change_reason")] for item in result.get("review_ledger") or [] if isinstance(item, dict)]
    claim_rows = [[item.get("claim_class"), item.get("statement"), item.get("evidence_grade"), item.get("source_ids"), item.get("reason_codes"), item.get("acceptance_criteria")] for item in result.get("claim_ledger") or [] if isinstance(item, dict)]

    sections: list[str] = ["# 海关买家深度情报报告 v4.2"]
    sections += ["\n## 1. 核心商业结论"]
    sections += table(["项目", "判断"], [
        ["买家", buyer.get("legal_name") or buyer.get("raw_name")], ["研究状态", result.get("research_status")],
        ["买家角色", buyer_intelligence.get("buyer_role")], ["产品", product.get("normalized_category")],
        ["产品匹配", product.get("match_level")], ["持续采购", (result.get("trade_history_summary") or {}).get("repeat_purchase_status")],
        ["已验证采购负责人", len(verified_procurement)], ["外联状态", completion.get("terminal_state")],
        ["当前开发判断", (dossier.get("business_decision") or {}).get("current_judgment")],
    ], "尚未形成核心结论。")
    sections += table(["类别", "关键发现", "商业影响", "反向可能", "核验方式"], findings_rows, "未生成实质性发现；不得只凭评分决定开发。")

    sections += ["\n## 2. 数据污染、字段作用域与纠错"]
    sections += table(["严重性", "代码", "说明", "来源"], warning_rows, "当前结构化检查未发现警告；不等于外部数据绝对无误。")
    sections += table(["字段类型", "值", "严重性", "原因", "处理"], contamination_rows, "当前本地污染索引无冲突；仍需核对原始单据。")
    sections += table(["字段", "原始值", "标准值", "状态", "可信度", "拒绝原因", "证据"], audit_rows, "字段级审计未生成。")
    sections += table(["输入项目", "值"], [["数据源", identity.get("data_source")], ["记录日期", identity.get("record_date")], ["主单号", identity.get("master_bill")], ["分单号", identity.get("house_bill")], ["集装箱", identity.get("container_numbers")], ["输入指纹", (result.get("input_snapshot") or {}).get("sha256")]], "输入信息未显示。")

    sections += ["\n## 3. 正确运输路线与原产地"]
    sections += table(["路线字段", "审计结果"], kv_rows(route, ["declared_origin", "manufacturing_origin", "manufacturing_origin_status", "country_of_export", "place_of_receipt", "port_of_lading", "foreign_port_of_lading", "transshipment_ports", "port_of_discharge", "final_delivery_location", "frob_status", "on_the_spot_export", "bonded_zone", "trade_regime"]), "路线字段不足。")
    sections += ["- 收货地、装货港、最后外国港和中转港不能单独证明制造原产地；冲突字段必须保留原值并解释，不能勉强拼成一条航线。"]

    sections += ["\n## 4. 产品标准化：事实、推理与未知"]
    sections += table(["产品字段", "结果"], [["原始描述", product.get("raw_description")], ["标准分类", product.get("normalized_category")], ["匹配等级", product.get("match_level")], ["匹配特征", product.get("matched_features")], ["分类依据", product.get("reason_codes")], ["长×宽×厚", f"{value((product.get('specifications') or {}).get('length_mm'))} × {value((product.get('specifications') or {}).get('width_mm'))} × {value((product.get('specifications') or {}).get('thickness_mm'))} mm"], ["密度", (product.get("specifications") or {}).get("density_g_cm3")], ["规格核验", product.get("requires_spec_verification")]], "产品信息不足。")
    sections += table(["情景", "产品/材质", "假设", "理论重量", "差异率", "状态", "证伪/核验"], scenario_rows, "没有足够尺寸、厚度、密度或包装信息，未生成张数/规格情景。")
    sections += ["- 禁止从通用品名自动补全1220×2440、3–10mm、Celuka/free-foam、密度、颜色、用途或板张数。"]

    sections += ["\n## 5. 数量、重量、金额与价格核算"]
    sections += table(["数量字段", "值"], [["申报数量", quantity.get("declared_quantity")], ["单位", quantity.get("declared_unit")], ["数量作用域", quantity.get("quantity_scope")], ["净重kg", quantity.get("weight_kg")], ["毛重kg", quantity.get("gross_weight_kg")], ["包装数", quantity.get("package_count")], ["包装类型", quantity.get("package_type")], ["包装是否等于产品数量", quantity.get("package_count_is_product_quantity")], ["估算板张数", quantity.get("estimated_sheets")]], "数量信息不足。")
    sections += table(["计算", "公式", "输入", "结果", "单位", "状态", "意义/限制"], calculation_rows, "没有可安全执行的计算；缺少厚度时不得估算具体板张数。")
    sections += ["- 所有金额必须区分商品行、整份申报、运费分摊、保险、税基和关联交易；数学闭合不等于商业价格可比。"]

    sections += ["\n## 6. 买家企业画像"]
    sections += table(["企业字段", "结果"], [["海关名称", buyer.get("raw_name")], ["法律名称", buyer.get("legal_name")], ["国家/城市", f"{value(buyer.get('country'))} / {value((outreach.get('buyer') or {}).get('city'))}"], ["身份解析", (result.get("entity_resolution") or {}).get("status")], ["注册地址/经营地址", (result.get("entity_resolution") or {}).get("address_type")], ["经营模式", buyer_intelligence.get("business_model")], ["企业规模", buyer_intelligence.get("company_scale")], ["法律登记", (result.get("entity_resolution") or {}).get("legal_registration")]], "买家身份尚未解析。")
    sections += ["- 法律主体、商业品牌、进口抬头、实际经营者和最终买家必须分开；名称相似、相同城市或相同供应商不能证明关联。"]

    sections += ["\n## 7. 买家角色、反向可能与采购决策中心"]
    sections += table(["情景", "角色", "状态", "依据", "证伪方式"], role_rows, "未形成买家角色情景。")
    decision_centers = ((result.get("strategic_intelligence") or {}).get("procurement_decision_center") or {})
    sections += table(["决策字段", "判断"], kv_rows(decision_centers), "尚未确认采购、付款、库存和供应商准入决策中心。")
    sections += ["- Consignee只能证明记录中的收货/进口抬头，不能自动证明其是终端买家或拥有供应商选择权。"]

    sections += ["\n## 8. 历史采购、连续性与供应关系"]
    sections += table(["连续性指标", "结果"], kv_rows(result.get("trade_history_summary") or {}), "没有可审计的持续采购汇总。")
    sections += table(["日期", "供应商", "产品原文", "数量", "单位", "重量kg", "数据层级", "重复状态", "来源"], trade_rows, "当前只有单票或没有逐票历史；不得写成持续采购、月采购量或唯一供应商。")

    sections += ["\n## 9. 供应商、品牌、出口商与实际制造商"]
    sections += table(["供应链字段", "判断"], [["海关供应商", supplier.get("legal_name") or supplier.get("raw_name")], ["海关角色", supplier.get("role")], ["候选分类", supplier_intelligence.get("candidate_classification")], ["分类状态", supplier_intelligence.get("classification_status")], ["工厂所有权", supplier_intelligence.get("factory_ownership_status")], ["品牌链", (result.get("strategic_intelligence") or {}).get("brand_chain")], ["关系解析", (result.get("strategic_intelligence") or {}).get("relationship_resolution")]], "供应商和制造商尚未解析。")
    sections += ["- 海关供应商可能是工厂、关联出口商、采购整合商、贸易商或物流出口主体；没有生产线、证书持有人和工商证据时不得写成自有工厂。"]

    sections += ["\n## 10. 官网、社媒、地图、工商、法律与来源"]
    sections += table(["来源ID", "直接链接", "类型", "等级", "页面日期", "核验日期", "时效", "可见证据"], source_rows, "本次没有外部来源；结论仅限用户提供的海关记录和离线规则。")
    sections += table(["搜索渠道", "状态", "结果", "链接", "链接类型"], coverage_rows, "未生成搜索覆盖日志。")
    sections += ["- 未完成准确主体、司法辖区和官方数据库检索时，不得写“无诉讼”“无风险”；Google Maps搜索入口也不等于已确认Google Business档案。"]

    sections += ["\n## 11. 决策人、电话与全部邮箱路线"]
    sections += table(["联系方式", "人员", "原始职位", "采购权", "核验状态", "推荐用途", "证据等级", "日期", "来源"], contact_rows, "未找到已验证采购负责人或官方联系方式；这不等于企业没有联系方式。")
    sections += table(["邮箱", "人员", "职位", "路线分类", "当前状态", "用途", "风险/原因", "日期"], email_route_rows, "没有发现邮箱；必须说明已检查和未完成的渠道。")
    sections += [f"- 邮箱遗漏检查：发现 {value(email_routing.get('discovered_email_count'), '0')} 个，已分类 {value(email_routing.get('accounted_email_count'), '0')} 个，检查结果={value(email_routing.get('omission_check_passed'))}。"]

    sections += ["\n## 12. 兴怀产品与能力匹配"]
    sections += table(["匹配字段", "判断"], [["目标产品分类", product.get("normalized_category")], ["结构匹配", product.get("match_level")], ["已验证卖方能力", [item.get("claim") for item in outreach.get("seller_capability_ledger") or [] if item.get("verified") and item.get("allowed_for_external_use")]], ["未知客户规格", [item.get("field") for item in result.get("unresolved") or [] if item.get("field") in {"thickness_mm", "density_g_cm3", "product", "quantity_count"}]], ["能力边界", "只有VERIFIED且允许外发的兴怀能力可进入开发信；证书和样品报告不能覆盖全部产品。"]], "尚未形成产品匹配判断。")

    sections += ["\n## 13. 竞争格局、供应链难度与切入机会"]
    sections += table(["能力", "现有供应链证据", "兴怀状态", "缺口", "验收标准", "来源"], competition_rows, "没有足够证据形成竞争能力矩阵；不得用主观匹配分替代。")
    sections += table(["商业决策", "内容"], kv_rows(dossier.get("business_decision") or {}), "当前应先验证买家角色、产品规格和决策路线。")

    sections += ["\n## 14. 客户等级、价值维度与阶段"]
    sections += table(["评分维度", "结果"], kv_rows(scores, ["enterprise_intelligence_grade", "product_demand_grade", "direct_outreach_grade", "supplier_lock_in", "contact_completeness", "data_quality", "product_fit", "stage", "stage_modifier"]), "评分信息不足。")
    sections += table(["升级条件", "降级/停止条件"], [[scores.get("upgrade_conditions"), scores.get("downgrade_conditions")]], "未生成升级和降级条件。")
    sections += ["- 一票记录不能直接评为A级；没有校准模型时不得发布回复率、成交率或供应链锁定百分比。"]

    sections += ["\n## 15. CRM审核结果"]
    sections += table(["CRM字段", "结果"], [["状态", final_crm.get("status")], ["允许导出", final_crm.get("export_allowed")], ["已接受字段数", final_crm.get("accepted_field_count")], ["待核验字段", final_crm.get("pending_fields")], ["拒绝字段", final_crm.get("rejected_fields")]], "尚未形成CRM裁决。")
    sections += table(["最终CRM字段", "值"], kv_rows(final_crm.get("record") or result.get("crm") or {}), "没有通过人工/模型审计的字段可进入CRM。")
    sections += table(["字段", "插件候选", "大脑审计", "最终决定", "是否修改", "原因"], review_rows, "尚未执行插件候选—大脑审计—最终CRM三层裁决。")

    sections += ["\n## 16. 下一步动作与验收标准"]
    sections += table(["优先级", "动作", "原因", "验收标准"], action_rows, "没有生成可执行下一步。")

    sections += ["\n## 17. 待验证问题与人工核验队列"]
    sections += table(["字段", "状态", "原因", "核验方法"], unresolved_rows, "当前结构化输出未列出未决项。")
    sections += table(["检查ID", "类型", "原因", "操作", "状态"], manual_rows, "没有人工视觉或付费档案核验队列。")

    sections += ["\n## 18. 事实、推理、假设、建议与证据边界"]
    sections += table(["类别", "陈述", "证据等级", "来源", "依据", "验收/核验"], claim_rows, "证据分类账未生成。")
    sections += table(["质量门", "结果"], [["研究状态", quality.get("research_status")], ["失败项", quality.get("failed_gates")], ["情报价值门", (dossier.get("value_gate") or {}).get("passed")], ["情报价值缺口", (dossier.get("value_gate") or {}).get("failed_gates")]], "质量门未生成。")
    sections += ["- FACT仅限输入记录或来源直接支持；INFERENCE说明推理链；HYPOTHESIS给出反向可能和证伪方式；RECOMMENDATION给出动作和验收标准；UNKNOWN明确缺口。"]
    sections += ["- 插件负责解析、检索、计算、异常和证据整理；GPT/人工审计负责处理矛盾、反向验证、商业判断和最终CRM准入。"]

    sections += ["\n### 18.1 外联执行附录（企业微信/腾讯企业邮箱兼容）"]
    sections += table(["外联字段", "结果"], [["终止状态", completion.get("terminal_state")], ["开发状态", outreach.get("outreach_status")], ["收件人", email.get("to")], ["主题", email.get("subject")], ["主要语言", (outreach.get("language") or {}).get("primary")], ["阻止原因", completion.get("block_reasons")]], "外联状态未生成。")
    sections += table(["时间字段", "结果"], kv_rows(outreach.get("timezone") or {}, ["buyer_iana_timezone", "buyer_local_time_now", "beijing_time_now", "buyer_local_send_time", "beijing_equivalent_window", "dst_status", "working_day", "holiday_status"]), "客户城市或时区未验证。")
    if email.get("body"):
        sections += ["\n**客户语言开发信**\n", str(email.get("body")).strip(), "\n**中文审核译文**\n", str(email.get("chinese_translation") or "未显示/待完整资料核验").strip()]
    action = completion.get("action") or {}
    if action.get("enabled") and action.get("url"):
        sections += [f"\n[一键打开邮件草稿 / Open email draft]({action.get('url')})"]
    else:
        sections += [f"- 草稿暂不可用：{value(completion.get('block_reasons'))}"]
    for item in outreach.get("alternate_drafts") or []:
        if isinstance(item, dict) and item.get("mailto_url"):
            sections += [f"- 备选路线 {value(item.get('to'))}：[单独打开草稿]({item.get('mailto_url')})"]
    sections += ["- 默认邮件环境：企业微信/腾讯企业邮箱。`mailto:`只负责打开本地草稿；没有真实连接器成功回执时，严禁声称已创建Gmail/Outlook/企业微信服务器草稿，也不得编造草稿ID。"]
    sections += ["- 插件绝不自动发送；任何连接器创建、修改或发送均需显示预览和新的明确确认。"]
    return "\n".join(sections).strip() + "\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
