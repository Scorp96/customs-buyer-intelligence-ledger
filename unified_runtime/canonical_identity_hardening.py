"""Evidence-bound Canonical Account resolution for the v6.1 production runtime.

The v5 compatibility registry historically treated every free-form ``aliases``
string as a legal identity key, allowed an address alone to match, and treated
``requested_account_id`` as a scoring hint rather than an exact identity
constraint. Those behaviors are too permissive for production buyer
intelligence.

This overlay preserves historical payloads while enforcing fail-closed legal
identity semantics:

* no alias field has automatic merge authority;
* address similarity is supporting evidence only;
* a requested Canonical Account ID is exact, never a fuzzy hint;
* contradictory Tax IDs block matching, even when names or requested IDs agree;
* ambiguous identity signals cannot silently create a second Account;
* an explicitly requested *new* ID remains creatable when no competing
  identity signal exists, preserving the supported low-information start path.
"""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .resilience import ACCOUNT_ID_RE, CanonicalRegistry, normalized_values


_ALIAS_REVIEW_REASON = "ALIAS_RELATION_REQUIRES_CANONICAL_ID_PROOF"
_REQUESTED_ID_COLLISION_REASON = "REQUESTED_ACCOUNT_ID_NOT_FOUND_IDENTITY_COLLISION"
_STRONG_ID_CONFLICT_REASON = "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW"


class EvidenceBoundCanonicalRegistry(CanonicalRegistry):
    """Canonical resolver that separates legal identity from weak similarity."""

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
    def _has_primary_identity(keys: dict[str, set[str]]) -> bool:
        return any(keys[key] for key in ("names", "tax_ids", "addresses", "external_ids"))

    @staticmethod
    def _same_country(candidate: dict[str, set[str]], row: dict[str, set[str]]) -> bool:
        return (
            not candidate["countries"]
            or not row["countries"]
            or bool(candidate["countries"] & row["countries"])
        )

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

        same_country = EvidenceBoundCanonicalRegistry._same_country(candidate, row)
        if same_country and candidate["names"] & row["names"]:
            score, reasons = max(score, 85), reasons + ["PRIMARY_LEGAL_NAME_COUNTRY"]
        if score and same_country and candidate["addresses"] & row["addresses"]:
            reasons.append("ADDRESS_SUPPORT")
        return score, sorted(set(reasons))

    @staticmethod
    def _tax_id_conflict(candidate: dict[str, set[str]], row: dict[str, set[str]]) -> bool:
        return bool(
            candidate["tax_ids"]
            and row["tax_ids"]
            and not (candidate["tax_ids"] & row["tax_ids"])
        )

    def _strong_identity_conflicts(
        self,
        candidate: dict[str, Any],
        *,
        requested_account_id: str = "",
    ) -> list[dict[str, Any]]:
        candidate_keys = self._keys(candidate)
        conflicts: list[dict[str, Any]] = []
        for entry in self.entries():
            if requested_account_id and entry["account_id"].casefold() != requested_account_id.casefold():
                continue
            row_keys = self._keys(entry["account"])
            same_primary_identity = (
                self._same_country(candidate_keys, row_keys)
                and bool(candidate_keys["names"] & row_keys["names"])
            )
            if not requested_account_id and not same_primary_identity:
                continue
            conflict_types: list[str] = []
            if self._tax_id_conflict(candidate_keys, row_keys):
                conflict_types.append("TAX_ID_CONFLICT")
            if conflict_types:
                conflicts.append({
                    "account_id": entry["account_id"],
                    "score": 0,
                    "reasons": [_STRONG_ID_CONFLICT_REASON, *conflict_types],
                    "origin": entry["origin"],
                })
        return sorted(conflicts, key=lambda item: item["account_id"].casefold())

    def _alias_collisions(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        candidate_keys = self._keys(candidate)
        candidate_primary = candidate_keys["names"]
        candidate_aliases = candidate_keys["aliases"] | candidate_keys["legal_aliases"]
        if not candidate_primary and not candidate_aliases:
            return []
        collisions: list[dict[str, Any]] = []
        for row in self.entries():
            row_keys = self._keys(row["account"])
            if not self._same_country(candidate_keys, row_keys):
                continue
            row_primary = row_keys["names"]
            row_aliases = row_keys["aliases"] | row_keys["legal_aliases"]
            overlap = sorted(
                (candidate_primary & row_aliases)
                | (candidate_aliases & row_primary)
                | (candidate_aliases & row_aliases)
            )
            if overlap:
                collisions.append({
                    "account_id": row["account_id"],
                    "score": 0,
                    "reasons": [_ALIAS_REVIEW_REASON],
                    "origin": row["origin"],
                    "alias_overlap": overlap,
                })
        return sorted(collisions, key=lambda item: item["account_id"].casefold())

    @staticmethod
    def _ambiguous(reason: str, candidates: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        return {
            "status": "AMBIGUOUS_MATCH",
            "match": None,
            "candidates": candidates,
            "ambiguity_reason": reason,
            "automatic_merge_allowed": False,
            "automatic_create_allowed": False,
            **extra,
        }

    def _resolve_unrequested(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_keys = self._keys(candidate)
        if not self._has_primary_identity(candidate_keys):
            collisions = self._alias_collisions(candidate)
            if collisions:
                return self._ambiguous(
                    _ALIAS_REVIEW_REASON,
                    collisions,
                    resolution_requirement="SUPPLY_EXACT_CANONICAL_ACCOUNT_ID_AFTER_EVIDENCE_REVIEW",
                )
            raise ValidationError("candidate requires a primary legal name, tax ID, address, or external ID")

        strong_conflicts = self._strong_identity_conflicts(candidate)
        if strong_conflicts:
            return self._ambiguous(
                _STRONG_ID_CONFLICT_REASON,
                strong_conflicts,
                resolution_requirement="RECONCILE_STRONG_IDENTITY_CONFLICT_BEFORE_CANONICAL_BIND",
            )
        resolved = super().resolve(candidate, requested_account_id="")
        if resolved["status"] != "NOT_FOUND":
            return resolved
        collisions = self._alias_collisions(candidate)
        if collisions:
            return self._ambiguous(
                _ALIAS_REVIEW_REASON,
                collisions,
                resolution_requirement="SUPPLY_EXACT_CANONICAL_ACCOUNT_ID_AFTER_EVIDENCE_REVIEW",
            )
        return resolved

    def resolve(self, candidate: dict[str, Any], *, requested_account_id: str = "") -> dict[str, Any]:
        requested_account_id = requested_account_id.strip()
        if requested_account_id and not ACCOUNT_ID_RE.fullmatch(requested_account_id):
            raise ValidationError("requested_account_id: invalid")
        if not requested_account_id:
            return self._resolve_unrequested(candidate)

        exact_rows = [
            row
            for row in self.entries()
            if row["account_id"].casefold() == requested_account_id.casefold()
        ]
        if len(exact_rows) > 1:
            return self._ambiguous(
                "DUPLICATE_CANONICAL_ACCOUNT_ID",
                [{
                    "account_id": row["account_id"],
                    "score": 0,
                    "reasons": ["DUPLICATE_CANONICAL_ACCOUNT_ID"],
                    "origin": row["origin"],
                } for row in exact_rows],
            )
        if exact_rows:
            conflicts = self._strong_identity_conflicts(
                candidate,
                requested_account_id=requested_account_id,
            )
            if conflicts:
                return self._ambiguous(
                    _STRONG_ID_CONFLICT_REASON,
                    conflicts,
                    requested_account_id=requested_account_id,
                    resolution_requirement="RECONCILE_STRONG_IDENTITY_CONFLICT_BEFORE_CANONICAL_BIND",
                )
            row = exact_rows[0]
            score, reasons = self._match_score(
                self._keys(candidate),
                self._keys(row["account"]),
                requested_account_id,
                row["account_id"],
            )
            return {
                "status": "MATCHED",
                "match": {
                    "account_id": row["account_id"],
                    "score": score,
                    "reasons": reasons,
                    "origin": row["origin"],
                },
                "candidates": [],
                "requested_account_id_exact": True,
            }

        # Explicit allocation with no fuzzy identity material is safe: there is
        # nothing to substitute against. This keeps the established MCP path for
        # creating a caller-chosen synthetic/known ID with only metadata such as
        # country, while still forbidding fuzzy replacement of that ID.
        candidate_keys = self._keys(candidate)
        if not self._has_primary_identity(candidate_keys) and not (
            candidate_keys["aliases"] or candidate_keys["legal_aliases"]
        ):
            return {
                "status": "NOT_FOUND",
                "match": None,
                "candidates": [],
                "requested_account_id": requested_account_id,
                "exact_id_allocation_without_fuzzy_identity": True,
            }

        other_identity = self._resolve_unrequested(candidate)
        if other_identity["status"] != "NOT_FOUND":
            candidates = list(other_identity.get("candidates") or [])
            if other_identity.get("match"):
                candidates.insert(0, dict(other_identity["match"]))
            return self._ambiguous(
                _REQUESTED_ID_COLLISION_REASON,
                candidates,
                requested_account_id=requested_account_id,
                discovered_identity_status=other_identity["status"],
                resolution_requirement="REVIEW_REQUESTED_ACCOUNT_ID_VS_EXISTING_CANONICAL_IDENTITY",
            )
        return {
            "status": "NOT_FOUND",
            "match": None,
            "candidates": [],
            "requested_account_id": requested_account_id,
        }


class V61CanonicalIdentityHardeningMixin:
    """Install the evidence-bound registry only on the v6.1 production runtime."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = self.canonical_registry
        if not isinstance(current, EvidenceBoundCanonicalRegistry):
            self.canonical_registry = EvidenceBoundCanonicalRegistry(current.root, current.session_root)

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
            "requested_account_id_is_exact_constraint": True,
            "requested_id_fuzzy_substitution_allowed": False,
            "explicit_new_id_without_fuzzy_identity_can_be_allocated": True,
            "contradictory_tax_ids_fail_closed": True,
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
