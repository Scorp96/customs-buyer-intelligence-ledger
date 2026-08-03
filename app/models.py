from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceType(str, Enum):
    GOVERNMENT_REGISTRY = "government_registry"
    OFFICIAL_DOMAIN = "official_domain"
    OFFICIAL_SOCIAL = "official_social"
    COURT_OR_REGULATOR = "court_or_regulator"
    TRADE_DATABASE = "trade_database"
    PROFESSIONAL_SOURCE = "professional_source"
    THIRD_PARTY_DIRECTORY = "third_party_directory"
    USER_INPUT = "user_input"
    UPLOADED_RECORD = "uploaded_record"
    CONNECTOR_RECEIPT = "connector_receipt"


PUBLIC_SOURCE_TYPES = {
    SourceType.GOVERNMENT_REGISTRY,
    SourceType.OFFICIAL_DOMAIN,
    SourceType.OFFICIAL_SOCIAL,
    SourceType.COURT_OR_REGULATOR,
    SourceType.TRADE_DATABASE,
    SourceType.PROFESSIONAL_SOURCE,
    SourceType.THIRD_PARTY_DIRECTORY,
}


class RouteClass(str, Enum):
    DIRECT_PROCUREMENT = "DIRECT_PROCUREMENT"
    FORMAL_GENERAL = "FORMAL_GENERAL"
    ALTERNATIVE_REFERRAL = "ALTERNATIVE_REFERRAL"
    VERIFY_ONLY = "VERIFY_ONLY"
    DO_NOT_USE = "DO_NOT_USE"


class VerificationStatus(str, Enum):
    OFFICIAL_CURRENT = "official_current"
    USER_CONFIRMED_CURRENT = "user_confirmed_current"
    DIRECTORY_CURRENT = "directory_current"
    HISTORICAL = "historical"
    INFERRED = "inferred"
    BOUNCED_SPECIFIC_ADDRESS = "bounced_specific_address"
    MISSING = "missing"


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=120)
    claim: str = Field(min_length=1, max_length=2000)
    claim_class: Literal["FACT", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION", "UNKNOWN"]
    source_type: SourceType
    source_reference: str = Field(min_length=1, max_length=2000)
    source_url: HttpUrl | None = None
    source_date: str | None = None
    checked_at: str = Field(default_factory=utc_now_iso)
    evidence_grade: Literal["A1", "A2", "B1", "B2", "C1", "C2", "D"]
    boundary: str = Field(min_length=1, max_length=2000)
    conflict: str | None = None

    @model_validator(mode="after")
    def require_url_for_public_sources(self) -> "EvidenceRecord":
        if self.source_type in PUBLIC_SOURCE_TYPES and self.source_url is None:
            raise ValueError("public evidence requires source_url")
        return self


class BuyerIdentity(StrictModel):
    legal_name: str = Field(min_length=1, max_length=300)
    customs_name: str | None = Field(default=None, max_length=300)
    country: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    business_type: str | None = Field(default=None, max_length=1000)
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("aliases")
    @classmethod
    def unique_aliases(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = value.strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result


class TradeRecord(StrictModel):
    record_id: str | None = Field(default=None, max_length=200)
    date: str = Field(min_length=1, max_length=50)
    master_bill: str | None = Field(default=None, max_length=120)
    house_bill: str | None = Field(default=None, max_length=120)
    declaration_number: str | None = Field(default=None, max_length=120)
    item_number: str | None = Field(default=None, max_length=120)
    buyer: str = Field(min_length=1, max_length=300)
    supplier_or_exporter: str | None = Field(default=None, max_length=300)
    product_raw: str = Field(min_length=1, max_length=3000)
    normalized_product: str | None = Field(default=None, max_length=300)
    quantity: float | None = None
    uom: str | None = Field(default=None, max_length=50)
    weight_kg: float | None = None
    provider: str = Field(min_length=1, max_length=200)
    data_level: Literal["shipment", "bill", "declaration", "item", "unknown"] = "unknown"
    date_semantics: str = Field(min_length=1, max_length=300)
    source_ids: list[str] = Field(min_length=1)


class ContactRecord(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    person_name: str | None = Field(default=None, max_length=300)
    title_as_sourced: str | None = Field(default=None, max_length=500)
    entity: str = Field(min_length=1, max_length=300)
    first_seen: str | None = None
    last_checked: str = Field(default_factory=utc_now_iso)
    verification_status: VerificationStatus
    employment_status: Literal["current", "historical", "unknown", "not_applicable"] = "unknown"
    procurement_authority_status: Literal["confirmed", "unverified", "not_procurement"] = "unverified"
    route_class: RouteClass
    risk_note: str | None = Field(default=None, max_length=2000)
    recommended_use: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(min_length=1)
    privacy_class: Literal["public_business", "private_or_sensitive"] = "public_business"

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[1] or any(ch.isspace() for ch in value):
            raise ValueError("invalid email shape")
        return value


class RunManifest(StrictModel):
    run_id: str = Field(min_length=1, max_length=200)
    input_hash: str = Field(min_length=8, max_length=200)
    investigated_at: str = Field(default_factory=utc_now_iso)
    prior_ledger_name: str | None = Field(default=None, max_length=500)
    prior_ledger_date: str | None = None
    declared_previous_trade_count: int | None = Field(default=None, ge=0)
    declared_previous_email_count: int | None = Field(default=None, ge=0)


class LedgerLookupRequest(StrictModel):
    legal_or_customs_name: str = Field(min_length=1, max_length=300)
    country: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class LedgerMergeRequest(StrictModel):
    buyer: BuyerIdentity
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=500)
    trade_records: list[TradeRecord] = Field(default_factory=list, max_length=1000)
    contacts: list[ContactRecord] = Field(default_factory=list, max_length=1000)
    run_manifest: RunManifest


class OutreachEvent(StrictModel):
    buyer_key: str = Field(min_length=1, max_length=200)
    event_type: Literal["sent", "bounced", "replied", "crm_created", "rating_changed"]
    target: str = Field(min_length=1, max_length=500)
    event_time: str
    source_type: Literal["user_confirmed", "uploaded_record", "connector_receipt"]
    source_reference: str = Field(min_length=1, max_length=2000)
    details: dict[str, Any] = Field(default_factory=dict)


class RecipientRoute(StrictModel):
    recipient: str = Field(min_length=3, max_length=320)
    recipient_status: VerificationStatus
    route_class: RouteClass
    role: str | None = Field(default=None, max_length=500)
    source_reference: str = Field(min_length=1, max_length=2000)

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[1]:
            raise ValueError("invalid recipient")
        return value


class OutreachValidationRequest(StrictModel):
    outreach_recommended: bool = True
    recipient: str = ""
    recipient_status: VerificationStatus = VerificationStatus.MISSING
    subject: str = Field(default="", max_length=160)
    body: str = Field(default="", max_length=10000)
    chinese_translation: str = Field(default="", max_length=10000)
    firewall_passed: bool = False
    human_style_passed: bool = False
    discovered_email_count: int = Field(ge=0)
    recipient_routes: list[RecipientRoute] = Field(default_factory=list, max_length=1000)
    time_plan: dict[str, Any] = Field(default_factory=dict)
    block_reasons: list[str] = Field(default_factory=list)

