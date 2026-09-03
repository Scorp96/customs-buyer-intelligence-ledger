import unittest

from unified_runtime.legacy_peer_projection import project_legacy_peer_receipt


class V63LegacyPeerProjectionTests(unittest.TestCase):
    def test_legacy_promote_maps_at_most_to_anchor_eligible_signal(self):
        result = project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "P001",
            "promotion_decision": "PROMOTE",
            "canonical_status": "NEW",
            "target_fit_grade": "A",
            "promotion_evidence_grade": "B",
        })
        self.assertEqual(result["maximum_stage"], "ANCHOR_ELIGIBLE_LEGACY_SIGNAL")
        self.assertFalse(result["grants_v63_anchor_authority"])
        self.assertFalse(result["creates_v63_lifecycle_event"])
        self.assertTrue(result["requires_v63_requalification"])

    def test_legacy_do_not_promote_stays_discovery_signal(self):
        result = project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "P002",
            "promotion_decision": "DO_NOT_PROMOTE",
            "canonical_status": "NEW",
        })
        self.assertEqual(result["maximum_stage"], "DISCOVERED_LEGACY_SIGNAL")
        self.assertFalse(result["grants_v63_anchor_authority"])

    def test_existing_or_ambiguous_canonical_peer_never_becomes_new_anchor_signal(self):
        for status in ("EXISTING", "AMBIGUOUS"):
            with self.subTest(status=status):
                result = project_legacy_peer_receipt({
                    "source_event": "PEER_RECEIPT_APPENDED",
                    "peer_id": "P003",
                    "promotion_decision": "PROMOTE",
                    "canonical_status": status,
                })
                self.assertEqual(result["maximum_stage"], "DISCOVERED_LEGACY_SIGNAL")
                self.assertFalse(result["grants_v63_anchor_authority"])

    def test_wrong_source_event_fails_closed(self):
        with self.assertRaises(ValueError):
            project_legacy_peer_receipt({
                "source_event": "EXECUTION_RECEIPT_APPENDED",
                "peer_id": "P004",
                "promotion_decision": "PROMOTE",
                "canonical_status": "NEW",
            })

    def test_projection_is_read_only(self):
        result = project_legacy_peer_receipt({
            "source_event": "PEER_RECEIPT_APPENDED",
            "peer_id": "P005",
            "promotion_decision": "PROMOTE",
            "canonical_status": "NEW",
        })
        self.assertTrue(result["projection_is_read_only"])
        self.assertFalse(result["persistent_mutation_performed"])


if __name__ == "__main__":
    unittest.main()
