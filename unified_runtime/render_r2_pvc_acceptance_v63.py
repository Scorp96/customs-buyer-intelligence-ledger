from __future__ import annotations

import copy
from typing import Any

from .product_profiles import get_product_profile
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256


PVC_ACCEPTANCE_SCHEMA = "cbi.render-r2-pvc-acceptance.v6.3"
PERSISTENCE_PROBE_SCHEMA = "cbi.render-r2-persistence-probe.v6.3"
PVC_ACCOUNT_ID = "C-V63-R2-PVC-ACCEPTANCE"
PVC_ACCOUNT_NAME = "Synthetic PVC Acceptance Buyer"
PVC_CANDIDATE_ID = "CAND-V63-R2-PVC-001"
PVC_OPPORTUNITY_ID = "OPP-V63-R2-PVC-001"
PVC_SEED_ANCHOR_ID = "ANCHOR-V63-R2-PVC-SEED"

MUTATION_EVENT_TYPES = {
    "append_candidate_discovery": "V63_CANDIDATE_DISCOVERED",
    "create_product_opportunity": "V63_PRODUCT_OPPORTUNITY_CREATED",
    "promote_opportunity_anchor": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
}

_SENSITIVE_KEY_MARKERS = (
    "idempotency_key",
    "bearer_token",
    "secret_access_key",
    "access_key_id",
    "authorization",
    "credential",
    "password",
    "api_key",
    "private_key",
    "client_secret",
)


def _sensitive_key(value: object) -> bool:
    key = str(value or "").strip().casefold().replace("-", "_")
    return any(marker in key for marker in _SENSITIVE_KEY_MARKERS)


def sanitize_pvc_acceptance_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_pvc_acceptance_value(item)
            for key, item in value.items()
            if not _sensitive_key(key)
        }
    if isinstance(value, list):
        return [sanitize_pvc_acceptance_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_pvc_acceptance_value(item) for item in value]
    return copy.deepcopy(value)


def build_pvc_mutation_arguments(investigation_id: str) -> dict[str, dict[str, Any]]:
    inv = str(investigation_id or "").strip()
    if not inv:
        raise ValueError("investigation_id is required")
    profile = get_product_profile("PVC")
    return {
        "append_candidate_discovery": {
            "investigation_id": inv,
            "candidate": {
                "candidate_id": PVC_CANDIDATE_ID,
                "discovered_from_anchor_id": PVC_SEED_ANCHOR_ID,
                "branch_group": "APPLICATION_GRAPH",
                "branch": "PVC_SIGNAGE_SYNTHETIC",
                "company_name": PVC_ACCOUNT_NAME,
                "product_profile_id": "PVC",
                "discovery_attempt_ids": ["ATTEMPT-V63-R2-PVC-001"],
                "relationship_evidence_ids": ["EV-SYNTH-PVC-REL-001"],
            },
            "idempotency_key": "v63-r2-pvc-candidate-0001",
        },
        "create_product_opportunity": {
            "investigation_id": inv,
            "canonical_resolution": {
                "canonical_status": "CONFIRMED",
                "canonical_account_id": PVC_ACCOUNT_ID,
                "resolver_authority": "EXACT_ACCOUNT_ID",
                "resolver_is_existing_production_authority": True,
                "ambiguous": False,
                "address_only_match": False,
                "alias_only_match": False,
            },
            "opportunity": {
                "opportunity_id": PVC_OPPORTUNITY_ID,
                "account_id": PVC_ACCOUNT_ID,
                "product_profile_id": "PVC",
                "product_profile_version": profile["profile_version"],
                "product_profile_sha256": profile["profile_sha256"],
                "application_ids": ["SIGNAGE"],
                "buyer_archetype_ids": ["SIGN_MAKER"],
                "market_cell_ids": ["SYNTHETIC_PVC_ACCEPTANCE"],
            },
            "idempotency_key": "v63-r2-pvc-opportunity-0001",
        },
        "promote_opportunity_anchor": {
            "investigation_id": inv,
            "opportunity_id": PVC_OPPORTUNITY_ID,
            "promotion_reason": (
                "Synthetic PVC acceptance anchor after exact evidence proof"
            ),
            "anchor_eligibility": {
                "anchor_eligible": True,
                "material_novelty_signals": ["SYNTHETIC_PVC_ACCEPTANCE"],
            },
            "cycle_dedup_complete": True,
            "idempotency_key": "v63-r2-pvc-anchor-0001",
        },
    }


def _mutation_expectations(
    arguments: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    return {
        tool: {
            "event_type": MUTATION_EVENT_TYPES[tool],
            "request_sha256": canonical_v63_wal_request_sha256(tool, args),
        }
        for tool, args in arguments.items()
    }


def _call_mutations(client: Any, arguments: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        tool: sanitize_pvc_acceptance_value(client.call_tool(tool, args))
        for tool, args in arguments.items()
    }


def run_v63_render_r2_pvc_acceptance(
    client: Any,
    replacement_controller: Any,
) -> dict[str, Any]:
    if client is None:
        raise TypeError("client is required")
    if replacement_controller is None:
        raise TypeError("replacement_controller is required")

    health_before = sanitize_pvc_acceptance_value(client.read_health())
    discovery = sanitize_pvc_acceptance_value(client.discover())
    initialized = sanitize_pvc_acceptance_value(client.initialize())
    mutation_surface = sanitize_pvc_acceptance_value(
        client.required_v63_mutation_surface()
    )

    started = client.call_tool(
        "start_investigation",
        {
            "account": {
                "account_id": PVC_ACCOUNT_ID,
                "country": "Synthetic",
                "name": PVC_ACCOUNT_NAME,
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "network_policy": {"closure_strategy": "DECISION_SATURATION"},
            "idempotency_key": "v63-r2-pvc-start-0001",
        },
    )
    investigation_id = str(started.get("investigation_id") or "").strip()
    if not investigation_id:
        raise RuntimeError("PVC_ACCEPTANCE_INVESTIGATION_ID_MISSING")

    planning = sanitize_pvc_acceptance_value(
        client.call_tool(
            "plan_candidate_expansion",
            {
                "investigation_id": investigation_id,
                "product_profile_id": "PVC",
            },
        )
    )

    mutation_arguments = build_pvc_mutation_arguments(investigation_id)
    expectations = _mutation_expectations(mutation_arguments)
    initial_responses = _call_mutations(client, mutation_arguments)
    evidence_before = sanitize_pvc_acceptance_value(
        replacement_controller.collect(investigation_id)
    )
    replacement = sanitize_pvc_acceptance_value(
        replacement_controller.replace_instance()
    )
    health_after = sanitize_pvc_acceptance_value(client.read_health())
    replay_responses = _call_mutations(client, mutation_arguments)
    evidence_after = sanitize_pvc_acceptance_value(
        replacement_controller.collect(investigation_id)
    )

    profile = get_product_profile("PVC")
    receipt = {
        "schema": PVC_ACCEPTANCE_SCHEMA,
        "production_ready": False,
        "health_before": health_before,
        "health_after": health_after,
        "protocol": {
            "discovery": discovery,
            "initialize": initialized,
            "mutation_surface": mutation_surface,
        },
        "product_profile": {
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "profile_sha256": profile["profile_sha256"],
        },
        "investigation_id": investigation_id,
        "planning": {
            "tool": "plan_candidate_expansion",
            "product_profile_id": "PVC",
            "result": planning,
        },
        "mutation_expectations": expectations,
        "initial_responses": initial_responses,
        "evidence_before": evidence_before,
        "replacement": replacement,
        "replay_responses": replay_responses,
        "evidence_after": evidence_after,
    }
    sanitized = sanitize_pvc_acceptance_value(receipt)
    if not isinstance(sanitized, dict):
        raise RuntimeError("PVC_ACCEPTANCE_SANITIZATION_FAILED")
    return sanitized
