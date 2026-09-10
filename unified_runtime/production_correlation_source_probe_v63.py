from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .production_source_snapshot_v63 import build_v63_production_source_snapshot

_CORRELATED_REL = 'mcp/server_v61_correlated.py'


def _attr_path(node: ast.AST) -> str | None:
    parts=[]; cur=node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr); cur=cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id); return '.'.join(reversed(parts))
    return None


def _fn(tree: ast.Module, name: str):
    rows=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    return rows[0] if len(rows)==1 else None


def _module_assign(tree: ast.Module, target_path: str, value_name: str, *, staticmethod: bool=False) -> bool:
    for node in tree.body:
        if not isinstance(node,(ast.Assign,ast.AnnAssign)): continue
        targets=node.targets if isinstance(node,ast.Assign) else [node.target]
        if not any(_attr_path(t)==target_path for t in targets): continue
        value=node.value
        if staticmethod:
            if isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and value.func.id=='staticmethod' and len(value.args)==1 and isinstance(value.args[0],ast.Name) and value.args[0].id==value_name:
                return True
        elif isinstance(value,ast.Name) and value.id==value_name:
            return True
    return False


def _contextvar(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node,(ast.Assign,ast.AnnAssign)): continue
        targets=node.targets if isinstance(node,ast.Assign) else [node.target]
        if not any(isinstance(t,ast.Name) and t.id=='_ACTIVE_MUTATION_CORRELATION' for t in targets): continue
        v=node.value
        if isinstance(v,ast.Call):
            name=v.func.id if isinstance(v.func,ast.Name) else getattr(v.func,'attr',None)
            if name=='ContextVar': return True
    return False


def _return_keys(fn: ast.AST|None) -> set[str]:
    keys=set()
    if fn is None: return keys
    for n in ast.walk(fn):
        if isinstance(n,ast.Return) and isinstance(n.value,ast.Dict):
            for k in n.value.keys:
                if isinstance(k,ast.Constant) and isinstance(k.value,str): keys.add(k.value)
    return keys


def inspect_v63_production_correlation_bridge(repo_root: str|Path) -> dict[str,Any]:
    root=Path(repo_root).resolve(); snap=build_v63_production_source_snapshot(root); blockers=[]
    path=root/_CORRELATED_REL
    if snap.get('status')!='READY': blockers.append('PRODUCTION_SOURCE_SNAPSHOT_NOT_READY')
    if _CORRELATED_REL not in dict(snap.get('files') or {}): blockers.append('CORRELATED_OVERLAY_NOT_PINNED')
    if not path.is_file():
        blockers.append('CORRELATED_OVERLAY_MISSING')
        return {'schema':'cbi.v63-production-correlation-source-probe.v1','status':'BLOCKED','static_correlation_bridge_proven':False,'live_backend_correlation_acceptance_verified':False,'production_ready':False,'blockers':list(dict.fromkeys(blockers))}
    try:
        source=path.read_text(encoding='utf-8',errors='strict'); tree=ast.parse(source)
    except Exception:
        blockers.append('CORRELATED_OVERLAY_AST_INVALID')
        return {'schema':'cbi.v63-production-correlation-source-probe.v1','status':'BLOCKED','static_correlation_bridge_proven':False,'live_backend_correlation_acceptance_verified':False,'production_ready':False,'blockers':list(dict.fromkeys(blockers))}
    corr=_fn(tree,'_correlation'); sess=_fn(tree,'_session_event'); hchain=_fn(tree,'_hashchain_append'); inv=_fn(tree,'_invoke_mutation')
    corr_src=ast.get_source_segment(source,corr) if corr else ''
    compact=re.sub(r'\s+','',corr_src or '')
    formula=bool('hashlib.sha256(' in compact and '.hexdigest()[:24]' in compact and ('f"{tool_name}:{key}"' in compact or "f'{tool_name}:{key}'" in compact) and 'MUTCORR-' in compact)
    raw='idempotency_key' in _return_keys(corr)
    sess_src=ast.get_source_segment(source,sess) if sess else ''
    sess_ok=bool(sess and 'mutation_correlation' in (sess_src or '') and 'event_hash' in (sess_src or '') and '_ACTIVE_MUTATION_CORRELATION.get()' in (sess_src or '') and _module_assign(tree,'_core.SessionStore._event','_session_event',staticmethod=True))
    h_src=ast.get_source_segment(source,hchain) if hchain else ''
    hash_ok=bool(hchain and 'mutation_correlation' in (h_src or '') and _module_assign(tree,'_resilience.HashChainLog.append','_hashchain_append'))
    inv_src=ast.get_source_segment(source,inv) if inv else ''
    invoke_ok=bool(inv and '_ACTIVE_MUTATION_CORRELATION.set(' in (inv_src or '') and '_ACTIVE_MUTATION_CORRELATION.reset(' in (inv_src or '') and '_BASE_INVOKE_MUTATION(' in (inv_src or '') and _module_assign(tree,'_v61._invoke_mutation','_invoke_mutation'))
    if not _contextvar(tree): blockers.append('MUTATION_CORRELATION_CONTEXT_NOT_PROVEN')
    if not formula: blockers.append('MUTCORR_FORMULA_NOT_PROVEN')
    if raw: blockers.append('RAW_IDEMPOTENCY_KEY_PERSISTENCE_DETECTED')
    if not sess_ok: blockers.append('SESSION_STORE_CORRELATION_PATCH_NOT_PROVEN')
    if not hash_ok: blockers.append('HASHCHAIN_CORRELATION_PATCH_NOT_PROVEN')
    if not invoke_ok: blockers.append('INVOKE_MUTATION_CORRELATION_SCOPE_NOT_PROVEN')
    blockers=list(dict.fromkeys(blockers)); proven=not blockers
    return {
        'schema':'cbi.v63-production-correlation-source-probe.v1','status':'STATIC_CORRELATION_BRIDGE_PROVEN' if proven else 'BLOCKED',
        'static_correlation_bridge_proven':proven,'live_backend_correlation_acceptance_verified':False,'production_ready':False,
        'production_source_snapshot_sha256':snap.get('snapshot_sha256'),'correlated_overlay_path':_CORRELATED_REL,
        'context_var_proven':_contextvar(tree),'mutcorr_formula_proven':formula,'session_store_envelope_injection_proven':sess_ok,
        'hashchain_envelope_injection_proven':hash_ok,'invoke_mutation_context_scope_proven':invoke_ok,'raw_idempotency_key_persisted':raw,
        'blockers':blockers,'next_gate':'RUN_LIVE_BACKEND_CORRELATION_ACCEPTANCE',
    }
