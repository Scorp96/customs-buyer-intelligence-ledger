#!/usr/bin/env python3
"""Aggregate observed customs shipments without overstating provider coverage."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


DATE_KEYS = ("arrival_date", "date", "estimated_arrival_date", "consignee_date")
BUYER_KEYS = ("buyer", "consignee", "importer", "company")
SUPPLIER_KEYS = ("supplier", "shipper", "exporter")
PRODUCT_KEYS = ("product", "description", "commodity", "goods")
HS_KEYS = ("hs_code", "hs", "hscode")
WEIGHT_KEYS = ("weight_kg", "weight", "gross_weight_kg")
QUANTITY_KEYS = ("quantity_count", "quantity")
BILL_KEYS = ("master_bill", "bill_of_lading", "bol", "bill")
HOUSE_BILL_KEYS = ("house_bill", "hbl", "house_bill_of_lading")
ITEM_KEYS = ("item_number", "item_no", "line_number")
CONTAINER_KEYS = ("containers", "container", "container_numbers")


def first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {str(key).casefold(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.casefold())
        if value not in (None, ""):
            return value
    return None


def number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def quantity_and_unit(row: dict[str, Any]) -> tuple[float | None, str]:
    value = first(row, QUANTITY_KEYS)
    quantity = number(value)
    explicit_unit = first(
        row,
        ("quantity_unit", "uom_code", "uom", "unit", "package_type"),
    )
    if explicit_unit not in (None, ""):
        unit = str(explicit_unit).strip().upper()
    else:
        match = re.search(r"\d[\d,.]*\s*([A-Za-z]+)", str(value or ""))
        unit = match.group(1).upper() if match else "UNSPECIFIED"
    return quantity, unit


def normalized_product(row: dict[str, Any]) -> str:
    text = str(first(row, PRODUCT_KEYS) or "").casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def normalized_containers(row: dict[str, Any]) -> str:
    value = first(row, CONTAINER_KEYS)
    if isinstance(value, list):
        tokens = [str(item).strip().upper() for item in value]
    else:
        tokens = re.split(r"[,;/\s]+", str(value or ""))
        tokens = [token.strip().upper() for token in tokens]
    return ",".join(sorted(token for token in tokens if token))


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def normalize_entity(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    suffixes = r"\b(CO|COMPANY|LTD|LIMITED|INC|INCORPORATED|LLC|CORP|CORPORATION|SA|S A)\b"
    text = re.sub(suffixes, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def product_matches(observed_value: Any, requested_value: str) -> bool:
    observed = re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", str(observed_value or "").casefold()),
    ).strip()
    requested = re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", requested_value.casefold()),
    ).strip()
    if not requested:
        return True
    target_aliases = {
        "pvc foam board",
        "pvc foamed board",
        "foamed pvc board",
        "expanded pvc sheet",
    }
    if requested in target_aliases:
        exclusions = (
            "structural pvc foam core",
            "marine foam core",
            "pvc foam core material",
            "pvc square tube",
            "pvc tube",
            "pvc pipe",
            "foam floor mat",
            "pvc display stand",
            "cosmetic display",
        )
        if any(phrase in observed for phrase in exclusions):
            return False
        return any(alias in observed for alias in target_aliases)
    return requested in observed


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("shipments"), list):
        return data["shipments"]
    raise ValueError("JSON must be a list of shipment objects or contain a 'shipments' list.")


def row_matches(row: dict[str, Any], buyer: str | None, product: str | None, hs_prefix: str | None) -> bool:
    if buyer:
        expected = normalize_entity(buyer)
        observed = normalize_entity(first(row, BUYER_KEYS))
        if not expected or observed != expected:
            return False
    if product:
        if not product_matches(first(row, PRODUCT_KEYS), product):
            return False
    if hs_prefix:
        hs = re.sub(r"\D", "", str(first(row, HS_KEYS) or ""))
        if not hs.startswith(hs_prefix):
            return False
    return True


def dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    bill = str(first(row, BILL_KEYS) or "").strip().upper()
    house_bill = str(first(row, HOUSE_BILL_KEYS) or "").strip().upper()
    item = str(first(row, ITEM_KEYS) or "").strip().upper()
    observed_date = parse_date(first(row, DATE_KEYS))
    buyer = normalize_entity(first(row, BUYER_KEYS))
    supplier = normalize_entity(first(row, SUPPLIER_KEYS))
    weight = number(first(row, WEIGHT_KEYS))
    quantity, unit = quantity_and_unit(row)
    hs = re.sub(r"\D", "", str(first(row, HS_KEYS) or ""))
    return (
        bill,
        house_bill,
        item,
        observed_date.isoformat() if observed_date else "",
        buyer,
        supplier,
        normalized_product(row),
        hs,
        f"{weight:.3f}" if weight is not None else "",
        f"{quantity:.3f}" if quantity is not None else "",
        unit,
        normalized_containers(row),
    )


def summarize(rows: list[dict[str, Any]], buyer: str | None, product: str | None, hs_prefix: str | None) -> dict[str, Any]:
    selected = [row for row in rows if row_matches(row, buyer, product, hs_prefix)]
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in selected:
        unique.setdefault(dedupe_key(row), row)
    records = list(unique.values())

    dates = sorted(item for item in (parse_date(first(row, DATE_KEYS)) for row in records) if item)
    weights = [value for value in (number(first(row, WEIGHT_KEYS)) for row in records) if value is not None]
    quantities_by_unit: dict[str, list[float]] = {}
    for row in records:
        quantity, unit = quantity_and_unit(row)
        if quantity is not None:
            quantities_by_unit.setdefault(unit, []).append(quantity)
    suppliers = Counter(
        str(first(row, SUPPLIER_KEYS)).strip()
        for row in records
        if first(row, SUPPLIER_KEYS) not in (None, "")
    )
    gaps = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
    as_of = max(dates) if dates else date.today()

    result: dict[str, Any] = {
        "filters": {"buyer": buyer, "product": product, "hs_prefix": hs_prefix},
        "source_rows": len(rows),
        "matched_rows_before_deduplication": len(selected),
        "observed_unique_shipments": len(records),
        "first_observed_date": dates[0].isoformat() if dates else None,
        "last_observed_date": dates[-1].isoformat() if dates else None,
        "active_calendar_months": len({(item.year, item.month) for item in dates}),
        "shipments_last_90_days_of_observed_period": sum(item >= as_of - timedelta(days=90) for item in dates),
        "shipments_last_365_days_of_observed_period": sum(item >= as_of - timedelta(days=365) for item in dates),
        "median_gap_days": round(statistics.median(gaps), 1) if gaps else None,
        "total_observed_weight_kg": round(sum(weights), 2) if weights else None,
        "total_observed_quantity": (
            round(sum(next(iter(quantities_by_unit.values()))), 2)
            if len(quantities_by_unit) == 1
            else None
        ),
        "total_observed_quantity_unit": (
            next(iter(quantities_by_unit)) if len(quantities_by_unit) == 1 else None
        ),
        "observed_quantity_totals_by_unit": {
            unit: round(sum(values), 2)
            for unit, values in sorted(quantities_by_unit.items())
        },
        "mixed_quantity_units": len(quantities_by_unit) > 1,
        "top_observed_suppliers": [
            {"supplier": supplier, "shipments": count}
            for supplier, count in suppliers.most_common(10)
        ],
        "coverage_warning": (
            "This summarizes only rows in the supplied dataset after conservative de-duplication. "
            "It is not a complete declaration of the buyer's imports."
        ),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--buyer")
    parser.add_argument("--product")
    parser.add_argument("--hs-prefix")
    args = parser.parse_args()

    result = summarize(read_rows(args.input), args.buyer, args.product, args.hs_prefix)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
