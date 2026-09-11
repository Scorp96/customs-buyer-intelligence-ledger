#!/usr/bin/env python3
"""Pure Social/Global-Radar -> CBI research handoff mapping.

This module intentionally performs no Runtime construction or mutation. It turns
an already validated upstream candidate bundle into an explicit research seed
while withholding all final CBI commercial authority.
"""

from __future__ import annotations

import copy
from typing import Any

from social_radar_intake import validate_and_normalize_social_radar_candidate


HANDOFF_SCHEMA = "cbi.social-radar-research-handoff.v1"


def build_social_radar_research_handoff(bundle: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_and_normalize_social_radar_candidate(bundle)

    return {
        "schema_version": HANDOFF_SCHEMA,
        "candidate_id": normalized["candidate_id"],
        "candidate_fingerprint": normalized["candidate_fingerprint"],
        "source_stage": normalized["source_stage"],
        "observed_at": normalized["observed_at"],
        "research_seed": {
            "canonical_identity": copy.deepcopy(normalized["canonical_identity"]),
            "profiles": copy.deepcopy(normalized["profiles"]),
        },
        "direct_evidence": copy.deepcopy(normalized["evidence"]),
        "inferences": copy.deepcopy(normalized["inferences"]),
        "routes": copy.deepcopy(normalized["routes"]),
        "discovery": copy.deepcopy(normalized["discovery"]),
        "source_score": copy.deepcopy(normalized["source_score"]),
        "recommended_cbi_priority": normalized["recommended_cbi_priority"],
        "cbi_authority": {
            "commercial_value": "NOT_EVALUATED",
            "research_confidence": "NOT_EVALUATED",
            "outreach_readiness": "NOT_EVALUATED",
            "decision_saturation": "NOT_EVALUATED",
            "final_grade": None,
        },
        "side_effects": {
            "runtime_constructed": False,
            "mcp_mutation_called": False,
            "crm_write_performed": False,
            "outreach_sent": False,
        },
    }
