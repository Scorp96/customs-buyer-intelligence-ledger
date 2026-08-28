"""Production-contract hardening layered over the v6.1 compatibility runtime.

This module intentionally avoids rewriting the stable compatibility core.  It
adds v6.1-facing derived views and makes legacy contract leakage explicit while
preserving append-only source-of-truth events.
"""

from __future__ import annotations

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
_v6.FRESHNESS_LEVELS = V61_FRESHNESS_LEVELS


class V61ProductionHardeningMixin:
    """Derived v6 production views layered ahead of ``V6RuntimeMixin``."""

    @staticmethod
    def _record_value(record: dict[str, Any]) -> dict[str, Any]:
        value = record.get("value")
        return value if isinstance(value, dict) else {}

    def _canonical_information_routes(self, investigation_id: str) -> list[dict[str, Any]]:
        """Return safe account-owned current routes from append-only Information.

        ``outreach_eligible_effective`` is already the compatibility runtime's
        non-destructive safety decision.  We additionally require currentness,
        account ownership, BUYER_DIRECT scope, verification, non-masked/
        non-guessed values and source Evidence before projecting a v6 Route.
        """
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

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract.setdefault("enums", {})["supply_chain_party_role"] = sorted(V61_CUSTOMS_PARTY_ROLES)
        contract["enums"]["freshness"] = list(V61_FRESHNESS_LEVELS)
        contract["production_contract_hardening"] = {
            "production_closure_strategy": "DECISION_SATURATION",
            "legacy_queue_saturation_is_completion_authority": False,
            "legacy_commercial_grade_cap_is_completion_authority": False,
            "canonical_route_view_includes_information_records": True,
            "resume_returns_last_safe_state": True,
            "account_state_returns_full_v6_view": True,
        }
        for key in ("network_policy_defaults", "network_saturation_policy", "commercial_result_policy"):
            section = contract.get(key)
            if isinstance(section, dict):
                section["legacy_compatibility_only"] = True
                section["does_not_override_v6_decision_saturation"] = True
        return contract

    def evaluate_outreach_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = super().evaluate_outreach_readiness(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        information_routes = self._canonical_information_routes(investigation_id)
        state = self._v6_state(investigation_id)
        claims = self._claims_view(state)
        identity_supported = claims.get("identity.legal_entity", {}).get("state") in {"SUPPORTED", "STRONGLY_SUPPORTED"}

        readiness = str(base.get("readiness") or "BLOCKED")
        named_information = [row for row in information_routes if row.get("named_person")]
        if identity_supported and information_routes and readiness in {"BLOCKED", "IDENTITY_ONLY"}:
            readiness = "NAMED_ROUTE_READY" if named_information else "COMPANY_ROUTE_READY"

        return {
            **base,
            "readiness": readiness,
            "valid_information_route_ids": [row["information_id"] for row in information_routes],
            "canonical_route_view": information_routes,
            "canonical_route_sources": sorted({row["route_source"] for row in information_routes} | ({"COMPILED_OBSERVATION"} if (base.get("valid_company_route_observation_ids") or base.get("valid_named_route_observation_ids")) else set())),
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
        routes = self._canonical_information_routes(investigation_id)
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
