"""Production-contract hardening layered over the v6.1 compatibility runtime.

This module intentionally avoids rewriting the stable compatibility core. It
adds v6.1-facing derived views and makes legacy contract leakage explicit while
preserving append-only source-of-truth events.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import core as _core
from . import v6 as _v6


V61_CUSTOMS_PARTY_ROLES = {
    "BUYER",
    "CONSIGNEE",
    "IMPORTER_OF_RECORD",
    "EXPORTER",
    "SHIPPER",
    "DECLARED_MANUFACTURER",
    "PROBABLE_MANUFACTURER",
    "PROBABLE_ACTUAL_MANUFACTURER",  # compatibility alias
    "TRADING_INTERMEDIARY",
    "CUSTOMS_BROKER",
    "NOTIFY_PARTY",
    "FORWARDER",
    "SUPPLIER_GROUP",
}

V61_PIVOT_STATES = (
    "OPEN_MATERIAL",
    "OPEN_OPTIONAL",
    "CONSUMED",
    "DUPLICATE",
    "LOW_VALUE",
    "BLOCKED",
    "EXHAUSTED",
)
V61_TERMINAL_PIVOT_STATES = {
    "CONSUMED",
    "DUPLICATE",
    "LOW_VALUE",
    "BLOCKED",
    "EXHAUSTED",
}

# Preserve existing aliases while exposing the stricter v6 currentness split.
V61_FRESHNESS_LEVELS = (
    "CURRENT_CONFIRMED",
    "CURRENT_LIKELY",
    "LIVE",
    "CURRENT",
    "RECENT",
    "HISTORICAL",
    "STALE",
    "UNKNOWN",
)

# The compatibility validators and MCP schemas read these module-level sets.
# Extending them in-place retains old clients while permitting the v6 roles.
_core.SUPPLY_CHAIN_PARTY_ROLES.update(V61_CUSTOMS_PARTY_ROLES)
_core.EVIDENCE_FRESHNESS.update({"CURRENT_CONFIRMED", "CURRENT_LIKELY"})
_core.INFORMATION_TEMPORAL_STATUS.update({"CURRENT_CONFIRMED", "CURRENT_LIKELY"})
_v6.FRESHNESS_LEVELS = V61_FRESHNESS_LEVELS


class V61ProductionHardeningMixin:
    """Derived v6 production views layered ahead of ``V6RuntimeMixin``."""

    @staticmethod
    def _record_value(record: dict[str, Any]) -> dict[str, Any]:
        value = record.get("value")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _pivot_status(pivot: dict[str, Any], threshold: float) -> str:
        status = str(pivot.get("status") or "OPEN").upper()
        if status == "OPEN":
            if (
                str(pivot.get("materiality") or "OPTIONAL").upper() == "MATERIAL"
                or float(pivot.get("estimated_eiv", 0.0)) >= threshold
            ):
                return "OPEN_MATERIAL"
            return "OPEN_OPTIONAL"
        if status == "NOT_MATERIAL":
            return "LOW_VALUE"
        return status

    def _v6_state(self, investigation_id: str) -> dict[str, Any]:
        """Normalize legacy Pivot aliases in the derived view without rewriting history."""
        state = super()._v6_state(investigation_id)
        threshold = float(state["extension"]["decision_saturation_threshold"])
        for pivot in state["pivots"].values():
            pivot["status"] = self._pivot_status(pivot, threshold)
        return state

    def _normalize_observation(
        self,
        investigation_id: str,
        bundle_id: str,
        index: int,
        raw: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Compile new Pivots directly into the canonical seven-state vocabulary."""
        observation = super()._normalize_observation(
            investigation_id,
            bundle_id,
            index,
            raw,
            state,
        )
        threshold = float(state["extension"]["decision_saturation_threshold"])
        for pivot in observation.get("pivots", []):
            pivot["status"] = self._pivot_status(pivot, threshold)
        return observation

    def _material_pivots(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Only OPEN_MATERIAL is a Decision Saturation blocker in v6.1."""
        return [
            pivot
            for pivot in state["pivots"].values()
            if self._pivot_status(
                pivot,
                float(state["extension"]["decision_saturation_threshold"]),
            )
            == "OPEN_MATERIAL"
        ]

    def get_material_pivots(self, arguments: dict[str, Any]) -> dict[str, Any]:
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        pivots = self._material_pivots(state)
        return {
            "schema": "cbi.pivot-view.v6.1",
            "investigation_id": investigation_id,
            "material_pivots": pivots,
            "count": len(pivots),
            "decision_saturation_blocking_state": "OPEN_MATERIAL",
        }

    @_v6._serialized_v6_mutation
    def close_pivot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Transition an open Pivot into one canonical terminal v6.1 state.

        ``NOT_MATERIAL`` remains accepted only as a direct-runtime compatibility
        alias and is persisted as ``LOW_VALUE``. The production MCP descriptor
        exposes only the canonical seven-state vocabulary.
        """
        args = _v6._require_object(arguments, "arguments")
        investigation_id = _v6._nonempty(args.get("investigation_id"), "investigation_id")
        self._ensure_v6(investigation_id)
        state = self._v6_state(investigation_id)
        _v6._walk_no_secrets(args, "arguments")
        pivot_id = _v6._nonempty(args.get("pivot_id"), "pivot_id")
        pivot = state["pivots"].get(pivot_id)
        if not pivot:
            raise _v6.ValidationError("pivot not found")

        requested = str(args.get("status") or "CONSUMED").upper()
        status = "LOW_VALUE" if requested == "NOT_MATERIAL" else requested
        if status not in V61_TERMINAL_PIVOT_STATES:
            raise _v6.ValidationError(
                "status must be CONSUMED, DUPLICATE, LOW_VALUE, BLOCKED or EXHAUSTED"
            )
        current = self._pivot_status(
            pivot,
            float(state["extension"]["decision_saturation_threshold"]),
        )
        if current in V61_TERMINAL_PIVOT_STATES:
            if current == status:
                return {"accepted": True, "deduplicated": True, **pivot}
            raise _v6.ValidationError("terminal Pivot state cannot regress or be rewritten")

        reason = _v6._nonempty(args.get("reason"), "reason")
        threshold = float(state["extension"]["decision_saturation_threshold"])
        objective_id = ""
        duplicate_of_pivot_id = ""
        max_remaining_eiv = max(0.0, float(pivot.get("estimated_eiv", 0.0)))

        if status == "CONSUMED":
            objective_id = _v6._nonempty(
                args.get("consumed_by_objective_id"),
                "consumed_by_objective_id",
            )
            if objective_id not in state["objectives"]:
                raise _v6.ValidationError("consuming objective not found")
            objective = state["objectives"][objective_id]
            if int(objective.get("_event_seq", 0)) <= int(pivot.get("_generated_seq", 0)):
                raise _v6.ValidationError("Pivot consumption requires a later independent objective")
            pivot_value = str(pivot.get("pivot_value") or "").casefold()
            if pivot_value not in str(objective.get("query_or_navigation") or "").casefold():
                raise _v6.ValidationError("consuming objective must contain the Pivot value")
            max_remaining_eiv = 0.0

        elif status == "LOW_VALUE":
            if len(reason) < 20:
                raise _v6.ValidationError("LOW_VALUE requires a specific decision basis")
            try:
                max_remaining_eiv = float(args.get("max_remaining_eiv"))
            except (TypeError, ValueError) as exc:
                raise _v6.ValidationError("LOW_VALUE requires max_remaining_eiv") from exc
            if not math.isfinite(max_remaining_eiv) or max_remaining_eiv < 0:
                raise _v6.ValidationError("max_remaining_eiv must be a finite non-negative number")
            if max_remaining_eiv >= threshold:
                raise _v6.ValidationError(
                    "LOW_VALUE requires remaining EIV below the decision-saturation threshold"
                )

        elif status == "DUPLICATE":
            duplicate_of_pivot_id = _v6._nonempty(
                args.get("duplicate_of_pivot_id"),
                "duplicate_of_pivot_id",
            )
            if duplicate_of_pivot_id == pivot_id:
                raise _v6.ValidationError("a Pivot cannot be a duplicate of itself")
            if duplicate_of_pivot_id not in state["pivots"]:
                raise _v6.ValidationError("duplicate_of_pivot_id not found")
            if len(reason) < 20:
                raise _v6.ValidationError("DUPLICATE requires a specific equivalence basis")
            max_remaining_eiv = 0.0

        elif status == "BLOCKED":
            if len(reason) < 20:
                raise _v6.ValidationError("BLOCKED requires a specific access or authority blocker")

        elif status == "EXHAUSTED":
            if len(reason) < 20:
                raise _v6.ValidationError("EXHAUSTED requires a specific search-exhaustion basis")
            objective_id = _v6._nonempty(
                args.get("exhausted_by_objective_id"),
                "exhausted_by_objective_id",
            )
            if objective_id not in state["objectives"]:
                raise _v6.ValidationError("exhausting objective not found")
            objective = state["objectives"][objective_id]
            if int(objective.get("_event_seq", 0)) <= int(pivot.get("_generated_seq", 0)):
                raise _v6.ValidationError("Pivot exhaustion requires a later independent objective")
            pivot_value = str(pivot.get("pivot_value") or "").casefold()
            if pivot_value not in str(objective.get("query_or_navigation") or "").casefold():
                raise _v6.ValidationError("exhausting objective must contain the Pivot value")
            try:
                max_remaining_eiv = float(args.get("max_remaining_eiv"))
            except (TypeError, ValueError) as exc:
                raise _v6.ValidationError("EXHAUSTED requires max_remaining_eiv") from exc
            if not math.isfinite(max_remaining_eiv) or max_remaining_eiv < 0:
                raise _v6.ValidationError("max_remaining_eiv must be a finite non-negative number")
            if max_remaining_eiv >= threshold:
                raise _v6.ValidationError(
                    "EXHAUSTED requires remaining EIV below the decision-saturation threshold"
                )

        payload = {
            "schema": "cbi.pivot-transition.v6.1",
            "pivot_id": pivot_id,
            "status": status,
            "reason": reason,
            "consumed_by_objective_id": objective_id if status == "CONSUMED" else "",
            "exhausted_by_objective_id": objective_id if status == "EXHAUSTED" else "",
            "duplicate_of_pivot_id": duplicate_of_pivot_id,
            "max_remaining_eiv": max_remaining_eiv,
            "closed_at": _v6.iso_utc(),
        }
        self.store.append(investigation_id, "V6_PIVOT_CLOSED", payload)
        return {"accepted": True, "deduplicated": False, **payload}

    def _canonical_information_routes(self, investigation_id: str) -> list[dict[str, Any]]:
        """Return safe account-owned current routes from append-only Information."""
        legacy = self._state(investigation_id)
        account_id = legacy["start"]["account"]["account_id"]
        rows: list[dict[str, Any]] = []
        for record in self._current_information_records(legacy):
            if record.get("information_type") not in {"CONTACT", "ROUTE"}:
                continue
            if record.get("subject_owner_id") != account_id:
                continue
            if record.get("route_scope") != "BUYER_DIRECT":
                continue
            if record.get("temporal_status") not in {"CURRENT", "CURRENT_CONFIRMED"}:
                continue
            if record.get("outreach_eligible_effective") is not True:
                continue
            value = self._record_value(record)
            if value.get("verified") is not True or value.get("masked") is True or value.get("guessed") is True:
                continue
            if not (record.get("evidence_ids") or record.get("source_url")):
                continue
            channel = str(value.get("channel") or "").upper().strip()
            route_value = str(value.get("value") or value.get("address") or "").strip()
            if channel not in {"EMAIL", "PHONE", "WHATSAPP", "ZALO"} or not route_value:
                continue
            if channel == "EMAIL" and _v6._EMAIL_RE.fullmatch(route_value) is None:
                continue
            if channel in {"WHATSAPP", "ZALO"} and value.get("channel_proof") is not True:
                continue
            person_name = str(
                value.get("person_name")
                or value.get("name")
                or record.get("subject_name")
                or ""
            ).strip()
            rows.append({
                "route_source": "INFORMATION_RECORD",
                "information_id": record["information_id"],
                "observation_id": "",
                "owner_id": account_id,
                "channel": channel,
                "value": route_value,
                "named_person": person_name if record.get("subject_type") == "PERSON" else "",
                "verified": True,
                "current": True,
                "route_scope": "BUYER_DIRECT",
                "source_url": record.get("source_url") or "",
                "source_locator": record.get("source_locator") or "",
                "evidence_ids": list(record.get("evidence_ids") or []),
            })
        return rows

    def _canonical_compiled_routes(self, investigation_id: str) -> list[dict[str, Any]]:
        """Project safe compiled route observations into the Canonical Route View."""
        state = self._v6_state(investigation_id)
        account_id = state["start"]["account"]["account_id"]
        rows: list[dict[str, Any]] = []
        for observation in state["observations"].values():
            if observation.get("result") != "POSITIVE":
                continue
            if observation.get("claim_key") not in {"contact.company_route", "contact.named_route"}:
                continue
            if observation.get("owner_id") != account_id:
                continue
            value = observation.get("value")
            if not isinstance(value, dict):
                continue
            if value.get("verified") is not True:
                continue
            if value.get("current") is not True or value.get("owned_by_account") is not True:
                continue
            if value.get("masked") is True or value.get("guessed") is True:
                continue
            if observation.get("source", {}).get("freshness") not in {
                "LIVE",
                "CURRENT_CONFIRMED",
                "CURRENT",
            }:
                continue
            channel = str(value.get("channel") or "").upper().strip()
            route_value = str(value.get("value") or "").strip()
            if channel not in {"EMAIL", "PHONE", "WHATSAPP", "ZALO"} or not route_value:
                continue
            if channel == "EMAIL" and _v6._EMAIL_RE.fullmatch(route_value) is None:
                continue
            if channel in {"WHATSAPP", "ZALO"} and value.get("channel_proof") is not True:
                continue
            person_name = str(value.get("person_name") or "").strip()
            rows.append({
                "route_source": "COMPILED_OBSERVATION",
                "information_id": "",
                "observation_id": observation["observation_id"],
                "owner_id": account_id,
                "channel": channel,
                "value": route_value,
                "named_person": person_name if observation.get("claim_key") == "contact.named_route" else "",
                "verified": True,
                "current": True,
                "route_scope": "BUYER_DIRECT",
                "source_url": observation.get("source", {}).get("url") or "",
                "source_locator": observation.get("source", {}).get("locator") or "",
                "evidence_ids": [observation["evidence_id"]] if observation.get("evidence_id") else [],
            })
        return rows

    def _canonical_route_view(self, investigation_id: str) -> list[dict[str, Any]]:
        rows = self._canonical_compiled_routes(investigation_id) + self._canonical_information_routes(investigation_id)
        deduplicated: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            key = (
                str(row.get("channel") or "").upper(),
                str(row.get("value") or "").casefold(),
                str(row.get("named_person") or "").casefold(),
                str(row.get("owner_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(row)
        return deduplicated

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract.setdefault("enums", {})["supply_chain_party_role"] = sorted(V61_CUSTOMS_PARTY_ROLES)
        contract["enums"]["freshness"] = list(V61_FRESHNESS_LEVELS)
        contract["enums"]["pivot_state"] = list(V61_PIVOT_STATES)
        contract["production_contract_hardening"] = {
            "production_closure_strategy": "DECISION_SATURATION",
            "legacy_queue_saturation_is_completion_authority": False,
            "legacy_commercial_grade_cap_is_completion_authority": False,
            "canonical_route_view_includes_information_records": True,
            "canonical_route_view_includes_compiled_observations": True,
            "resume_returns_last_safe_state": True,
            "account_state_returns_full_v6_view": True,
            "pivot_blocking_state": "OPEN_MATERIAL",
            "legacy_pivot_aliases": {"OPEN": "DERIVED_BY_MATERIALITY_AND_EIV", "NOT_MATERIAL": "LOW_VALUE"},
        }
        for key in ("network_policy_defaults", "network_saturation_policy", "commercial_result_policy"):
            section = contract.get(key)
            if isinstance(section, dict):
                section["legacy_compatibility_only"] = True
                section["does_not_override_v6_decision_saturation"] = True
        return contract

    def evaluate_outreach_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Compute readiness from one Canonical Route View across both evidence lanes."""
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        routes = self._canonical_route_view(investigation_id)
        named = [row for row in routes if row.get("named_person")]
        prior_stage = str(state["start"].get("history_highest_stage") or "")
        unexpired_closure = any(
            not closure.get("used")
            and datetime.fromisoformat(str(closure["expires_at"]).replace("Z", "+00:00"))
            > datetime.now(timezone.utc)
            and not any(
                event["seq"] > closure["seq"]
                and event["event_type"] in _v6.V6_OPERATIONAL_EVENTS
                for event in state["events"]
            )
            for closure in state["closures"].values()
        )
        identity_supported = self._claims_view(state)["identity.legal_entity"]["state"] in {
            "SUPPORTED",
            "STRONGLY_SUPPORTED",
        }

        if state["start"].get("opt_out"):
            readiness = "BLOCKED"
            reasons = ["ACCOUNT_OPTED_OUT"]
        elif unexpired_closure and named:
            readiness = "FOLLOW_UP_READY" if prior_stage else "SEND_READY"
            reasons = []
        elif named:
            readiness = "NAMED_ROUTE_READY"
            reasons = ["DECISION_SATURATION_CLOSURE_REQUIRED"]
        elif routes:
            readiness = "COMPANY_ROUTE_READY"
            reasons = ["NAMED_ROUTE_NOT_PROVEN"]
        elif identity_supported:
            readiness = "IDENTITY_ONLY"
            reasons = ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"]
        else:
            readiness = "BLOCKED"
            reasons = ["IDENTITY_AND_ROUTE_NOT_READY"]

        return {
            "schema": "cbi.outreach-readiness.v6.1",
            "investigation_id": investigation_id,
            "outreach_readiness": readiness,
            "readiness": readiness,
            "valid_company_route_observation_ids": [
                row["observation_id"] for row in routes if row.get("observation_id")
            ],
            "valid_named_route_observation_ids": [
                row["observation_id"] for row in named if row.get("observation_id")
            ],
            "valid_information_route_ids": [
                row["information_id"] for row in routes if row.get("information_id")
            ],
            "canonical_route_view": routes,
            "canonical_route_sources": sorted({row["route_source"] for row in routes}),
            "block_reasons": reasons,
            "crm_sync_required_for_readiness": False,
            "sends_message": False,
        }

    def resume_investigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = super().resume_investigation(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        claims = self._claims_view(state)
        pending_host = [
            row for row in self._v6_queue().entries()
            if row.get("investigation_id") == investigation_id
            and row.get("status") in {"PENDING", "PARTIAL_SUCCESS"}
        ]
        critical_conflicts = [
            {"claim_key": key, **value}
            for key, value in claims.items()
            if state["extension"]["claim_catalog"].get(key, {}).get("critical") is True
            and value.get("state") == "CONFLICTED"
        ]
        material_pivots = self._material_pivots(state)
        objectives = self.get_next_research_objectives({"investigation_id": investigation_id, "limit": 25})
        portfolio = self.get_portfolio_queue({"limit": 1000})
        priority = next((row for row in portfolio.get("queue", []) if row.get("investigation_id") == investigation_id), None)
        last = state["events"][-1]
        last_safe_state = {
            "last_committed_mutation": {
                "seq": last["seq"],
                "event_type": last["event_type"],
                "event_hash": last["event_hash"],
            },
            "pending_host_bundles": pending_host,
            "current_objectives": objectives,
            "critical_conflicts": critical_conflicts,
            "material_open_pivots": material_pivots,
            "portfolio_priority": priority,
        }
        return {
            **base,
            "last_safe_state": last_safe_state,
            "pending_host_bundles": pending_host,
            "current_objectives": objectives,
            "critical_conflicts": critical_conflicts,
            "material_open_pivots": material_pivots,
            "portfolio_priority": priority,
        }

    def get_account_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = super().get_account_state(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        legacy = self._state(investigation_id)
        current_information = self._current_information_records(legacy)
        claims = self._claims_view(state)
        routes = self._canonical_route_view(investigation_id)
        material_pivots = self._material_pivots(state)
        next_objectives = self.get_next_research_objectives({"investigation_id": investigation_id, "limit": 25})

        latest_crm = list(legacy.get("crm_writebacks", {}).values())[-1] if legacy.get("crm_writebacks") else None
        if not latest_crm:
            crm_sync = "NOT_REQUESTED"
        elif latest_crm.get("status") == "COMMITTED":
            crm_sync = "COMMITTED"
        elif latest_crm.get("status") == "NO_CHANGE_VERIFIED":
            crm_sync = "NO_CHANGE_REQUIRED"
        elif latest_crm.get("status") == "FAILED":
            crm_sync = "FAILED"
        else:
            crm_sync = "CONFLICT"

        observations = list(state["observations"].values())
        conflicts = [
            {"claim_key": key, **value}
            for key, value in claims.items()
            if value.get("state") == "CONFLICTED"
        ] + [
            row for row in current_information
            if row.get("information_type") == "CONFLICT" or row.get("conflicts_with_information_ids")
        ]
        contacts = [row for row in current_information if row.get("information_type") in {"CONTACT", "ROUTE"}]
        buying_group = [row for row in current_information if row.get("subject_type") == "PERSON"]
        suppliers = [row for row in current_information if row.get("subject_type") == "SUPPLIER"]
        brands = [
            row for row in current_information
            if row.get("subject_type") in {"BRAND", "DBA", "OPERATING_BRAND", "FORMER_BRAND", "STORE_BRAND"}
        ]
        product_rows = [row for row in observations if str(row.get("claim_key") or "").startswith("product.")]
        trade_rows = [row for row in observations if str(row.get("claim_key") or "").startswith("trade.")]

        return {
            **base,
            "crm_sync": crm_sync,
            "identity": dict(base.get("account") or {}),
            "brands": brands,
            "products": product_rows,
            "trade": {"observations": trade_rows},
            "suppliers": suppliers,
            "buying_group": buying_group,
            "contacts": contacts,
            "routes": routes,
            "claims": claims,
            "conflicts": conflicts,
            "network": {"peers": list(state["peers"].values())},
            "material_pivots": material_pivots,
            "next_objectives": next_objectives,
        }
