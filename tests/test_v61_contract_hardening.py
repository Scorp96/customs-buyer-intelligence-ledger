from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_runtime import (
    EVIDENCE_FRESHNESS,
    FRESHNESS_LEVELS,
    SUPPLY_CHAIN_PARTY_ROLES,
    UnifiedRuntime,
)


class V61ContractHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-hardening-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-HARDEN-SYNTH",
                "country": "Synthetic",
                "name": "Synthetic Hardening Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = started["investigation_id"]

    def observation(
        self,
        claim_key: str,
        suffix: str,
        *,
        value: object | None = None,
        pivots: list[dict] | None = None,
    ) -> dict:
        return {
            "claim_key": claim_key,
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": "C-HARDEN-SYNTH",
            "value": value if value is not None else {"fixture": suffix},
            "source": {
                "source_family": "synthetic_official",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": f"https://example.invalid/hardening/{suffix}",
                "locator": f"https://example.invalid/hardening/{suffix}#record",
                "raw_excerpt": f"Synthetic hardening fixture {suffix}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT_CONFIRMED",
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": "Synthetic test fixture only; no live-company fact is asserted.",
            "pivots": pivots or [],
        }

    def compile(self, observations: list[dict], bundle_id: str) -> dict:
        return self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": bundle_id, "observations": observations},
        })

    def test_complete_customs_party_and_freshness_vocabularies_are_exposed(self) -> None:
        required_roles = {
            "BUYER", "CONSIGNEE", "IMPORTER_OF_RECORD", "EXPORTER", "SHIPPER",
            "DECLARED_MANUFACTURER", "PROBABLE_MANUFACTURER", "TRADING_INTERMEDIARY",
            "CUSTOMS_BROKER", "NOTIFY_PARTY", "FORWARDER", "SUPPLIER_GROUP",
        }
        self.assertTrue(required_roles <= set(SUPPLY_CHAIN_PARTY_ROLES))
        self.assertIn("CURRENT_CONFIRMED", EVIDENCE_FRESHNESS)
        self.assertIn("CURRENT_LIKELY", EVIDENCE_FRESHNESS)
        self.assertIn("CURRENT_CONFIRMED", FRESHNESS_LEVELS)
        self.assertIn("CURRENT_LIKELY", FRESHNESS_LEVELS)

        contract = self.runtime.get_runtime_contract({})
        self.assertTrue(required_roles <= set(contract["enums"]["supply_chain_party_role"]))
        self.assertIn("CURRENT_CONFIRMED", contract["enums"]["freshness"])
        self.assertEqual(
            set(contract["enums"]["pivot_state"]),
            {
                "OPEN_MATERIAL", "OPEN_OPTIONAL", "CONSUMED", "DUPLICATE",
                "LOW_VALUE", "BLOCKED", "EXHAUSTED",
            },
        )
        self.assertEqual(
            contract["production_contract_hardening"]["production_closure_strategy"],
            "DECISION_SATURATION",
        )
        self.assertEqual(
            contract["production_contract_hardening"]["pivot_blocking_state"],
            "OPEN_MATERIAL",
        )

    def test_resume_returns_structured_last_safe_state(self) -> None:
        resumed = self.runtime.resume_investigation({"investigation_id": self.investigation_id})
        self.assertEqual(resumed["status"], "RESUMED")
        last_safe = resumed["last_safe_state"]
        self.assertIn("last_committed_mutation", last_safe)
        self.assertIn("pending_host_bundles", last_safe)
        self.assertIn("current_objectives", last_safe)
        self.assertIn("critical_conflicts", last_safe)
        self.assertIn("material_open_pivots", last_safe)
        self.assertIn("portfolio_priority", last_safe)
        self.assertEqual(
            last_safe["last_committed_mutation"]["event_hash"],
            resumed["last_safe_event_hash"],
        )

    def test_account_state_exposes_full_v6_view_without_fabricating_data(self) -> None:
        state = self.runtime.get_account_state({"investigation_id": self.investigation_id})
        for key in (
            "identity", "brands", "products", "trade", "suppliers", "buying_group",
            "contacts", "routes", "claims", "conflicts", "network", "material_pivots",
            "next_objectives", "crm_sync",
        ):
            self.assertIn(key, state)
        self.assertEqual(state["crm_sync"], "NOT_REQUESTED")
        self.assertEqual(state["brands"], [])
        self.assertEqual(state["contacts"], [])
        self.assertEqual(state["routes"], [])
        self.assertEqual(state["conflicts"], [])

    def test_information_route_updates_primary_outreach_readiness(self) -> None:
        self.compile(
            [self.observation("identity.legal_entity", "identity-route")],
            "BUNDLE-HARDEN-IDENTITY-ROUTE",
        )
        self.runtime.store.append(
            self.investigation_id,
            "INFORMATION_RECORD_APPENDED",
            {
                "record": {
                    "information_id": "INFO-HARDEN-ROUTE-001",
                    "information_type": "ROUTE",
                    "subject_type": "ACCOUNT",
                    "subject_owner_id": "C-HARDEN-SYNTH",
                    "route_scope": "BUYER_DIRECT",
                    "temporal_status": "CURRENT_CONFIRMED",
                    "outreach_eligible_effective": True,
                    "value": {
                        "channel": "EMAIL",
                        "value": "buyer@example.invalid",
                        "verified": True,
                        "masked": False,
                        "guessed": False,
                    },
                    "evidence_ids": ["EVD-HARDEN-HISTORICAL-ROUTE"],
                    "source_url": "https://example.invalid/hardening/contact",
                    "source_locator": "https://example.invalid/hardening/contact#route",
                    "conflicts_with_information_ids": [],
                }
            },
        )
        readiness = self.runtime.evaluate_outreach_readiness({
            "investigation_id": self.investigation_id,
        })
        self.assertEqual(readiness["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(readiness["readiness"], "COMPANY_ROUTE_READY")
        self.assertIn("INFO-HARDEN-ROUTE-001", readiness["valid_information_route_ids"])
        self.assertIn("INFORMATION_RECORD", readiness["canonical_route_sources"])
        state = self.runtime.get_account_state({"investigation_id": self.investigation_id})
        self.assertEqual(state["outreach_readiness"]["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(state["routes"][0]["information_id"], "INFO-HARDEN-ROUTE-001")

    def test_pivot_seven_state_view_and_only_open_material_blocks(self) -> None:
        self.compile(
            [
                self.observation(
                    "identity.legal_entity",
                    "pivot-material",
                    pivots=[{
                        "type": "ALIAS",
                        "value": "Synthetic Material Alias",
                        "materiality": "MATERIAL",
                        "estimated_eiv": 9.0,
                    }],
                ),
                self.observation(
                    "product.fit",
                    "pivot-optional",
                    pivots=[{
                        "type": "APPLICATION",
                        "value": "Synthetic Low Value Application",
                        "materiality": "OPTIONAL",
                        "estimated_eiv": 0.01,
                    }],
                ),
            ],
            "BUNDLE-HARDEN-PIVOT-STATES",
        )
        state = self.runtime._v6_state(self.investigation_id)
        statuses = {pivot["pivot_value"]: pivot["status"] for pivot in state["pivots"].values()}
        self.assertEqual(statuses["Synthetic Material Alias"], "OPEN_MATERIAL")
        self.assertEqual(statuses["Synthetic Low Value Application"], "OPEN_OPTIONAL")

        material = self.runtime.get_material_pivots({"investigation_id": self.investigation_id})
        self.assertEqual(material["count"], 1)
        pivot = material["material_pivots"][0]
        objective = self.runtime.submit_research_objective({
            "investigation_id": self.investigation_id,
            "objective": {
                "claim_key": "identity.legal_entity",
                "query_or_navigation": "Synthetic Material Alias official registry",
                "source_family": "official_registry",
            },
        })
        closed = self.runtime.close_pivot({
            "investigation_id": self.investigation_id,
            "pivot_id": pivot["pivot_id"],
            "status": "CONSUMED",
            "reason": "Consumed by a later independent objective using the exact alias.",
            "consumed_by_objective_id": objective["objective_id"],
        })
        self.assertEqual(closed["status"], "CONSUMED")
        material = self.runtime.get_material_pivots({"investigation_id": self.investigation_id})
        self.assertEqual(material["count"], 0)

    def test_blocked_pivot_is_terminal_but_not_decision_saturation_blocker(self) -> None:
        self.compile(
            [
                self.observation(
                    "identity.legal_entity",
                    "pivot-blocked",
                    pivots=[{
                        "type": "REGISTRY",
                        "value": "Synthetic Blocked Registry Pivot",
                        "materiality": "MATERIAL",
                        "estimated_eiv": 5.0,
                    }],
                )
            ],
            "BUNDLE-HARDEN-PIVOT-BLOCKED",
        )
        pivot = self.runtime.get_material_pivots({
            "investigation_id": self.investigation_id,
        })["material_pivots"][0]
        closed = self.runtime.close_pivot({
            "investigation_id": self.investigation_id,
            "pivot_id": pivot["pivot_id"],
            "status": "BLOCKED",
            "reason": "Registry access is unavailable and no alternate authority route is currently available.",
        })
        self.assertEqual(closed["status"], "BLOCKED")
        self.assertEqual(
            self.runtime.get_material_pivots({"investigation_id": self.investigation_id})["count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
