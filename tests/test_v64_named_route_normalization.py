import unittest

from tests.test_v64_route_promotion_safety import ACCOUNT_ID, INVESTIGATION_ID, Runtime


class NamedRouteNormalizationTests(unittest.TestCase):
    def test_lower_named_route_is_reprojected_with_explicit_account_ownership(self):
        runtime = Runtime()
        observation_id = "OBS-NAMED-1"
        evidence_id = "EVD-NAMED-1"
        runtime.state["observations"] = {
            observation_id: {
                "observation_id": observation_id,
                "evidence_id": evidence_id,
                "claim_key": "contact.named_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": ACCOUNT_ID,
                "value": {
                    "channel": "EMAIL",
                    "value": "buyer@example.com",
                    "person_name": "Buyer Name",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": False,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }
        # v6.1 lower canonical row carries legacy owner_id/named_person but not
        # the explicit ownership aliases required by v6.4 route qualification.
        runtime.outreach_result = {
            "outreach_readiness": "NAMED_ROUTE_READY",
            "readiness": "NAMED_ROUTE_READY",
            "valid_company_route_observation_ids": [observation_id],
            "valid_named_route_observation_ids": [observation_id],
            "valid_information_route_ids": [],
            "canonical_route_view": [{
                "route_source": "COMPILED_OBSERVATION",
                "observation_id": observation_id,
                "information_id": "",
                "owner_id": ACCOUNT_ID,
                "channel": "EMAIL",
                "value": "buyer@example.com",
                "named_person": "Buyer Name",
                "verified": True,
                "current": True,
                "route_scope": "BUYER_DIRECT",
                "evidence_ids": [evidence_id],
            }],
            "canonical_route_sources": ["COMPILED_OBSERVATION"],
            "block_reasons": [],
            "sends_message": False,
        }

        result = runtime.evaluate_outreach_readiness({"investigation_id": INVESTIGATION_ID})

        self.assertEqual(result["outreach_readiness"], "NAMED_ROUTE_READY")
        self.assertEqual(result["valid_named_route_observation_ids"], [observation_id])
        routes = result["canonical_route_view"]
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual(route["named_person"], "Buyer Name")
        self.assertTrue(route["owned_by_account"])
        self.assertEqual(route["owner_entity_id"], ACCOUNT_ID)
        self.assertEqual(route["route_scope"], "BUYER_DIRECT")
        self.assertEqual(route["evidence_ids"], [evidence_id])


if __name__ == "__main__":
    unittest.main()
