from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_event_primitive_probe_v63 import probe_v63_runtime_event_primitives
from .backend_correlation_acceptance_v63 import validate_v63_backend_correlation_acceptance
from .production_correlation_source_probe_v63 import inspect_v63_production_correlation_bridge


def build_v63_runtime_backend_binding_plan(repo_root: str|Path, *, backend_correlation_acceptance_report: dict[str,Any]|None=None, expected_production_source_snapshot_sha256: str|None=None) -> dict[str,Any]:
    root=Path(repo_root).resolve(); primitive=probe_v63_runtime_event_primitives(root); source_probe=inspect_v63_production_correlation_bridge(root)
    codegen_blockers=[]; release_blockers=[]
    primitive_ok=primitive.get('status')=='SHARED_DURABLE_PRIMITIVE_PROVEN'
    if not primitive_ok: codegen_blockers.extend(str(v) for v in primitive.get('blockers') or [])
    static=bool(source_probe.get('static_correlation_bridge_proven'))
    validation=None; live=False
    if backend_correlation_acceptance_report is not None:
        validation=validate_v63_backend_correlation_acceptance(backend_correlation_acceptance_report, expected_production_source_snapshot_sha256=expected_production_source_snapshot_sha256)
        live=bool(validation.get('verified'))
        if not live: release_blockers.extend(str(v) for v in validation.get('blockers') or [])
    propagation=static or live
    candidate=primitive_ok and propagation
    proven=primitive_ok and live
    if not candidate:
        codegen_blockers.extend(str(v) for v in primitive.get('remaining_blockers') or [])
        codegen_blockers.extend(str(v) for v in source_probe.get('blockers') or [])
        codegen_blockers.append('V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND')
    if not proven: release_blockers.append('V63_RUNTIME_DURABLE_BACKEND_LIVE_ACCEPTANCE_REQUIRED')
    codegen_blockers=list(dict.fromkeys(codegen_blockers)); release_blockers=list(dict.fromkeys(release_blockers)); blockers=list(dict.fromkeys(codegen_blockers+release_blockers))
    status='BACKEND_BINDING_PROVEN' if proven else ('BACKEND_BINDING_CANDIDATE_PROVEN_LIVE_ACCEPTANCE_PENDING' if candidate else 'BACKEND_BINDING_BLOCKED')
    return {
        'schema':'cbi.v63-runtime-backend-binding-plan.v2','status':status,'repo_root':str(root),'event_primitive_probe':primitive,'shared_primitive':primitive.get('shared_primitive'),
        'correlation_source_probe':source_probe,'static_correlation_bridge_proven':static,'correlation_propagation_proven':propagation,
        'live_backend_correlation_acceptance_verified':live,'backend_correlation_acceptance_validation':validation,
        'runtime_durable_backend_binding_candidate_proven':candidate,'runtime_durable_backend_binding_proven':proven,'backend_codegen_allowed':candidate,
        'codegen_blockers':codegen_blockers,'release_blockers':release_blockers,'blockers':blockers,'modifies_checkout':False,'parallel_state_store_allowed':False,'request_arguments_can_authorize_binding':False,'production_ready':proven,
    }
