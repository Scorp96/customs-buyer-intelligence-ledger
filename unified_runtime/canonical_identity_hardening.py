"""Evidence-bound Canonical Account resolution for the v6.1 production runtime.

The v5 compatibility registry historically treated every free-form ``aliases``
string as a legal identity key and allowed an address alone to produce a
canonical match. That is too permissive for production buyer intelligence:
brands, trade names, occupants and related entities can share aliases or an
address without being the same legal entity.

This overlay preserves historical alias payloads but gives *no alias field*
automatic legal-entity merge authority. Alias overlap is a review signal only
and fails closed. After evidence review, callers must bind the known Canonical
Account explicitly by account ID; a free-form alias string can never perform
that legal-identity transition by itself.
"""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .resilience import CanonicalRegistry, normalized_values


_ALIAS_REVIEW_REASON = "ALIAS_RELATION_REQUIRES_CANONICAL_ID_PROOF"


class EvidenceBoundCanonicalRegistry(CanonicalRegistry):
    """Canonical resolver that separates legal identity from all alias strings."""

    @staticmethod
    def _string_array(account: dict[str, Any], field: str) -> list[str]:
        value = account.get(field) or []
        if isinstance(value, str):
            value = [value]
        elif not isinstance(value, list):
            raise ValidationError(f"account.{field}: string array required")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValidationError(f"account.{field}: string array required")
        return [item.strip() for item in value]

    @classmethod
    def _keys(cls, account: dict[str, Any]) -> dict[str, set[str]]:
        # Both legacy ``aliases`` and newer typed/descriptive ``legal_aliases``
        # remain durable metadata only. Neither can become a legal match key
        # without a separate evidence-bound identity transition, which this
        # resolver intentionally does not invent.
        aliases = cls._string_array(account, "aliases")
        legal_aliases = cls._string_array(account, "legal_aliases")
        return {
            "names": normalized_values(account.get("name")),
            "aliases": normalized_values(aliases),
            "legal_aliases": normalized_values(legal_aliases),
            "tax_ids": normalized_values(account.get("tax_ids") or account.get("tax_id")),
            "addresses": normalized_values(account.get("addresses") or account.get("address")),
            "external_ids": normalized_values(account.get("external_ids")),
            "countries": normalized_values(account.get("country")),
        }

    @staticmethod
    def _match_score(
        candidate: dict[str, set[str]],
        row: dict[str, set[str]],
        requested_id: str,
        row_id: str,
    ) -> tuple[int, list[str]]:
        reasons: list[str] = []
        score = 0
        if requested_id and requested_id.casefold() == row_id.casefold():
            score, reasons = 100, ["EXACT_ACCOUNT_ID"]
        if candidate["tax_ids"] & row["tax_ids"]:
            score, reasons = max(score, 95), reasons + ["TAX_ID"]
        if candidate["external_ids"] & row["external_ids"]:
            score, reasons = max(score, 90), reasons + ["EXTERNAL_ID"]

        same_country = (
            not candidate["countries"]
            or not row["countries"]
            or bool(candidate["countries"] & row["countries"])
        )
        if same_country and candidate["names"] & row["names"]:
            score, reasons = max(score, 85), reasons + ["PRIMARY_LEGAL_NAME_COUNTRY"]

        # Address is supporting evidence only. Shared offices, warehouses,
        # registered agents, malls and group facilities cannot merge entities.
        if score and same_country and candidate["addresses"] & row["addresses"]:
            reasons.append("ADDRESS_SUPPORT")
        return score, sorted(set(reasons))

    def _alias_collisions(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        candidate_keys = self._keys(candidate)
        candidate_primary = candidate_keys["names"]
        candidate_aliases = candidate_keys["aliases"] | candidate_keys["legal_aliases"]
        if not candidate_primary and not candidate_aliases:
            return []

        collisions: list[dict[str, Any]] = []
        for row in self.entries():
            row_keys = self._keys(row["account"])
            same_country = (
                not candidate_keys["countries"]
                or not row_keys["countries"]
                or bool(candidate_keys["countries"] & row_keys["countries"])
            )
            if not same_country:
                continue

            row_primary = row_keys["names"]
            row_aliases = row_keys["aliases"] | row_keys["legal_aliases"]
            overlap = sorted(
                (candidate_primary & row_aliases)
                | (candidate_aliases & row_primary)
                | (candidate_aliases & row_aliases)
            )
            if not overlap:
                continue
            collisions.append({
                "account_id": row["account_id"],
                "score": 0,
                "reasons": [_ALIAS_REVIEW_REASON],
                "origin": row["origin"],
                "alias_overlap": overlap,
            })
        return sorted(collisions, key=lambda item: item["account_id"].casefold())

    def resolve(self, candidate: dict[str, Any], *, requested_account_id: str = "") -> dict[str, Any]:
        resolved = super().resolve(candidate, requested_account_id=requested_account_id)
        if resolved["status"] != "NOT_FOUND" or requested_account_id.strip():
            return resolved

        collisions = self._alias_collisions(candidate)
        if collisions:
            return {
                "status": "AMBIGUOUS_MATCH",
                "match": None,
                "candidates": collisions,
                "ambiguity_reason": _ALIAS_REVIEW_REASON,
                "automatic_merge_allowed": False,
                "automatic_create_allowed": False,
                "resolution_requirement": "SUPPLY_EXACT_CANONICAL_ACCOUNT_ID_AFTER_EVIDENCE_REVIEW",
            }
        return resolved


class V61CanonicalIdentityHardeningMixin:
    """Install the evidence-bound registry only on the v6.1 production runtime."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = self.canonical_registry
        if not isinstance(current, EvidenceBoundCanonicalRegistry):
            self.canonical_registry = EvidenceBoundCanonicalRegistry(
                current.root,
                current.session_root,
            )

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract["canonical_identity_resolution_v6_1"] = {
            "raw_aliases_are_legal_identity_keys": False,
            "typed_aliases_are_automatic_match_keys": False,
            "alias_fields_preserved": ["aliases", "legal_aliases"],
            "alias_collision_policy": "AMBIGUOUS_FAIL_CLOSED",
            "alias_resolution_requirement": "EXACT_CANONICAL_ACCOUNT_ID_AFTER_EVIDENCE_REVIEW",
            "address_only_match_allowed": False,
            "address_is_supporting_evidence_only": True,
            "automatic_match_authorities": [
                "EXACT_ACCOUNT_ID",
                "TAX_ID",
                "EXTERNAL_ID",
                "PRIMARY_LEGAL_NAME_COUNTRY",
            ],
            "historical_alias_payloads_preserved": True,
            "resolver_can_invent_legal_alias_authority": False,
        }
        return contract
