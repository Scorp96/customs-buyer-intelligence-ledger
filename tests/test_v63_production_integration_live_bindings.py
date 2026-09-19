from __future__ import annotations

import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.mcp_schema_v63 import V63_READ_ONLY_TOOL_NAMES
from unified_runtime.production_integration_v63 import (
    V63OpportunityEventIndex,
    V63ProductionIntegrationMixin,
    _private_bundle,
    product_mentions,
    validate_v63_evidence_provenance,
    validate_v63_opportunity_evidence_binding,
)


_REQUIRED_READ_MODEL_TOOLS = {
    "get_product_opportunities",
    "get_demand_anchors",
    "get_market_cells",
    "evaluate_market_acceptance",
    "get_expansion_state",
}


class _EvidenceRuntime:
    def __init__(self, observation: dict):
        self.observation = observation

    def _v6_state(self, investigation_id: str) -> dict:
        return {
            "start": {"account": {"account_id": "ACC-1"}},
            "observations": {"OBS-1": self.observation},
        }


class _CountingStore:
    def __init__(self, root: Path, event: dict, fail: bool = False):
        self.root = root
        self.event = event
        self.fail = fail
        self.read_count = 0
        (root / "INV-1.jsonl").write_text("{}\n", encoding="utf-8")

    def read(self, investigation_id: str):
        self.read_count += 1
        if self.fail:
            raise RuntimeError("synthetic read failure")
        return [self.event]


def _observation(*, value: dict, boundary: str, reference_type: str = "PUBLIC_URL", source_type: str = "CUSTOMS_MANIFEST") -> dict:
    return {
        "observation_id": "OBS-1",
        "evidence_id": "EVD-1",
        "owner_type": "ACCOUNT",
        "owner_id": "ACC-1",
        "claim_key": "trade.import_activity",
        "result": "POSITIVE",
        "value": value,
        "boundary": boundary,
        "source": {
            "reference_type": reference_type,
            "source_type": source_type,
            "source_family": source_type,
            "freshness": "CURRENT",
        },
    }


class V63ProductionIntegrationExactHeadTests(unittest.TestCase):
    def test_product_aliases_distinguish_pvc_and_wpc(self) -> None:
        self.assertEqual(product_mentions("FREE PVC FOAM BOARD"), {"PVC"})
        self.assertEqual(product_mentions("WPC WALL CLADDING"), {"WPC"})
        self.assertEqual(
            product_mentions("PVC FOAM BOARD and WPC WALL CLADDING"),
            {"PVC", "WPC"},
        )

    def test_same_account_wrong_product_fails_closed(self) -> None:
        runtime = _EvidenceRuntime(
            _observation(
                value={"product": "WPC WALL CLADDING"},
                boundary="Current WPC wall cladding import shipment.",
            )
        )
        result = validate_v63_opportunity_evidence_binding(
            runtime,
            "INV-1",
            {"product_profile_id": "PVC"},
            ["EVD-1"],
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["wrong_product_evidence_ids"], ["EVD-1"])

    def test_multi_product_evidence_is_ambiguous_without_explicit_profile(self) -> None:
        runtime = _EvidenceRuntime(
            _observation(
                value={"product": "PVC FOAM BOARD and WPC WALL CLADDING"},
                boundary="One source row mentions two product families.",
            )
        )
        result = validate_v63_opportunity_evidence_binding(
            runtime,
            "INV-1",
            {"product_profile_id": "PVC"},
            ["EVD-1"],
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["ambiguous_product_evidence_ids"], ["EVD-1"])

    def test_user_input_customs_label_cannot_upgrade_to_direct_procurement(self) -> None:
        runtime = _EvidenceRuntime(
            _observation(
                value={"product": "PVC FOAM BOARD", "shipment": "BOL 123"},
                boundary="User supplied shipment text.",
                reference_type="USER_INPUT",
                source_type="CUSTOMS",
            )
        )
        result = validate_v63_evidence_provenance(
            runtime,
            "INV-1",
            ["EVD-1"],
            "CUSTOMS",
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["failed_evidence_ids"], ["EVD-1"])

    def test_public_customs_manifest_can_support_direct_procurement(self) -> None:
        runtime = _EvidenceRuntime(
            _observation(
                value={"product": "PVC FOAM BOARD", "shipment": "BOL 123"},
                boundary="Public bill of lading proves current import shipment.",
            )
        )
        result = validate_v63_evidence_provenance(
            runtime,
            "INV-1",
            ["EVD-1"],
            "CUSTOMS",
        )
        self.assertTrue(result["valid"])

    def test_opportunity_index_rebuilds_once_then_serves_without_rescan(self) -> None:
        event = {
            "seq": 5,
            "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
            "payload": {
                "investigation_id": "INV-1",
                "result_snapshot": {
                    "opportunity_id": "OPP-1",
                    "account_id": "ACC-1",
                    "product_profile_id": "PVC",
                },
            },
            "mutation_correlation": {"correlation_id": "corr-1"},
        }
        with tempfile.TemporaryDirectory() as td:
            store = _CountingStore(Path(td), event)
            index = V63OpportunityEventIndex()
            index.ensure_built(store)
            for _ in range(20):
                rows = index.query({"account_id": "ACC-1"})
                self.assertEqual(len(rows), 1)
            self.assertEqual(store.read_count, 1)

    def test_opportunity_index_rebuild_failure_is_not_silent(self) -> None:
        event = {
            "seq": 5,
            "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
            "payload": {
                "investigation_id": "INV-1",
                "result_snapshot": {
                    "opportunity_id": "OPP-1",
                    "account_id": "ACC-1",
                    "product_profile_id": "PVC",
                },
            },
            "mutation_correlation": {"correlation_id": "corr-1"},
        }
        with tempfile.TemporaryDirectory() as td:
            store = _CountingStore(Path(td), event, fail=True)
            index = V63OpportunityEventIndex()
            with self.assertRaisesRegex(RuntimeError, "V63_OPPORTUNITY_INDEX_REBUILD_FAILED"):
                index.ensure_built(store)
            self.assertTrue(index.dirty)

    def test_gzip_base64_private_bundle_decodes_without_echoing_specs(self) -> None:
        bundle = {
            "schema": "test.private-capability.v1",
            "public_git_allowed": False,
            "profiles": {"PVC": {"product_profile_id": "PVC"}},
        }
        encoded = base64.b64encode(
            gzip.compress(json.dumps(bundle).encode("utf-8"))
        ).decode("ascii")
        decoded, source = _private_bundle(
            {"CBI_V63_CAPABILITY_BUNDLE_GZIP_B64": encoded}
        )
        self.assertEqual(decoded, bundle)
        self.assertEqual(source, "PRIVATE_ENV_GZIP_B64")

    def test_schema_exposes_all_required_read_model_tools(self) -> None:
        self.assertTrue(_REQUIRED_READ_MODEL_TOOLS.issubset(set(V63_READ_ONLY_TOOL_NAMES)))

    def test_unified_runtime_mro_places_production_integration_before_v63_domain(self) -> None:
        from unified_runtime import UnifiedRuntime

        names = [cls.__name__ for cls in UnifiedRuntime.__mro__]
        self.assertLess(
            names.index("V63ProductionIntegrationMixin"),
            names.index("V63DemandExpansionMixin"),
        )
        self.assertTrue(issubclass(UnifiedRuntime, V63ProductionIntegrationMixin))

    def test_server_registers_all_required_read_model_handlers(self) -> None:
        from mcp import server_v61

        handlers = server_v61._server.TOOL_HANDLERS
        self.assertTrue(_REQUIRED_READ_MODEL_TOOLS.issubset(set(handlers)))


if __name__ == "__main__":
    unittest.main()
