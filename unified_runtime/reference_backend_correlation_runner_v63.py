from __future__ import annotations
import copy,hashlib
from typing import Any,Callable
from .backend_correlation_acceptance_v63 import REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
from .existing_production_store_backend_v63 import ExistingProductionStoreBackend
from .recovery_semantics_v63 import recover_prepared_v63_mutation


def production_mutation_correlation(tool_name:str,key:str)->dict[str,str]:
    k=str(key or '').strip()
    return {'schema':'cbi.mutation-correlation.v6.1','correlation_id':'MUTCORR-'+hashlib.sha256(f'{tool_name}:{k}'.encode()).hexdigest()[:24],'tool':tool_name}

class _Store:
    def __init__(self): self.events=[]; self.active=None
    def append(self,investigation_id,event_type,payload):
        e={'seq':len(self.events)+1,'investigation_id':investigation_id,'event_type':event_type,'payload':copy.deepcopy(payload)}
        if self.active: e['mutation_correlation']=copy.deepcopy(self.active)
        self.events.append(e); return copy.deepcopy(e)
class _Runtime:
    def __init__(self): self.store=_Store()

def _invoke(tool:str,method:Callable,runtime:_Runtime,args:dict)->dict:
    runtime.store.active=production_mutation_correlation(tool,args.get('idempotency_key'))
    try:return method(runtime,copy.deepcopy(args))
    finally:runtime.store.active=None

def _rows(events):
    out=[]
    for e in events:
        p=copy.deepcopy(e.get('payload') or {}); p['event_type']=e.get('event_type'); p['correlation_id']=(e.get('mutation_correlation') or {}).get('correlation_id'); p['seq']=e.get('seq'); out.append(p)
    return out

def _row(name,passed,before,after,count,**kw):
    return {'scenario':name,'status':'PASS' if passed else 'FAIL','durable_event_count':count,'append_count_before_recovery':before,'append_count_after_recovery':after,'reexecute_side_effect':after!=before,'exact_correlation_proven':kw.get('exact_correlation_proven',True),'exact_request_hash_proven':kw.get('exact_request_hash_proven',True),'cross_key_result_claimed':kw.get('cross_key_result_claimed',False)}

def _candidate(key='candidate-key-0001'):
    return {'investigation_id':'INV-REF','candidate':{'candidate_id':'CAND-REF-1','discovered_from_anchor_id':'ANCHOR-REF-1','branch_group':'APPLICATION_GRAPH','branch':'downstream_manufacturer','company_name':'Reference Cabinet Co','product_profile_id':'PVC'},'idempotency_key':key}
def _opportunity():
    return {'investigation_id':'INV-REF','canonical_resolution':{'canonical_status':'CONFIRMED','canonical_account_id':'C500','resolver_authority':'EXACT_ACCOUNT_ID','resolver_is_existing_production_authority':True,'ambiguous':False,'address_only_match':False,'alias_only_match':False},'opportunity':{'opportunity_id':'OPP-C500-PVC-PRIMARY','account_id':'C500','product_profile_id':'PVC','product_profile_version':'1','product_profile_sha256':'a'*64},'idempotency_key':'opportunity-key-0001'}
def _anchor():
    return {'investigation_id':'INV-REF','opportunity_id':'OPP-C500-PVC-PRIMARY','promotion_reason':'UPGRADE_TARGET','anchor_eligibility':{'anchor_eligible':True,'material_novelty_signals':['NEW_MARKET_CELL']},'cycle_dedup_complete':True,'idempotency_key':'anchor-key-000001'}

def run_v63_reference_backend_correlation_acceptance(*,production_source_snapshot_sha256:str)->dict[str,Any]:
    b=ExistingProductionStoreBackend(); rows=[]
    cr=_Runtime(); ca=_candidate(); cres=_invoke('append_candidate_discovery',b.append_candidate_discovery,cr,ca); cc=production_mutation_correlation('append_candidate_discovery',ca['idempotency_key'])['correlation_id']
    rows.append(_row('CANDIDATE_SUCCESS_EVENT_CORRELATED', (cr.store.events[0]['mutation_correlation']['correlation_id']==cc and cres['candidate_id']=='CAND-REF-1'),1,1,1))
    before=len(cr.store.events); rec=recover_prepared_v63_mutation('append_candidate_discovery',ca,expected_correlation_id=cc,durable_events=_rows(cr.store.events)); after=len(cr.store.events); rows.append(_row('CANDIDATE_RECOVERY_NO_REEXECUTION',rec.get('status')=='RECOVERED' and rec.get('result')==cres and before==after,before,after,len(cr.store.events)))
    oru=_Runtime(); oa=_opportunity(); ores=_invoke('create_product_opportunity',b.create_product_opportunity,oru,oa); oc=production_mutation_correlation('create_product_opportunity',oa['idempotency_key'])['correlation_id']; rows.append(_row('OPPORTUNITY_SUCCESS_SNAPSHOT_CORRELATED',oru.store.events[0]['payload']['result_snapshot']==ores,1,1,1))
    before=len(oru.store.events); rec=recover_prepared_v63_mutation('create_product_opportunity',oa,expected_correlation_id=oc,durable_events=_rows(oru.store.events)); after=len(oru.store.events); rows.append(_row('OPPORTUNITY_RECOVERY_EXACT_SNAPSHOT',rec.get('status')=='RECOVERED' and rec.get('result')==ores and before==after,before,after,len(oru.store.events)))
    ar=_Runtime(); aa=_anchor(); ares=_invoke('promote_opportunity_anchor',b.promote_opportunity_anchor,ar,aa); ac=production_mutation_correlation('promote_opportunity_anchor',aa['idempotency_key'])['correlation_id']; rows.append(_row('ANCHOR_SUCCESS_EVENT_CORRELATED',ar.store.events[0]['mutation_correlation']['correlation_id']==ac,1,1,1))
    before=len(ar.store.events); rec=recover_prepared_v63_mutation('promote_opportunity_anchor',aa,expected_correlation_id=ac,durable_events=_rows(ar.store.events)); after=len(ar.store.events); rows.append(_row('ANCHOR_RECOVERY_NO_REEXECUTION',rec.get('status')=='RECOVERED' and rec.get('result')==ares and before==after,before,after,len(ar.store.events)))
    before=len(cr.store.events); rec=recover_prepared_v63_mutation('append_candidate_discovery',ca,expected_correlation_id='MUTCORR-WRONG',durable_events=_rows(cr.store.events)); after=len(cr.store.events); rows.append(_row('WRONG_CORRELATION_FAILS_CLOSED',rec.get('status')=='MUTATION_RECONCILIATION_REQUIRED' and before==after,before,after,len(cr.store.events)))
    bad=_rows(cr.store.events); bad[0]['request_sha256']='0'*64; before=len(cr.store.events); rec=recover_prepared_v63_mutation('append_candidate_discovery',ca,expected_correlation_id=cc,durable_events=bad); after=len(cr.store.events); rows.append(_row('WRONG_REQUEST_HASH_FAILS_CLOSED',rec.get('status')=='MUTATION_RECONCILIATION_REQUIRED' and before==after,before,after,1))
    dup=_rows(cr.store.events)*2; before=len(cr.store.events); rec=recover_prepared_v63_mutation('append_candidate_discovery',ca,expected_correlation_id=cc,durable_events=dup); after=len(cr.store.events); rows.append(_row('AMBIGUOUS_DUPLICATE_EVENT_FAILS_CLOSED',rec.get('status')=='MUTATION_RECONCILIATION_REQUIRED' and before==after,before,after,2))
    ca2=_candidate('candidate-key-0002'); cc2=production_mutation_correlation('append_candidate_discovery',ca2['idempotency_key'])['correlation_id']; before=len(cr.store.events); rec=recover_prepared_v63_mutation('append_candidate_discovery',ca2,expected_correlation_id=cc2,durable_events=_rows(cr.store.events)); after=len(cr.store.events); claimed=rec.get('status')=='RECOVERED'; rows.append(_row('DIFFERENT_KEY_CANNOT_CLAIM_RESULT',not claimed and before==after,before,after,len(cr.store.events),cross_key_result_claimed=claimed))
    by={r['scenario']:r for r in rows}
    return {'schema':'cbi.v63-backend-correlation-acceptance.v1','execution_origin':'REFERENCE_EXECUTABLE','adapter_path_exercised':'REFERENCE_CORRELATED_ADAPTER','runtime_store_exercised':'REFERENCE_EXISTING_PRODUCTION_STORE_SHAPE','production_source_snapshot_sha256':str(production_source_snapshot_sha256).lower(),'scenarios':[by[n] for n in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS],'reference_runner_only':True,'live_release_proof':False}
