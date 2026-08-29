"""Conservative country-identity normalization for v6.1 Canonical resolution.

``account.country`` is a required free-form string at the public Runtime boundary,
not an ISO enum.  Legal-identity decisions therefore must not treat two different
spellings as proof that two countries differ.  This overlay adds a conservative
four-state relation:

* SAME: exact normalized spelling or a known operational alias group agrees;
* CONFLICT: both sides are fully recognized and resolve to different countries;
* MISSING: one side has no country in legacy/internal state;
* UNRESOLVED: both sides state countries but their representations cannot be
  compared reliably.

Only CONFLICT is affirmative contradictory-country evidence.  UNRESOLVED fails
closed for strong-ID binding and same-name duplicate creation rather than being
invented into either SAME or CONFLICT.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .canonical_identity_hardening import (
    EvidenceBoundCanonicalRegistry,
    V61CanonicalIdentityHardeningMixin,
    _NAME_COUNTRY_REVIEW_REASON,
    _STRONG_ID_CONFLICT_REASON,
)


COUNTRY_RELATION_SAME = "SAME"
COUNTRY_RELATION_CONFLICT = "CONFLICT"
COUNTRY_RELATION_MISSING = "MISSING"
COUNTRY_RELATION_UNRESOLVED = "UNRESOLVED"
_COUNTRY_REPRESENTATION_REASON = "COUNTRY_REPRESENTATION_UNRESOLVED"


def _country_token(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


_COUNTRY_GROUPS: dict[str, tuple[str, ...]] = {
    "AE": ("ae", "are", "united arab emirates", "uae", "u a e"),
    "AR": ("ar", "arg", "argentina", "argentine republic"),
    "AT": ("at", "aut", "austria", "republic of austria"),
    "AU": ("au", "aus", "australia"),
    "BD": ("bd", "bgd", "bangladesh", "people s republic of bangladesh"),
    "BE": ("be", "bel", "belgium", "kingdom of belgium"),
    "BG": ("bg", "bgr", "bulgaria", "republic of bulgaria"),
    "BN": ("bn", "brn", "brunei", "brunei darussalam"),
    "BR": ("br", "bra", "brazil", "federative republic of brazil"),
    "BY": ("by", "blr", "belarus", "republic of belarus"),
    "CA": ("ca", "can", "canada"),
    "CH": ("ch", "che", "switzerland", "swiss confederation"),
    "CL": ("cl", "chl", "chile", "republic of chile"),
    "CN": ("cn", "chn", "china", "prc", "p r c", "people s republic of china", "mainland china"),
    "CO": ("co", "col", "colombia", "republic of colombia"),
    "CZ": ("cz", "cze", "czechia", "czech republic"),
    "DE": ("de", "deu", "germany", "federal republic of germany"),
    "DK": ("dk", "dnk", "denmark", "kingdom of denmark"),
    "EG": ("eg", "egy", "egypt", "arab republic of egypt"),
    "ES": ("es", "esp", "spain", "kingdom of spain"),
    "FI": ("fi", "fin", "finland", "republic of finland"),
    "FR": ("fr", "fra", "france", "french republic"),
    "GB": ("gb", "gbr", "uk", "u k", "united kingdom", "great britain", "britain", "united kingdom of great britain and northern ireland"),
    "GR": ("gr", "grc", "greece", "hellenic republic"),
    "HK": ("hk", "hkg", "hong kong", "hong kong sar", "hong kong sar china", "hong kong special administrative region of china"),
    "HU": ("hu", "hun", "hungary"),
    "ID": ("id", "idn", "indonesia", "republic of indonesia"),
    "IE": ("ie", "irl", "ireland"),
    "IL": ("il", "isr", "israel", "state of israel"),
    "IN": ("in", "ind", "india", "republic of india"),
    "IT": ("it", "ita", "italy", "italian republic"),
    "JP": ("jp", "jpn", "japan"),
    "KE": ("ke", "ken", "kenya", "republic of kenya"),
    "KH": ("kh", "khm", "cambodia", "kingdom of cambodia"),
    "KP": ("kp", "prk", "north korea", "korea north", "democratic people s republic of korea"),
    "KR": ("kr", "kor", "south korea", "korea south", "republic of korea", "korea republic of"),
    "KW": ("kw", "kwt", "kuwait", "state of kuwait"),
    "KZ": ("kz", "kaz", "kazakhstan", "republic of kazakhstan"),
    "LA": ("la", "lao", "laos", "lao people s democratic republic", "lao pdr"),
    "LK": ("lk", "lka", "sri lanka", "democratic socialist republic of sri lanka"),
    "MA": ("ma", "mar", "morocco", "kingdom of morocco"),
    "MO": ("mo", "mac", "macao", "macau", "macao sar", "macau sar", "macao special administrative region of china"),
    "MX": ("mx", "mex", "mexico", "united mexican states"),
    "MY": ("my", "mys", "malaysia"),
    "NG": ("ng", "nga", "nigeria", "federal republic of nigeria"),
    "NL": ("nl", "nld", "netherlands", "kingdom of the netherlands"),
    "NO": ("no", "nor", "norway", "kingdom of norway"),
    "NP": ("np", "npl", "nepal", "federal democratic republic of nepal"),
    "NZ": ("nz", "nzl", "new zealand"),
    "PE": ("pe", "per", "peru", "republic of peru"),
    "PH": ("ph", "phl", "philippines", "republic of the philippines"),
    "PK": ("pk", "pak", "pakistan", "islamic republic of pakistan"),
    "PL": ("pl", "pol", "poland", "republic of poland"),
    "PR": ("pr", "pri", "puerto rico"),
    "PT": ("pt", "prt", "portugal", "portuguese republic"),
    "QA": ("qa", "qat", "qatar", "state of qatar"),
    "RO": ("ro", "rou", "romania"),
    "RS": ("rs", "srb", "serbia", "republic of serbia"),
    "RU": ("ru", "rus", "russia", "russian federation"),
    "SA": ("sa", "sau", "saudi arabia", "kingdom of saudi arabia"),
    "SE": ("se", "swe", "sweden", "kingdom of sweden"),
    "SG": ("sg", "sgp", "singapore", "republic of singapore"),
    "SK": ("sk", "svk", "slovakia", "slovak republic"),
    "TH": ("th", "tha", "thailand", "kingdom of thailand"),
    "TR": ("tr", "tur", "turkey", "türkiye", "turkiye", "republic of türkiye", "republic of turkey"),
    "TW": ("tw", "twn", "taiwan", "taiwan province of china"),
    "UA": ("ua", "ukr", "ukraine"),
    "US": ("us", "usa", "u s", "u s a", "united states", "united states of america"),
    "VN": ("vn", "vnm", "vietnam", "viet nam", "socialist republic of viet nam", "socialist republic of vietnam"),
    "ZA": ("za", "zaf", "south africa", "republic of south africa"),
}

_COUNTRY_ALIAS_TO_KEY: dict[str, str] = {
    _country_token(alias): key
    for key, aliases in _COUNTRY_GROUPS.items()
    for alias in aliases
}


class CountryAwareCanonicalRegistry(EvidenceBoundCanonicalRegistry):
    """Evidence-bound Canonical Registry with conservative country semantics."""

    @classmethod
    def _country_relation(cls, candidate: dict[str, set[str]], row: dict[str, set[str]]) -> str:
        candidate_tokens = {_country_token(value) for value in candidate["countries"] if value}
        row_tokens = {_country_token(value) for value in row["countries"] if value}
        candidate_tokens.discard("")
        row_tokens.discard("")
        if not candidate_tokens or not row_tokens:
            return COUNTRY_RELATION_MISSING
        if candidate_tokens & row_tokens:
            return COUNTRY_RELATION_SAME

        candidate_known = {_COUNTRY_ALIAS_TO_KEY[token] for token in candidate_tokens if token in _COUNTRY_ALIAS_TO_KEY}
        row_known = {_COUNTRY_ALIAS_TO_KEY[token] for token in row_tokens if token in _COUNTRY_ALIAS_TO_KEY}
        if candidate_known & row_known:
            return COUNTRY_RELATION_SAME

        candidate_all_known = len(candidate_known) == len(candidate_tokens)
        row_all_known = len(row_known) == len(row_tokens)
        if candidate_known and row_known and candidate_all_known and row_all_known:
            return COUNTRY_RELATION_CONFLICT
        return COUNTRY_RELATION_UNRESOLVED

    @classmethod
    def _country_overlap(cls, candidate: dict[str, set[str]], row: dict[str, set[str]]) -> bool:
        return cls._country_relation(candidate, row) == COUNTRY_RELATION_SAME

    @classmethod
    def _country_compatible(cls, candidate: dict[str, set[str]], row: dict[str, set[str]]) -> bool:
        return cls._country_relation(candidate, row) != COUNTRY_RELATION_CONFLICT

    @classmethod
    def _country_conflict(cls, candidate: dict[str, set[str]], row: dict[str, set[str]]) -> bool:
        return cls._country_relation(candidate, row) == COUNTRY_RELATION_CONFLICT

    @classmethod
    def _match_score(
        cls,
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
        if cls._country_overlap(candidate, row) and candidate["names"] & row["names"]:
            score, reasons = max(score, 85), reasons + ["PRIMARY_LEGAL_NAME_COUNTRY"]
        if score and cls._country_overlap(candidate, row) and candidate["addresses"] & row["addresses"]:
            reasons.append("ADDRESS_SUPPORT")
        return score, sorted(set(reasons))

    @classmethod
    def _scored_resolution(
        cls,
        candidate_keys: dict[str, set[str]],
        entries: list[dict[str, Any]],
        *,
        requested_account_id: str = "",
    ) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        for row in entries:
            score, reasons = cls._match_score(
                candidate_keys,
                cls._keys(row["account"]),
                requested_account_id,
                row["account_id"],
            )
            if score:
                matches.append({
                    "account_id": row["account_id"],
                    "score": score,
                    "reasons": reasons,
                    "origin": row["origin"],
                })
        matches.sort(key=lambda item: (-item["score"], item["account_id"].casefold()))
        if not matches:
            return {"status": "NOT_FOUND", "match": None, "candidates": []}
        top_score = matches[0]["score"]
        top = [item for item in matches if item["score"] == top_score]
        unique_ids = {item["account_id"].casefold() for item in top}
        if len(unique_ids) > 1:
            return {"status": "AMBIGUOUS_MATCH", "match": None, "candidates": top}
        return {"status": "MATCHED", "match": top[0], "candidates": matches}

    def _strong_identity_conflicts(
        self,
        candidate: dict[str, Any],
        *,
        requested_account_id: str = "",
        entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.entries() if entries is None else entries
        candidate_keys = self._keys(candidate)
        conflicts: list[dict[str, Any]] = []
        for entry in rows:
            exact_requested = bool(
                requested_account_id
                and entry["account_id"].casefold() == requested_account_id.casefold()
            )
            if requested_account_id and not exact_requested:
                continue
            row_keys = self._keys(entry["account"])
            relation = self._country_relation(candidate_keys, row_keys)
            same_primary_name = bool(
                relation != COUNTRY_RELATION_CONFLICT
                and candidate_keys["names"] & row_keys["names"]
            )
            same_tax_id = bool(candidate_keys["tax_ids"] & row_keys["tax_ids"])
            same_external_id = bool(candidate_keys["external_ids"] & row_keys["external_ids"])
            if not (exact_requested or same_primary_name or same_tax_id or same_external_id):
                continue

            conflict_types: list[str] = []
            if self._tax_id_conflict(candidate_keys, row_keys):
                conflict_types.append("TAX_ID_CONFLICT")
            if relation == COUNTRY_RELATION_CONFLICT and (exact_requested or same_tax_id or same_external_id):
                conflict_types.append("COUNTRY_CONFLICT")
            if relation == COUNTRY_RELATION_UNRESOLVED and (exact_requested or same_tax_id or same_external_id):
                conflict_types.append(_COUNTRY_REPRESENTATION_REASON)
            if conflict_types:
                conflicts.append({
                    "account_id": entry["account_id"],
                    "score": 0,
                    "reasons": [_STRONG_ID_CONFLICT_REASON, *conflict_types],
                    "origin": entry["origin"],
                    "country_relation": relation,
                })
        return sorted(conflicts, key=lambda item: item["account_id"].casefold())

    def _name_country_review_collisions(
        self,
        candidate: dict[str, Any],
        *,
        entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.entries() if entries is None else entries
        candidate_keys = self._keys(candidate)
        if not candidate_keys["names"]:
            return []
        collisions: list[dict[str, Any]] = []
        for row in rows:
            row_keys = self._keys(row["account"])
            if not (candidate_keys["names"] & row_keys["names"]):
                continue
            relation = self._country_relation(candidate_keys, row_keys)
            if relation in {COUNTRY_RELATION_SAME, COUNTRY_RELATION_CONFLICT}:
                continue
            reason = (
                _COUNTRY_REPRESENTATION_REASON
                if relation == COUNTRY_RELATION_UNRESOLVED
                else _NAME_COUNTRY_REVIEW_REASON
            )
            collisions.append({
                "account_id": row["account_id"],
                "score": 0,
                "reasons": [reason],
                "origin": row["origin"],
                "country_relation": relation,
            })
        return sorted(collisions, key=lambda item: item["account_id"].casefold())


class V61CountryIdentityHardeningMixin(V61CanonicalIdentityHardeningMixin):
    """Install country-aware semantics after the evidence-bound registry exists."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = self.canonical_registry
        if not isinstance(current, CountryAwareCanonicalRegistry):
            self.canonical_registry = CountryAwareCanonicalRegistry(current.root, current.session_root)

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        canonical = contract["canonical_identity_resolution_v6_1"]
        canonical.update({
            "country_input_contract": "FREE_FORM_NONEMPTY_STRING",
            "country_relation_states": [
                COUNTRY_RELATION_SAME,
                COUNTRY_RELATION_CONFLICT,
                COUNTRY_RELATION_MISSING,
                COUNTRY_RELATION_UNRESOLVED,
            ],
            "country_alias_equivalence_is_conservative": True,
            "unknown_country_representation_policy": "AMBIGUOUS_FAIL_CLOSED",
            "country_string_inequality_alone_is_conflict_proof": False,
            "same_name_unknown_country_representation_can_create_duplicate": False,
        })
        return contract
