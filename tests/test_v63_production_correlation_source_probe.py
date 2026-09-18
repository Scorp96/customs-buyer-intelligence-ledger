import json,tempfile,unittest
from pathlib import Path
from unified_runtime.production_correlation_source_probe_v63 import inspect_v63_production_correlation_bridge

CORRELATED='''\
import copy,hashlib
from contextvars import ContextVar
from mcp import server_v61_recovery as _recovery
from unified_runtime import core as _core
from unified_runtime import resilience as _resilience
_v61=_recovery._v61
_BASE_INVOKE_MUTATION=_v61._invoke_mutation
_BASE_SESSION_EVENT=_core.SessionStore._event
_BASE_HASHCHAIN_APPEND=_resilience.HashChainLog.append
_ACTIVE_MUTATION_CORRELATION=ContextVar("cbi",default=None)
def _correlation(tool_name,arguments):
    key=str(arguments.get("idempotency_key") or "").strip()
    correlation_id="MUTCORR-"+hashlib.sha256(f"{tool_name}:{key}".encode("utf-8")).hexdigest()[:24]
    return {"schema":"cbi.mutation-correlation.v6.1","correlation_id":correlation_id,"tool":tool_name}
def _session_event(seq,previous,event_type,payload):
    event=_BASE_SESSION_EVENT(seq,previous,event_type,payload)
    correlation=_ACTIVE_MUTATION_CORRELATION.get()
    if correlation:
        event["mutation_correlation"]=copy.deepcopy(correlation)
        event["event_hash"]=_core.digest({k:v for k,v in event.items() if k!="event_hash"})
    return event
def _hashchain_append(self,event_type,payload):
    correlation=_ACTIVE_MUTATION_CORRELATION.get()
    if correlation is None: return _BASE_HASHCHAIN_APPEND(self,event_type,payload)
    return {"mutation_correlation":copy.deepcopy(correlation)}
def _invoke_mutation(tool_name,handler,arguments):
    correlation=_correlation(tool_name,arguments)
    token=_ACTIVE_MUTATION_CORRELATION.set(correlation)
    try: return _BASE_INVOKE_MUTATION(tool_name,handler,arguments)
    finally: _ACTIVE_MUTATION_CORRELATION.reset(token)
_core.SessionStore._event=staticmethod(_session_event)
_resilience.HashChainLog.append=_hashchain_append
_v61._invoke_mutation=_invoke_mutation
'''
class V63ProductionCorrelationSourceProbeTests(unittest.TestCase):
    def _repo(self,root,source=CORRELATED):
        (root/'mcp').mkdir(); (root/'unified_runtime').mkdir()
        (root/'.mcp.json').write_text(json.dumps({'mcpServers':{'cbi':{'args':['mcp/server_v61_backup_recovery.py','--stdio']}}}))
        files={'server_v61_backup_recovery.py':'from mcp import server_v61_correlated as _base\n','server_v61_correlated.py':source,'server_v61_recovery.py':'from mcp import server_v61 as _v61\n','server_v61.py':'def main(): return 0\n'}
        for n,v in files.items():(root/'mcp'/n).write_text(v)
        for n in ('__init__.py','research_orchestration_hardening.py','v6.py','core.py','resilience.py'):(root/'unified_runtime'/n).write_text('# authority\n')
        return root
    def test_static_bridge_proven_but_live_false(self):
        with tempfile.TemporaryDirectory() as td:
            r=inspect_v63_production_correlation_bridge(self._repo(Path(td)))
            self.assertEqual(r['status'],'STATIC_CORRELATION_BRIDGE_PROVEN'); self.assertTrue(r['static_correlation_bridge_proven']); self.assertFalse(r['live_backend_correlation_acceptance_verified']); self.assertEqual(r['blockers'],[])
    def test_wrong_formula_fails(self):
        with tempfile.TemporaryDirectory() as td:
            r=inspect_v63_production_correlation_bridge(self._repo(Path(td),CORRELATED.replace('f"{tool_name}:{key}"','f"{key}:{tool_name}"')))
            self.assertIn('MUTCORR_FORMULA_NOT_PROVEN',r['blockers'])
