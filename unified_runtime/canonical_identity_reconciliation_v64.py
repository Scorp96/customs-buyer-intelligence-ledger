"""Read-only canonical identity duplicate/conflict detection for CBI v6.4.

This module never mutates the canonical registry and never authorizes automatic
merges.  It only identifies pairs that require audited reconciliation.
"""

from __future__ import annotations

from itertools import combinations
import re
import unicodedata
from typing import Any, Iterable


_NAME_TOKEN_MAP = {
    "co": "company",
    "company": "company",
    "ltd": "limited",
    "limited": "limited",
    "corp": "corporation",
    "corporation": "corporation",
    "inc": "incorporated",
    "incorporated": "incorporated",
}


def _text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _normalized_country(value: Any) -> str:
    return " ".join(_text(value).split())


def _normalized_legal_name(value: Any) -> str:
    text = _text(value).replace("&", " and ")
    tokens = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    normalized = [_NAME_TOKEN_MAP.get(token, token) for token in tokens]
    return " ".join(normalized)


def _normalized_compact(value: Any) -> str:
    return "".join(ch for ch in _text(value) if ch.isalnum())


def _normalized_tax_id(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _tax_ids(record: dict[str, Any]) -> set[str]:
    values: list[Any] = [record.get("tax_id")]
    values.extend(record.get("tax_ids") or [])
    return {item for item in (_normalized_tax_id(value) for value in values) if item}


def _addresses(record: dict[str, Any]) -> set[str]:
    values: list[Any] = [record.get("address")]
    values.extend(record.get("addresses") or [])
    return {item for item in (_normalized_compact(value) for value in values) if item}


def _normalized_external_id(value: Any) -> str:
    text = _text(value)
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    return text.rstrip("/")


def _external_ids(record: dict[str, Any]) -> set[str]:
    return {
        item
        for item in (_normalized_external_id(value) for value in (record.get("external_ids") or []))
        if item
    }


def _account_id(record: dict[str, Any]) -> str:
    return str(record.get("account_id") or "").strip()


def _pair_item(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_id = _account_id(left)
    right_id = _account_id(right)
    if not left_id or not right_id or left_id == right_id:
        return None

    left_country = _normalized_country(left.get("country"))
    right_country = _normalized_country(right.get("country"))
    if not left_country or left_country != right_country:
        return None

    left_tax = _tax_ids(left)
    right_tax = _tax_ids(right)
    shared_tax = left_tax & right_tax

    left_name = _normalized_legal_name(left.get("name"))
    right_name = _normalized_legal_name(right.get("name"))
    name_match = bool(left_name and left_name == right_name)

    shared_external = _external_ids(left) & _external_ids(right)
    shared_address = _addresses(left) & _addresses(right)
    tax_conflict = bool(left_tax and right_tax and not shared_tax)

    evidence_basis: list[str] = []
    if shared_tax:
        evidence_basis.append("SHARED_TAX_ID")
    if name_match:
        evidence_basis.append("LEGAL_NAME_MATCH")
    if shared_external:
        evidence_basis.append("SHARED_EXTERNAL_ID")
    if shared_address:
        evidence_basis.append("SHARED_ADDRESS")

    if shared_tax:
        status = "DETERMINISTIC_DUPLICATE_CANDIDATE"
        recommended_action = "AUDIT_CANONICAL_DUPLICATE_AND_SELECT_SURVIVING_ACCOUNT"
    elif tax_conflict and (name_match or shared_external):
        status = "IDENTITY_CONFLICT"
        if name_match:
            evidence_basis.append("LEGAL_NAME_MATCH_TAX_ID_CONFLICT")
        else:
            evidence_basis.append("SHARED_EXTERNAL_ID_TAX_ID_CONFLICT")
        recommended_action = "RESOLVE_IDENTITY_CONFLICT_BEFORE_ANY_MERGE"
    elif name_match or shared_external:
        status = "REVIEW_REQUIRED"
        recommended_action = "AUDIT_IDENTITY_BEFORE_CANONICAL_RECONCILIATION"
    else:
        return None

    return {
        "account_ids": sorted([left_id, right_id]),
        "status": status,
        "evidence_basis": sorted(set(evidence_basis)),
        "auto_merge_allowed": False,
        "recommended_action": recommended_action,
    }


def _cluster_item(
    component_indexes: list[int],
    snapshot: list[dict[str, Any]],
    pair_items: list[dict[str, Any]],
) -> dict[str, Any]:
    records = [snapshot[index] for index in component_indexes]
    account_ids = sorted(_account_id(record) for record in records)
    account_id_set = set(account_ids)
    component_pairs = [
        item for item in pair_items if set(item["account_ids"]).issubset(account_id_set)
    ]

    evidence_basis = {
        basis
        for item in component_pairs
        for basis in item.get("evidence_basis", [])
    }
    tax_sets = [_tax_ids(record) for record in records]
    all_have_tax = all(tax_sets)
    shared_by_all = set.intersection(*tax_sets) if all_have_tax else set()
    any_shared_tax = any("SHARED_TAX_ID" in item.get("evidence_basis", []) for item in component_pairs)
    any_conflict = any(item.get("status") == "IDENTITY_CONFLICT" for item in component_pairs)

    if any_conflict:
        status = "IDENTITY_CONFLICT"
        recommended_action = "RESOLVE_IDENTITY_CONFLICT_BEFORE_ANY_MERGE"
    elif shared_by_all:
        status = "DETERMINISTIC_DUPLICATE_CANDIDATE"
        recommended_action = "AUDIT_CANONICAL_DUPLICATE_AND_SELECT_SURVIVING_ACCOUNT"
    else:
        status = "REVIEW_REQUIRED"
        recommended_action = "AUDIT_IDENTITY_BEFORE_CANONICAL_RECONCILIATION"
        if any_shared_tax:
            evidence_basis.discard("SHARED_TAX_ID")
            evidence_basis.add("PARTIAL_SHARED_TAX_ID")

    return {
        "account_ids": account_ids,
        "status": status,
        "evidence_basis": sorted(evidence_basis),
        "auto_merge_allowed": False,
        "recommended_action": recommended_action,
    }


def detect_identity_reconciliation(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a read-only reconciliation queue without altering input records."""
    snapshot = [dict(record) for record in records]
    indexed_by_account = {
        _account_id(record): index
        for index, record in enumerate(snapshot)
        if _account_id(record)
    }
    pair_items = [
        item
        for left, right in combinations(snapshot, 2)
        if (item := _pair_item(left, right)) is not None
    ]

    adjacency: dict[int, set[int]] = {}
    for item in pair_items:
        left_id, right_id = item["account_ids"]
        left_index = indexed_by_account[left_id]
        right_index = indexed_by_account[right_id]
        adjacency.setdefault(left_index, set()).add(right_index)
        adjacency.setdefault(right_index, set()).add(left_index)

    components: list[list[int]] = []
    unseen = set(adjacency)
    while unseen:
        start = unseen.pop()
        component = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            for neighbor in adjacency.get(current, set()):
                if neighbor in component:
                    continue
                component.add(neighbor)
                unseen.discard(neighbor)
                pending.append(neighbor)
        components.append(sorted(component))

    items = [_cluster_item(component, snapshot, pair_items) for component in components]
    items.sort(key=lambda item: (item["account_ids"], item["status"]))
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "schema": "cbi.canonical-identity-reconciliation.v6.4",
        "read_only": True,
        "auto_merge_allowed": False,
        "pair_count": len(pair_items),
        "cluster_count": len(items),
        "counts": counts,
        "items": items,
    }
