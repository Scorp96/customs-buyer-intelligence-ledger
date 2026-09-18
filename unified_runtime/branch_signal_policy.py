from __future__ import annotations

from typing import Any

from .expansion_planner import BRANCH_GROUPS


_TRADE_PROOF_ELIGIBLE = {
    "same_supplier_buyer",
    "same_product_buyer",
    "same_hs_application_buyer",
    "competing_supplier_buyer",
    "importer_network",
    "historical_supplier_network",
    "trade_cluster",
    "competitor_customer",
    "second_source_candidate",
    "supplier_switching_candidate",
}


def get_branch_signal_policy(branch_group: str, branch: str) -> dict[str, Any]:
    group = str(branch_group or "").strip().upper()
    branch_name = str(branch or "").strip()
    allowed = BRANCH_GROUPS.get(group)
    if not allowed or branch_name not in allowed:
        raise ValueError(f"invalid v6.3 branch pair: {group}/{branch_name}")

    default_tier = "D3" if group == "APPLICATION_GRAPH" else "D4"
    trade_proof_eligible = branch_name in _TRADE_PROOF_ELIGIBLE
    result = {
        "branch_group": group,
        "branch": branch_name,
        "default_signal_tier": default_tier,
        "requires_independent_candidate_evidence": True,
        "inherited_anchor_facts": False,
        "archetype_match_can_prove_procurement": False,
        "application_fit_can_be_researched": group == "APPLICATION_GRAPH",
        "candidate_owned_trade_evidence_required_for_d1": trade_proof_eligible,
        "maximum_tier_with_candidate_owned_trade_evidence": "D1" if trade_proof_eligible else None,
        "replacement_opportunity_relevant": group == "COMPETITIVE_GRAPH",
        "cross_sell_hypothesis_only": group == "CROSS_SELL_GRAPH",
        "contact_coverage_is_discovery_gate": False,
        "canonical_identity_required_for_discovery": False,
        "canonical_identity_required_for_research": False,
        "canonical_identity_required_before_qualification": True,
    }
    return result
