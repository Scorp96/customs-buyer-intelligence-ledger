from __future__ import annotations

from typing import Any

from .candidate_anchor import MATERIAL_NOVELTY_SIGNALS
from .expansion_planner import BRANCH_GROUPS
from .opportunity_domain import LIFECYCLE_STAGES
from .product_profiles import list_product_profiles
from .wal_contract_v63 import build_v63_wal_contract
from .adapter_recovery_mapping_v63 import V63_PRODUCTION_RECOVERY_MAPPINGS
from .local_outreach_policy import CHANNEL_WINDOWS, OUTREACH_POLICY_VERSION


MARKET_ACCEPTANCE_LEVELS = ("M0", "M1", "M2", "M3", "M4", "M5")
RELATIVE_CLASSES = (
    "UPGRADE_TARGET",
    "SAME_TIER_HIGH",
    "SAME_TIER",
    "STRATEGIC_LOWER",
    "SECONDARY",
    "REJECT",
)
V63_MUTATION_EVENT_TYPES = (
    "V63_CANDIDATE_DISCOVERED",
    "V63_PRODUCT_OPPORTUNITY_CREATED",
    "V63_OPPORTUNITY_ANCHOR_PROMOTED",
)

V63_DERIVED_VIEWS = (
    "DEMAND_ANCHOR",
    "CANDIDATE_RESEARCHABILITY",
    "PRODUCT_OPPORTUNITY_EVALUATION",
    "RELATIVE_OPPORTUNITY",
    "MARKET_ACCEPTANCE",
    "MARKET_SCOPE",
    "EXPANSION_SATURATION",
    "SOURCE_COVERAGE",
    "CONTACT_READINESS",
    "PORTFOLIO_METRICS",
    "LOCAL_OUTREACH_POLICY",
    "SALES_READINESS",
)

V63_STATE_DIMENSIONS = (
    "research_state",
    "resource_state",
    "research_action",
    "source_coverage_state",
    "commercial_value",
    "research_confidence",
    "outreach_readiness",
    "expansion_state",
    "expansion_coverage",
    "market_acceptance",
    "crm_sync_state",
    "closure_state",
)


def build_v63_contract() -> dict[str, Any]:
    profiles = list_product_profiles()
    return {
        "schema": "cbi.demand-expansion.v6.3",
        "primary_product_profile": "PVC",
        "product_profiles": {
            row["profile_id"]: {
                "profile_version": row["profile_version"],
                "profile_sha256": row["profile_sha256"],
                "portfolio_priority": row["portfolio_priority"],
                "scheduler_weight": row["scheduler_weight"],
            }
            for row in profiles
        },
        "opportunity_model": "ONE_CANONICAL_ACCOUNT_MANY_PRODUCT_OPPORTUNITIES",
        "opportunity_lifecycle": list(LIFECYCLE_STAGES),
        "relative_classes": list(RELATIVE_CLASSES),
        "market_acceptance_levels": list(MARKET_ACCEPTANCE_LEVELS),
        "branch_groups": {name: list(branches) for name, branches in BRANCH_GROUPS.items()},
        "material_anchor_novelty_signals": sorted(MATERIAL_NOVELTY_SIGNALS),
        "fixed_depth_or_count_closes_expansion": False,
        "budget_exhaustion_closes_research": False,
        "decision_saturation_remains_closure_authority": True,
        "source_coverage_separate_from_expansion_saturation": True,
        "commercial_value_independent_of_contact": True,
        "contact_readiness_required_for_anchor_eligibility": False,
        "candidate_research_policy": {
            "strategy": "WIDE_DISCOVERY_STRICT_PROMOTION",
            "canonical_identity_required_for_discovery": False,
            "canonical_identity_required_for_research": False,
            "canonical_identity_required_before_opportunity_creation": True,
            "contact_readiness_is_discovery_gate": False,
            "contact_readiness_is_research_gate": False,
            "procurement_proof_required_for_candidate_retention": False,
            "d3_d4_can_remain_research_active": True,
            "positive_eiv_keeps_unresolved_candidate_material": True,
            "proven_rejection_authorities": [
                "PROVEN_NEGATIVE",
                "PROVEN_DUPLICATE",
                "PROVEN_MISMATCH",
            ],
            "strict_gates_apply_at": [
                "OPPORTUNITY_CREATION",
                "COMMERCIAL_CLAIM",
                "ANCHOR_PROMOTION",
                "OUTREACH_EXECUTION",
            ],
        },
        "public_source_execution_boundary": {
            "planning_is_execution_proof": False,
            "real_execution_receipt_required": True,
            "host_execution_required": True,
            "blocked_is_terminal_exhaustion": False,
        },
        "local_outreach_policy": {
            "policy_version": OUTREACH_POLICY_VERSION,
            "iana_timezone_required": True,
            "dst_aware": True,
            "high_or_verified_timezone_confidence_required": True,
            "holiday_calendar_must_be_current_for_execution_ready": True,
            "market_workweek_must_be_resolved_or_curated": True,
            "unknown_market_assumes_mon_fri_for_execution": False,
            "research_language_separate_from_outreach_language": True,
            "language_priority": [
                "RECIPIENT_PREFERENCE",
                "RECIPIENT_REPLY",
                "OFFICIAL_SITE",
                "MARKET_LOCALE",
                "ENGLISH_FALLBACK",
            ],
            "channel_windows_local": {name: [list(window) for window in windows] for name, windows in CHANNEL_WINDOWS.items()},
            "followup_business_days_are_route_result_sensitive": True,
            "hard_bounce_disables_same_route": True,
            "technical_claims_remain_evidence_bound": True,
            "sends_message": False,
            "server_side_draft_created": False,
        },
        "sales_readiness_policy": {
            "commercial_outreach_separate_from_technical_offer": True,
            "route_readiness_required": True,
            "recipient_local_execution_context_required": True,
            "capability_mismatch_blocks_current_product_outreach": True,
            "capability_needs_verification_blocks_technical_promise_only": True,
            "commercial_grade_is_not_mutated_by_readiness": True,
            "sends_message": False,
            "server_side_draft_created": False,
        },
        "legacy_peer_compatibility": {
            "projection_is_read_only": True,
            "legacy_promote_grants_v63_anchor_authority": False,
            "maximum_projection": "ANCHOR_ELIGIBLE_LEGACY_SIGNAL",
        },
        "mutation_event_types": list(V63_MUTATION_EVENT_TYPES),
        "derived_views": list(V63_DERIVED_VIEWS),
        "state_dimensions": list(V63_STATE_DIMENSIONS),
        "mutation_wal_v6_3": build_v63_wal_contract(),
        "production_recovery_mapping_v6_3": {name: dict(mapping) for name, mapping in V63_PRODUCTION_RECOVERY_MAPPINGS.items()},
        "recovery_overlay_binding": "FAIL_CLOSED_PENDING_ACTIVE_OVERLAY_BINDING",
        "recovery_overlay_candidate_is_binding_proof": False,
        "exact_recovery_acceptance_v6_3": {
            "required_before_production": True,
            "reference_runner": "scripts/run_v63_recovery_acceptance.py",
            "live_runner": "scripts/run_v63_live_exact_recovery_acceptance.py",
            "live_receipt_schema": "cbi.v63-live-exact-recovery-receipts.v1",
            "result_schema": "cbi.v63-recovery-acceptance.v1",
            "execution_origin_required": "LIVE_PRODUCTION_CHECKOUT",
            "adapter_path_required": "ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH",
            "must_match_current_production_source_snapshot": True,
            "reference_runner_sufficient": False,
            "side_effect_reexecution_allowed": False,
        },
        "live_backend_correlation_acceptance_v6_3": {
            "required_before_production": True,
            "result_schema": "cbi.v63-backend-correlation-acceptance.v1",
            "adapter_path_required": "EXISTING_PRODUCTION_INVOKE_MUTATION",
            "runtime_store_required": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
            "synthetic_or_reference_run_sufficient": False,
            "side_effect_reexecution_allowed": False,
            "must_match_current_production_source_snapshot": True,
        },
        "live_recovery_overlay_acceptance_v6_3": {
            "required_before_production": True,
            "receipt_schema": "cbi.v63-live-recovery-overlay-receipts.v1",
            "runner": "scripts/run_v63_live_recovery_overlay_acceptance.py",
            "result_schema": "cbi.v63-recovery-overlay-acceptance.v1",
            "active_overlay_path_required": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
            "must_match_current_production_source_snapshot": True,
            "expected_snapshot_must_be_external_authority": True,
            "report_builder_claims_verified": False,
            "reference_runner_sufficient": False,
            "side_effect_reexecution_allowed": False,
        },
        "runtime_durable_backend_contract_v6_3": {
            "schema": "cbi.v63-production-durable-backend.v1",
            "binding_strategy": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
            "parallel_state_store_allowed": False,
            "requires_existing_mutation_correlation": True,
            "raw_idempotency_key_persisted": False,
            "side_effect_reexecution_allowed": False,
            "request_arguments_cannot_authorize_binding": True,
            "concrete_backend_supplied_by_staging": False,
        },
        "mutations_require_existing_wal_integration": True,
        "parallel_wal_allowed": False,
        "persistence_invariants": {
            "append_only": True,
            "exact_durable_event_correlation_required": True,
            "idempotency_required": True,
            "optimistic_concurrency_preserved": True,
            "r2_durable_state_preserved": True,
        },
    }
