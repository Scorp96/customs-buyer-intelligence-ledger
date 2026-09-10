import unittest


class V63CanonicalResolutionGateTests(unittest.TestCase):
    def _proof(self, **overrides):
        row = {
            "canonical_status": "CONFIRMED",
            "canonical_account_id": "C501",
            "resolver_authority": "PRIMARY_LEGAL_NAME_COUNTRY",
            "resolver_is_existing_production_authority": True,
            "ambiguous": False,
            "address_only_match": False,
            "alias_only_match": False,
            "tax_conflict": False,
            "country_conflict": False,
        }
        row.update(overrides)
        return row

    def test_existing_production_canonical_resolution_can_authorize_opportunity_creation(self):
        from unified_runtime.canonical_resolution_gate import validate_canonical_resolution_proof
        result = validate_canonical_resolution_proof(self._proof())
        self.assertTrue(result["opportunity_creation_allowed"])
        self.assertEqual(result["canonical_account_id"], "C501")

    def test_address_only_match_never_authorizes_resolution(self):
        from unified_runtime.canonical_resolution_gate import validate_canonical_resolution_proof
        result = validate_canonical_resolution_proof(self._proof(address_only_match=True))
        self.assertFalse(result["opportunity_creation_allowed"])
        self.assertIn("ADDRESS_ONLY_MATCH_FORBIDDEN", result["blockers"])

    def test_ambiguous_resolution_fails_closed(self):
        from unified_runtime.canonical_resolution_gate import validate_canonical_resolution_proof
        result = validate_canonical_resolution_proof(self._proof(canonical_status="AMBIGUOUS", ambiguous=True))
        self.assertFalse(result["opportunity_creation_allowed"])
        self.assertIn("CANONICAL_RESOLUTION_AMBIGUOUS", result["blockers"])

    def test_untrusted_resolver_marker_fails_closed(self):
        from unified_runtime.canonical_resolution_gate import validate_canonical_resolution_proof
        result = validate_canonical_resolution_proof(self._proof(resolver_is_existing_production_authority=False))
        self.assertFalse(result["opportunity_creation_allowed"])
        self.assertIn("PRODUCTION_CANONICAL_AUTHORITY_NOT_PROVEN", result["blockers"])

    def test_alias_only_match_never_authorizes_resolution(self):
        from unified_runtime.canonical_resolution_gate import validate_canonical_resolution_proof
        result = validate_canonical_resolution_proof(self._proof(alias_only_match=True))
        self.assertFalse(result["opportunity_creation_allowed"])
        self.assertIn("ALIAS_ONLY_MATCH_FORBIDDEN", result["blockers"])
