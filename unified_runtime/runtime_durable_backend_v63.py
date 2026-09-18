from __future__ import annotations

from typing import Any


V63_DURABLE_BACKEND_SCHEMA = "cbi.v63-production-durable-backend.v1"
V63_DURABLE_BACKEND_BINDING_STRATEGY = "EXISTING_PRODUCTION_APPEND_ONLY_STORE"
V63_DURABLE_MUTATION_METHODS = (
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
)

_BACKEND_ATTR = "_v63_runtime_durable_backend"


def _backend_contract_errors(backend: Any) -> list[str]:
    errors: list[str] = []
    if str(getattr(backend, "backend_schema", "")) != V63_DURABLE_BACKEND_SCHEMA:
        errors.append("BACKEND_SCHEMA_MISMATCH")
    if str(getattr(backend, "binding_strategy", "")) != V63_DURABLE_BACKEND_BINDING_STRATEGY:
        errors.append("BINDING_STRATEGY_MISMATCH")
    if getattr(backend, "parallel_state_store_allowed", None) is not False:
        errors.append("PARALLEL_STATE_STORE_NOT_FORBIDDEN")
    if getattr(backend, "requires_existing_mutation_correlation", None) is not True:
        errors.append("EXISTING_MUTATION_CORRELATION_NOT_REQUIRED")
    if getattr(backend, "raw_idempotency_key_persisted", None) is not False:
        errors.append("RAW_IDEMPOTENCY_KEY_PERSISTENCE_NOT_FORBIDDEN")
    if getattr(backend, "side_effect_reexecution_allowed", None) is not False:
        errors.append("SIDE_EFFECT_REEXECUTION_NOT_FORBIDDEN")
    for name in V63_DURABLE_MUTATION_METHODS:
        if not callable(getattr(backend, name, None)):
            errors.append(f"MISSING_BACKEND_METHOD:{name}")
    return errors


def get_v63_runtime_durable_backend_state(runtime: Any) -> dict[str, Any]:
    backend = getattr(runtime, _BACKEND_ATTR, None)
    if backend is None:
        return {
            "status": "UNBOUND_FAIL_CLOSED",
            "backend": None,
            "backend_schema": V63_DURABLE_BACKEND_SCHEMA,
            "binding_strategy": V63_DURABLE_BACKEND_BINDING_STRATEGY,
            "parallel_state_store_allowed": False,
            "requires_existing_mutation_correlation": True,
            "raw_idempotency_key_persisted": False,
            "side_effect_reexecution_allowed": False,
            "contract_errors": [],
        }
    errors = _backend_contract_errors(backend)
    return {
        "status": "BOUND_EXISTING_DURABLE_STORE" if not errors else "INVALID_BINDING_FAIL_CLOSED",
        "backend": backend,
        "backend_schema": str(getattr(backend, "backend_schema", "")),
        "binding_strategy": str(getattr(backend, "binding_strategy", "")),
        "parallel_state_store_allowed": getattr(backend, "parallel_state_store_allowed", None),
        "requires_existing_mutation_correlation": getattr(backend, "requires_existing_mutation_correlation", None),
        "raw_idempotency_key_persisted": getattr(backend, "raw_idempotency_key_persisted", None),
        "side_effect_reexecution_allowed": getattr(backend, "side_effect_reexecution_allowed", None),
        "contract_errors": errors,
    }


def bind_v63_runtime_durable_backend(runtime: Any, backend: Any) -> dict[str, Any]:
    errors = _backend_contract_errors(backend)
    if errors:
        raise RuntimeError("V63_DURABLE_BACKEND_CONTRACT_REJECTED:" + ",".join(errors))

    existing = getattr(runtime, _BACKEND_ATTR, None)
    if existing is not None and existing is not backend:
        raise RuntimeError("V63_DURABLE_BACKEND_ALREADY_BOUND")
    if existing is None:
        setattr(runtime, _BACKEND_ATTR, backend)
    return get_v63_runtime_durable_backend_state(runtime)


def invoke_v63_runtime_durable_backend(
    runtime: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    state = get_v63_runtime_durable_backend_state(runtime)
    if state["status"] != "BOUND_EXISTING_DURABLE_STORE":
        raise RuntimeError("V63_MUTATION_REQUIRES_PRODUCTION_WAL_BINDING")
    backend = state["backend"]
    handler = getattr(backend, tool_name, None)
    if not callable(handler):
        raise RuntimeError("V63_DURABLE_BACKEND_CONTRACT_REJECTED:MISSING_BACKEND_METHOD")
    result = handler(runtime, dict(arguments))
    if not isinstance(result, dict):
        raise RuntimeError("V63_DURABLE_BACKEND_INVALID_RESULT")
    return result
