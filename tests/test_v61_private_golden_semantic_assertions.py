from __future__ import annotations

import unittest

from scripts.run_private_golden_acceptance import assert_rule


class V61PrivateGoldenSemanticAssertionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.response = {
            "network": {
                "peers": [
                    {
                        "peer_id": "PEER-SYNTH-001",
                        "name": "Arecibo Home Center, Inc.",
                        "stage": "ANCHOR_ELIGIBLE",
                        "assessment": {
                            "entity_verified": True,
                            "product_fit_verified": True,
                        },
                    },
                    {
                        "peer_id": "PEER-SYNTH-002",
                        "name": "Edwin Seda Perez",
                        "stage": "DISCOVERED",
                        "roles": ["TRADING_INTERMEDIARY", "CUSTOMS_BROKER"],
                    },
                ]
            }
        }

    def test_list_item_subset_matches_nested_semantic_fact_without_index(self) -> None:
        result = assert_rule(
            self.response,
            {
                "path": "network.peers",
                "op": "list_item_subset",
                "value": {
                    "name": "Arecibo Home Center, Inc.",
                    "stage": "ANCHOR_ELIGIBLE",
                    "assessment": {"entity_verified": True},
                },
            },
        )
        self.assertTrue(result["passed"])

    def test_list_item_subset_supports_subset_lists(self) -> None:
        result = assert_rule(
            self.response,
            {
                "path": "network.peers",
                "op": "list_item_subset",
                "value": {
                    "name": "Edwin Seda Perez",
                    "roles": ["CUSTOMS_BROKER"],
                },
            },
        )
        self.assertTrue(result["passed"])

    def test_no_list_item_subset_proves_forbidden_semantic_fact_absent(self) -> None:
        result = assert_rule(
            self.response,
            {
                "path": "network.peers",
                "op": "no_list_item_subset",
                "value": {
                    "name": "Edwin Seda Perez",
                    "roles": ["BUYER_DECISION_MAKER"],
                },
            },
        )
        self.assertTrue(result["passed"])

    def test_no_list_item_subset_fails_when_forbidden_fact_exists(self) -> None:
        result = assert_rule(
            self.response,
            {
                "path": "network.peers",
                "op": "no_list_item_subset",
                "value": {
                    "name": "Arecibo Home Center, Inc.",
                    "stage": "ANCHOR_ELIGIBLE",
                },
            },
        )
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
