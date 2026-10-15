"""Offline fixture-contract preflight; does not replace sales_readiness integration tests."""
from pathlib import Path
import ast
import unittest

from unified_runtime.route_reuse import reuse_route_for_opportunity


def fixture_payload():
    path = Path(__file__).with_name('test_v63_sales_readiness.py')
    module = ast.parse(path.read_text(encoding='utf-8'))
    candidate = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'base_payload')
    code = compile(ast.Module(body=[candidate], type_ignores=[]), str(path), 'exec')
    ns = {}
    exec(code, ns)
    return ns['base_payload']()


class V64SalesRouteContractPreflight(unittest.TestCase):
    def test_positive_fixture_is_explicitly_owner_bound(self):
        p = fixture_payload()
        self.assertEqual(p['selected_route'].get('account_id'), p['opportunity']['account_id'])
        result = reuse_route_for_opportunity(p['selected_route'], p['opportunity'])
        self.assertTrue(result['route_reusable'])
        self.assertFalse(result['route_proves_procurement'])

    def test_cross_owner_sales_fixture_is_blocked(self):
        p = fixture_payload()
        p['selected_route']['account_id'] = 'C600'
        result = reuse_route_for_opportunity(p['selected_route'], p['opportunity'])
        self.assertFalse(result['route_reusable'])
        self.assertIn('ROUTE_ACCOUNT_OWNER_MISMATCH', result['blockers'])

    def test_missing_account_binding_is_not_inferred_from_route_id(self):
        p = fixture_payload()
        p['selected_route'].pop('account_id')
        result = reuse_route_for_opportunity(p['selected_route'], p['opportunity'])
        self.assertFalse(result['route_reusable'])
        self.assertIn('ROUTE_ACCOUNT_BINDING_MISSING', result['blockers'])


if __name__ == '__main__':
    unittest.main()
