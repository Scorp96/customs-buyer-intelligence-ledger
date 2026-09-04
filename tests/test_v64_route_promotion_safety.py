import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_overlay():
    try:
        from unified_runtime.research_orchestration_hardening import (  # type: ignore
            V61ResearchOrchestrationHardeningMixin,
        )
        from unified_runtime.errors import ValidationError  # type: ignore
        return V61ResearchOrchestrationHardeningMixin, ValidationError
    except ModuleNotFoundError:
        for name in list(sys.modules):
            if name == "unified_runtime" or name.startswith("unified_runtime."):
                sys.modules.pop(name, None)
        root = Path(__file__).resolve().parents[1]
        if (root / "unified_runtime" / "__init__.py").exists():
            from unified_runtime.research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin  # type: ignore
            from unified_runtime.errors import ValidationError  # type: ignore
            return V61ResearchOrchestrationHardeningMixin, ValidationError
        package = types.ModuleType("unified_runtime")
        package.__path__ = [str(root / "unified_runtime")]
        sys.modules["unified_runtime"] = package
        errors = types.ModuleType("unified_runtime.errors")

        class ValidationError(ValueError):
            pass

        errors.ValidationError = ValidationError
        sys.modules["unified_runtime.errors"] = errors
        path = root / "unified_runtime" / "research_orchestration_hardening.py"
        spec = importlib.util.spec_from_file_location(
            "unified_runtime.research_orchestration_hardening", path
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.V61ResearchOrchestrationHardeningMixin, ValidationError


V61ResearchOrchestrationHardeningMixin, ValidationError = _load_overlay()


ACCOUNT_ID = "SYNTH-ACCOUNT-001"
INVESTIGATION_ID = "INV-SYNTH-001"


def information_route(*, temporal_status="CURRENT", channel="EMAIL", value="buyer@example.com", **overrides):
    record = {
        "information_id": "INFO-1",
        "information_type": "ROUTE",
        "subject_owner_id": ACCOUNT_ID,
        "related_account_id": ACCOUNT_ID,
        "route_scope": "BUYER_DIRECT",
        "temporal_status": temporal_status,
        "confidence": "HIGH",
        "outreach_eligible_claimed": True,
        "outreach_eligible_effective": temporal_status == "CURRENT",
        "usage_warnings": [] if temporal_status == "CURRENT" else ["CONTACT_IS_NOT_CONFIRMED_CURRENT"],
        "supersedes_information_ids": [],
        "conflicts_with_information_ids": [],
        "evidence_ids": ["EVD-1"],
        "value": {
            "channel": channel,
            "value": value,
            "verified": True,
            "masked": False,
            "guessed": False,
        },
    }
    for key, val in overrides.items():
        if key.startswith("value_"):
            record["value"][key[6:]] = val
        else:
            record[key] = val
    return record


class FakeCanonicalRegistry:
    def __init__(self):
        self.result = {"status": "NOT_FOUND", "match": None, "candidates": []}

    def resolve(self, identity):
        self.last_identity = dict(identity)
        return dict(self.result)


class FakeBase:
    def __init__(self):
        self.state = {
            "start": {"investigation_id": INVESTIGATION_ID, "account": {"account_id": ACCOUNT_ID}},
            "observations": {},
            "peers": {},
        }
        self.compat_state = {
            "start": {"account": {"account_id": ACCOUNT_ID}},
            "information_records": {},
            "evidence": {"EVD-1": {"evidence_id": "EVD-1"}},
        }
        self.outreach_result = {
            "outreach_readiness": "IDENTITY_ONLY",
            "readiness": "IDENTITY_ONLY",
            "valid_company_route_observation_ids": [],
            "valid_named_route_observation_ids": [],
            "valid_information_route_ids": [],
            "canonical_route_view": [],
            "canonical_route_sources": [],
            "block_reasons": ["VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"],
            "sends_message": False,
        }
        self.canonical_registry = FakeCanonicalRegistry()
        self.promotions = 0
        self.discoveries = 0
        self.evaluations = 0

    def _v6_state(self, investigation_id):
        return self.state

    def _state(self, investigation_id):
        return self.compat_state

    def _claims_view(self, state):
        return state.get("claims", {})

    @staticmethod
    def _information_route_warnings(record, account_id):
        warnings = []
        if record.get("outreach_eligible_claimed") is not True:
            return warnings
        if record.get("information_type") not in {"CONTACT", "ROUTE"}:
            warnings.append("INFORMATION_TYPE_IS_NOT_A_CONTACT_OR_ROUTE")
        if record.get("subject_owner_id") != account_id:
            warnings.append("SUBJECT_OWNER_IS_NOT_THE_BUYER_ACCOUNT")
        if record.get("route_scope") != "BUYER_DIRECT":
            warnings.append("ROUTE_SCOPE_IS_NOT_BUYER_DIRECT")
        if record.get("temporal_status") != "CURRENT":
            warnings.append("CONTACT_IS_NOT_CONFIRMED_CURRENT")
        if record.get("confidence") not in {"HIGH", "MEDIUM_HIGH"}:
            warnings.append("CONFIDENCE_TOO_LOW_FOR_DIRECT_OUTREACH")
        value = record.get("value") or {}
        if value.get("verified") is not True:
            warnings.append("CONTACT_NOT_VERIFIED")
        if value.get("masked") is True:
            warnings.append("MASKED_CONTACT")
        if value.get("guessed") is True:
            warnings.append("GUESSED_CONTACT")
        channel = str(value.get("channel") or "").upper()
        route_value = str(value.get("value") or "").strip()
        if not channel or not route_value:
            warnings.append("CONTACT_CHANNEL_OR_VALUE_MISSING")
        elif channel in {"WHATSAPP", "ZALO"} and value.get("channel_proof") is not True:
            warnings.append(f"{channel}_CHANNEL_NOT_PROVEN")
        return sorted(set(warnings))

    def evaluate_outreach_readiness(self, arguments):
        return dict(self.outreach_result)

    def get_account_state(self, arguments):
        return {"account": {"account_id": ACCOUNT_ID}}

    def plan_public_source_calls(self, arguments):
        return {"calls": [], "truncated": False}

    def append_peer_discovery(self, arguments):
        self.discoveries += 1
        return {"accepted": True, "peer_id": arguments["peer_id"]}

    def evaluate_peer(self, arguments):
        self.evaluations += 1
        return {"accepted": True, "peer_id": arguments["peer_id"]}

    def promote_anchor(self, arguments):
        self.promotions += 1
        peer_id = arguments["peer_id"]
        self.state["peers"][peer_id]["stage"] = "PROMOTED_ANCHOR"
        return {"accepted": True, "peer_id": peer_id, "stage": "PROMOTED_ANCHOR"}


class Runtime(V61ResearchOrchestrationHardeningMixin, FakeBase):
    pass


class RouteSafetyTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.args = {"investigation_id": INVESTIGATION_ID}

    def test_current_confirmed_information_route_has_no_currentness_warning(self):
        record = information_route(temporal_status="CURRENT_CONFIRMED")
        warnings = self.runtime._information_route_warnings(record, ACCOUNT_ID)
        self.assertNotIn("CONTACT_IS_NOT_CONFIRMED_CURRENT", warnings)

    def test_only_current_and_current_confirmed_are_strong_direct_states(self):
        for state in ("CURRENT", "CURRENT_CONFIRMED"):
            with self.subTest(state=state):
                warnings = self.runtime._information_route_warnings(
                    information_route(temporal_status=state), ACCOUNT_ID
                )
                self.assertNotIn("CONTACT_IS_NOT_CONFIRMED_CURRENT", warnings)
        for state in ("LIVE", "CURRENT_LIKELY", "RECENT", "HISTORICAL", "STALE", "UNKNOWN"):
            with self.subTest(state=state):
                warnings = self.runtime._information_route_warnings(
                    information_route(temporal_status=state), ACCOUNT_ID
                )
                self.assertIn("CONTACT_IS_NOT_CONFIRMED_CURRENT", warnings)

    def test_current_confirmed_does_not_bypass_other_route_safety_gates(self):
        cases = [
            ("unverified", {"value_verified": False}, "CONTACT_NOT_VERIFIED"),
            ("masked", {"value_masked": True}, "MASKED_CONTACT"),
            ("guessed", {"value_guessed": True}, "GUESSED_CONTACT"),
            ("wrong-owner", {"subject_owner_id": "OTHER"}, "SUBJECT_OWNER_IS_NOT_THE_BUYER_ACCOUNT"),
            ("wrong-scope", {"route_scope": "THIRD_PARTY"}, "ROUTE_SCOPE_IS_NOT_BUYER_DIRECT"),
        ]
        for name, overrides, expected in cases:
            with self.subTest(name=name):
                warnings = self.runtime._information_route_warnings(
                    information_route(temporal_status="CURRENT_CONFIRMED", **overrides), ACCOUNT_ID
                )
                self.assertIn(expected, warnings)

    def test_stale_cached_false_current_confirmed_information_is_reprojected(self):
        record = information_route(temporal_status="CURRENT_CONFIRMED")
        record["outreach_eligible_effective"] = False
        record["usage_warnings"] = ["CONTACT_IS_NOT_CONFIRMED_CURRENT"]
        self.runtime.compat_state["information_records"] = {"INFO-1": record}

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertEqual(result["valid_information_route_ids"], ["INFO-1"])
        self.assertEqual(result["canonical_route_view"][0]["value"], "buyer@example.com")

    def test_official_email_does_not_require_channel_proof(self):
        record = information_route(temporal_status="CURRENT_CONFIRMED", channel="EMAIL")
        record["value"].pop("channel_proof", None)
        self.runtime.compat_state["information_records"] = {"INFO-1": record}

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")

    def test_current_confirmed_information_with_active_conflict_is_not_actionable(self):
        record = information_route(temporal_status="CURRENT_CONFIRMED")
        conflict = information_route(temporal_status="CURRENT_CONFIRMED")
        conflict["information_id"] = "INFO-CONFLICT"
        conflict["outreach_eligible_claimed"] = False
        record["conflicts_with_information_ids"] = ["INFO-CONFLICT"]
        self.runtime.compat_state["information_records"] = {
            "INFO-1": record,
            "INFO-CONFLICT": conflict,
        }

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_view"], [])

    def test_compiled_current_confirmed_account_route_derives_ownership_and_currentness(self):
        self.runtime.state["observations"] = {
            "OBS-C279-COMPANY": {
                "observation_id": "OBS-C279-COMPANY",
                "evidence_id": "EVD-C279-COMPANY",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": ACCOUNT_ID,
                "value": {
                    "channel": "PHONE",
                    "value": "+966535267771",
                    "verified": True,
                    "masked": False,
                    "guessed": False,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "COMPANY_ROUTE_READY")
        route = result["canonical_route_view"][0]
        self.assertTrue(route["current"])
        self.assertTrue(route["owned_by_account"])
        self.assertEqual(route["owner_entity_id"], ACCOUNT_ID)
        self.assertEqual(route["observation_id"], "OBS-C279-COMPANY")

    def test_compiled_current_confirmed_account_route_still_requires_verified_value(self):
        self.runtime.state["observations"] = {
            "OBS-C279-COMPANY": {
                "observation_id": "OBS-C279-COMPANY",
                "evidence_id": "EVD-C279-COMPANY",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": ACCOUNT_ID,
                "value": {
                    "channel": "PHONE",
                    "value": "+966535267771",
                    "masked": False,
                    "guessed": False,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_view"], [])

    def test_compiled_current_confirmed_route_requires_bound_evidence_id(self):
        self.runtime.state["observations"] = {
            "OBS-NO-EVIDENCE": {
                "observation_id": "OBS-NO-EVIDENCE",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": ACCOUNT_ID,
                "value": {
                    "channel": "PHONE",
                    "value": "+966535267771",
                    "verified": True,
                    "masked": False,
                    "guessed": False,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_view"], [])

    def test_supported_company_route_claim_without_canonical_route_exposes_projection_diagnostic(self):
        self.runtime.state["claims"] = {
            "contact.company_route": {
                "state": "SUPPORTED",
                "observation_ids": ["OBS-C279-COMPANY"],
                "evidence_ids": ["EVD-C279-COMPANY"],
            }
        }
        self.runtime.state["observations"] = {
            "OBS-C279-COMPANY": {
                "observation_id": "OBS-C279-COMPANY",
                "evidence_id": "EVD-C279-COMPANY",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": ACCOUNT_ID,
                "value": {
                    "channel": "PHONE",
                    "value": "+966535267771",
                    "masked": False,
                    "guessed": False,
                },
                "source": {"freshness": "CURRENT_CONFIRMED"},
            }
        }

        result = self.runtime.get_account_state(self.args)

        diagnostic = result["route_projection_diagnostics"]
        self.assertEqual(diagnostic["status"], "SUPPORTED_CLAIM_WITHOUT_CANONICAL_ROUTE")
        self.assertEqual(diagnostic["claim_state"], "SUPPORTED")
        self.assertEqual(diagnostic["claim_observation_ids"], ["OBS-C279-COMPANY"] )
        row = diagnostic["observations"][0]
        self.assertEqual(row["observation_id"], "OBS-C279-COMPANY")
        self.assertIn("ROUTE_NOT_VERIFIED", row["rejection_reasons"])

    def test_compiled_current_likely_route_is_not_actionable(self):
        self.runtime.state["observations"] = {
            "OBS-1": {
                "observation_id": "OBS-1",
                "evidence_id": "EVD-1",
                "claim_key": "contact.company_route",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": ACCOUNT_ID,
                "value": {
                    "channel": "PHONE",
                    "value": "+15550101002",
                    "verified": True,
                    "masked": False,
                    "guessed": False,
                    "channel_proof": True,
                },
                "source": {"freshness": "CURRENT_LIKELY"},
            }
        }

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_view"], [])

    def test_whatsapp_still_requires_channel_proof(self):
        record = information_route(
            temporal_status="CURRENT_CONFIRMED",
            channel="WHATSAPP",
            value="+15550101001",
        )
        record["value"].pop("channel_proof", None)
        self.runtime.compat_state["information_records"] = {"INFO-1": record}

        result = self.runtime.evaluate_outreach_readiness(self.args)

        self.assertEqual(result["outreach_readiness"], "IDENTITY_ONLY")
        self.assertEqual(result["canonical_route_view"], [])


class PromotionIdentityGateTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.runtime.state["peers"] = {
            "PEER-1": {
                "peer_id": "PEER-1",
                "stage": "ANCHOR_ELIGIBLE",
                "name": "Synthetic Peer",
                "country": "ZZ",
                "tax_id": "TAX-SYNTH-1",
                "canonical_resolution": {
                    "status": "NOT_FOUND",
                    "match": None,
                    "candidates": [],
                },
            }
        }
        self.args = {"investigation_id": INVESTIGATION_ID, "peer_id": "PEER-1"}

    def _set_root_identity(self, legal_state, ultimate_state):
        self.runtime.state["claims"] = {
            "identity.legal_entity": {"state": legal_state},
            "identity.ultimate_buyer": {"state": ultimate_state},
        }

    def test_root_identity_blocking_states_fail_closed_before_promotion(self):
        for blocked_state in ("CONFLICTED", "REFUTED", "BLOCKED", "SEARCHING"):
            with self.subTest(blocked_state=blocked_state):
                self.runtime.promotions = 0
                self.runtime.state["peers"]["PEER-1"]["stage"] = "ANCHOR_ELIGIBLE"
                self._set_root_identity(blocked_state, "SUPPORTED")

                with self.assertRaises(ValidationError) as caught:
                    self.runtime.promote_anchor(self.args)

                self.assertIn("ROOT_CRITICAL_IDENTITY_BLOCKED", str(caught.exception))
                self.assertEqual(self.runtime.promotions, 0)
                self.assertEqual(
                    self.runtime.state["peers"]["PEER-1"]["stage"],
                    "ANCHOR_ELIGIBLE",
                )

    def test_missing_root_identity_claim_fails_closed_before_promotion(self):
        self.runtime.state["claims"] = {
            "identity.legal_entity": {"state": "SUPPORTED"}
        }

        with self.assertRaises(ValidationError) as caught:
            self.runtime.promote_anchor(self.args)

        self.assertIn("identity.ultimate_buyer=UNSEEN", str(caught.exception))
        self.assertEqual(self.runtime.promotions, 0)

    def test_supported_root_identity_allows_promotion_to_delegate(self):
        self._set_root_identity("SUPPORTED", "STRONGLY_SUPPORTED")

        result = self.runtime.promote_anchor(self.args)

        self.assertTrue(result["accepted"])
        self.assertEqual(self.runtime.promotions, 1)
        self.assertEqual(self.runtime.state["peers"]["PEER-1"]["stage"], "PROMOTED_ANCHOR")

    def test_identity_gate_does_not_block_discovery_or_evaluation(self):
        self._set_root_identity("CONFLICTED", "SEARCHING")

        discovered = self.runtime.append_peer_discovery(self.args)
        evaluated = self.runtime.evaluate_peer(self.args)

        self.assertTrue(discovered["accepted"])
        self.assertTrue(evaluated["accepted"])
        self.assertEqual(self.runtime.discoveries, 1)
        self.assertEqual(self.runtime.evaluations, 1)


class PromotionCanonicalReresolutionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.runtime.state["claims"] = {
            "identity.legal_entity": {"state": "SUPPORTED"},
            "identity.ultimate_buyer": {"state": "SUPPORTED"},
        }
        self.runtime.state["peers"] = {
            "PEER-1": {
                "peer_id": "PEER-1",
                "stage": "ANCHOR_ELIGIBLE",
                "name": "Synthetic Peer",
                "country": "ZZ",
                "tax_id": "TAX-SYNTH-1",
                "canonical_resolution": {
                    "status": "NOT_FOUND",
                    "match": None,
                    "candidates": [],
                },
            }
        }
        self.args = {"investigation_id": INVESTIGATION_ID, "peer_id": "PEER-1"}

    def test_peer_that_now_resolves_to_canonical_account_is_blocked_before_promotion(self):
        historical = dict(self.runtime.state["peers"]["PEER-1"]["canonical_resolution"])
        self.runtime.canonical_registry.result = {
            "status": "MATCH",
            "match": {"account_id": "C999"},
            "candidates": [],
        }

        with self.assertRaises(ValidationError) as caught:
            self.runtime.promote_anchor(self.args)

        self.assertIn("PEER_NOW_RESOLVES_TO_CANONICAL_ACCOUNT:C999", str(caught.exception))
        self.assertEqual(self.runtime.promotions, 0)
        self.assertEqual(self.runtime.state["peers"]["PEER-1"]["stage"], "ANCHOR_ELIGIBLE")
        self.assertEqual(
            self.runtime.state["peers"]["PEER-1"]["canonical_resolution"],
            historical,
        )
        self.assertEqual(
            self.runtime.canonical_registry.last_identity,
            {"name": "Synthetic Peer", "country": "ZZ", "tax_id": "TAX-SYNTH-1"},
        )

    def test_peer_still_not_found_delegates_to_existing_promotion_path(self):
        result = self.runtime.promote_anchor(self.args)

        self.assertTrue(result["accepted"])
        self.assertEqual(self.runtime.promotions, 1)
        self.assertEqual(self.runtime.state["peers"]["PEER-1"]["stage"], "PROMOTED_ANCHOR")

    def test_account_state_exposes_non_mutating_peer_reconciliation_view(self):
        historical = dict(self.runtime.state["peers"]["PEER-1"]["canonical_resolution"])
        self.runtime.canonical_registry.result = {
            "status": "MATCH",
            "match": {"account_id": "C999"},
            "candidates": [],
        }

        result = self.runtime.get_account_state({"investigation_id": INVESTIGATION_ID})

        row = result["peer_reconciliation"][0]
        self.assertEqual(row["peer_id"], "PEER-1")
        self.assertEqual(row["historical_canonical_resolution"], historical)
        self.assertEqual(row["current_canonical_resolution"]["status"], "MATCH")
        self.assertEqual(row["matched_account_id"], "C999")
        self.assertEqual(row["reconciliation_state"], "NOW_CANONICAL_ACCOUNT_EXISTS")
        self.assertFalse(row["promotion_eligible_under_current_identity"])
        self.assertEqual(
            self.runtime.state["peers"]["PEER-1"]["canonical_resolution"],
            historical,
        )

    def test_reconciliation_view_reports_still_canonical_new_when_not_found(self):
        result = self.runtime.get_account_state({"investigation_id": INVESTIGATION_ID})

        row = result["peer_reconciliation"][0]
        self.assertEqual(row["reconciliation_state"], "STILL_CANONICAL_NEW")
        self.assertTrue(row["promotion_eligible_under_current_identity"])

    def test_reconciliation_view_reports_ambiguous_without_claiming_account_exists(self):
        self.runtime.canonical_registry.result = {
            "status": "AMBIGUOUS",
            "match": None,
            "candidates": [{"account_id": "C998"}, {"account_id": "C999"}],
        }

        result = self.runtime.get_account_state({"investigation_id": INVESTIGATION_ID})

        row = result["peer_reconciliation"][0]
        self.assertEqual(row["reconciliation_state"], "CANONICAL_RESOLUTION_AMBIGUOUS")
        self.assertIsNone(row["matched_account_id"])
        self.assertFalse(row["promotion_eligible_under_current_identity"])

    def test_promoted_peer_is_not_reclassified_by_reconciliation_view(self):
        self.runtime.state["peers"]["PEER-1"]["stage"] = "PROMOTED_ANCHOR"
        historical = dict(self.runtime.state["peers"]["PEER-1"]["canonical_resolution"])
        self.runtime.canonical_registry.result = {
            "status": "MATCH",
            "match": {"account_id": "C999"},
            "candidates": [],
        }

        result = self.runtime.get_account_state({"investigation_id": INVESTIGATION_ID})

        self.assertEqual(result["peer_reconciliation"], [])
        self.assertEqual(self.runtime.state["peers"]["PEER-1"]["stage"], "PROMOTED_ANCHOR")
        self.assertEqual(
            self.runtime.state["peers"]["PEER-1"]["canonical_resolution"],
            historical,
        )


if __name__ == "__main__":
    unittest.main()
