from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from .models import (
    ContactRecord,
    LedgerLookupRequest,
    LedgerMergeRequest,
    OutreachEvent,
    RouteClass,
    VerificationStatus,
    utc_now_iso,
)
from .storage import LedgerStore


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", value)


def make_buyer_key(name: str, country: str) -> str:
    seed = f"{normalize_text(country)}|{normalize_text(name)}".encode("utf-8")
    return "buyer_" + hashlib.sha256(seed).hexdigest()[:20]


def stable_hash(value: Any, length: int = 24) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def union_strings(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            item = item.strip()
            key = item.casefold()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
    return result


def trade_key(record: dict[str, Any]) -> str:
    declared = record.get("record_id")
    if declared:
        return f"record:{normalize_text(declared)}"
    primary = [
        record.get("master_bill"),
        record.get("house_bill"),
        record.get("declaration_number"),
        record.get("item_number"),
    ]
    if any(primary):
        return "document:" + stable_hash(primary)
    fallback = {
        "date": record.get("date"),
        "buyer": normalize_text(record.get("buyer", "")),
        "supplier": normalize_text(record.get("supplier_or_exporter") or ""),
        "product": normalize_text(record.get("product_raw", "")),
        "quantity": record.get("quantity"),
        "uom": record.get("uom"),
        "weight_kg": record.get("weight_kg"),
    }
    return "fallback:" + stable_hash(fallback)


def contact_key(contact: dict[str, Any]) -> str:
    return contact["email"].strip().casefold()


def _candidate_names(record: dict[str, Any]) -> set[str]:
    identity = record.get("identity", {})
    names = [identity.get("legal_name"), identity.get("customs_name"), *identity.get("aliases", [])]
    return {normalize_text(name) for name in names if name}


def find_matching_keys(document: dict[str, Any], request: LedgerLookupRequest) -> list[str]:
    wanted = {
        normalize_text(request.legal_or_customs_name),
        *(normalize_text(alias) for alias in request.aliases),
    }
    wanted.discard("")
    country = normalize_text(request.country)
    matches: list[str] = []
    for key, record in document.get("buyers", {}).items():
        identity = record.get("identity", {})
        if normalize_text(identity.get("country", "")) != country:
            continue
        if wanted.intersection(_candidate_names(record)):
            matches.append(key)
    return matches


def _buyer_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "buyer_key": record["buyer_key"],
        "identity": record["identity"],
        "trade_count": len(record.get("trade_records", {})),
        "email_count": len(record.get("contacts", {})),
        "evidence_count": len(record.get("evidence", {})),
        "history_event_count": len(record.get("history_events", [])),
        "last_updated": record.get("updated_at"),
        "ledger_hash": stable_hash(record, 32),
    }


class LedgerService:
    def __init__(self, store: LedgerStore) -> None:
        self.store = store

    async def lookup(self, request: LedgerLookupRequest) -> dict[str, Any]:
        document = await self.store.read()
        keys = find_matching_keys(document, request)
        matches = []
        for key in keys:
            record = document["buyers"][key]
            matches.append({**_buyer_summary(record), "ledger_record": record})
        return {
            "status": "LEDGER_LOADED",
            "match_count": len(matches),
            "matches": matches,
            "ledger_updated_at": document.get("updated_at"),
        }

    async def merge(self, request: LedgerMergeRequest) -> dict[str, Any]:
        payload = request.model_dump(mode="json")

        def mutate(document: dict[str, Any]) -> dict[str, Any]:
            lookup = LedgerLookupRequest(
                legal_or_customs_name=request.buyer.legal_name,
                country=request.buyer.country,
                aliases=union_strings(
                    request.buyer.aliases,
                    [request.buyer.customs_name] if request.buyer.customs_name else [],
                ),
            )
            matches = find_matching_keys(document, lookup)
            warnings: list[str] = []
            if len(matches) > 1:
                raise ValueError(f"ambiguous buyer identity: matched {len(matches)} ledger records")
            buyer_key = matches[0] if matches else make_buyer_key(request.buyer.legal_name, request.buyer.country)
            existing = document["buyers"].get(buyer_key)
            created = existing is None
            if existing is None:
                existing = {
                    "buyer_key": buyer_key,
                    "identity": payload["buyer"],
                    "evidence": {},
                    "trade_records": {},
                    "contacts": {},
                    "history_events": [],
                    "runs": [],
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
                document["buyers"][buyer_key] = existing

            previous_counts = {
                "trade": len(existing.get("trade_records", {})),
                "email": len(existing.get("contacts", {})),
                "evidence": len(existing.get("evidence", {})),
            }

            old_identity = existing.get("identity", {})
            new_identity = payload["buyer"]
            old_identity["legal_name"] = old_identity.get("legal_name") or new_identity["legal_name"]
            old_identity["customs_name"] = new_identity.get("customs_name") or old_identity.get("customs_name")
            old_identity["country"] = old_identity.get("country") or new_identity["country"]
            old_identity["address"] = new_identity.get("address") or old_identity.get("address")
            old_identity["business_type"] = new_identity.get("business_type") or old_identity.get("business_type")
            old_identity["aliases"] = union_strings(
                old_identity.get("aliases", []),
                new_identity.get("aliases", []),
                [new_identity["legal_name"]],
                [new_identity["customs_name"]] if new_identity.get("customs_name") else [],
            )
            old_identity["source_ids"] = union_strings(
                old_identity.get("source_ids", []), new_identity.get("source_ids", [])
            )
            existing["identity"] = old_identity

            evidence_map = existing.setdefault("evidence", {})
            evidence_added = 0
            evidence_updated = 0
            for evidence in payload["evidence"]:
                evidence_id = evidence["evidence_id"]
                if evidence_id in evidence_map and evidence_map[evidence_id] != evidence:
                    raise ValueError(
                        f"evidence ID collision for {evidence_id}; submit a new unique evidence_id to preserve both sources"
                    )
                if evidence_id in evidence_map:
                    evidence_updated += 1
                else:
                    evidence_added += 1
                evidence_map[evidence_id] = evidence

            known_evidence = set(evidence_map)
            referenced_ids = set(old_identity.get("source_ids", []))
            for item in [*payload["trade_records"], *payload["contacts"]]:
                referenced_ids.update(item["source_ids"])
            missing_sources = sorted(referenced_ids - known_evidence)
            if missing_sources:
                raise ValueError("records reference missing evidence IDs: " + ", ".join(missing_sources))

            trades = existing.setdefault("trade_records", {})
            trade_added = 0
            trade_updated = 0
            for trade in payload["trade_records"]:
                key = trade_key(trade)
                if key in trades:
                    trade_updated += 1
                    prior = trades[key]
                    trade["source_ids"] = union_strings(prior.get("source_ids", []), trade["source_ids"])
                    trade["first_seen"] = prior.get("first_seen", utc_now_iso())
                else:
                    trade_added += 1
                    trade["first_seen"] = utc_now_iso()
                trade["last_seen"] = utc_now_iso()
                trades[key] = trade

            contacts = existing.setdefault("contacts", {})
            email_added = 0
            email_updated = 0
            for contact in payload["contacts"]:
                key = contact_key(contact)
                if key in contacts:
                    email_updated += 1
                    prior = contacts[key]
                    merged = self._merge_contact(prior, contact)
                else:
                    email_added += 1
                    merged = contact
                    merged["first_seen"] = merged.get("first_seen") or utc_now_iso()
                contacts[key] = merged

            manifest = payload["run_manifest"]
            run_ids = {run.get("run_id") for run in existing.setdefault("runs", [])}
            if manifest["run_id"] not in run_ids:
                existing["runs"].append(manifest)
            if manifest.get("declared_previous_trade_count") is not None and (
                manifest["declared_previous_trade_count"] != previous_counts["trade"]
            ):
                warnings.append("declared previous trade count did not match the loaded ledger")
            if manifest.get("declared_previous_email_count") is not None and (
                manifest["declared_previous_email_count"] != previous_counts["email"]
            ):
                warnings.append("declared previous email count did not match the loaded ledger")

            existing["updated_at"] = utc_now_iso()
            total_counts = {
                "trade": len(trades),
                "email": len(contacts),
                "evidence": len(evidence_map),
            }
            return {
                "status": "LEDGER_MERGED",
                "created": created,
                "buyer_key": buyer_key,
                "previous_counts": previous_counts,
                "submitted_counts": {
                    "trade": len(payload["trade_records"]),
                    "email": len(payload["contacts"]),
                    "evidence": len(payload["evidence"]),
                },
                "added_counts": {"trade": trade_added, "email": email_added, "evidence": evidence_added},
                "updated_counts": {
                    "trade": trade_updated,
                    "email": email_updated,
                    "evidence": evidence_updated,
                },
                "total_counts": total_counts,
                "warnings": warnings,
            }

        result, document = await self.store.atomic_update(mutate)
        record = document["buyers"][result["buyer_key"]]
        result["ledger_hash"] = stable_hash(record, 32)
        result["ledger_updated_at"] = document.get("updated_at")
        return result

    @staticmethod
    def _merge_contact(prior: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(prior)
        for field in ["person_name", "title_as_sourced", "risk_note"]:
            if incoming.get(field):
                merged[field] = incoming[field]
        for field in ["entity", "recommended_use", "privacy_class"]:
            merged[field] = incoming.get(field) or prior.get(field)
        merged["source_ids"] = union_strings(prior.get("source_ids", []), incoming.get("source_ids", []))
        merged["first_seen"] = prior.get("first_seen") or incoming.get("first_seen") or utc_now_iso()
        merged["last_checked"] = incoming.get("last_checked") or prior.get("last_checked")

        if prior.get("verification_status") == VerificationStatus.BOUNCED_SPECIFIC_ADDRESS.value:
            merged["verification_status"] = VerificationStatus.BOUNCED_SPECIFIC_ADDRESS.value
            merged["route_class"] = RouteClass.DO_NOT_USE.value
        else:
            rank = {
                VerificationStatus.MISSING.value: 0,
                VerificationStatus.INFERRED.value: 1,
                VerificationStatus.HISTORICAL.value: 2,
                VerificationStatus.DIRECTORY_CURRENT.value: 3,
                VerificationStatus.OFFICIAL_CURRENT.value: 4,
                VerificationStatus.USER_CONFIRMED_CURRENT.value: 5,
            }
            old_status = prior.get("verification_status", VerificationStatus.MISSING.value)
            new_status = incoming.get("verification_status", VerificationStatus.MISSING.value)
            merged["verification_status"] = new_status if rank.get(new_status, 0) >= rank.get(old_status, 0) else old_status
            merged["route_class"] = incoming.get("route_class") or prior.get("route_class")
        if incoming.get("employment_status") == "current" or prior.get("employment_status") != "current":
            merged["employment_status"] = incoming.get("employment_status", prior.get("employment_status"))
        if incoming.get("procurement_authority_status") == "confirmed":
            merged["procurement_authority_status"] = "confirmed"
        return merged

    async def record_event(self, event: OutreachEvent) -> dict[str, Any]:
        payload = event.model_dump(mode="json")

        def mutate(document: dict[str, Any]) -> dict[str, Any]:
            buyer = document.get("buyers", {}).get(event.buyer_key)
            if buyer is None:
                raise ValueError("buyer_key does not exist")
            events = buyer.setdefault("history_events", [])
            event_key = stable_hash(payload, 32)
            if any(item.get("event_key") == event_key for item in events):
                return {"status": "EVENT_ALREADY_RECORDED", "buyer_key": event.buyer_key, "event_key": event_key}
            stored = {**payload, "event_key": event_key, "recorded_at": utc_now_iso()}
            events.append(stored)
            if event.event_type == "bounced":
                target = event.target.strip().casefold()
                contact = buyer.get("contacts", {}).get(target)
                if contact is not None:
                    contact["verification_status"] = VerificationStatus.BOUNCED_SPECIFIC_ADDRESS.value
                    contact["route_class"] = RouteClass.DO_NOT_USE.value
                    note = f"Specific address bounce recorded from {event.source_reference}."
                    contact["risk_note"] = " ".join(filter(None, [contact.get("risk_note"), note]))
            buyer["updated_at"] = utc_now_iso()
            return {"status": "EVENT_RECORDED", "buyer_key": event.buyer_key, "event_key": event_key}

        result, document = await self.store.atomic_update(mutate)
        record = document["buyers"][event.buyer_key]
        result["ledger_hash"] = stable_hash(record, 32)
        result["history_event_count"] = len(record.get("history_events", []))
        return result
