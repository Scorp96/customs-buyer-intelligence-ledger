import json
import unittest

from scripts.discover_v64_positive_route_candidate import normalizable_lower_named_count, qualified_count, sanitize_health, select_candidate


class PositiveRouteDiscoveryTests(unittest.TestCase):
    def test_scans_all_saturated_rows_and_selects_named_saturated_route_without_value(self):
        company = {"kind":"EMAIL","value":"company@example.invalid","verified":True,"current":True,"owned_by_account":True,"owner_entity_id":"A","masked":False,"guessed":False,"evidence_ids":["E1"],"observation_id":"OBS-COMPANY","route_source":"COMPILED_OBSERVATION"}
        named = {**company,"value":"named@example.invalid","named_person":"Private Name","observation_id":"OBS-NAMED"}
        portfolio = {"queue":[
            {"investigation_id":"INV-COMPANY","decision_saturation":"SATURATED"},
            {"investigation_id":"INV-NAMED","decision_saturation":"SATURATED"},
            {"investigation_id":"INV-UNSAT","decision_saturation":"NOT_SATURATED"},
        ]}
        states = {
            "INV-COMPANY":{"account":{"account_id":"A"},"decision_saturation":{"decision_saturated":True},"outreach_readiness":{"outreach_readiness":"COMPANY_ROUTE_READY","canonical_route_view":[company],"valid_named_route_observation_ids":[]}},
            "INV-NAMED":{"account":{"account_id":"A"},"decision_saturation":{"decision_saturated":True},"outreach_readiness":{"outreach_readiness":"NAMED_ROUTE_READY","canonical_route_view":[named],"valid_named_route_observation_ids":["OBS-NAMED"]}},
        }
        tails = {key:{"last_safe_seq":1,"last_safe_event_hash":"a" * 64} for key in states}
        calls = []
        def call(name, arguments):
            calls.append((name, arguments["investigation_id"]))
            return states[arguments["investigation_id"]] if name == "get_account_state" else tails[arguments["investigation_id"]]
        result = select_candidate(portfolio, call)
        self.assertEqual(result["candidate"]["investigation_id"], "INV-NAMED")
        self.assertNotIn(company["value"], json.dumps(result))
        self.assertNotIn(named["value"], json.dumps(result))
        self.assertNotIn(named["named_person"], json.dumps(result))
        self.assertTrue(result["candidate"]["eligibility"]["fully_qualified_canonical_route"])
        self.assertTrue(result["candidate"]["eligibility"]["named_route"])
        self.assertTrue(result["candidate"]["eligibility"]["decision_saturated"])
        self.assertEqual(calls, [("get_account_state", "INV-COMPANY"), ("get_account_state", "INV-NAMED"), ("get_investigation_state", "INV-NAMED")])

    def test_company_only_route_is_not_an_authoritative_positive_case(self):
        company = {"kind":"EMAIL","value":"company@example.invalid","verified":True,"current":True,"owned_by_account":True,"owner_entity_id":"A","masked":False,"guessed":False,"evidence_ids":["E1"],"observation_id":"OBS-COMPANY","route_source":"COMPILED_OBSERVATION"}
        portfolio = {"queue":[{"investigation_id":"INV-COMPANY","decision_saturation":"SATURATED"}]}
        def call(name, arguments):
            self.assertEqual(name, "get_account_state")
            return {"account":{"account_id":"A"},"decision_saturation":{"decision_saturated":True},"outreach_readiness":{"outreach_readiness":"COMPANY_ROUTE_READY","canonical_route_view":[company],"valid_named_route_observation_ids":[]}}
        result = select_candidate(portfolio, call)
        self.assertEqual(result["result"], "NO_ELIGIBLE_POSITIVE_CASE")
        self.assertIn("COMPANY_ROUTE_ONLY_REJECTED", result["reason_codes"])

    def test_rejects_masked_and_missing_proof(self):
        base = {"kind":"WHATSAPP","value":"+15550101999","verified":True,"current":True,"owned_by_account":True,"owner_entity_id":"A","masked":False,"guessed":False,"evidence_ids":["E1"],"information_id":"INF1"}
        self.assertEqual(qualified_count([{**base,"masked":True,"channel_proof":True}], "A"), 0)
        self.assertEqual(qualified_count([{**base,"channel_proof":False}], "A"), 0)

    def test_recognizes_only_strictly_revalidatable_lower_named_projection_without_value(self):
        row = {"route_source":"COMPILED_OBSERVATION","observation_id":"OBS-NAMED","owner_id":"A","channel":"EMAIL","value":"private@example.invalid","named_person":"Private Name","verified":True,"current":True,"route_scope":"BUYER_DIRECT","evidence_ids":["E1"]}
        readiness = {"valid_named_route_observation_ids":["OBS-NAMED"],"valid_information_route_ids":[]}
        self.assertEqual(normalizable_lower_named_count([row], "A", readiness), 1)
        self.assertEqual(normalizable_lower_named_count([{**row,"owner_id":"OTHER"}], "A", readiness), 0)
        self.assertEqual(normalizable_lower_named_count([{**row,"evidence_ids":[]}], "A", readiness), 0)
        self.assertNotIn(row["value"], json.dumps({"count": normalizable_lower_named_count([row], "A", readiness)}))

    def test_information_lane_requires_explicit_projection_not_legacy_normalization(self):
        row = {
            "route_source": "INFORMATION_RECORD", "information_id": "INFO-NAMED",
            "owner_id": "A", "channel": "EMAIL", "value": "private@example.invalid",
            "named_person": "Private Name", "verified": True, "current": True,
            "route_scope": "BUYER_DIRECT", "evidence_ids": ["E1"],
        }
        readiness = {
            "valid_named_route_observation_ids": [],
            "valid_information_route_ids": ["INFO-NAMED"],
        }
        self.assertEqual(normalizable_lower_named_count([row], "A", readiness), 0)

    def test_health_sanitizer_is_fixed_allowlist(self):
        result = sanitize_health({"status":"ok","durable_root_bound":True,"deployment_identity":{"git_sha":"a311","object_state_generation":7,"restore_generation":7},"object_store_persistence":{"recovery_fingerprint_sha256":"f" * 64},"secret":"no"}, {"mutation_wal":{"prepared_count":0,"invalid_count":0,"reconciliation_required":False,"raw":"no"}})
        self.assertEqual(set(result), {"status","git_sha","object_state_generation","restore_generation","recovery_fingerprint_sha256","runtime_ready","wal_prepared_count","wal_invalid_count","wal_reconciliation_required"})
        self.assertNotIn("secret", json.dumps(result))
