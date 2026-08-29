#!/usr/bin/env python3
"""Build a de-duplicated seed plan for an exhaustive Source/Pivot investigation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def quote(value: Any) -> str:
    return f'"{clean(value)}"'


def canonical_query(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"\b(co|company|ltd|limited|inc|corp|corporation)\b\.?", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def product_phrase(product: Any) -> str:
    text = clean(product)
    normalized = re.sub(r"[-_/]+", " ", text.casefold())
    normalized = re.sub(r"\s+", " ", normalized)
    excluded = (
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
    if any(phrase in normalized for phrase in excluded):
        words = re.findall(r"[A-Za-z0-9.-]+", text)
        return " ".join(words[:8])
    exact = (
        "pvc foam board",
        "pvc foamed board",
        "foamed pvc board",
        "expanded pvc sheet",
        "pvc celuka board",
        "pvc crust board",
        "pvc发泡板",
        "聚氯乙烯发泡板",
    )
    if any(phrase in normalized for phrase in exact):
        return "PVC foam board"
    words = re.findall(r"[A-Za-z0-9.-]+", text)
    return " ".join(words[:6])


def government_domain(country: str) -> str:
    folded = country.casefold()
    if "philipp" in folded:
        return "gov.ph"
    if "vietnam" in folded or "viet nam" in folded:
        return "gov.vn"
    if "puerto rico" in folded or "united states" in folded or folded == "usa":
        return "pr.gov" if "puerto rico" in folded else "gov"
    if "china" in folded:
        return "gov.cn"
    return "gov"


def add_query(
    rows: list[dict[str, str]],
    seen: set[str],
    lane: str,
    query: str,
    purpose: str,
) -> None:
    query = clean(query)
    if not query:
        return
    canonical = canonical_query(query)
    if not canonical or canonical in seen:
        return
    seen.add(canonical)
    rows.append(
        {
            "lane": lane,
            "query": query,
            "canonical_query": canonical,
            "purpose": purpose,
            "status": "planned",
        }
    )


def build_plan(
    normalized: dict[str, Any], policy: dict[str, Any], mode: str
) -> dict[str, Any]:
    record = normalized.get("record", {})
    resolved_mode = {
        "quick": "deep-dive",
        "standard": "deep-dive",
    }.get(mode, mode)
    policy_mode = policy["modes"][resolved_mode]
    buyer = clean(record.get("buyer"))
    supplier = clean(record.get("supplier"))
    bill = clean(record.get("master_bill") or record.get("house_bill"))
    product = product_phrase(record.get("product"))
    hs = clean(record.get("hs_code") or record.get("hs4"))
    country = clean(
        record.get("destination_country")
        or record.get("country_code")
        or record.get("buyer_address")
    )
    address = clean(record.get("buyer_address"))
    address_hint = " ".join(address.split()[-6:]) if address else ""
    gov_domain = government_domain(f"{country} {address}")

    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    if policy_mode.get("offline_only"):
        return {
            "mode": resolved_mode,
            "buyer": buyer,
            "cache_key": None,
            "policy": policy_mode,
            "query_ledger": [],
            "web_search_batches": [],
            "open_page_policy": {"browse": False},
            "recovery_gate": {
                "maximum_queries": 0,
                "allowed_questions": [],
            },
            "circuit_breaker": policy["circuit_breaker"],
            "completion_rule": "Fast Scan is preliminary and cannot issue research_complete.",
        }

    add_query(rows, seen, "entity_contact", quote(buyer), "Resolve exact company identity")
    add_query(
        rows,
        seen,
        "entity_contact",
        f"{quote(buyer)} {country} company registry",
        "Find official or attributable registration",
    )
    add_query(
        rows,
        seen,
        "entity_contact",
        f"{quote(buyer)} official website contact",
        "Find first-party business and contact details",
    )
    if address_hint:
        add_query(
            rows,
            seen,
            "entity_contact",
            f"{quote(buyer)} {quote(address_hint)}",
            "Confirm address/entity match",
        )

    if bill:
        add_query(
            rows,
            seen,
            "trade",
            quote(bill),
            "Seek an exact public shipment match",
        )
    add_query(
        rows,
        seen,
        "trade",
        f"{quote(buyer)} {quote(product)} {hs}".strip(),
        "Find product-specific purchase evidence",
    )
    if supplier:
        add_query(
            rows,
            seen,
            "trade",
            f"{quote(buyer)} {quote(supplier)}",
            "Check buyer-supplier pairing",
        )
    add_query(
        rows,
        seen,
        "trade",
        f"{quote(buyer)} imports {quote(product)}",
        "Find repeat-purchase history",
    )

    add_query(
        rows,
        seen,
        "legal_contact",
        f"site:{gov_domain} {quote(buyer)}",
        "Target official registry/court/regulator records",
    )
    add_query(
        rows,
        seen,
        "legal_contact",
        f"{quote(buyer)} lawsuit OR judgment OR revocation",
        "Limited adverse-record search",
    )
    add_query(
        rows,
        seen,
        "legal_contact",
        f'site:linkedin.com/in {quote(buyer)} procurement OR purchasing',
        "Find an attributable procurement professional",
    )

    # These are seed queries, not a completion budget. Every generated alias,
    # person, address, phone, tax ID, domain, supplier and Peer becomes a later
    # PivotEvent and must be consumed by a distinct execution receipt.
    batch_size = int(policy_mode.get("search_batch_size", 4))
    web_batches = [
        [row["query"] for row in rows[index : index + batch_size]]
        for index in range(0, len(rows), batch_size)
    ]

    cache_basis = "|".join(
        [country.casefold(), canonical_query(buyer), canonical_query(address)]
    )
    cache_key = hashlib.sha256(cache_basis.encode("utf-8")).hexdigest()[:20]

    return {
        "mode": resolved_mode,
        "buyer": buyer,
        "cache_key": cache_key,
        "policy": policy_mode,
        "query_ledger": rows,
        "web_search_batches": web_batches,
        "open_page_policy": {
            "maximum_total_as_completion": None,
            "maximum_per_domain_as_completion": None,
            "preserve_site_retry_circuit_breaker": True,
        },
        "recovery_gate": {
            "maximum_queries_as_completion": None,
            "allowed_questions": [
                "Could this change the legal-entity match?",
                "Could this change observed versus repeat product purchasing?",
                "Could this produce a usable official contact channel?",
                "Could this change the risk or credit recommendation?",
            ],
        },
        "circuit_breaker": policy["circuit_breaker"],
        "completion_rule": "Only the unified Runtime may close research after every applicable Source Family, Pivot, Peer, promoted Anchor, visual queue and Evidence binding is closed.",
        "resource_limit_rule": "Pause as PAUSED_RESOURCE_LIMIT or INCOMPLETE_BLOCKED; never convert a time, query, page or first-positive limit into COMPLETE.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--mode",
        choices=("fast-scan", "deep-dive", "quick", "standard"),
        default="deep-dive",
        help="quick/standard are accepted as legacy aliases for deep-dive.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "references"
        / "runtime-policy.json",
    )
    args = parser.parse_args()

    normalized = json.loads(args.input.read_text(encoding="utf-8-sig"))
    policy = json.loads(args.policy.read_text(encoding="utf-8-sig"))
    result = build_plan(normalized, policy, args.mode)
    unicode_rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(unicode_rendered + "\n", encoding="utf-8")
    else:
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
