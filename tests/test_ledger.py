from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ledger import LedgerService
from app.models import (
    EvidenceRecord,
    LedgerLookupRequest,
    LedgerMergeRequest,
    OutreachEvent,
)
from app.storage import LocalJsonStore


def merge_payload(run_id: str, contacts: list[dict] | None = None) -> dict:
    return {
        "buyer": {
            "legal_name": "Dantzler Trade, Inc.",
            "customs_name": "Dantzler Trade Inc",
            "country": "United States / Puerto Rico",
            "address": "Toa Baja, Puerto Rico",
            "aliases": ["Dantzler Trade"],
            "business_type": "Importer under investigation",
            "source_ids": ["usr-shipment-1"],
        },
        "evidence": [
            {
                "evidence_id": "usr-shipment-1",
                "claim": "User supplied one customs record naming this buyer.",
                "claim_class": "FACT",
                "source_type": "user_input",
                "source_reference": "Current user message: MEDUWV360930",
                "evidence_grade": "B1",
                "boundary": "Proves only what the supplied record states.",
            },
            {
                "evidence_id": "official-contact-1",
                "claim": "The official site publishes the business email.",
                "claim_class": "FACT",
                "source_type": "official_domain",
                "source_reference": "Official contact page",
                "source_url": "https://example.com/contact",
                "evidence_grade": "A2",
                "boundary": "Does not prove procurement authority.",
            },
        ],
        "trade_records": [
            {
                "record_id": "MEDUWV360930",
                "date": "2026-05-10",
                "master_bill": "MEDUWV360930",
                "buyer": "Dantzler Trade Inc",
                "supplier_or_exporter": "Shanghai Cloudsky Int'l Co., Ltd",
                "product_raw": "PVC Celuka Foam Board",
                "normalized_product": "PVC Celuka foam board",
                "quantity": 54,
                "uom": "CAS",
                "weight_kg": 80656,
                "provider": "user-supplied customs dataset",
                "data_level": "bill",
                "date_semantics": "provider record date; not assumed to be arrival date",
                "source_ids": ["usr-shipment-1"],
            }
        ],
        "contacts": contacts
        if contacts is not None
        else [
            {
                "email": "sales@example.com",
                "entity": "Dantzler Trade, Inc.",
                "verification_status": "official_current",
                "employment_status": "not_applicable",
                "procurement_authority_status": "unverified",
                "route_class": "FORMAL_GENERAL",
                "recommended_use": "Ask for referral to PVC board purchasing.",
                "source_ids": ["official-contact-1"],
            }
        ],
        "run_manifest": {
            "run_id": run_id,
            "input_hash": "12345678abcdef",
        },
    }


@pytest.mark.asyncio
async def test_merge_lookup_and_preserve_old_contacts(tmp_path):
    service = LedgerService(LocalJsonStore(tmp_path / "ledger.json"))
    first = await service.merge(LedgerMergeRequest.model_validate(merge_payload("run-1")))
    assert first["created"] is True
    assert first["total_counts"] == {"trade": 1, "email": 1, "evidence": 2}

    second_payload = merge_payload(
        "run-2",
        contacts=[
            {
                "email": "procurement@example.com",
                "person_name": "Purchasing Team",
                "entity": "Dantzler Trade, Inc.",
                "verification_status": "official_current",
                "employment_status": "current",
                "procurement_authority_status": "confirmed",
                "route_class": "DIRECT_PROCUREMENT",
                "recommended_use": "Primary route.",
                "source_ids": ["official-contact-1"],
            }
        ],
    )
    second = await service.merge(LedgerMergeRequest.model_validate(second_payload))
    assert second["created"] is False
    assert second["previous_counts"]["email"] == 1
    assert second["added_counts"]["email"] == 1
    assert second["total_counts"]["email"] == 2

    lookup = await service.lookup(
        LedgerLookupRequest(
            legal_or_customs_name="Dantzler Trade Inc",
            country="United States / Puerto Rico",
        )
    )
    assert lookup["match_count"] == 1
    contacts = lookup["matches"][0]["ledger_record"]["contacts"]
    assert set(contacts) == {"sales@example.com", "procurement@example.com"}


def test_public_evidence_requires_direct_url():
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate(
            {
                "evidence_id": "bad-source",
                "claim": "Official site claim",
                "claim_class": "FACT",
                "source_type": "official_domain",
                "source_reference": "Official contact page",
                "evidence_grade": "A2",
                "boundary": "Missing URL must fail.",
            }
        )


@pytest.mark.asyncio
async def test_missing_evidence_binding_fails(tmp_path):
    service = LedgerService(LocalJsonStore(tmp_path / "ledger.json"))
    payload = merge_payload("run-bad")
    payload["contacts"][0]["source_ids"] = ["does-not-exist"]
    with pytest.raises(ValueError, match="missing evidence IDs"):
        await service.merge(LedgerMergeRequest.model_validate(payload))


@pytest.mark.asyncio
async def test_bounce_marks_only_exact_address(tmp_path):
    service = LedgerService(LocalJsonStore(tmp_path / "ledger.json"))
    payload = merge_payload("run-1")
    payload["contacts"].append(
        {
            "email": "procurement@example.com",
            "entity": "Dantzler Trade, Inc.",
            "verification_status": "official_current",
            "employment_status": "current",
            "procurement_authority_status": "confirmed",
            "route_class": "DIRECT_PROCUREMENT",
            "recommended_use": "Primary route.",
            "source_ids": ["official-contact-1"],
        }
    )
    merged = await service.merge(LedgerMergeRequest.model_validate(payload))
    await service.record_event(
        OutreachEvent(
            buyer_key=merged["buyer_key"],
            event_type="bounced",
            target="sales@example.com",
            event_time="2026-08-03T10:00:00+08:00",
            source_type="user_confirmed",
            source_reference="User confirmed a 550 response for this exact address.",
        )
    )
    lookup = await service.lookup(
        LedgerLookupRequest(
            legal_or_customs_name="Dantzler Trade, Inc.",
            country="United States / Puerto Rico",
        )
    )
    contacts = lookup["matches"][0]["ledger_record"]["contacts"]
    assert contacts["sales@example.com"]["route_class"] == "DO_NOT_USE"
    assert contacts["procurement@example.com"]["route_class"] == "DIRECT_PROCUREMENT"


def test_outreach_event_rejects_untrusted_source_type():
    with pytest.raises(ValidationError):
        OutreachEvent.model_validate(
            {
                "buyer_key": "buyer_x",
                "event_type": "sent",
                "target": "sales@example.com",
                "event_time": "2026-08-03T10:00:00+08:00",
                "source_type": "model_memory",
                "source_reference": "Old chat summary",
            }
        )
