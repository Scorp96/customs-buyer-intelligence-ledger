import unittest
from unified_runtime.reference_backend_correlation_runner_v63 import run_v63_reference_backend_correlation_acceptance
from unified_runtime.backend_correlation_acceptance_v63 import validate_v63_backend_correlation_acceptance,REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
class V63ReferenceBackendCorrelationRunnerTests(unittest.TestCase):
    def test_all_scenarios_pass_without_reappend(self):
        r=run_v63_reference_backend_correlation_acceptance(production_source_snapshot_sha256='a'*64); self.assertEqual({x['scenario'] for x in r['scenarios']},set(REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS)); self.assertTrue(all(x['status']=='PASS' and x['reexecute_side_effect'] is False for x in r['scenarios']))
    def test_reference_is_not_live_proof(self):
        r=run_v63_reference_backend_correlation_acceptance(production_source_snapshot_sha256='a'*64); v=validate_v63_backend_correlation_acceptance(r,expected_production_source_snapshot_sha256='a'*64); self.assertFalse(v['verified']); self.assertIn('PRODUCTION_ADAPTER_NOT_EXERCISED',v['blockers']); self.assertIn('PRODUCTION_DURABLE_STORE_NOT_EXERCISED',v['blockers'])
