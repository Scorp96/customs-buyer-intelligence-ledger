from __future__ import annotations

import importlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.core import SessionStore, canonical_json, digest


MODULE = "unified_runtime.exact_checkout_persistence_reader_v63"
INVESTIGATION_ID = "INV-20260903T041500Z-abcdef123456"


class V63ExactCheckoutPersistenceReaderTests(unittest.TestCase):
    def _module(self):
        spec = importlib.util.find_spec(MODULE)
        self.assertIsNotNone(
            spec,
            "exact-checkout read-only persistence reader has not been implemented",
        )
        return importlib.import_module(MODULE)

    def test_reads_valid_session_chain_without_creating_reader_side_effects(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            persistence_root = Path(td)
            session_root = persistence_root / "sessions"
            store = SessionStore(session_root)
            store.create({"investigation_id": INVESTIGATION_ID})
            store.append(
                INVESTIGATION_ID,
                "V63_CANDIDATE_DISCOVERED",
                {
                    "investigation_id": INVESTIGATION_ID,
                    "candidate_id": "CAND-READER-1",
                    "request_sha256": "a" * 64,
                },
            )
            before = sorted(
                str(path.relative_to(persistence_root))
                for path in persistence_root.rglob("*")
            )

            reader = module.ExactCheckoutPersistenceReader(persistence_root)
            events = reader.read_session_events(INVESTIGATION_ID)

            after = sorted(
                str(path.relative_to(persistence_root))
                for path in persistence_root.rglob("*")
            )
            self.assertEqual(before, after)
            self.assertEqual([event["seq"] for event in events], [1, 2])
            self.assertEqual(events[-1]["event_type"], "V63_CANDIDATE_DISCOVERED")
            self.assertEqual(events[-1]["payload"]["candidate_id"], "CAND-READER-1")

    def test_reads_existing_wal_but_never_exposes_raw_idempotency_key(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            persistence_root = Path(td)
            wal_root = persistence_root / "mcp-idempotency-v61"
            wal_root.mkdir(parents=True)
            raw_key = "secret-live-idempotency-key-0001"
            (wal_root / "example.json").write_text(
                json.dumps(
                    {
                        "schema": "cbi.mcp-mutation-wal.v6.1",
                        "status": "COMMITTED",
                        "tool": "append_candidate_discovery",
                        "idempotency_key": raw_key,
                        "request_sha256": "b" * 64,
                        "mutation_correlation_id": "MUTCORR-reader-0001",
                        "result": {
                            "candidate_id": "CAND-READER-1",
                            "mutation_meta": {
                                "idempotency_key": raw_key,
                                "request_sha256": "b" * 64,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            reader = module.ExactCheckoutPersistenceReader(persistence_root)
            rows = reader.read_wal_records()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["tool"], "append_candidate_discovery")
            self.assertEqual(rows[0]["request_sha256"], "b" * 64)
            self.assertEqual(rows[0]["mutation_correlation_id"], "MUTCORR-reader-0001")
            serialized = json.dumps(rows, sort_keys=True)
            self.assertNotIn(raw_key, serialized)
            self.assertNotIn('"idempotency_key"', serialized)

    def test_normalizes_correlation_request_hash_snapshot_and_counts_without_raw_key(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            persistence_root = Path(td)
            session_root = persistence_root / "sessions"
            store = SessionStore(session_root)
            first = store.create({"investigation_id": INVESTIGATION_ID})
            correlation_id = "MUTCORR-reader-opportunity-0001"
            request_sha = "c" * 64
            snapshot = {
                "status": "CREATED",
                "opportunity_id": "OPP-READER-1",
            }
            snapshot_sha = "d" * 64
            second = store.append(
                INVESTIGATION_ID,
                "V63_PRODUCT_OPPORTUNITY_CREATED",
                {
                    "investigation_id": INVESTIGATION_ID,
                    "request_sha256": request_sha,
                    "result_snapshot": snapshot,
                    "result_snapshot_sha256": snapshot_sha,
                },
            )
            second["mutation_correlation"] = {
                "schema": "cbi.mutation-correlation.v6.1",
                "correlation_id": correlation_id,
                "tool": "create_product_opportunity",
            }
            second["event_hash"] = digest(
                {key: value for key, value in second.items() if key != "event_hash"}
            )
            store.path(INVESTIGATION_ID).write_text(
                canonical_json(first) + "\n" + canonical_json(second) + "\n",
                encoding="utf-8",
            )

            raw_key = "secret-opportunity-idempotency-key-0001"
            wal_root = persistence_root / "mcp-idempotency-v61"
            wal_root.mkdir(parents=True)
            (wal_root / "opportunity.json").write_text(
                json.dumps(
                    {
                        "schema": "cbi.mcp-mutation-wal.v6.1",
                        "status": "COMMITTED",
                        "tool": "create_product_opportunity",
                        "idempotency_key": raw_key,
                        "request_sha256": request_sha,
                        "mutation_correlation_id": correlation_id,
                        "result": {
                            **snapshot,
                            "mutation_meta": {"idempotency_key": raw_key},
                        },
                    }
                ),
                encoding="utf-8",
            )

            reader = module.ExactCheckoutPersistenceReader(persistence_root)
            evidence = reader.normalize_mutation_evidence(
                INVESTIGATION_ID,
                "create_product_opportunity",
            )

            self.assertEqual(evidence["event_count"], 1)
            self.assertEqual(evidence["wal_record_count"], 1)
            self.assertEqual(evidence["events"][0]["seq"], 2)
            self.assertEqual(
                evidence["events"][0]["event_type"],
                "V63_PRODUCT_OPPORTUNITY_CREATED",
            )
            self.assertEqual(evidence["events"][0]["correlation_id"], correlation_id)
            self.assertEqual(evidence["events"][0]["request_sha256"], request_sha)
            self.assertEqual(evidence["events"][0]["result_snapshot"], snapshot)
            self.assertEqual(
                evidence["events"][0]["result_snapshot_sha256"],
                snapshot_sha,
            )
            serialized = json.dumps(evidence, sort_keys=True)
            self.assertNotIn(raw_key, serialized)
            self.assertNotIn('"idempotency_key"', serialized)


if __name__ == "__main__":
    unittest.main()
