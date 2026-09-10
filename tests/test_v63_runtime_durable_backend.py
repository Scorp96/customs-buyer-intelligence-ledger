import unittest

from unified_runtime.demand_expansion import V63DemandExpansionMixin
from unified_runtime.runtime_durable_backend_v63 import (
    bind_v63_runtime_durable_backend,
    get_v63_runtime_durable_backend_state,
)


class Base:
    def get_runtime_contract(self, arguments=None):
        return {"runtime_version": "6.1.0"}


class Runtime(V63DemandExpansionMixin, Base):
    pass


class SafeFakeBackend:
    backend_schema = "cbi.v63-production-durable-backend.v1"
    binding_strategy = "EXISTING_PRODUCTION_APPEND_ONLY_STORE"
    parallel_state_store_allowed = False
    requires_existing_mutation_correlation = True
    raw_idempotency_key_persisted = False
    side_effect_reexecution_allowed = False

    def __init__(self):
        self.calls = []

    def _call(self, tool, runtime, arguments):
        self.calls.append((tool, runtime, dict(arguments)))
        return {"status": "COMMITTED_SYNTHETIC_TEST_BACKEND", "tool": tool}

    def append_candidate_discovery(self, runtime, arguments):
        return self._call("append_candidate_discovery", runtime, arguments)

    def create_product_opportunity(self, runtime, arguments):
        return self._call("create_product_opportunity", runtime, arguments)

    def promote_opportunity_anchor(self, runtime, arguments):
        return self._call("promote_opportunity_anchor", runtime, arguments)


class UnsafeBackend(SafeFakeBackend):
    parallel_state_store_allowed = True


class V63RuntimeDurableBackendTests(unittest.TestCase):
    def test_unbound_runtime_remains_fail_closed_even_with_forged_request_flags(self):
        runtime = Runtime()
        for name in (
            "append_candidate_discovery",
            "create_product_opportunity",
            "promote_opportunity_anchor",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, "V63_MUTATION_REQUIRES_PRODUCTION_WAL_BINDING"):
                    getattr(runtime, name)({
                        "idempotency_key": "forged-key-123",
                        "wal_bound": True,
                        "runtime_durable_backend_binding": "BOUND_EXISTING_DURABLE_STORE",
                    })

    def test_unsafe_or_parallel_backend_is_rejected(self):
        runtime = Runtime()
        with self.assertRaisesRegex(RuntimeError, "V63_DURABLE_BACKEND_CONTRACT_REJECTED"):
            bind_v63_runtime_durable_backend(runtime, UnsafeBackend())
        self.assertEqual(
            get_v63_runtime_durable_backend_state(runtime)["status"],
            "UNBOUND_FAIL_CLOSED",
        )

    def test_binding_is_internal_one_time_and_different_backend_cannot_replace_it(self):
        runtime = Runtime()
        first = SafeFakeBackend()
        second = SafeFakeBackend()
        state = bind_v63_runtime_durable_backend(runtime, first)
        self.assertEqual(state["status"], "BOUND_EXISTING_DURABLE_STORE")
        self.assertFalse(state["parallel_state_store_allowed"])
        self.assertIs(bind_v63_runtime_durable_backend(runtime, first)["backend"], first)
        with self.assertRaisesRegex(RuntimeError, "V63_DURABLE_BACKEND_ALREADY_BOUND"):
            bind_v63_runtime_durable_backend(runtime, second)

    def test_bound_runtime_routes_all_three_mutations_only_to_internal_backend(self):
        runtime = Runtime()
        backend = SafeFakeBackend()
        bind_v63_runtime_durable_backend(runtime, backend)

        methods = (
            "append_candidate_discovery",
            "create_product_opportunity",
            "promote_opportunity_anchor",
        )
        for name in methods:
            result = getattr(runtime, name)({
                "investigation_id": "INV-1",
                "idempotency_key": f"key-{name}-123",
                "expected_state_version": 7,
                "payload": {"x": 1},
            })
            self.assertEqual(result["tool"], name)

        self.assertEqual([row[0] for row in backend.calls], list(methods))
        self.assertTrue(all(row[1] is runtime for row in backend.calls))
        # Adapter control material can be seen by the trusted backend for exact
        # correlation/recovery, but the backend contract explicitly forbids
        # persisting the raw idempotency key.
        self.assertTrue(all("idempotency_key" in row[2] for row in backend.calls))

    def test_runtime_contract_reports_backend_binding_separately_from_wal_wrapper(self):
        runtime = Runtime()
        before = runtime.get_runtime_contract({})["demand_expansion_v6_3"]
        self.assertEqual(before["runtime_durable_backend_binding"], "UNBOUND_FAIL_CLOSED")

        bind_v63_runtime_durable_backend(runtime, SafeFakeBackend())
        after = runtime.get_runtime_contract({})["demand_expansion_v6_3"]
        self.assertEqual(after["runtime_durable_backend_binding"], "BOUND_EXISTING_DURABLE_STORE")
        self.assertEqual(after["runtime_durable_backend_schema"], "cbi.v63-production-durable-backend.v1")
        self.assertFalse(after["runtime_durable_backend_parallel_store_allowed"])


if __name__ == "__main__":
    unittest.main()
