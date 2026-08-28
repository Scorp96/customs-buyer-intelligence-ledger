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
            contract["production_contract_hardening"]["production_closure_strategy"],
            "DECISION_SATURATION",
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


if __name__ == "__main__":
    unittest.main()
