"""Evidence-bound Brand Relationship Graph for v6.1.

Canonical account aliases are historically untyped. Production v6.1 therefore
must not infer that an alias is a legal alias, DBA, operating brand or former
brand merely from its string value. Explicit BRAND InformationRecords create
brand relationships while the canonical Account remains the legal entity.
"""

from __future__ import annotations

from typing import Any

from . import v6 as _v6


BRAND_RELATIONSHIPS = (
    "OPERATING_BRAND",
    "DBA",
    "TRADE_NAME",
    "STORE_BRAND",
    "FORMER_BRAND",
    "AFFILIATED_BRAND",
    "LICENSED_BRAND",
    "UNKNOWN_BRAND_RELATIONSHIP",
)

_CURRENT_BRAND_RELATIONSHIPS = {
    "OPERATING_BRAND",
    "DBA",
    "TRADE_NAME",
    "STORE_BRAND",
    "AFFILIATED_BRAND",
    "LICENSED_BRAND",
}


class V61BrandHardeningMixin:
    """Keep Legal Account, aliases and Brand relationships explicitly separate."""

    @staticmethod
    def _brand_name(record: dict[str, Any]) -> str:
        value = record.get("value")
        if isinstance(value, dict):
            for key in ("brand_name", "name", "brand", "trade_name", "dba"):
                name = str(value.get(key) or "").strip()
                if name:
                    return name
        if isinstance(value, str) and value.strip():
            return value.strip()
        return ""

    @staticmethod
    def _brand_relation(record: dict[str, Any]) -> str:
        value = record.get("value")
        value_relation = ""
        if isinstance(value, dict):
            value_relation = str(value.get("relationship") or value.get("relation") or "").upper().strip()
        relation = value_relation or str(record.get("relationship_to_account") or "").upper().strip()
        return relation if relation in BRAND_RELATIONSHIPS else "UNKNOWN_BRAND_RELATIONSHIP"

    @staticmethod
    def _normalized_token(value: str) -> str:
        return " ".join(value.casefold().split())

    def _brand_record_view(self, record: dict[str, Any]) -> dict[str, Any] | None:
        if record.get("subject_type") != "BRAND":
            return None
        name = self._brand_name(record)
        if not name:
            return None
        source_bound = bool(record.get("evidence_ids") or record.get("source_url") or record.get("source_locator"))
        if not source_bound:
            return None
        relation = self._brand_relation(record)
        temporal = str(record.get("temporal_status") or "UNKNOWN").upper()
        return {
            "brand_id": str(record.get("subject_owner_id") or "").strip(),
            "brand_name": name,
            "relationship_to_legal_account": relation,
            "temporal_status": temporal,
            "information_id": record.get("information_id"),
            "evidence_ids": list(record.get("evidence_ids") or []),
            "source_url": record.get("source_url") or "",
            "source_locator": record.get("source_locator") or "",
            "confidence": record.get("confidence") or "",
            "legal_entity_merge_allowed": False,
            "legal_identity_inference_from_brand_prohibited": True,
            "supersedes_information_ids": list(record.get("supersedes_information_ids") or []),
        }

    def _brand_graph(self, investigation_id: str) -> dict[str, Any]:
        legacy = self._state(investigation_id)
        all_records = list(legacy.get("information_records", {}).values())
        current_record_ids = {
            row.get("information_id")
            for row in self._current_information_records(legacy)
        }
        history: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        for record in all_records:
            row = self._brand_record_view(record)
            if row is None:
                continue
            history.append(row)
            if (
                record.get("information_id") in current_record_ids
                and row["relationship_to_legal_account"] in _CURRENT_BRAND_RELATIONSHIPS
                and row["temporal_status"] in {"CURRENT_CONFIRMED", "CURRENT", "CURRENT_LIKELY"}
            ):
                current.append(row)

        account = legacy["start"]["account"]
        aliases = [str(item).strip() for item in account.get("aliases") or [] if str(item).strip()]
        brand_tokens = {
            self._normalized_token(row["brand_name"]): row["brand_name"]
            for row in history
        }
        explicit_legal_aliases = {
            self._normalized_token(self._brand_name(record)): self._brand_name(record)
            for record in all_records
            if record.get("subject_type") in {"ACCOUNT", "COMPANY"}
            and str(record.get("relationship_to_account") or "").upper() == "LEGAL_ALIAS"
            and self._brand_name(record)
            and bool(record.get("evidence_ids") or record.get("source_url") or record.get("source_locator"))
        }

        classified_brand_aliases: list[str] = []
        classified_legal_aliases: list[str] = []
        unclassified_aliases: list[str] = []
        for alias in aliases:
            token = self._normalized_token(alias)
            if token in brand_tokens:
                classified_brand_aliases.append(alias)
            elif token in explicit_legal_aliases:
                classified_legal_aliases.append(alias)
            else:
                unclassified_aliases.append(alias)

        return {
            "schema": "cbi.brand-relationship-graph.v6.1",
            "legal_account_id": account.get("account_id"),
            "legal_account_name": account.get("name"),
            "current_brands": current,
            "brand_history": history,
            "canonical_alias_view": {
                "brand_tokens": classified_brand_aliases,
                "legal_aliases": classified_legal_aliases,
                "unclassified_aliases": unclassified_aliases,
                "raw_aliases_preserved": aliases,
            },
            "policy": {
                "alias_string_alone_proves_brand": False,
                "alias_string_alone_proves_legal_alias": False,
                "brand_record_merges_legal_entity": False,
                "brand_history_append_only": True,
            },
        }

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract.setdefault("enums", {})["brand_relationship"] = list(BRAND_RELATIONSHIPS)
        contract["brand_legal_entity_separation_v6_1"] = {
            "legal_account_is_canonical_entity": True,
            "brand_relationship_graph_is_separate": True,
            "brand_requires_explicit_source_bound_information_record": True,
            "canonical_aliases_are_untyped_until_evidence_classifies_them": True,
            "brand_name_never_auto_merges_legal_entity": True,
            "former_brand_history_is_preserved": True,
        }
        return contract

    def get_account_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = super().get_account_state(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        graph = self._brand_graph(investigation_id)
        identity = dict(base.get("identity") or base.get("account") or {})
        identity["alias_classification"] = graph["canonical_alias_view"]
        identity["legal_entity_separate_from_brand_graph"] = True
        return {
            **base,
            "identity": identity,
            "brands": graph["current_brands"],
            "brand_relationship_graph": graph,
        }
