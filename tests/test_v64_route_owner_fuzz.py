"""Deterministic synthetic safety-invariant matrix. Never tests real customer contacts."""
import random
import unittest
from unified_runtime.route_reuse import reuse_route_for_opportunity


class RouteBindingSafetyInvariants(unittest.TestCase):
    def test_randomized_owner_binding_never_accepts_unproven_or_mismatched_account(self):
        rng = random.Random(20261015)
        seen_reusable = 0
        for _ in range(2048):
            target = rng.choice(["C500", "C600", "C700"])
            owner_scope = rng.choice(["ACCOUNT", "COMPANY", "BUYER", "PERSON", "THIRD_PARTY", ""])
            alias = rng.choice(["", target, "C999"])
            alias2 = rng.choice(["", target, "C999"])
            canon_owner = rng.choice(["", target, "C999", "PERSON-P21"])
            owned = rng.choice([None, True, False])
            route_scope = rng.choice(["BUYER_DIRECT", "THIRD_PARTY", ""])
            route = {
                "route_id": "SYNTHETIC-NO-CONTACT", "owner_scope": owner_scope,
                "route_scope": route_scope, "owner_entity_id": canon_owner,
                "owned_by_account": owned, "account_id": alias,
                "owner_account_id": alias2, "verified": True,
                "route_eligible": True, "guessed": False,
                "freshness": "CURRENT", "current_company_association": True,
                "role_relevant": True, "product_relevance": ["GENERAL_PROCUREMENT"],
            }
            result = reuse_route_for_opportunity(route, {"account_id": target, "product_profile_id": "PVC"})
            if not result["route_reusable"]:
                continue
            seen_reusable += 1
            self.assertNotEqual(owned, False)
            self.assertIn(owner_scope, {"ACCOUNT", "COMPANY", "BUYER", "PERSON"})
            self.assertTrue(alias or alias2 or canon_owner)
            self.assertTrue(all(v == target for v in (alias, alias2) if v))
            if owner_scope in {"ACCOUNT", "COMPANY", "BUYER"} and owned is True and route_scope == "BUYER_DIRECT" and canon_owner:
                self.assertEqual(canon_owner, target)
            elif owner_scope in {"ACCOUNT", "COMPANY", "BUYER"}:
                self.assertTrue(alias or alias2)
            else:
                # PERSON's owner_entity_id may be a person ID, never account proof.
                self.assertTrue(alias or alias2)
            self.assertFalse(result["route_proves_procurement"])
        self.assertGreater(seen_reusable, 10)

if __name__ == '__main__':
    unittest.main()
