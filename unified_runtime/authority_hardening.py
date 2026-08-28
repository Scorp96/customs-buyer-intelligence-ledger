"""Strict v6.1 Current Authority rules for Buyer Decision Chain claims.

The v6 specification explicitly separates company association from decision
authority. A person can be visibly associated with a company without proving a
current procurement-relevant decision role. This mixin keeps the underlying
append-only observations intact and only changes the derived Claim view.
"""

from __future__ import annotations

from typing import Any

from . import v6 as _v6


CURRENT_ASSOCIATION_STATES = {
    "CURRENT_CONFIRMED",
    "CURRENT_LIKELY",
    "CURRENT",
}

CURRENT_OR_RECENT_ROLE_STATES = {
    "CURRENT_CONFIRMED",
    "CURRENT_LIKELY",
    "CURRENT",
    "RECENT",
}

DECISION_RELEVANT_ROLES = {
    "OWNER",
    "CEO",
    "PRESIDENT",
    "GENERAL_MANAGER",
    "PROCUREMENT_MANAGER",
    "PURCHASING_MANAGER",
    "PURCHASING",
    "SUPPLY_CHAIN_MANAGER",
    "SUPPLY_CHAIN",
}

EXPLICIT_RELEVANCE_VALUES = {
    "DIRECT",
    "HIGH",
    "RELEVANT",
    "PROCUREMENT_RELEVANT",
    "DECISION_RELEVANT",
}


def _role_token(value: Any) -> str:
    return "_".join(
        str(value or "")
        .upper()
        .replace("/", " ")
        .replace("-", " ")
        .replace("&", " ")
        .split()
    )


class V61CurrentAuthorityMixin:
    """Fail closed when a Decision Chain observation lacks current authority proof."""

    @staticmethod
    def _decision_value(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        value = row.get("value") if isinstance(row.get("value"), dict) else {}
        person = value.get("person") if isinstance(value.get("person"), dict) else {}
        return value, person

    def _decision_authority_assessment(self, row: dict[str, Any]) -> dict[str, Any]:
        value, person = self._decision_value(row)
        source = row.get("source") if isinstance(row.get("source"), dict) else {}

        person_name = str(
            value.get("person_name")
            or value.get("name")
            or person.get("name")
            or ""
        ).strip()

        association_state = str(
            value.get("company_association_status")
            or person.get("company_association_status")
            or ""
        ).upper()
        current_association = (
            value.get("company_association_current") is True
            or person.get("company_association_current") is True
            or association_state in CURRENT_ASSOCIATION_STATES
        )

        role = str(
            value.get("role")
            or value.get("title")
            or value.get("position")
            or person.get("role")
            or person.get("title")
            or person.get("position")
            or ""
        ).strip()
        role_state = str(
            value.get("role_freshness")
            or person.get("role_freshness")
            or source.get("freshness")
            or ""
        ).upper()
        role_current_or_recent = bool(role) and (
            value.get("role_current") is True
            or person.get("role_current") is True
            or role_state in CURRENT_OR_RECENT_ROLE_STATES
        )

        relevance = value.get(
            "procurement_relevance",
            person.get("procurement_relevance"),
        )
        role_relevant = (
            relevance is True
            or str(relevance or "").upper() in EXPLICIT_RELEVANCE_VALUES
            or _role_token(role) in DECISION_RELEVANT_ROLES
        )

        missing: list[str] = []
        if not person_name:
            missing.append("NAMED_PERSON_REQUIRED")
        if not current_association:
            missing.append("CURRENT_COMPANY_ASSOCIATION_REQUIRED")
        if not role:
            missing.append("CURRENT_ROLE_REQUIRED")
        elif not role_current_or_recent:
            missing.append("CURRENT_OR_SUFFICIENTLY_RECENT_ROLE_REQUIRED")
        if not role_relevant:
            missing.append("ROLE_RELEVANCE_REQUIRED")

        return {
            "observation_id": row.get("observation_id"),
            "evidence_id": row.get("evidence_id"),
            "person_name": person_name,
            "company_association_current": current_association,
            "role": role,
            "role_freshness": role_state,
            "role_relevant": role_relevant,
            "procurement_relevance": relevance,
            "qualifies": not missing,
            "missing_prerequisites": missing,
        }

    def _claims_view(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        output = super()._claims_view(state)
        claim = output.get("buying_group.decision_chain")
        if not claim:
            return output

        account_id = state["start"]["account"]["account_id"]
        positive_rows = [
            row
            for row in state["observations"].values()
            if row.get("claim_key") == "buying_group.decision_chain"
            and row.get("owner_type") == "ACCOUNT"
            and row.get("owner_id") == account_id
            and row.get("result") == "POSITIVE"
        ]
        assessments = [self._decision_authority_assessment(row) for row in positive_rows]
        qualifying_ids = {
            item["observation_id"]
            for item in assessments
            if item["qualifies"] and item.get("observation_id")
        }
        qualifying_rows = [
            row for row in positive_rows if row.get("observation_id") in qualifying_ids
        ]

        claim["current_authority_policy"] = {
            "requires": [
                "NAMED_PERSON",
                "CURRENT_COMPANY_ASSOCIATION",
                "CURRENT_OR_SUFFICIENTLY_RECENT_ROLE",
                "ROLE_RELEVANCE",
            ],
            "mere_company_association_is_sufficient": False,
        }
        claim["current_authority_assessments"] = assessments
        claim["qualifying_current_authority_observation_ids"] = sorted(qualifying_ids)

        # Preserve stronger adverse states. Current-authority hardening only
        # prevents a positive observation from being over-promoted.
        if positive_rows and claim.get("state") in {"SUPPORTED", "STRONGLY_SUPPORTED"}:
            if not qualifying_rows:
                claim["state"] = "SEARCHING"
                claim["blocked_from_support_reason"] = (
                    "CURRENT_DECISION_AUTHORITY_PREREQUISITES_NOT_PROVEN"
                )
                claim["independent_source_count"] = 0
            else:
                independent_sources = {
                    _v6._independent_source_key(row["source"])
                    for row in qualifying_rows
                }
                strong_authority = any(
                    str(row.get("source", {}).get("authority_level") or "").startswith(
                        ("A1_", "A2_", "B1_")
                    )
                    for row in qualifying_rows
                )
                claim["state"] = (
                    "STRONGLY_SUPPORTED"
                    if len(independent_sources) >= 2 and strong_authority
                    else "SUPPORTED"
                )
                claim["independent_source_count"] = len(independent_sources)
                claim.pop("blocked_from_support_reason", None)
        return output

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract["current_authority_v6_1"] = {
            "decision_chain_requires": [
                "NAMED_PERSON",
                "CURRENT_COMPANY_ASSOCIATION",
                "CURRENT_OR_SUFFICIENTLY_RECENT_ROLE",
                "ROLE_RELEVANCE",
            ],
            "mere_company_association_is_decision_chain_authority": False,
            "association_only_observation_can_support": "CURRENT_ASSOCIATION_ONLY",
            "decision_relevant_roles": sorted(DECISION_RELEVANT_ROLES),
            "buying_group_dimensions": [
                "identity_confidence",
                "company_association_confidence",
                "role_confidence",
                "authority_confidence",
                "route_confidence",
                "procurement_relevance",
                "freshness",
            ],
        }
        hardening = contract.setdefault("production_contract_hardening", {})
        hardening["decision_chain_current_authority_fail_closed"] = True
        return contract
