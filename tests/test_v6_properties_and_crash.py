from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


def start(runtime: UnifiedRuntime, account_id: str) -> str:
    return runtime.start_investigation({
        "account": {"account_id": account_id, "country": "Synthetic", "name": "Synthetic Property Buyer"},
        "mode": "EXHAUSTIVE",
        "history": {"events": []},
    })["investigation_id"]


def observation(index: int) -> dict:
    return {
        "claim_key": "product.fit",
        "result": "POSITIVE",
        "value": {"synthetic_index": index},
        "source": {
            "source_family": "synthetic_property_source",
            "source_type": "OFFICIAL",
            "reference_type": "PUBLIC_URL",
            "url": f"https://example.invalid/property/{index}",
            "locator": f"https://example.invalid/property/{index}#fact",
            "raw_excerpt": f"Synthetic property fixture {index}",
            "authority_level": "B1_OFFICIAL_COMPANY",
            "freshness": "CURRENT",
            "observed_at": "2026-08-28T00:00:00Z",
        },
        "boundary": "Synthetic property-test fixture only.",
    }


class V6PropertyAndCrashTests(unittest.TestCase):
    def test_batch_partition_and_order_do_not_change_observation_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v6-property-") as temp:
            one = UnifiedRuntime(Path(temp) / "one")
            many = UnifiedRuntime(Path(temp) / "many")
            one_id = start(one, "C-PROPERTY-SAME")
            many_id = start(many, "C-PROPERTY-SAME")
            rows = [observation(index) for index in range(30)]
            one.compile_and_append_research_bundle({
                "investigation_id": one_id,
                "bundle": {"bundle_id": "BUNDLE-PROPERTY-ALL", "observations": rows},
            })
            for part, chunk in enumerate((rows[20:30], rows[0:10], rows[10:20])):
                many.compile_and_append_research_bundle({
                    "investigation_id": many_id,
                    "bundle": {"bundle_id": f"BUNDLE-PROPERTY-{part}", "observations": chunk},
                })
            one_hashes = {row["source_observation_hash"] for row in one._v6_state(one_id)["observations"].values()}
            many_hashes = {row["source_observation_hash"] for row in many._v6_state(many_id)["observations"].values()}
            self.assertEqual(one_hashes, many_hashes)
            self.assertEqual(len(one_hashes), 30)

    def test_corrupt_tail_is_quarantined_with_last_safe_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v6-crash-") as temp:
            runtime = UnifiedRuntime(Path(temp) / "sessions")
            investigation_id = start(runtime, "C-CRASH-SYNTH")
            before = runtime.get_investigation_health({"investigation_id": investigation_id})
            self.assertEqual(before["status"], "READY")
            with runtime.store.path(investigation_id).open("a", encoding="utf-8") as handle:
                handle.write('{"seq":')
                handle.flush()
            after = runtime.get_investigation_health({"investigation_id": investigation_id})
            self.assertEqual(after["status"], "QUARANTINED_READ_ONLY")
            self.assertTrue(after["read_only"])
            self.assertEqual(after["last_safe_seq"], before["last_safe_seq"])
            self.assertEqual(after["last_safe_event_hash"], before["last_safe_event_hash"])


if __name__ == "__main__":
    unittest.main()
