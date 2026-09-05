import unittest

from unified_runtime.research_orchestration_hardening import (
    V61ResearchOrchestrationHardeningMixin,
)


class FakeBase:
    def __init__(self):
        self.state = {
            "start": {"account": {"account_id": "SYNTH-ACCOUNT-ROUTE-001"}},
            "observations": {},
        }
        self.next_result = {
            "status": "READY",
            "budget": {
                "allocated_units": 20.0,
                "used_units": 0.0,
                "remaining_units": 20.0,
                "budget_exhaustion_closes_research": False,
            },
            "objectives": [],
            "deferred_objectives": [],
        }
        self.outreach_result = {
            "outreach_readiness": "IDENTITY_ONLY",
            "readiness": "IDENTITY_ONLY",
            "valid_company_route_observation_ids": [],
            "valid_named_route_observation_ids": [],
            "valid_information_route_ids": [],
            "canonical_route_view": [],
            "canonical_route_sources": [],
            "block_reasons": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            "sends_message": False,
        }
        self.info_history = {"merged_current_view": []}
        self.raise_information_history_error = False
        self.decision_result = {
            "status": "PAUSED_RESOURCE_LIMIT",
            "decision_saturated": False,
            "high_eiv_objectives": [],
            "blockers": [],
            "budget_exhausted": True,
            "budget_exhaustion_is_completion": False,
        }
        self.public_plan = {
            "status": "READY",
            "calls": [],
            "returned_count": 0,
            "truncated": False,
        }
        self.account_result = {
            "account": {"account_id": "SYNTH-ACCOUNT-ROUTE-001"},
            "outreach_readiness": dict(self.outreach_result),
            "routes": [],
        }
        self.contract = {}

    def _v6_state(self, investigation_id):
        return self.state

    def get_next_research_objectives(self, arguments):
        return dict(self.next_result)

    def evaluate_outreach_readiness(self, arguments):
        return dict(self.outreach_result)

    def get_information_history(self, arguments):
        if self.raise_information_history_error:
            raise KeyError("supersedes_information_ids")
        return self.info_history

    def evaluate_decision_saturation(self, arguments):
        return dict(self.decision_result)

    def plan_public_source_calls(self, arguments):
        return dict(self.public_plan)

    def get_account_state(self, arguments):
        result = dict(self.account_result)
        result["outreach_readiness"] = dict(self.account_result["outreach_readiness"])
        result["routes"] = list(self.account_result["routes"])
        return result

    def get_runtime_contract(self, arguments):
        return dict(self.contract)


class Runtime(V61ResearchOrchestrationHardeningMixin, FakeBase):
    pass


class ResearchOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.args = {"investigation_id": "INV-TEST"}

    def test_soft_budget_exhaustion_does_not_hide_material_deferred_work(self):
        self.runtime.next_result = {
            "status": "PAUSED_RESOURCE_LIMIT",
            "budget": {
                "allocated_units": 20.0,
                "used_units": 20.0,
                "remaining_units": 0.0,
                "budget_exhaustion_closes_research": False,
            },
            "objectives": [],
            "deferred_objectives": [
                {"claim_key": "contact.named_route", "eiv": 0.378, "material": True}
            ],
        }
        result = self.runtime.get_next_research_objectives(self.args)
        self.assertEqual(result["status"], "PAUSED_RESOURCE_LIMIT")
        self.assertEqual(result["legacy_status"], "PAUSED_RESOURCE_LIMIT")
        self.assertEqual(result["resource_state"], "SOFT_BUDGET_EXCEEDED")
        self.assertEqual(result["research_action"], "CONTINUE_HIGH_EIV_RESEARCH")
        self.assertEqual(result["objectives"][0]["claim_key"], "contact.named_route")
        self.assertEqual(result["budget"]["remaining_units"], 0.0)

    def test_budget_exhaustion_without_work_is_not_fabricated_completion(self):
        self.runtime.next_result["status"] = "PAUSED_RESOURCE_LIMIT"
        self.runtime.next_result["budget"]["remaining_units"] = 0.0
        result = self.runtime.get_next_research_objectives(self.args)
        self.assertEqual(result["status"], "PAUSED_RESOURCE_LIMIT")
        self.assertEqual(result["resource_state"], "EXHAUSTED")
        self.assertEqual(result["research_action"], "NO_HIGH_EIV_WORK")

    def test_compiled_account_owned_verified_route_upgrades_company_readiness(self):
        self.runtime.state["observations"] = {
            "OBS-1": {
                "observation_id": "OBS-1",
                "evidence_id": "EVD-1",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": "SYNTH-ACCOUNT-ROUTE-001",
                "relationship_to_account": "SELF",
                "value": {
                    "channel": "EMAIL",
                    "value": "contact@example.com",
                    "verified": True,
                    "guessed": False,
                    "channel_proof": True,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }
        result = self.runtime.evaluate_outreach_readiness(self.args)
        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(result["valid_company_route_observation_ids"], ["OBS-1"])
        self.assertEqual(result["canonical_route_view"][0]["value"], "contact@example.com")
        self.assertEqual(result["valid_named_route_observation_ids"], [])

    def test_information_record_account_owned_route_is_eligible(self):
        self.runtime.outreach_result = {
            "outreach_readiness": "COMPANY_ROUTE_READY",
            "readiness": "COMPANY_ROUTE_READY",
            "valid_company_route_observation_ids": [],
            "valid_named_route_observation_ids": [],
            "valid_information_route_ids": ["INFO-1"],
            "canonical_route_view": [
                {
                    "information_id": "INFO-1",
                    "kind": "PHONE",
                    "value": "+15550101001",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "owner_entity_id": "SYNTH-ACCOUNT-ROUTE-001",
                    "evidence_ids": ["EVD-I1"],
                    "route_scope": "BUYER_DIRECT",
                    "source": "INFORMATION_HISTORY",
                }
            ],
            "canonical_route_sources": ["INFORMATION_HISTORY"],
            "block_reasons": [],
            "sends_message": False,
        }
        result = self.runtime.evaluate_outreach_readiness(self.args)
        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(result["valid_information_route_ids"], ["INFO-1"])

    def test_lower_valid_information_route_ids_are_preserved_without_reparse(self):
        self.runtime.outreach_result = {
            "outreach_readiness": "COMPANY_ROUTE_READY",
            "readiness": "COMPANY_ROUTE_READY",
            "valid_company_route_observation_ids": [],
            "valid_named_route_observation_ids": [],
            "valid_information_route_ids": ["INFO-LOWER-1"],
            "canonical_route_view": [],
            "canonical_route_sources": ["INFORMATION_HISTORY"],
            "block_reasons": [],
            "sends_message": False,
        }
        self.runtime.raise_information_history_error = True
        result = self.runtime.evaluate_outreach_readiness(self.args)
        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(result["valid_information_route_ids"], ["INFO-LOWER-1"])
        self.assertIn("INFORMATION_HISTORY", result["canonical_route_sources"])

    def test_overlay_does_not_reparse_information_history_after_lower_readiness(self):
        self.runtime.raise_information_history_error = True
        self.runtime.state["observations"] = {
            "OBS-1": {
                "observation_id": "OBS-1",
                "evidence_id": "EVD-1",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": "SYNTH-ACCOUNT-ROUTE-001",
                "value": {
                    "channel": "EMAIL",
                    "value": "contact@example.com",
                    "verified": True,
                    "guessed": False,
                    "channel_proof": True,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }
        result = self.runtime.evaluate_outreach_readiness(self.args)
        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")

    def test_person_owned_route_is_not_promoted_to_company_route(self):
        self.runtime.outreach_result["canonical_route_view"] = [
            {
                "information_id": "INFO-PERSON",
                "kind": "PHONE",
                "value": "+15550101002",
                "verified": True,
                "current": True,
                "owned_by_account": False,
                "owner_entity_id": "PERSON-SYNTH-ROUTE-OWNER-001",
                "route_scope": "BUYER_DIRECT",
                "source": "INFORMATION_HISTORY",
            }
        ]
        result = self.runtime.evaluate_outreach_readiness(self.args)
        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_view"], [])

    def test_decision_and_resource_states_are_independent(self):
        self.runtime.decision_result = {
            "status": "PAUSED_RESOURCE_LIMIT",
            "decision_saturated": False,
            "high_eiv_objectives": [{"claim_key": "contact.named_route", "eiv": 0.378}],
            "blockers": ["CONFLICTED_CLAIM:contact.named_route"],
            "budget_exhausted": True,
            "budget_exhaustion_is_completion": False,
        }
        result = self.runtime.evaluate_decision_saturation(self.args)
        self.assertEqual(result["decision_state"], "NOT_SATURATED")
        self.assertEqual(result["resource_state"], "EXHAUSTED")
        self.assertEqual(result["research_action"], "CONTINUE_HIGH_EIV_RESEARCH")

    def test_saturated_and_budget_exhausted_reports_no_high_eiv_work(self):
        self.runtime.decision_result.update(
            decision_saturated=True,
            high_eiv_objectives=[],
            blockers=[],
        )
        result = self.runtime.evaluate_decision_saturation(self.args)
        self.assertEqual(result["decision_state"], "SATURATED")
        self.assertEqual(result["resource_state"], "EXHAUSTED")
        self.assertEqual(result["research_action"], "NO_HIGH_EIV_WORK")

    def test_missing_public_source_attempt_marks_source_coverage_incomplete(self):
        self.runtime.public_plan = {
            "status": "READY",
            "calls": [{"reason": "MISSING_SOURCE_ATTEMPT"}],
            "returned_count": 1,
            "truncated": False,
        }
        result = self.runtime.plan_public_source_calls(self.args)
        self.assertFalse(result["source_coverage_complete"])
        self.assertEqual(result["source_coverage_status"], "INCOMPLETE")
        self.assertEqual(result["remaining_source_attempt_count_at_least"], 1)

    def test_no_missing_source_attempt_marks_source_coverage_proven_complete(self):
        result = self.runtime.plan_public_source_calls(self.args)
        self.assertTrue(result["source_coverage_complete"])
        self.assertEqual(result["source_coverage_status"], "PROVEN_COMPLETE")

    def test_account_state_reuses_normalized_outreach_and_routes(self):
        self.runtime.state["observations"] = {
            "OBS-ROUTE": {
                "observation_id": "OBS-ROUTE",
                "evidence_id": "EVD-R",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": "SYNTH-ACCOUNT-ROUTE-001",
                "relationship_to_account": "SELF",
                "value": {
                    "channel": "PHONE",
                    "value": "+15550101003",
                    "verified": True,
                    "guessed": False,
                    "channel_proof": True,
                },
                "source": {"freshness": "CURRENT_LIKELY"},
            }
        }
        result = self.runtime.get_account_state(self.args)
        self.assertEqual(result["outreach_readiness"]["readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(result["routes"][0]["value"], "+15550101003")

    def test_account_state_exposes_current_source_coverage_without_mutating_closure(self):
        self.runtime.public_plan = {
            "status": "READY",
            "calls": [{"reason": "MISSING_SOURCE_ATTEMPT"}],
            "returned_count": 1,
            "truncated": False,
        }
        result = self.runtime.get_account_state(self.args)
        coverage = result["source_coverage"]
        self.assertFalse(coverage["source_coverage_complete"])
        self.assertEqual(coverage["source_coverage_status"], "INCOMPLETE")
        self.assertEqual(coverage["remaining_source_attempt_count_at_least"], 1)
        self.assertEqual(
            coverage["closure_snapshot_policy"],
            "CLOSURE_MUTATION_RESULT_UNCHANGED",
        )

    def test_runtime_contract_documents_new_semantics(self):
        result = self.runtime.get_runtime_contract({})
        policy = result["research_orchestration_v6_2"]
        self.assertFalse(policy["budget_exhaustion_stops_host_research"])
        self.assertTrue(policy["decision_saturation_remains_closure_authority"])
        self.assertEqual(policy["company_route_readiness"], "COMPANY_ROUTE_READY")


if __name__ == "__main__":
    unittest.main()
