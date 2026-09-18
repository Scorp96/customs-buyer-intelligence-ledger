import unittest


PRECEDENTS = {
    "append_peer_discovery",
    "promote_anchor",
    "resolve_or_create_account",
    "append_information_record",
}


def healthy_health():
    return {
        "status": "READY",
        "runtime_version": "6.1.0",
        "mutation_wal": {
            "prepared_count": 0,
            "reconciliation_required": False,
            "guarded_mutation_tools": sorted(PRECEDENTS | {"other"}),
            "automatic_reconciliation_tools": sorted(PRECEDENTS | {"other"}),
            "unreconciled_mutation_tools": [],
            "exact_automatic_reconciliation_complete": True,
            "automatic_reexecution_of_unproven_prepared": False,
        },
        "mutation_event_correlation": {
            "status": "ENABLED",
            "correlation_contains_raw_idempotency_key": False,
        },
        "peer_pivot_lifecycle_recovery": {
            "status": "ENABLED",
            "automatic_reconciliation_tools": ["append_peer_discovery", "promote_anchor"],
            "requires_event_correlation": True,
        },
    }


def healthy_contract(v62=True):
    result = {
        "production_adapter_mutation_wal": {
            "prepared_auto_replay_without_proof": False,
            "automatic_reconciliation_requires_durable_proof": True,
            "exact_automatic_reconciliation_complete": True,
            "durable_event_correlation": {
                "enabled": True,
                "correlation_contains_raw_idempotency_key": False,
                "correlation_alone_authorizes_replay": False,
            },
            "peer_pivot_lifecycle_recovery": {
                "enabled": True,
                "tools": ["append_peer_discovery", "promote_anchor"],
                "requires_exact_event_correlation": True,
                "reexecutes_side_effect": False,
            },
        }
    }
    if v62:
        result["research_orchestration_v6_2"] = {
            "soft_budget": True,
            "budget_exhaustion_closes_research": False,
        }
    return result


class V63LiveContractValidatorTests(unittest.TestCase):
    def test_v61_live_can_prove_recovery_precedents_but_not_v62_baseline(self):
        from unified_runtime.live_contract_validator_v63 import validate_live_phase_b_preconditions
        result = validate_live_phase_b_preconditions(healthy_health(), healthy_contract(v62=False))
        self.assertTrue(result["recovery_precedents_ready"])
        self.assertFalse(result["v62_live_contract_present"])
        self.assertFalse(result["ready_for_v63_phase_b_live"])
        self.assertIn("V62_LIVE_CONTRACT_NOT_PRESENT", result["blockers"])

    def test_v62_overlay_marker_allows_phase_b_even_if_version_string_stays_61(self):
        from unified_runtime.live_contract_validator_v63 import validate_live_phase_b_preconditions
        health = healthy_health()
        self.assertEqual(health["runtime_version"], "6.1.0")
        result = validate_live_phase_b_preconditions(health, healthy_contract(v62=True))
        self.assertTrue(result["v62_live_contract_present"])
        self.assertTrue(result["recovery_precedents_ready"])
        self.assertTrue(result["ready_for_v63_phase_b_live"])
        self.assertEqual(result["blockers"], [])

    def test_unresolved_prepared_intent_blocks_phase_b(self):
        from unified_runtime.live_contract_validator_v63 import validate_live_phase_b_preconditions
        health = healthy_health()
        health["mutation_wal"]["prepared_count"] = 1
        health["mutation_wal"]["reconciliation_required"] = True
        result = validate_live_phase_b_preconditions(health, healthy_contract())
        self.assertFalse(result["ready_for_v63_phase_b_live"])
        self.assertIn("PRODUCTION_WAL_NOT_QUIESCENT", result["blockers"])

    def test_missing_recovery_precedent_blocks_phase_b(self):
        from unified_runtime.live_contract_validator_v63 import validate_live_phase_b_preconditions
        health = healthy_health()
        health["mutation_wal"]["automatic_reconciliation_tools"].remove("append_information_record")
        result = validate_live_phase_b_preconditions(health, healthy_contract())
        self.assertFalse(result["recovery_precedents_ready"])
        self.assertIn("RECOVERY_PRECEDENTS_INCOMPLETE", result["blockers"])
        self.assertIn("append_information_record", result["missing_precedent_tools"])

    def test_unsafe_correlation_or_auto_replay_blocks_phase_b(self):
        from unified_runtime.live_contract_validator_v63 import validate_live_phase_b_preconditions
        health = healthy_health()
        health["mutation_event_correlation"]["correlation_contains_raw_idempotency_key"] = True
        contract = healthy_contract()
        contract["production_adapter_mutation_wal"]["prepared_auto_replay_without_proof"] = True
        result = validate_live_phase_b_preconditions(health, contract)
        self.assertFalse(result["ready_for_v63_phase_b_live"])
        self.assertIn("MUTATION_CORRELATION_POLICY_UNSAFE", result["blockers"])
        self.assertIn("UNPROVEN_PREPARED_REPLAY_NOT_FAIL_CLOSED", result["blockers"])


if __name__ == "__main__":
    unittest.main()
