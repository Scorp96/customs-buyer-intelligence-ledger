"""Evidence-bound Commercial Opportunity model for v6.1.

Commercial Value answers whether an account is worth developing. It must not be
a proxy for research completeness, contact coverage, or CRM state. This layer
keeps the existing claim-weight score as a conservative baseline and adds only
positive, evidence-bound opportunity lift from the v6 commercial factors.
Unknown opportunity factors do not become fabricated zero facts and do not cap
the grade. Explicit adverse facts can be represented by low factor strength.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable

from . import v6 as _v6


COMMERCIAL_OPPORTUNITY_FACTORS = (
    "product_fit",
    "current_import",
    "volume",
    "frequency",
    "supplier_diversity",
    "recency",
    "market_channel_position",
    "growth",
    "strategic_fit",
    "replacement_opportunity",
)

# The specification names the factors but deliberately leaves the first v6
# implementation heuristic. These weights are bounded lift, not probabilities.
OPPORTUNITY_LIFT_WEIGHTS = {
    "product_fit": 2.5,
    "current_import": 2.5,
    "volume": 4.0,
    "frequency": 3.0,
    "supplier_diversity": 2.5,
    "recency": 2.0,
    "market_channel_position": 1.5,
    "growth": 1.5,
    "strategic_fit": 1.5,
    "replacement_opportunity": 2.0,
}

_CLAIM_STRENGTH = {
    "STRONGLY_SUPPORTED": 1.0,
    "SUPPORTED": 0.82,
    "CONFLICTED": 0.25,
    "STALE": 0.20,
    "REFUTED": 0.0,
    "NEGATIVE_EXHAUSTED": 0.0,
    "BLOCKED": 0.0,
    "NOT_APPLICABLE": 0.0,
    "SEARCHING": 0.0,
    "UNSEEN": 0.0,
}

_LEVEL_STRENGTH = {
    "HUGE": 1.0,
    "VERY_HIGH": 1.0,
    "VERY_LARGE": 1.0,
    "MAJOR": 0.95,
    "HIGH": 0.85,
    "LARGE": 0.85,
    "STRONG": 0.80,
    "MEDIUM_HIGH": 0.70,
    "MEDIUM": 0.55,
    "MODERATE": 0.50,
    "LOW": 0.25,
    "VERY_LOW": 0.10,
    "NONE": 0.0,
}

_POSITIVE_MARKERS = {"TRUE", "YES", "Y", "POSITIVE", "OPEN", "ACTIVE"}


def _flatten(value: Any, prefix: str = "", depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth > 5:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path.casefold(), item
            yield from _flatten(item, path, depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield from _flatten(item, path, depth + 1)


def _leaf_key(path: str) -> str:
    return path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()


def _numbers(value: Any, keys: set[str]) -> list[tuple[str, float]]:
    output: list[tuple[str, float]] = []
    for path, item in _flatten(value):
        if _leaf_key(path) not in keys or isinstance(item, bool):
            continue
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append((path, number))
    return output


def _strings(value: Any, keys: set[str]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for path, item in _flatten(value):
        if _leaf_key(path) not in keys or not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            output.append((path, text))
    return output


def _lists(value: Any, keys: set[str]) -> list[tuple[str, list[Any]]]:
    output: list[tuple[str, list[Any]]] = []
    for path, item in _flatten(value):
        if _leaf_key(path) in keys and isinstance(item, list):
            output.append((path, item))
    return output


def _level_strength(values: list[tuple[str, str]]) -> tuple[float | None, list[str]]:
    candidates: list[tuple[float, str]] = []
    for path, text in values:
        token = "_".join(text.upper().replace("-", " ").replace("/", " ").split())
        if token in _LEVEL_STRENGTH:
            candidates.append((_LEVEL_STRENGTH[token], path))
    if not candidates:
        return None, []
    strength = max(item[0] for item in candidates)
    return strength, [path for score, path in candidates if score == strength]


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))


def _date_value(text: str) -> datetime | None:
    value = text.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value[:10] + "T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class V61CommercialOpportunityMixin:
    """Add evidence-bound opportunity factors without contact/CRM grade caps."""

    @staticmethod
    def _factor(
        name: str,
        strength: float | None,
        observations: list[dict[str, Any]],
        *,
        evidence_paths: list[str] | None = None,
        basis: str = "",
    ) -> dict[str, Any]:
        supported = strength is not None
        return {
            "factor": name,
            "status": "SUPPORTED" if supported else "UNKNOWN",
            "strength": round(_bounded(strength or 0.0), 4) if supported else None,
            "basis": basis if supported else "No structured evidence-bound value was available.",
            "observation_ids": sorted({
                str(row.get("observation_id"))
                for row in observations
                if row.get("observation_id")
            }),
            "evidence_ids": sorted({
                str(row.get("evidence_id"))
                for row in observations
                if row.get("evidence_id")
            }),
            "evidence_paths": sorted(set(evidence_paths or [])),
        }

    @staticmethod
    def _positive_account_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
        account_id = state["start"]["account"]["account_id"]
        return [
            row
            for row in state["observations"].values()
            if row.get("owner_type") == "ACCOUNT"
            and row.get("owner_id") == account_id
            and row.get("result") == "POSITIVE"
        ]

    def _claim_factor(
        self,
        name: str,
        claim_key: str,
        claims: dict[str, dict[str, Any]],
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        claim = claims.get(claim_key) or {}
        strength = _CLAIM_STRENGTH.get(str(claim.get("state") or ""), 0.0)
        bound = [row for row in rows if row.get("claim_key") == claim_key]
        if not bound or strength <= 0:
            return self._factor(name, None, [])
        return self._factor(
            name,
            strength,
            bound,
            basis=f"Derived from {claim_key}={claim.get('state')} using only bound positive Evidence.",
        )

    def _trade_factor_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if row.get("claim_key") == "trade.import_activity"]

    def _volume_factor(self, trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
        level_keys = {"volume_level", "buyer_volume_level", "import_volume_level", "scale_level"}
        level_values: list[tuple[str, str]] = []
        kg_values: list[tuple[str, float]] = []
        ton_values: list[tuple[str, float]] = []
        for row in trade_rows:
            value = row.get("value")
            level_values.extend(_strings(value, level_keys))
            kg_values.extend(_numbers(value, {
                "visible_weight_kg", "total_weight_kg", "import_weight_kg",
                "annualized_visible_weight_kg", "annualized_weight_kg", "volume_kg",
                "total_volume_kg",
            }))
            ton_values.extend(_numbers(value, {
                "visible_weight_tons", "total_weight_tons", "import_weight_tons",
                "annualized_visible_tons", "annualized_tons", "volume_tons",
            }))
        strength, paths = _level_strength(level_values)
        normalized_kg = kg_values + [(path, value * 1000.0) for path, value in ton_values]
        if normalized_kg:
            maximum = max(value for _, value in normalized_kg)
            numeric_strength = (
                1.0 if maximum >= 500_000
                else 0.9 if maximum >= 250_000
                else 0.8 if maximum >= 100_000
                else 0.65 if maximum >= 25_000
                else 0.45 if maximum >= 5_000
                else 0.25 if maximum > 0
                else 0.0
            )
            if strength is None or numeric_strength > strength:
                strength = numeric_strength
                paths = [path for path, value in normalized_kg if value == maximum]
        return self._factor(
            "volume",
            strength,
            trade_rows if strength is not None else [],
            evidence_paths=paths,
            basis="Visible/annualized import volume is derived from structured trade Evidence or an explicit evidence-bound volume level.",
        )

    def _frequency_factor(self, trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
        levels: list[tuple[str, str]] = []
        counts: list[tuple[str, float]] = []
        for row in trade_rows:
            value = row.get("value")
            levels.extend(_strings(value, {"frequency_level", "import_frequency_level", "shipment_frequency"}))
            counts.extend(_numbers(value, {
                "shipment_count", "import_count", "shipments_12m", "imports_12m",
                "shipment_count_12m", "visible_shipments", "bill_of_lading_count",
            }))
        strength, paths = _level_strength(levels)
        if counts:
            maximum = max(value for _, value in counts)
            numeric_strength = (
                1.0 if maximum >= 12
                else 0.85 if maximum >= 6
                else 0.65 if maximum >= 3
                else 0.45 if maximum >= 2
                else 0.20 if maximum >= 1
                else 0.0
            )
            if strength is None or numeric_strength > strength:
                strength = numeric_strength
                paths = [path for path, value in counts if value == maximum]
        return self._factor(
            "frequency",
            strength,
            trade_rows if strength is not None else [],
            evidence_paths=paths,
            basis="Import frequency is derived from structured shipment/import counts or an explicit evidence-bound frequency level.",
        )

    def _supplier_diversity_factor(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        relevant = [
            row for row in rows
            if row.get("claim_key") in {"trade.import_activity", "relationship.supply_chain"}
        ]
        counts: list[tuple[str, float]] = []
        lists: list[tuple[str, list[Any]]] = []
        levels: list[tuple[str, str]] = []
        for row in relevant:
            value = row.get("value")
            counts.extend(_numbers(value, {"supplier_count", "active_supplier_count", "visible_supplier_count"}))
            lists.extend(_lists(value, {"suppliers", "supplier_names", "active_suppliers"}))
            levels.extend(_strings(value, {"supplier_diversity", "supplier_diversity_level"}))
        strength, paths = _level_strength(levels)
        derived_counts = counts + [(path, float(len({str(item).casefold() for item in values if str(item).strip()}))) for path, values in lists]
        if derived_counts:
            maximum = max(value for _, value in derived_counts)
            numeric_strength = (
                1.0 if maximum >= 4
                else 0.8 if maximum >= 3
                else 0.6 if maximum >= 2
                else 0.25 if maximum >= 1
                else 0.0
            )
            if strength is None or numeric_strength > strength:
                strength = numeric_strength
                paths = [path for path, value in derived_counts if value == maximum]
        return self._factor(
            "supplier_diversity",
            strength,
            relevant if strength is not None else [],
            evidence_paths=paths,
            basis="Supplier diversity is derived from structured supplier counts/lists or an explicit evidence-bound diversity level.",
        )

    def _recency_factor(self, trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not trade_rows:
            return self._factor("recency", None, [])
        freshness_rank = {
            "LIVE": 1.0,
            "CURRENT_CONFIRMED": 1.0,
            "CURRENT": 0.95,
            "CURRENT_LIKELY": 0.90,
            "RECENT": 0.75,
            "HISTORICAL": 0.20,
            "STALE": 0.10,
            "UNKNOWN": 0.0,
        }
        best = max(
            freshness_rank.get(str(row.get("source", {}).get("freshness") or "UNKNOWN"), 0.0)
            for row in trade_rows
        )
        paths = ["source.freshness"] if best > 0 else []
        days_values: list[tuple[str, float]] = []
        date_values: list[tuple[str, datetime]] = []
        for row in trade_rows:
            value = row.get("value")
            days_values.extend(_numbers(value, {"days_since_latest_import", "days_since_latest_shipment"}))
            for path, text in _strings(value, {"latest_import_date", "latest_shipment_date", "last_import_date", "last_shipment_date"}):
                parsed = _date_value(text)
                if parsed:
                    date_values.append((path, parsed))
        if days_values:
            minimum = max(0.0, min(value for _, value in days_values))
            numeric = 1.0 if minimum <= 45 else 0.9 if minimum <= 90 else 0.75 if minimum <= 180 else 0.5 if minimum <= 365 else 0.2
            if numeric > best:
                best = numeric
                paths = [path for path, value in days_values if value == min(v for _, v in days_values)]
        elif date_values:
            latest = max(value for _, value in date_values)
            days = max(0, (datetime.now(timezone.utc) - latest).days)
            numeric = 1.0 if days <= 45 else 0.9 if days <= 90 else 0.75 if days <= 180 else 0.5 if days <= 365 else 0.2
            if numeric > best:
                best = numeric
                paths = [path for path, value in date_values if value == latest]
        return self._factor(
            "recency",
            best if best > 0 else None,
            trade_rows,
            evidence_paths=paths,
            basis="Opportunity recency uses only bound trade Evidence freshness or an explicit latest-import/shipment date.",
        )

    def _growth_factor(self, trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
        rates: list[tuple[str, float]] = []
        levels: list[tuple[str, str]] = []
        for row in trade_rows:
            value = row.get("value")
            rates.extend(_numbers(value, {"growth_rate", "yoy_growth_rate", "volume_growth_rate", "shipment_growth_rate"}))
            levels.extend(_strings(value, {"growth", "growth_level", "import_growth"}))
        strength, paths = _level_strength(levels)
        if rates:
            maximum = max(value for _, value in rates)
            # Accept either ratio (0.25) or percentage (25).
            ratio = maximum / 100.0 if abs(maximum) > 2 else maximum
            numeric_strength = 1.0 if ratio >= 0.30 else 0.8 if ratio >= 0.15 else 0.6 if ratio >= 0.05 else 0.35 if ratio >= 0 else 0.10
            if strength is None or numeric_strength > strength:
                strength = numeric_strength
                paths = [path for path, value in rates if value == maximum]
        return self._factor(
            "growth",
            strength,
            trade_rows if strength is not None else [],
            evidence_paths=paths,
            basis="Growth uses an explicit evidence-bound growth rate or qualitative growth level; no trend is invented from one shipment.",
        )

    def _ordinal_factor(
        self,
        name: str,
        rows: list[dict[str, Any]],
        keys: set[str],
    ) -> dict[str, Any]:
        values: list[tuple[str, str]] = []
        booleans: list[tuple[str, bool]] = []
        for row in rows:
            value = row.get("value")
            values.extend(_strings(value, keys))
            for path, item in _flatten(value):
                if _leaf_key(path) in keys and isinstance(item, bool):
                    booleans.append((path, item))
        strength, paths = _level_strength(values)
        if strength is None:
            explicit_positive = [path for path, item in booleans if item]
            if explicit_positive:
                strength = 0.8
                paths = explicit_positive
            else:
                for path, text in values:
                    if text.upper() in _POSITIVE_MARKERS:
                        strength = 0.8
                        paths = [path]
                        break
        return self._factor(
            name,
            strength,
            rows if strength is not None else [],
            evidence_paths=paths,
            basis=f"{name} uses only an explicit structured value bound to accepted Evidence.",
        )

    def _commercial_opportunity_factors(
        self,
        state: dict[str, Any],
        claims: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        rows = self._positive_account_rows(state)
        trade_rows = self._trade_factor_rows(rows)
        return {
            "product_fit": self._claim_factor("product_fit", "product.fit", claims, rows),
            "current_import": self._claim_factor("current_import", "trade.import_activity", claims, rows),
            "volume": self._volume_factor(trade_rows),
            "frequency": self._frequency_factor(trade_rows),
            "supplier_diversity": self._supplier_diversity_factor(rows),
            "recency": self._recency_factor(trade_rows),
            "market_channel_position": self._ordinal_factor(
                "market_channel_position",
                rows,
                {"market_position", "channel_position", "market_channel_position", "buyer_scale", "business_scale"},
            ),
            "growth": self._growth_factor(trade_rows),
            "strategic_fit": self._ordinal_factor(
                "strategic_fit",
                rows,
                {"strategic_fit", "strategic_fit_level", "target_segment_fit"},
            ),
            "replacement_opportunity": self._ordinal_factor(
                "replacement_opportunity",
                rows,
                {"replacement_opportunity", "replacement_window", "supplier_change_opportunity", "supplier_switch_opportunity"},
            ),
        }

    def evaluate_commercial_value(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _v6._require_object(arguments, "arguments")
        investigation_id = _v6._nonempty(args.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        claims = self._claims_view(state)

        weighted = sum(
            claim["commercial_weight"] * _CLAIM_STRENGTH[claim["state"]]
            for claim in claims.values()
        )
        total = sum(claim["commercial_weight"] for claim in claims.values()) or 1.0
        baseline = round(100.0 * weighted / total, 2)

        factors = self._commercial_opportunity_factors(state, claims)
        contributions: dict[str, float] = {}
        for name, factor in factors.items():
            strength = factor.get("strength")
            contribution = 0.0 if strength is None else OPPORTUNITY_LIFT_WEIGHTS[name] * float(strength)
            contributions[name] = round(contribution, 4)
            factor["lift_weight"] = OPPORTUNITY_LIFT_WEIGHTS[name]
            factor["score_contribution"] = contributions[name]

        lift = round(sum(contributions.values()), 2)
        score = round(min(100.0, baseline + lift), 2)
        grade = _v6._grade_for_score(score)
        return {
            "schema": "cbi.commercial-value.v6.1",
            "investigation_id": investigation_id,
            "commercial_value_grade": grade,
            "score": score,
            "baseline_claim_score": baseline,
            "opportunity_lift": lift,
            "opportunity_model": "EVIDENCE_BOUND_HEURISTIC_V1",
            "opportunity_factors": factors,
            "unknown_opportunity_factors": [
                name for name, row in factors.items() if row["status"] == "UNKNOWN"
            ],
            "basis": [
                {
                    "claim_key": key,
                    "claim_state": row["state"],
                    "weight": row["commercial_weight"],
                }
                for key, row in claims.items()
                if row["commercial_weight"] > 0
            ],
            "factor_weights_are_probabilities": False,
            "unknown_factors_are_fabricated_zero_facts": False,
            "contact_or_crm_caps_grade": False,
            "conversion_guaranteed": False,
        }

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract["commercial_opportunity_v6_1"] = {
            "factors": list(COMMERCIAL_OPPORTUNITY_FACTORS),
            "model": "EVIDENCE_BOUND_HEURISTIC_V1",
            "lift_weights": dict(OPPORTUNITY_LIFT_WEIGHTS),
            "unknown_factor_policy": "UNKNOWN_DOES_NOT_BECOME_A_FABRICATED_NEGATIVE_FACT",
            "single_shipment_implies_growth": False,
            "contact_or_crm_caps_grade": False,
            "weights_are_probabilities": False,
        }
        hardening = contract.setdefault("production_contract_hardening", {})
        hardening["commercial_opportunity_factors_evidence_bound"] = True
        return contract
