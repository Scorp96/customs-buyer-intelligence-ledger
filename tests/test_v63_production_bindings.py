import json
import os
import tempfile
import unittest
from pathlib import Path

from unified_runtime.production_integration_bindings_v63 import V63ProductionIntegrationBindingMixin
from unified_runtime.recovery_semantics_v63 import snapshot_sha256
from unified_runtime.product_profiles import get_product_profile


class FakeStore:
    def __init__(self, root, events):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = events
        for inv in events:
            (self.root / f"{inv}.jsonl").write_text("seed\n", encoding="utf-8")

    def read(self, investigation_id):
        return list(self.events.get(investigation_id, []))


def create_event(inv, opp, account, profile="PVC"):
    p = get_product_profile(profile)
    snap = {
        "status": "CREATED",
        "opportunity_id": opp,
        "account_id": account,
        "product_profile_id": profile,
        "product_profile_version": p["profile_version"],
        "product_profile_sha256": p["profile_sha256"],
        "stage": "OPPORTUNITY_CREATED",
    }
    return {
        "seq": 3,
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "mutation_correlation": {
            "schema": "cbi.mutation-correlation.v6.1",
            "correlation_id": "MUTCORR-1234567890abcdef12345678",
            "tool": "create_product_opportunity",
        },
        "payload": {
            "investigation_id": inv,
            "request_sha256": "a" * 64,
            "result_snapshot": snap,
            "result_snapshot_sha256": snapshot_sha256(snap),
            "raw_idempotency_key_persisted": False,
        },
    }


class FakeBase:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        events = {
            "INV-1": [create_event("INV-1", "OPP-C1-PVC", "C1")],
            "INV-2": [create_event("INV-2", "OPP-C2-PVC", "C2")],
        }
        self.store = FakeStore(Path(self.tmp.name) / "sessions", events)
        self.states = {
            "INV-1": self._state("INV-1", "C1"),
            "INV-2": self._state("INV-2", "C2"),
        }

    def _state(self, inv, account):
        return {
            "start": {"account": {"account_id": account}},
            "observations": {
                "O1": {
                    "investigation_id": inv, "owner_type": "ACCOUNT", "owner_id": account,
                    "claim_key": "product.fit", "result": "POSITIVE", "evidence_id": f"E-{account}-PVC",
                    "value": {"product_profile_id": "PVC"}, "commercial_signals": {},
                    "boundary": "PVC foam board evidence",
                    "source": {"source_type": "CUSTOMS", "source_family": "CUSTOMS", "raw_excerpt": "PVC foam board"},
                },
                "O2": {
                    "investigation_id": inv, "owner_type": "ACCOUNT", "owner_id": account,
                    "claim_key": "trade.import_activity", "result": "POSITIVE", "evidence_id": f"E-{account}-TRADE",
                    "value": {"product_profile_id": "PVC"}, "commercial_signals": {},
                    "boundary": "PVC shipment evidence",
                    "source": {"source_type": "CUSTOMS", "source_family": "CUSTOMS", "raw_excerpt": "PVC foam board shipment"},
                },
                "O3": {
                    "investigation_id": inv, "owner_type": "ACCOUNT", "owner_id": account,
                    "claim_key": "commercial.procurement_need", "result": "POSITIVE", "evidence_id": f"E-{account}-NEED",
                    "value": {"product_profile_id": "PVC"}, "commercial_signals": {},
                    "boundary": "PVC procurement evidence",
                    "source": {"source_type": "CUSTOMS", "source_family": "CUSTOMS", "raw_excerpt": "PVC foam board procurement"},
                },
                "O4": {
                    "investigation_id": inv, "owner_type": "ACCOUNT", "owner_id": account,
                    "claim_key": "product.fit", "result": "POSITIVE", "evidence_id": f"E-{account}-WPC",
                    "value": {"product_profile_id": "WPC"}, "commercial_signals": {},
                    "boundary": "WPC decking evidence",
                    "source": {"source_type": "PUBLIC_WEB", "source_family": "PUBLIC_WEB", "raw_excerpt": "WPC decking"},
                },
            },
        }

    def _v6_state(self, investigation_id):
        return self.states[investigation_id]

    def get_claims(self, arguments):
        account = self.states[arguments["investigation_id"]]["start"]["account"]["account_id"]
        return {"claims": {
            "product.fit": {"state": "STRONGLY_SUPPORTED", "commercial_weight": 1.0, "evidence_ids": [f"E-{account}-PVC"]},
            "trade.import_activity": {"state": "STRONGLY_SUPPORTED", "commercial_weight": 1.0, "evidence_ids": [f"E-{account}-TRADE"]},
            "commercial.procurement_need": {"state": "STRONGLY_SUPPORTED", "commercial_weight": 1.0, "evidence_ids": [f"E-{account}-NEED"]},
        }}

    def evaluate_research_confidence(self, arguments):
        return {"score": 90.0, "research_confidence": "R5"}

    def evaluate_outreach_readiness(self, arguments):
        return {"outreach_readiness": "COMPANY_ROUTE_READY"}

    def _invoke_v63_durable_mutation(self, tool_name, arguments):
        return {"status": "BASE_CALLED", "tool": tool_name}


class Runtime(V63ProductionIntegrationBindingMixin, FakeBase):
    pass


class ProductionBindingTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def tearDown(self):
        self.runtime.tmp.cleanup()

    def test_event_reader_normalizes_correlation_envelope(self):
        rows = self.runtime._read_v63_durable_events("INV-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["correlation_id"], "MUTCORR-1234567890abcdef12345678")

    def test_global_query_uses_derived_locator_and_returns_authoritative_events(self):
        rows = self.runtime._query_v63_opportunity_events({"account_id": "C2", "product_profile_id": "PVC"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["investigation_id"], "INV-2")
        index = json.loads(self.runtime._v63_locator_index_path().read_text(encoding="utf-8"))
        self.assertEqual(index["authority"], "DERIVED_LOCATOR_ONLY")
        self.assertTrue(index["session_event_chain_remains_authority"])

    def test_legacy_bridge_never_shadows_existing_v63_durable_events(self):
        result = self.runtime._v63_project_legacy_v61_opportunities({"investigation_id": "INV-1"})
        self.assertEqual(result["status"], "NOT_APPLICABLE")
        self.assertEqual(result["opportunities"], [])
        self.assertTrue(result["projection_read_only"])

    def test_ownership_rejects_cross_investigation(self):
        result = self.runtime._validate_v63_evidence_ownership("INV-1", "C1", ["E-C2-PVC"])
        self.assertFalse(result["valid"])

    def test_provenance_uses_persisted_source_not_caller_label(self):
        good = self.runtime._validate_v63_evidence_provenance("INV-1", ["E-C1-PVC"], "CUSTOMS")
        bad = self.runtime._validate_v63_evidence_provenance("INV-1", ["E-C1-WPC"], "CUSTOMS")
        self.assertTrue(good["valid"])
        self.assertFalse(bad["valid"])

    def test_product_binding_rejects_same_account_wrong_product(self):
        opportunity = {"account_id": "C1", "product_profile_id": "PVC"}
        good = self.runtime._validate_v63_opportunity_evidence_binding("INV-1", opportunity, ["E-C1-PVC"])
        bad = self.runtime._validate_v63_opportunity_evidence_binding("INV-1", opportunity, ["E-C1-WPC"])
        self.assertTrue(good["valid"])
        self.assertFalse(bad["valid"])

    def test_derived_view_only_uses_product_bound_claim_evidence(self):
        opportunity = {"opportunity_id": "OPP-C1-PVC", "account_id": "C1", "product_profile_id": "PVC"}
        view = self.runtime._derive_v63_opportunity_runtime_view("INV-1", opportunity)
        self.assertEqual(view["commercial_value_grade"], "A+")
        self.assertEqual(view["lifecycle_target"], "QUALIFIED_TARGET")
        self.assertEqual(len(view["commercial_evidence_ids"]), 3)

    def test_private_capability_json_loader_is_private_contract_only(self):
        old = os.environ.get("CBI_V63_PRIVATE_CAPABILITY_BUNDLE_JSON")
        try:
            os.environ["CBI_V63_PRIVATE_CAPABILITY_BUNDLE_JSON"] = json.dumps({"public_git_allowed": False, "profiles": {"PVC": {}}})
            bundle = self.runtime._load_v63_capability_bundle()
            self.assertFalse(bundle["public_git_allowed"])
        finally:
            if old is None:
                os.environ.pop("CBI_V63_PRIVATE_CAPABILITY_BUNDLE_JSON", None)
            else:
                os.environ["CBI_V63_PRIVATE_CAPABILITY_BUNDLE_JSON"] = old

    def test_mutation_refreshes_target_locator(self):
        self.runtime._ensure_v63_locator_index()
        result = self.runtime._invoke_v63_durable_mutation("create_product_opportunity", {"investigation_id": "INV-1"})
        self.assertEqual(result["status"], "BASE_CALLED")


if __name__ == "__main__":
    unittest.main()
