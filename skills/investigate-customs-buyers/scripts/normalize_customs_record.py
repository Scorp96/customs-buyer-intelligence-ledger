#!/usr/bin/env python3
"""Normalize multilingual customs text or JSON and reconcile common declaration fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


PLACEHOLDERS = {"", "-", "N/A", "NA", "NONE", "NULL", "NOT SHOWN"}

KEY_MAP = {
    # Chinese/common shipment fields
    "数据源": "data_source",
    "日期": "arrival_date",
    "主单号": "master_bill",
    "分单号": "house_bill",
    "供应商": "supplier",
    "供应商地址": "supplier_address",
    "采购商": "buyer",
    "采购商地址": "buyer_address",
    "数量": "quantity",
    "重量（kg）": "weight_kg",
    "重量(kg)": "weight_kg",
    "毛重（kg）": "gross_weight_kg",
    "毛重(kg)": "gross_weight_kg",
    "产品": "product",
    "原产地": "origin",
    "起运港": "port_of_lading",
    "目的地": "destination_country",
    "目的港": "port_of_discharge",
    "承运人": "carrier",
    "船名": "vessel",
    "运输方式": "transport_mode",
    "集装箱": "containers",
    "物流发货人": "logistics_shipper",
    # English/common shipment fields
    "data source": "data_source",
    "date": "arrival_date",
    "arrival date": "arrival_date",
    "master bill": "master_bill",
    "master bill no": "master_bill",
    "house bill": "house_bill",
    "bill of lading": "master_bill",
    "supplier": "supplier",
    "supplier address": "supplier_address",
    "buyer": "buyer",
    "buyer address": "buyer_address",
    "quantity": "quantity",
    "weight": "weight_kg",
    "weight kg": "weight_kg",
    "gross weight": "gross_weight_kg",
    "teu": "teu",
    "product": "product",
    "origin": "origin",
    "port of lading": "port_of_lading",
    "destination": "destination_country",
    "port of discharge": "port_of_discharge",
    "carrier": "carrier",
    "vessel": "vessel",
    "transport mode": "transport_mode",
    "container": "containers",
    "containers": "containers",
    "logistics shipper": "logistics_shipper",
    # Other common fields
    "update date": "update_date",
    "run date": "run_date",
    "vessel country": "vessel_country",
    "hidden": "hidden",
    "bill type": "bill_type",
    "manifest number": "manifest_number",
    "notify": "notify_party",
    "measurement": "measurement",
    "record status": "record_status",
    "voyage number": "voyage_number",
    "i m o number/ lloyds number": "imo_number",
    "imo number": "imo_number",
    "estimated arrival date": "estimated_arrival_date",
    "place of receipt": "place_of_receipt",
    "notify_addr": "notify_address",
    "currency": "currency",
}

# Keys copied from customs platforms often contain a space between every letter.
# canonical_key removes separators before consulting this map.
COMPACT_KEY_MAP = {
    # Vietnam declaration fields
    "supplierinfo": "supplier_info",
    "buyerinfo": "buyer_info",
    "4digit": "hs4",
    "6digit": "hs6",
    "importtariff": "import_tariff_percent",
    "originalunitprice": "unit_price",
    "typeofcurrency": "currency",
    "customsbranchcode1": "customs_branch_code",
    "provincecode": "province_code",
    "typeofimport": "import_type",
    "exportcountryname": "export_country",
    "importeraddressvn": "importer_address_local",
    "transtype": "trans_type",
    "productdescriptioninvietnamese": "product_description_local",
    "paymentterm": "payment_term",
    "importtypecode": "import_type_code",
    "originscode": "origin_code",
    "provincename": "province_name",
    "coocode": "coo_code",
    "declarationno": "declaration_number",
    "chapter": "chapter",
    "uomcode": "uom_code",
    "originalamount": "original_amount",
    "vndexchangerate": "vnd_exchange_rate",
    "meansoftransportation": "means_of_transportation",
    "importerregisternamevn": "importer_registered_name_local",
    "countrycode": "country_code",
    # Philippines declaration fields
    "manifest": "manifest_number",
    "itemno": "item_number",
    "typepkgs": "package_type",
    "typeofpkgs": "package_type",
    "modeldeclaration": "model_declaration",
    "insurance": "insurance_amount",
    "nopackages": "package_count",
    "numberpackages": "package_count",
    "totalassessment": "total_assessment",
    "locgoods": "location_of_goods",
    "broker": "broker",
    "procedurecode": "procedure_code",
    "dutyrate": "duty_rate_percent",
    "vatpaid": "vat_paid",
    "dutiableforeign": "dutiable_foreign",
    "prefcode": "preference_code",
    "fob": "fob_amount",
    "collectiondate": "collection_date",
    "portofentry": "port_of_entry",
    "eserial": "entry_serial",
    "eserial1": "entry_serial_secondary",
    "grossmasskgs": "gross_weight_kg",
    "grossweightkgs": "gross_weight_kg",
    "countryorigin": "country_origin_code",
    "countryorigin1": "country_origin_code_secondary",
    "assessmentdate": "assessment_date",
    "asessementdate": "assessment_date",
    "asessmentdate": "assessment_date",
    "currency": "currency",
    "dutiablevaluephp": "dutiable_value_local",
    "port": "port_code",
    "port1": "port_code_secondary",
    "customsvalue": "customs_value",
    "othertaxes": "other_taxes",
    "exchangerate": "exchange_rate",
    "totalfees": "total_fees",
    "dutypaid": "duty_paid",
    "countryexport": "country_export",
    "vattaxbase": "vat_base",
    "exciseadvalorem": "excise_ad_valorem",
    "freight": "freight_amount",
    "nationalcode": "national_code",
    "noofcontainer": "declared_container_count",
    "numberofcontainer": "declared_container_count",
    "eyear": "entry_year",
    "destination": "destination_code",
    "brokeradd": "broker_address",
    "brokeraddress": "broker_address",
    "typedeclaration": "declaration_type",
    "yellow": "yellow_lane_flag",
    "entryno": "entry_number",
    "finepenalties": "fine_penalties",
    "dutiestaxes": "duties_taxes",
    "brokertin": "broker_tin",
}

SECTION_NAMES = {
    "基本信息": "basic",
    "产品信息": "product",
    "货运信息": "freight",
    "其它信息": "other",
    "其他信息": "other",
}


def clean_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", text.strip().strip("*")).casefold()


def compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_key(value))


def canonical_key(value: str) -> str | None:
    direct = KEY_MAP.get(clean_key(value))
    if direct:
        return direct
    return COMPACT_KEY_MAP.get(compact_key(value))


def fallback_ascii_key(value: str) -> str | None:
    """Preserve an unknown English key without pretending it is understood."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not re.search(r"[a-z]", normalized):
        return None
    token = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return token or None


def parse_text(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    duplicates: dict[str, list[str]] = {}
    unmapped: dict[str, str] = {}
    section = "unsectioned"
    raw_sections: dict[str, dict[str, str]] = {section: {}}
    known_keys = sorted(KEY_MAP, key=len, reverse=True)
    data_lines = 0
    recognized_lines = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in {"```", "```text"}:
            continue
        heading = line.strip("*# ").strip()
        if heading in SECTION_NAMES:
            section = SECTION_NAMES[heading]
            raw_sections.setdefault(section, {})
            continue

        data_lines += 1
        key_text: str | None = None
        value = ""
        parts = re.split(r"\t+|\s{2,}", line, maxsplit=1)
        if len(parts) == 2:
            key_text, value = parts[0], parts[1]
        elif ":" in line:
            candidate, candidate_value = line.split(":", 1)
            if canonical_key(candidate) or fallback_ascii_key(candidate):
                key_text, value = candidate, candidate_value
        else:
            lower_line = clean_key(line)
            for known in known_keys:
                if lower_line == known or lower_line.startswith(known + " "):
                    key_text = line[: len(known)]
                    value = line[len(known) :].strip()
                    break

        if not key_text:
            raw_sections.setdefault(section, {})[
                f"unparsed_{len(raw_sections[section]) + 1}"
            ] = line
            continue

        key_text = key_text.strip()
        value = value.strip()
        raw_sections.setdefault(section, {})[key_text] = value
        canonical = canonical_key(key_text)
        if not canonical:
            fallback = fallback_ascii_key(key_text)
            if fallback:
                unmapped[fallback] = value
            else:
                raw_sections.setdefault(section, {})[
                    f"unparsed_{len(raw_sections[section]) + 1}"
                ] = line
            continue

        recognized_lines += 1
        existing = parsed.get(canonical)
        if existing is None or str(existing).strip().upper() in PLACEHOLDERS:
            parsed[canonical] = value
        elif value.upper() not in PLACEHOLDERS and value != existing:
            duplicates.setdefault(canonical, [str(existing)]).append(value)

    parsed["_raw_sections"] = raw_sections
    parsed["_unmapped_fields"] = unmapped
    parsed["_duplicate_values"] = duplicates
    parsed["_parse_stats"] = {
        "data_lines": data_lines,
        "recognized_lines": recognized_lines,
        "unmapped_lines": len(unmapped),
        "unparsed_lines": max(data_lines - recognized_lines - len(unmapped), 0),
    }
    return parsed


def flatten_json(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    unmapped: dict[str, Any] = {}
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object.")
    for key, item in value.items():
        if isinstance(item, dict):
            nested = flatten_json(item)
            result.update({k: v for k, v in nested.items() if not k.startswith("_")})
            unmapped.update(nested.get("_unmapped_fields", {}))
            continue
        canonical = canonical_key(str(key))
        if canonical:
            result[canonical] = item
        else:
            fallback = fallback_ascii_key(str(key))
            if fallback:
                unmapped[fallback] = item
    result["_unmapped_fields"] = unmapped
    result["_parse_stats"] = {
        "data_lines": len(value),
        "recognized_lines": len(result) - 2,
        "unmapped_lines": len(unmapped),
        "unparsed_lines": 0,
    }
    return result


def read_text_safely(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
    raise UnicodeError("Unable to decode input. " + " | ".join(errors))


def parse_date_info(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    result: dict[str, Any] = {
        "raw": text or None,
        "normalized": None,
        "valid": False,
        "ambiguous": False,
    }
    if not text:
        return result

    iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        result["normalized"] = datetime.fromisoformat(iso_candidate).date().isoformat()
        result["valid"] = True
        return result
    except ValueError:
        pass

    for fmt in ("%Y/%m/%d", "%Y%m%d"):
        try:
            result["normalized"] = datetime.strptime(text, fmt).date().isoformat()
            result["valid"] = True
            return result
        except ValueError:
            pass

    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash:
        first, second, year = map(int, slash.groups())
        if first <= 12 and second <= 12:
            result["valid"] = True
            result["ambiguous"] = True
            return result
        fmt = "%d/%m/%Y" if first > 12 else "%m/%d/%Y"
        try:
            result["normalized"] = datetime.strptime(text, fmt).date().isoformat()
            result["valid"] = True
            return result
        except ValueError:
            return result
    return result


def parse_date(value: Any) -> str | None:
    info = parse_date_info(value)
    return info["normalized"] if info["normalized"] else info["raw"]


def first_number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def parse_quantity(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    number = first_number(value)
    unit_match = re.search(r"\d[\d,.]*\s*([A-Za-z]+)", str(value))
    return number, unit_match.group(1).upper() if unit_match else None


def parse_containers(value: Any) -> list[str]:
    if value is None:
        return []
    candidates = (
        [str(item) for item in value]
        if isinstance(value, list)
        else re.split(r"[,;/\s]+", str(value))
    )
    result: list[str] = []
    for item in candidates:
        token = item.strip().upper()
        if token and token not in PLACEHOLDERS:
            result.append(token)
    return list(dict.fromkeys(result))


def extract_hs_candidates(value: Any) -> list[str]:
    if not value:
        return []
    candidates: list[str] = []
    for match in re.finditer(r"\d(?:[\d.\s-]{2,}\d|\d{3,})", str(value)):
        digits = re.sub(r"\D", "", match.group(0))
        if 4 <= len(digits) <= 10:
            candidates.append(digits)
    return list(dict.fromkeys(candidates))


def extract_hs(product: Any) -> str | None:
    if not product:
        return None
    match = re.search(
        r"\bH\s*\.?\s*S\s*\.?\s*(?:CODE)?\s*:?\s*"
        r"(\d(?:[\d.\s-]{2,}\d|\d{3,}))",
        str(product),
        re.I,
    )
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return digits if 4 <= len(digits) <= 10 else None


def container_check_digit_valid(container: str) -> bool | None:
    token = re.sub(r"[^A-Z0-9]", "", container.upper())
    if not re.fullmatch(r"[A-Z]{4}\d{7}", token):
        return None
    letter_values = {
        letter: value
        for letter, value in zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            (
                10,
                12,
                13,
                14,
                15,
                16,
                17,
                18,
                19,
                20,
                21,
                23,
                24,
                25,
                26,
                27,
                28,
                29,
                30,
                31,
                32,
                34,
                35,
                36,
                37,
                38,
            ),
        )
    }
    values = [letter_values[c] if c.isalpha() else int(c) for c in token[:10]]
    expected = sum(value * (2**position) for position, value in enumerate(values)) % 11
    expected = 0 if expected == 10 else expected
    return expected == int(token[-1])


def possible_email(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    text = str(value)
    valid = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    if valid:
        return {
            "value": valid.group(0).lower(),
            "status": "observed_in_source",
            "confidence": "indicative",
        }
    missing_at = re.search(
        r"\b(?:e-?mail)\s*:?\s*([A-Za-z0-9_+.-]*[A-Za-z0-9_+-])"
        r"\s+([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b",
        text,
        re.I,
    )
    if missing_at:
        return {
            "value": f"{missing_at.group(1)}@{missing_at.group(2)}".lower(),
            "status": "candidate_unverified",
            "confidence": "inferred",
            "note": "Syntactically repaired from customs text; verify before use.",
        }
    return None


def add_anomaly(
    items: list[dict[str, str]], code: str, severity: str, message: str
) -> None:
    items.append({"code": code, "severity": severity, "message": message})


def add_reconciliation(
    items: list[dict[str, Any]],
    check: str,
    calculated: float,
    declared: float,
    formula: str,
    tolerance: float | None = None,
) -> None:
    allowed = tolerance if tolerance is not None else 0.02
    difference = calculated - declared
    items.append(
        {
            "check": check,
            "formula": formula,
            "calculated": round(calculated, 4),
            "declared": round(declared, 4),
            "difference": round(difference, 4),
            "status": "matched" if abs(difference) <= allowed else "mismatch",
            "evidence": "derived",
        }
    )


def extract_pvc_sheet_inference(
    product: Any, weight_kg: float | None, package_count: float | None
) -> dict[str, Any] | None:
    text = str(product or "")
    lowered = text.casefold()
    if "pvc" not in lowered or "foam" not in lowered:
        return None

    triple_dimension = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(mm)?\s*[x×*]\s*"
        r"(\d+(?:\.\d+)?)\s*(mm)?\s*[x×*]\s*"
        r"(\d+(?:\.\d+)?)\s*mm\b",
        text,
        re.I,
    )
    dimension = re.search(
        r"\b(\d{3,4}(?:\.\d+)?)\s*(mm)?\s*[x×*]\s*"
        r"(\d{3,4}(?:\.\d+)?)\s*(mm)?\b",
        text,
        re.I,
    )
    thickness = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*mm\b", text, re.I)
    explicit_density = re.search(
        r"(?<!\d)(0?\.\d{1,3}|\d(?:\.\d{1,3})?)\s*g\s*/?\s*cm(?:3|³)\b",
        text,
        re.I,
    )
    kg_m3_density = re.search(
        r"(?<!\d)(\d{2,4}(?:\.\d+)?)\s*kg\s*/?\s*m(?:3|³)\b",
        text,
        re.I,
    )
    shorthand_density = re.search(
        r"(?<!\d)(0?\.\d{2,3})\s*g\b", text, re.I
    )

    result: dict[str, Any] = {
        "evidence": "inferred_from_product_text",
        "verification_required": True,
    }
    if triple_dimension:
        result["width_mm"] = float(triple_dimension.group(1))
        result["length_mm"] = float(triple_dimension.group(3))
        result["thickness_mm"] = float(triple_dimension.group(5))
        result["dimension_unit_source"] = (
            "explicit_mm"
            if triple_dimension.group(2) and triple_dimension.group(4)
            else "partly_inferred_mm"
        )
    elif dimension:
        result["width_mm"] = float(dimension.group(1))
        result["length_mm"] = float(dimension.group(3))
        result["dimension_unit_source"] = (
            "explicit_mm"
            if dimension.group(2) and dimension.group(4)
            else "inferred_mm_from_board_format"
        )
        # Find a thickness token after the two-dimensional board-size expression.
        trailing = text[dimension.end() :]
        trailing_thickness = re.search(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*mm\b", trailing, re.I
        )
        if trailing_thickness:
            result["thickness_mm"] = float(trailing_thickness.group(1))
    if "thickness_mm" not in result and thickness:
        result["thickness_mm"] = float(thickness.group(1))

    density_match = explicit_density or kg_m3_density or shorthand_density
    if density_match:
        density = float(density_match.group(1))
        if kg_m3_density and density_match is kg_m3_density:
            density /= 1000
        result["density_g_cm3"] = density
        if explicit_density:
            result["density_source"] = "explicit_g_cm3"
        elif kg_m3_density:
            result["density_source"] = "explicit_kg_m3"
        else:
            result["density_source"] = "ambiguous_shorthand"
        if shorthand_density and not explicit_density:
            result["density_note"] = (
                "Interpreted from shorthand such as '.65g'; verify that it means g/cm³."
            )

    required = {"width_mm", "length_mm", "thickness_mm", "density_g_cm3"}
    if required.issubset(result):
        warnings: list[str] = []
        if not 0.2 <= result["density_g_cm3"] <= 1.5:
            warnings.append("implausible_density")
        if not 0.5 <= result["thickness_mm"] <= 60:
            warnings.append("implausible_thickness")
        if not 300 <= result["width_mm"] <= 3000:
            warnings.append("implausible_width")
        if not 300 <= result["length_mm"] <= 6000:
            warnings.append("implausible_length")
        result["plausibility_warnings"] = warnings
        result["plausible_for_sheet_count"] = not warnings
        if warnings:
            return result

        sheet_kg = (
            result["width_mm"]
            / 1000
            * result["length_mm"]
            / 1000
            * result["thickness_mm"]
            / 1000
            * result["density_g_cm3"]
            * 1000
        )
        result["theoretical_kg_per_sheet"] = round(sheet_kg, 5)
        if weight_kg is not None and sheet_kg > 0:
            estimated = weight_kg / sheet_kg
            nearest = round(estimated)
            result["estimated_sheet_count"] = round(estimated, 4)
            result["nearest_full_sheet_count"] = nearest
            if nearest > 0:
                result["weight_fit_to_nearest_percent"] = round(
                    abs(estimated - nearest) / nearest * 100, 3
                )
                if (
                    package_count
                    and float(package_count).is_integer()
                    and nearest % int(package_count) == 0
                ):
                    result["inferred_sheets_per_package"] = nearest // int(package_count)
    return result


def normalize(raw: dict[str, Any], input_encoding: str | None = None) -> dict[str, Any]:
    declared_quantity, declared_unit = parse_quantity(raw.get("quantity"))
    package_count = first_number(raw.get("package_count"))
    package_type = str(raw.get("package_type") or "").strip() or None
    quantity_count = declared_quantity
    quantity_unit = declared_unit
    quantity_source = "quantity_field" if declared_quantity is not None else None

    weight_kg = first_number(raw.get("weight_kg"))
    gross_weight_kg = first_number(raw.get("gross_weight_kg"))
    teu = first_number(raw.get("teu"))
    containers = parse_containers(raw.get("containers"))
    declared_container_count = first_number(raw.get("declared_container_count"))
    measurement_m3 = first_number(raw.get("measurement"))
    product = raw.get("product")

    numeric_fields = {
        key: first_number(raw.get(key))
        for key in (
            "unit_price",
            "original_amount",
            "vnd_exchange_rate",
            "import_tariff_percent",
            "insurance_amount",
            "total_assessment",
            "duty_rate_percent",
            "vat_paid",
            "dutiable_foreign",
            "fob_amount",
            "dutiable_value_local",
            "customs_value",
            "other_taxes",
            "exchange_rate",
            "total_fees",
            "duty_paid",
            "vat_base",
            "excise_ad_valorem",
            "freight_amount",
            "fine_penalties",
            "duties_taxes",
        )
    }

    metrics: dict[str, float] = {}
    if weight_kg is not None and quantity_count:
        metrics["net_kg_per_package_or_quantity"] = round(
            weight_kg / quantity_count, 4
        )
    if gross_weight_kg is not None and quantity_count:
        metrics["gross_kg_per_package_or_quantity"] = round(
            gross_weight_kg / quantity_count, 4
        )
    if weight_kg is not None and package_count:
        metrics["net_kg_per_package"] = round(weight_kg / package_count, 4)
    if gross_weight_kg is not None and package_count:
        metrics["gross_kg_per_package"] = round(
            gross_weight_kg / package_count, 4
        )
    if weight_kg is not None and gross_weight_kg is not None:
        metrics["packaging_or_tare_kg"] = round(gross_weight_kg - weight_kg, 4)
    if weight_kg is not None and teu:
        metrics["kg_per_teu"] = round(weight_kg / teu, 2)
    if weight_kg is not None and containers:
        metrics["kg_per_listed_container"] = round(
            weight_kg / len(containers), 2
        )
    if quantity_count is not None and containers:
        metrics["packages_per_listed_container"] = round(
            quantity_count / len(containers), 2
        )
    if teu and containers:
        metrics["teu_per_listed_container"] = round(teu / len(containers), 2)
    if weight_kg is not None and measurement_m3:
        metrics["implied_kg_per_m3"] = round(weight_kg / measurement_m3, 2)
    if numeric_fields["original_amount"] is not None and quantity_count:
        metrics["effective_unit_price"] = round(
            numeric_fields["original_amount"] / quantity_count, 6
        )
    if numeric_fields["unit_price"] is not None and quantity_count:
        metrics["total_from_displayed_unit_price"] = round(
            numeric_fields["unit_price"] * quantity_count, 4
        )
    if (
        numeric_fields["unit_price"] is not None
        and quantity_count
        and numeric_fields["original_amount"] is not None
    ):
        metrics["displayed_price_total_difference"] = round(
            numeric_fields["unit_price"] * quantity_count
            - numeric_fields["original_amount"],
            4,
        )
    if (
        numeric_fields["dutiable_foreign"] is not None
        and weight_kg not in (None, 0)
    ):
        metrics["dutiable_foreign_per_net_kg"] = round(
            numeric_fields["dutiable_foreign"] / weight_kg, 6
        )

    reconciliations: list[dict[str, Any]] = []
    customs_value = numeric_fields["customs_value"]
    freight = numeric_fields["freight_amount"]
    fob = numeric_fields["fob_amount"]
    insurance = numeric_fields["insurance_amount"]
    dutiable_foreign = numeric_fields["dutiable_foreign"]
    exchange_rate = numeric_fields["exchange_rate"]
    dutiable_local = numeric_fields["dutiable_value_local"]
    vat_base = numeric_fields["vat_base"]
    vat_paid = numeric_fields["vat_paid"]
    duty_rate = numeric_fields["duty_rate_percent"]
    duty_paid = numeric_fields["duty_paid"]

    if (
        numeric_fields["unit_price"] is not None
        and quantity_count
        and numeric_fields["original_amount"] is not None
    ):
        add_reconciliation(
            reconciliations,
            "displayed_unit_price_times_quantity",
            numeric_fields["unit_price"] * quantity_count,
            numeric_fields["original_amount"],
            "displayed unit price × quantity = original amount",
        )
    if None not in (customs_value, freight, fob):
        add_reconciliation(
            reconciliations,
            "customs_value_plus_freight",
            customs_value + freight,
            fob,
            "customs_value + freight = displayed FOB field",
        )
    if None not in (fob, insurance, dutiable_foreign):
        add_reconciliation(
            reconciliations,
            "fob_plus_insurance",
            fob + insurance,
            dutiable_foreign,
            "displayed FOB field + insurance = dutiable foreign value",
        )
    if None not in (dutiable_foreign, exchange_rate, dutiable_local):
        add_reconciliation(
            reconciliations,
            "foreign_value_times_exchange_rate",
            dutiable_foreign * exchange_rate,
            dutiable_local,
            "dutiable foreign value × exchange rate = dutiable local value",
        )
    data_source_text = " ".join(
        str(value or "")
        for value in (
            raw.get("data_source"),
            raw.get("destination_country"),
            raw.get("country_code"),
        )
    ).casefold()
    is_philippines = "菲律宾" in data_source_text or "philipp" in data_source_text
    if vat_base not in (None, 0) and vat_paid is not None:
        metrics["inferred_vat_rate_percent"] = round(vat_paid / vat_base * 100, 4)
    if (
        is_philippines
        and vat_base not in (None, 0)
        and vat_paid is not None
    ):
        add_reconciliation(
            reconciliations,
            "vat_base_times_inferred_12_percent",
            vat_base * 0.12,
            vat_paid,
            "VAT base × 12% = VAT paid",
        )
    if (
        duty_rate is not None
        and dutiable_local is not None
        and duty_paid is not None
    ):
        add_reconciliation(
            reconciliations,
            "dutiable_value_times_duty_rate",
            dutiable_local * duty_rate / 100,
            duty_paid,
            "dutiable local value × duty rate = duty paid",
        )

    anomalies: list[dict[str, str]] = []
    for reconciliation in reconciliations:
        if reconciliation["status"] == "mismatch":
            add_anomaly(
                anomalies,
                "financial_reconciliation_mismatch",
                "medium",
                f"{reconciliation['check']} did not reconcile within the configured absolute tolerance; verify rounding and field meaning.",
            )
    mode = str(raw.get("transport_mode") or "").casefold()
    if containers and "non-container" in mode:
        add_anomaly(
            anomalies,
            "mode_container_conflict",
            "high",
            "Transport mode says non-container while container identifiers are present.",
        )
    if weight_kg is not None and containers and weight_kg / len(containers) > 30000:
        add_anomaly(
            anomalies,
            "high_weight_per_container",
            "high",
            "Calculated cargo weight exceeds 30,000 kg per listed container.",
        )
    if weight_kg is not None and measurement_m3 and weight_kg / measurement_m3 > 10000:
        add_anomaly(
            anomalies,
            "weight_measurement_conflict",
            "high",
            "Implied density exceeds 10,000 kg/m³; measurement may be truncated or misparsed.",
        )
    if (
        weight_kg is not None
        and gross_weight_kg is not None
        and gross_weight_kg < weight_kg
    ):
        add_anomaly(
            anomalies,
            "gross_weight_below_net_weight",
            "high",
            "Gross weight is below reported net/cargo weight; reconcile the source fields.",
        )
    if (
        declared_container_count is not None
        and containers
        and int(declared_container_count) != len(containers)
    ):
        add_anomaly(
            anomalies,
            "declared_container_count_conflict",
            "medium",
            "Declared container count differs from the number of explicit container identifiers.",
        )
    if teu and containers and abs((teu / len(containers)) - 2) < 0.05:
        add_anomaly(
            anomalies,
            "forty_foot_equivalent_inference",
            "info",
            "TEU/listed-container ratio is 2.0, consistent with 40-foot-equivalent equipment but not equipment-code confirmation.",
        )

    port_of_lading = str(raw.get("port_of_lading") or "").strip()
    port_of_discharge = str(raw.get("port_of_discharge") or "").strip()
    normalized_lading = re.sub(r"[^a-z0-9]+", "", port_of_lading.casefold())
    normalized_discharge = re.sub(r"[^a-z0-9]+", "", port_of_discharge.casefold())
    lading_tokens = set(re.findall(r"[a-z0-9]+", port_of_lading.casefold()))
    discharge_tokens = set(re.findall(r"[a-z0-9]+", port_of_discharge.casefold()))
    similarity = (
        len(lading_tokens & discharge_tokens) / len(lading_tokens | discharge_tokens)
        if lading_tokens and discharge_tokens
        else 0
    )
    if normalized_lading and (
        normalized_lading == normalized_discharge or similarity >= 0.55
    ):
        add_anomaly(
            anomalies,
            "same_loading_discharge_port",
            "high",
            "Port of lading and port of discharge are the same or strongly overlap; reconcile merged fields.",
        )

    product_text = " ".join(
        str(value or "")
        for value in (product, raw.get("product_description_local"))
    ).casefold()
    if "foam" in product_text and (
        "non-porous" in product_text or "không xốp" in product_text
    ):
        add_anomaly(
            anomalies,
            "product_structure_conflict",
            "medium",
            "Description says foam board and also non-porous/non-foamed; verify the product structure.",
        )

    receipt = str(raw.get("place_of_receipt") or "").strip()
    origin = str(raw.get("origin") or "").strip()
    if receipt and origin and receipt.casefold() != origin.casefold():
        add_anomaly(
            anomalies,
            "origin_route_ambiguity",
            "medium",
            "Place of receipt and origin differ; one field may represent route rather than manufacture.",
        )
    if str(raw.get("yellow_lane_flag") or "").strip() == "1":
        add_anomaly(
            anomalies,
            "yellow_lane_indicator",
            "info",
            "A yellow-lane flag is a procedural indicator, not evidence of a violation; verify the jurisdictional meaning.",
        )
    for primary_key, secondary_key, code, label in (
        (
            "port_code",
            "port_code_secondary",
            "primary_secondary_port_conflict",
            "port code",
        ),
        (
            "country_origin_code",
            "country_origin_code_secondary",
            "primary_secondary_origin_conflict",
            "origin code",
        ),
        (
            "entry_serial",
            "entry_serial_secondary",
            "primary_secondary_serial_conflict",
            "entry serial",
        ),
    ):
        primary = str(raw.get(primary_key) or "").strip()
        secondary = str(raw.get(secondary_key) or "").strip()
        if primary and secondary and primary.casefold() != secondary.casefold():
            add_anomaly(
                anomalies,
                code,
                "medium",
                f"Primary and secondary {label} fields differ; preserve both and verify the declaration layout.",
            )
    if declared_container_count == 0 and not containers and (
        weight_kg is not None and weight_kg < 5000
    ):
        add_anomaly(
            anomalies,
            "possible_small_consolidated_shipment",
            "info",
            "Zero declared containers with a small cargo weight may be consistent with LCL or non-containerized reporting; verify if material.",
        )

    pvc_sheet_inference = extract_pvc_sheet_inference(
        product, weight_kg, package_count
    )
    if pvc_sheet_inference:
        for warning in pvc_sheet_inference.get("plausibility_warnings", []):
            add_anomaly(
                anomalies,
                warning,
                "high",
                "A parsed PVC specification is outside the configured plausibility range; sheet-count inference was suppressed.",
            )
        if pvc_sheet_inference.get("density_source") == "ambiguous_shorthand":
            add_anomaly(
                anomalies,
                "density_shorthand_requires_verification",
                "info",
                "Density was inferred from shorthand such as '.65g'; verify g/cm³ before using the calculation.",
            )
        if pvc_sheet_inference.get("weight_fit_to_nearest_percent", 100) <= 3:
            add_anomaly(
                anomalies,
                "weight_consistent_with_integer_sheet_count",
                "info",
                "Net weight is within 3% of an integer full-sheet count under the inferred dimensions and density.",
            )

    date_keys = (
        "arrival_date",
        "estimated_arrival_date",
        "update_date",
        "run_date",
        "collection_date",
        "assessment_date",
    )
    date_validation = {
        key: parse_date_info(raw.get(key))
        for key in date_keys
        if raw.get(key) is not None
    }
    dates = {
        key: info["normalized"] if info["normalized"] else info["raw"]
        for key, info in date_validation.items()
    }
    for key, info in date_validation.items():
        if not info["valid"]:
            add_anomaly(
                anomalies,
                "invalid_date",
                "high",
                f"{key} is not a valid supported date: {info['raw']!r}.",
            )
        elif info["ambiguous"]:
            add_anomaly(
                anomalies,
                "ambiguous_date",
                "medium",
                f"{key} is ambiguous between day/month and month/day: {info['raw']!r}.",
            )

    stats = raw.get("_parse_stats", {})
    data_lines = int(stats.get("data_lines") or 0)
    recognized_lines = int(stats.get("recognized_lines") or 0)
    coverage = recognized_lines / data_lines if data_lines else 1.0
    def present(value: Any) -> bool:
        return str(value or "").strip().upper() not in PLACEHOLDERS

    missing_research = [
        key
        for key, value in (("buyer", raw.get("buyer")), ("product", product))
        if not present(value)
    ]
    arrival_info = date_validation.get(
        "arrival_date",
        {"valid": False, "ambiguous": False},
    )
    has_shipment_reference = any(
        present(raw.get(key))
        for key in (
            "master_bill",
            "house_bill",
            "manifest_number",
            "declaration_number",
            "entry_number",
        )
    )
    missing_shipment: list[str] = list(missing_research)
    if not arrival_info["valid"] or arrival_info["ambiguous"]:
        missing_shipment.append("valid_unambiguous_arrival_date")
    if not has_shipment_reference:
        missing_shipment.append("shipment_reference")
    identity_ready = present(raw.get("buyer"))
    research_ready = not missing_research and coverage >= 0.75
    shipment_ready = research_ready and not missing_shipment
    parse_quality = {
        **stats,
        "recognized_coverage": round(coverage, 4),
        "input_encoding": input_encoding,
        "identity_ready": identity_ready,
        "research_ready": research_ready,
        "shipment_ready": shipment_ready,
        "missing_research_fields": missing_research,
        "missing_shipment_fields": list(dict.fromkeys(missing_shipment)),
        "missing_critical_fields": missing_research,
        "strict_pass": research_ready,
    }
    if coverage < 0.75:
        add_anomaly(
            anomalies,
            "low_parse_coverage",
            "high",
            "Less than 75% of data lines matched known fields; reconcile before research.",
        )

    product_hs = extract_hs(product)
    hs_candidates = list(
        dict.fromkeys(
            ([product_hs] if product_hs else [])
            + extract_hs_candidates(raw.get("hs6"))
            + extract_hs_candidates(raw.get("hs4"))
        )
    )
    if len(hs_candidates) > 1:
        add_anomaly(
            anomalies,
            "multiple_hs_candidates",
            "medium",
            "Multiple HS candidates were observed; preserve the list instead of concatenating them.",
        )

    record = {
        "data_source": raw.get("data_source"),
        "master_bill": raw.get("master_bill"),
        "house_bill": raw.get("house_bill"),
        "manifest_number": raw.get("manifest_number"),
        "entry_number": raw.get("entry_number"),
        "item_number": raw.get("item_number"),
        "supplier": raw.get("supplier"),
        "supplier_address": raw.get("supplier_address"),
        "logistics_shipper": raw.get("logistics_shipper"),
        "buyer": raw.get("buyer"),
        "buyer_address": raw.get("buyer_address"),
        "buyer_registered_name_local": raw.get("importer_registered_name_local"),
        "buyer_address_local": raw.get("importer_address_local"),
        "dates": dates,
        "quantity_count": quantity_count,
        "quantity_unit": quantity_unit,
        "quantity_source": quantity_source,
        "quantity_scope": (
            "declared_line_or_record_quantity"
            if quantity_count is not None
            else "not_declared"
        ),
        "package_count": package_count,
        "package_type": package_type,
        "package_scope": "shipment_or_packaging_level",
        "package_count_is_product_quantity": False,
        "weight_kg": weight_kg,
        "gross_weight_kg": gross_weight_kg,
        "teu": teu,
        "product": product,
        "hs_code": hs_candidates[0] if hs_candidates else None,
        "hs_candidates": hs_candidates,
        "hs4": next(iter(extract_hs_candidates(raw.get("hs4"))), None),
        "origin": raw.get("origin"),
        "country_origin_code": raw.get("country_origin_code"),
        "country_export": raw.get("country_export"),
        "place_of_receipt": raw.get("place_of_receipt"),
        "port_of_lading": raw.get("port_of_lading"),
        "destination_country": raw.get("destination_country"),
        "port_of_discharge": raw.get("port_of_discharge"),
        "port_of_entry": raw.get("port_of_entry"),
        "port_code": raw.get("port_code"),
        "destination_code": raw.get("destination_code"),
        "carrier": raw.get("carrier"),
        "vessel": raw.get("vessel"),
        "vessel_country": raw.get("vessel_country"),
        "voyage_number": raw.get("voyage_number"),
        "imo_number": raw.get("imo_number"),
        "transport_mode": raw.get("transport_mode"),
        "containers": containers,
        "declared_container_count": declared_container_count,
        "measurement_raw": raw.get("measurement"),
        "measurement_m3": measurement_m3,
        "notify_party": raw.get("notify_party"),
        "notify_address": raw.get("notify_address"),
        "record_status": raw.get("record_status"),
        "bill_type": raw.get("bill_type"),
        "declaration_number": raw.get("declaration_number"),
        "declaration_type": raw.get("declaration_type"),
        "model_declaration": raw.get("model_declaration"),
        "procedure_code": raw.get("procedure_code"),
        "entry_serial": raw.get("entry_serial"),
        "entry_serial_secondary": raw.get("entry_serial_secondary"),
        "entry_year": raw.get("entry_year"),
        "customs_branch_code": raw.get("customs_branch_code"),
        "import_type": raw.get("import_type"),
        "import_type_code": raw.get("import_type_code"),
        "payment_term": raw.get("payment_term"),
        "currency": raw.get("currency"),
        "preference_code": raw.get("preference_code"),
        "national_code": raw.get("national_code"),
        "location_of_goods": raw.get("location_of_goods"),
        "yellow_lane_flag": raw.get("yellow_lane_flag"),
        "broker": raw.get("broker"),
        "broker_address": raw.get("broker_address"),
        "broker_tin": raw.get("broker_tin"),
        "unit_price": numeric_fields["unit_price"],
        "original_amount": numeric_fields["original_amount"],
        "vnd_exchange_rate": numeric_fields["vnd_exchange_rate"],
        "import_tariff_percent": numeric_fields["import_tariff_percent"],
        "insurance_amount": insurance,
        "total_assessment": numeric_fields["total_assessment"],
        "customs_value": customs_value,
        "freight_amount": freight,
        "fob_amount": fob,
        "dutiable_foreign": dutiable_foreign,
        "exchange_rate": exchange_rate,
        "dutiable_value_local": dutiable_local,
        "duty_rate_percent": duty_rate,
        "duty_paid": duty_paid,
        "vat_base": vat_base,
        "vat_paid": vat_paid,
        "duties_taxes": numeric_fields["duties_taxes"],
        "other_taxes": numeric_fields["other_taxes"],
        "total_fees": numeric_fields["total_fees"],
        "fine_penalties": numeric_fields["fine_penalties"],
        "excise_ad_valorem": numeric_fields["excise_ad_valorem"],
        "port_code_secondary": raw.get("port_code_secondary"),
        "country_origin_code_secondary": raw.get(
            "country_origin_code_secondary"
        ),
        "origin_code": raw.get("origin_code"),
        "coo_code": raw.get("coo_code"),
        "country_code": raw.get("country_code"),
        "province_code": raw.get("province_code"),
        "province_name": raw.get("province_name"),
        "product_description_local": raw.get("product_description_local"),
        "uom_code": raw.get("uom_code"),
    }

    normalized: dict[str, Any] = {
        "record": record,
        "derived_metrics": metrics,
        "reconciliations": reconciliations,
        "date_validation": date_validation,
        "pvc_sheet_inference": pvc_sheet_inference,
        "container_validation": [
            {
                "container": container,
                "iso_6346_check_digit_valid": container_check_digit_valid(container),
            }
            for container in containers
        ],
        "contact_candidates": {
            "buyer_address_email": possible_email(raw.get("buyer_address")),
            "notify_address_email": possible_email(raw.get("notify_address")),
        },
        "parse_quality": parse_quality,
        "anomalies": anomalies,
        "unmapped_fields": raw.get("_unmapped_fields", {}),
        "duplicate_values": raw.get("_duplicate_values", {}),
        "evidence_boundary": [
            "Derived metrics and PVC sheet counts are arithmetic, not source-declared facts.",
            "A density parsed from shorthand such as '.65g' requires specification confirmation.",
            "Email repairs are candidates only and require independent verification.",
            "Anomaly flags indicate reconciliation needs, not misconduct.",
            "Customs field labels may be vendor-normalized; inspect the original declaration before assigning Incoterm meaning.",
        ],
    }
    if "_raw_sections" in raw:
        normalized["raw_sections"] = raw["_raw_sections"]
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 when parse coverage is low or buyer/product is missing.",
    )
    args = parser.parse_args()

    text, input_encoding = read_text_safely(args.input)
    raw = (
        flatten_json(json.loads(text))
        if args.input.suffix.casefold() == ".json"
        else parse_text(text)
    )
    result = normalize(raw, input_encoding=input_encoding)
    unicode_rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(unicode_rendered + "\n", encoding="utf-8")
    else:
        # ASCII escapes avoid mojibake in Windows shells with an incompatible code page.
        print(json.dumps(result, ensure_ascii=True, indent=2))

    if args.strict and not result["parse_quality"]["strict_pass"]:
        print(
            "Strict parse failed: "
            + json.dumps(result["parse_quality"], ensure_ascii=True),
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
