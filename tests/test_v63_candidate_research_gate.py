import unittest

from unified_runtime.candidate_research_gate import assess_candidate_researchability


class V63CandidateResearchGateTests(unittest.TestCase):
    def test_d4_candidate_without_canonical_identity_remains_active_research(self):
        result = assess_candidate_researchability({
            "candidate_id": "CAN-D4-1",
            "company_name": "Example Cabinet Works",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.72,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": True,
            "proven_negative": False,
            "duplicate_proven": False,
            "mismatch_proven": False,
        })
        self.assertEqual(result["research_state"], "RESEARCH_ACTIVE")
        self.assertTrue(result["retain_in_candidate_pool"])
        self.assertTrue(result["canonical_research_required"])
        self.assertFalse(result["opportunity_creation_ready"])
        self.assertFalse(result["rejected"])
        self.assertIn("CANONICAL_IDENTITY_UNRESOLVED", result["qualification_gaps"])

    def test_d3_application_proof_is_not_rejected_for_lack_of_procurement_proof(self):
        result = assess_candidate_researchability({
            "candidate_id": "CAN-D3-1",
            "company_name": "Example Sign Fabricator",
            "product_profile_id": "PVC",
            "signal_tier": "D3",
            "eiv": 0.64,
            "canonical_status": "CONFIRMED",
            "product_or_application_signal": True,
            "procurement_proven": False,
        })
        self.assertEqual(result["research_state"], "RESEARCH_ACTIVE")
        self.assertTrue(result["retain_in_candidate_pool"])
        self.assertFalse(result["rejected"])
        self.assertIn("PROCUREMENT_NOT_YET_PROVEN", result["qualification_gaps"])

    def test_d1_candidate_with_confirmed_canonical_can_be_ready_for_qualification(self):
        result = assess_candidate_researchability({
            "candidate_id": "CAN-D1-1",
            "company_name": "Example Importer",
            "product_profile_id": "PVC",
            "signal_tier": "D1",
            "eiv": 0.85,
            "canonical_status": "CONFIRMED",
            "product_or_application_signal": True,
            "procurement_proven": True,
        })
        self.assertEqual(result["research_state"], "READY_FOR_QUALIFICATION")
        self.assertTrue(result["opportunity_creation_ready"])
        self.assertFalse(result["rejected"])

    def test_zero_eiv_weak_signal_is_deferred_not_deleted(self):
        result = assess_candidate_researchability({
            "candidate_id": "CAN-DEFER-1",
            "company_name": "Weak Directory Match",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.0,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": False,
        })
        self.assertEqual(result["research_state"], "DEFERRED_LOW_EIV")
        self.assertTrue(result["retain_in_candidate_pool"])
        self.assertFalse(result["rejected"])

    def test_only_proven_negative_duplicate_or_mismatch_can_reject(self):
        for field in ("proven_negative", "duplicate_proven", "mismatch_proven"):
            with self.subTest(field=field):
                payload = {
                    "candidate_id": "CAN-REJECT-1",
                    "company_name": "Rejected Candidate",
                    "product_profile_id": "PVC",
                    "signal_tier": "D4",
                    "eiv": 0.8,
                    "canonical_status": "UNRESOLVED",
                    "product_or_application_signal": True,
                    field: True,
                }
                result = assess_candidate_researchability(payload)
                self.assertEqual(result["research_state"], "REJECTED_PROVEN")
                self.assertFalse(result["retain_in_candidate_pool"])
                self.assertTrue(result["rejected"])

    def test_contact_is_never_a_discovery_or_research_gate(self):
        result = assess_candidate_researchability({
            "candidate_id": "CAN-NOCONTACT-1",
            "company_name": "No Public Contact Co",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.78,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": True,
            "contact_readiness": "BLOCKED",
        })
        self.assertEqual(result["research_state"], "RESEARCH_ACTIVE")
        self.assertFalse(result["contact_readiness_is_discovery_gate"])
        self.assertFalse(result["contact_readiness_is_research_gate"])


if __name__ == "__main__":
    unittest.main()

class V63CandidateResearchQueueTests(unittest.TestCase):
    def test_high_eiv_d4_candidate_gets_positive_research_priority_without_commercial_grade(self):
        from unified_runtime.candidate_research_gate import rank_candidate_research_queue
        rows = rank_candidate_research_queue([{
            "candidate_id": "CAN-D4-HIGH",
            "company_name": "Regional PVC Cabinet Maker",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.82,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": True,
        }])
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["research_priority"], 0)
        self.assertNotIn("commercial_value_grade", rows[0])
        self.assertTrue(rows[0]["priority_is_research_order_not_commercial_value"])

    def test_d1_outranks_same_eiv_d4_but_d4_is_not_zeroed(self):
        from unified_runtime.candidate_research_gate import rank_candidate_research_queue
        rows = rank_candidate_research_queue([
            {
                "candidate_id": "CAN-D4",
                "company_name": "D4 Co",
                "product_profile_id": "PVC",
                "signal_tier": "D4",
                "eiv": 0.7,
                "canonical_status": "UNRESOLVED",
                "product_or_application_signal": True,
            },
            {
                "candidate_id": "CAN-D1",
                "company_name": "D1 Co",
                "product_profile_id": "PVC",
                "signal_tier": "D1",
                "eiv": 0.7,
                "canonical_status": "CONFIRMED",
                "product_or_application_signal": True,
                "procurement_proven": True,
            },
        ])
        self.assertEqual(rows[0]["candidate_id"], "CAN-D1")
        d4 = next(row for row in rows if row["candidate_id"] == "CAN-D4")
        self.assertGreater(d4["research_priority"], 0)

    def test_proven_rejected_candidate_is_not_in_active_queue(self):
        from unified_runtime.candidate_research_gate import rank_candidate_research_queue
        rows = rank_candidate_research_queue([{
            "candidate_id": "CAN-BAD",
            "company_name": "Mismatch Co",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.9,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": True,
            "mismatch_proven": True,
        }])
        self.assertEqual(rows, [])

    def test_pvc_is_scheduler_preference_not_absolute_commercial_gate(self):
        from unified_runtime.candidate_research_gate import rank_candidate_research_queue
        rows = rank_candidate_research_queue([
            {
                "candidate_id": "PVC-LOWER-EIV",
                "company_name": "PVC Co",
                "product_profile_id": "PVC",
                "signal_tier": "D4",
                "eiv": 0.45,
                "canonical_status": "UNRESOLVED",
                "product_or_application_signal": True,
            },
            {
                "candidate_id": "ACRYLIC-HIGH-EIV",
                "company_name": "Acrylic Co",
                "product_profile_id": "ACRYLIC_PMMA",
                "signal_tier": "D2",
                "eiv": 0.95,
                "canonical_status": "CONFIRMED",
                "product_or_application_signal": True,
            },
        ])
        self.assertEqual(rows[0]["candidate_id"], "ACRYLIC-HIGH-EIV")
