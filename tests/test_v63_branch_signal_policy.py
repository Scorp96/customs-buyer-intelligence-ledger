import unittest

from unified_runtime.branch_signal_policy import get_branch_signal_policy
from unified_runtime.expansion_planner import BRANCH_GROUPS


class V63BranchSignalPolicyTests(unittest.TestCase):
    def test_every_branch_requires_candidate_owned_evidence(self):
        for group, branches in BRANCH_GROUPS.items():
            for branch in branches:
                with self.subTest(group=group, branch=branch):
                    policy = get_branch_signal_policy(group, branch)
                    self.assertTrue(policy["requires_independent_candidate_evidence"])
                    self.assertFalse(policy["inherited_anchor_facts"])

    def test_regional_peer_is_discovery_only(self):
        policy = get_branch_signal_policy("MARKET_GRAPH", "regional_peer")
        self.assertEqual(policy["default_signal_tier"], "D4")
        self.assertFalse(policy["archetype_match_can_prove_procurement"])

    def test_application_user_match_cannot_prove_procurement(self):
        policy = get_branch_signal_policy("APPLICATION_GRAPH", "downstream_manufacturer")
        self.assertEqual(policy["default_signal_tier"], "D3")
        self.assertFalse(policy["archetype_match_can_prove_procurement"])
        self.assertTrue(policy["application_fit_can_be_researched"])

    def test_same_supplier_buyer_can_reach_d1_only_with_candidate_owned_trade_proof(self):
        policy = get_branch_signal_policy("TRADE_GRAPH", "same_supplier_buyer")
        self.assertEqual(policy["default_signal_tier"], "D4")
        self.assertEqual(policy["maximum_tier_with_candidate_owned_trade_evidence"], "D1")
        self.assertTrue(policy["candidate_owned_trade_evidence_required_for_d1"])

    def test_competing_supplier_buyer_is_high_value_but_still_needs_own_trade_evidence(self):
        policy = get_branch_signal_policy("COMPETITIVE_GRAPH", "competing_supplier_buyer")
        self.assertTrue(policy["replacement_opportunity_relevant"])
        self.assertTrue(policy["candidate_owned_trade_evidence_required_for_d1"])
        self.assertFalse(policy["inherited_anchor_facts"])

    def test_cross_sell_is_hypothesis_only(self):
        policy = get_branch_signal_policy("CROSS_SELL_GRAPH", "same_company_other_product")
        self.assertEqual(policy["default_signal_tier"], "D4")
        self.assertTrue(policy["cross_sell_hypothesis_only"])

    def test_invalid_branch_pair_fails_closed(self):
        with self.assertRaises(ValueError):
            get_branch_signal_policy("MARKET_GRAPH", "same_supplier_buyer")


if __name__ == "__main__":
    unittest.main()

class V63WideDiscoveryBoundaryTests(unittest.TestCase):
    def test_canonical_identity_is_not_required_for_discovery_or_research(self):
        policy = get_branch_signal_policy("MARKET_GRAPH", "regional_peer")
        self.assertFalse(policy["canonical_identity_required_for_discovery"])
        self.assertFalse(policy["canonical_identity_required_for_research"])
        self.assertTrue(policy["canonical_identity_required_before_qualification"])
        self.assertFalse(policy["contact_coverage_is_discovery_gate"])
