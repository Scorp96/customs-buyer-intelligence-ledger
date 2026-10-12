"""Read-only catalogue HS6 *candidate* intake; never customs or buyer proof.

This intentionally does not modify version-pinned SOAP_MACHINERY profiles or
the immutable customer/event store. A local/authorized operator may supply a
validated JSON export of the user's machinery audit workbook.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_HS6 = re.compile(r"^[0-9]{6}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROW_ID = re.compile(r"^SMARTORS-[0-9]{8}-[0-9]{4}$")
_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNDETERMINED"}
_DISALLOWED_CLAIMS = {
    "national_tariff_verified", "buyer_verified", "actual_import_verified",
    "seller_capability_verified", "binding_customs_classification",
    "product_purchase_verified", "hs10_confirmed", "tariff_ruling",
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _require_clean_str(value: Any, label: str, maximum: int = 300) -> str:
    text = _clean(value)
    if not text or len(text) > maximum:
        raise ValueError(f"CBI_MACHINERY_CATALOG_{label}_REQUIRED")
    return text


def _aliases(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("CBI_MACHINERY_CATALOG_ALIASES_MUST_BE_ARRAY")
    seen: set[str] = set()
    out: list[str] = []
    for term in value:
        cleaned = _require_clean_str(term, "ALIAS", 180)
        key = cleaned.casefold()
        if key not in seen:
            out.append(cleaned)
            seen.add(key)
    if not out or len(out) > 10:
        raise ValueError("CBI_MACHINERY_CATALOG_ALIASES_COUNT_INVALID")
    return out


def validate_machinery_catalog_candidates(
    raw_rows: list[dict[str, Any]],
    *,
    expected_row_count: int | None = None,
    expected_hs6_candidate_count: int | None = None,
) -> dict[str, Any]:
    """Validate a scoped source workbook export; return sanitized discovery rows.

    Existence of a six-digit candidate never upgrades it to official product
    classification, national HS extension or observed importer purchase.
    """
    if not isinstance(raw_rows, list) or not raw_rows or len(raw_rows) > 1000:
        raise ValueError("CBI_MACHINERY_CATALOG_INPUT_ROWS_INVALID")
    if expected_row_count is not None and len(raw_rows) != expected_row_count:
        raise ValueError("CBI_MACHINERY_CATALOG_ROW_COUNT_MISMATCH")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    source_hashes: set[str] = set()
    candidates = 0
    for index, item in enumerate(raw_rows):
        if not isinstance(item, dict):
            raise ValueError("CBI_MACHINERY_CATALOG_ROW_NOT_OBJECT")
        if any(key in item for key in _DISALLOWED_CLAIMS):
            raise ValueError("CBI_MACHINERY_CATALOG_UNSUPPORTED_VERIFICATION_CLAIM")
        row_id = _require_clean_str(item.get("catalog_row_id"), "ROW_ID", 32)
        if not _ROW_ID.fullmatch(row_id):
            raise ValueError("CBI_MACHINERY_CATALOG_ROW_ID_INVALID")
        if row_id in seen_ids:
            raise ValueError("CBI_MACHINERY_CATALOG_DUPLICATE_ROW_ID")
        seen_ids.add(row_id)
        group = _require_clean_str(item.get("catalog_group"), "GROUP", 80)
        name_en = _require_clean_str(item.get("product_name_english"), "ENGLISH_NAME")
        name_zh = _require_clean_str(item.get("product_name_chinese"), "CHINESE_NAME")
        raw_code = item.get("hs6_candidate")
        hs6 = _clean(raw_code) if raw_code not in (None, "") else None
        if hs6 and not _HS6.fullmatch(hs6):
            raise ValueError("CBI_MACHINERY_CATALOG_HS6_FORMAT_INVALID")
        confidence = _clean(item.get("candidate_confidence") or "UNDETERMINED").upper()
        if confidence not in _CONFIDENCE:
            raise ValueError("CBI_MACHINERY_CATALOG_CONFIDENCE_INVALID")
        reason = _clean(item.get("engineering_classification_conditions"))
        if not hs6 and not reason:
            raise ValueError("CBI_MACHINERY_CATALOG_UNCLASSIFIED_REQUIRES_REASON")
        sha = _clean(item.get("source_document_sha256")).lower()
        if not _SHA256.fullmatch(sha):
            raise ValueError("CBI_MACHINERY_CATALOG_SOURCE_SHA256_INVALID")
        source_hashes.add(sha)
        terms = _aliases(item.get("search_aliases_english"))
        candidates += bool(hs6)
        rows.append({
            "catalog_row_id": row_id,
            "catalog_group": group,
            "catalog_page": _clean(item.get("catalog_page")),
            "product_name_chinese": name_zh,
            "product_name_english": name_en,
            "hs6_candidate": hs6,
            "candidate_confidence": confidence,
            "engineering_classification_conditions": reason,
            "search_aliases_english": terms,
            "source_document_sha256": sha,
            "source_row_number": index + 2,
            "classification_status": "HS6_CANDIDATE_NOT_RULING" if hs6
                                     else "PENDING_TECHNICAL_CLASSIFICATION",
            "national_hs_code": None,
            "verified_buyer": False,
            "seller_model_capability_verified": False,
        })
    if expected_hs6_candidate_count is not None and candidates != expected_hs6_candidate_count:
        raise ValueError("CBI_MACHINERY_CATALOG_HS6_COUNT_MISMATCH")
    return {
        "schema": "cbi.machinery-catalog-search-seeds.v6.4",
        "rows": rows,
        "row_count": len(rows),
        "hs6_candidate_count": candidates,
        "pending_classification_count": len(rows) - candidates,
        "source_sha256_set": sorted(source_hashes),
        "source_kind": "USER_CATALOG_HS_WORKBOOK_AUDIT",
        "source_edition": "WCO_HS2022_CANDIDATE_REVIEW",
        "seller_capability": "UNCONFIGURED",
        "national_tariff_codes_confirmed": 0,
        "actual_import_records_verified": 0,
        "candidate_rows_are_not_customs_rulings": True,
        "persistent_mutation_performed": False,
        "search_execution_performed": False,
    }


def plan_catalog_customs_queries(
    validated: dict[str, Any], *,
    target_country: str,
    limit: int = 200,
) -> dict[str, Any]:
    """Build query *seeds* for discovery; execution receipts are still required."""
    if validated.get("schema") != "cbi.machinery-catalog-search-seeds.v6.4":
        raise ValueError("CBI_MACHINERY_CATALOG_VALIDATED_SCHEMA_REQUIRED")
    country = _require_clean_str(target_country, "TARGET_COUNTRY", 120)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("CBI_MACHINERY_CATALOG_LIMIT_INVALID")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in validated["rows"]:
        code = row.get("hs6_candidate")
        for name in row["search_aliases_english"]:
            for query in (
                (f'{code} "{name}" {country}' if code else None),
                f'"{name}" {country}',
            ):
                if query is None:
                    continue
                key = query.casefold()
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "query": query,
                    "catalog_row_id": row["catalog_row_id"],
                    "hs6_candidate": code,
                    "query_uses_unverified_hs6_candidate": bool(code),
                    "search_execution_performed": False,
                    "evidence_ids": [],
                    "buyer_identity_verified": False,
                })
    return {
        "status": "PLANNED",
        "schema": "cbi.machinery-catalog-customs-query-plan.v6.4",
        "target_country": country,
        "candidate_query_count": len(out),
        "returned_count": min(limit, len(out)),
        "truncated": len(out) > limit,
        "queries": out[:limit],
        "source_coverage_complete": False,
        "planning_is_execution_proof": False,
        "host_execution_required": True,
        "persistent_mutation_performed": False,
    }
