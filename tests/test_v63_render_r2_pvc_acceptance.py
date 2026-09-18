from __future__ import annotations

import copy
import inspect
import json
import unittest

from unified_runtime.product_profiles import get_product_profile
from unified_runtime.recovery_semantics_v63 import canonical_v63_wal_request_sha256
from unified_runtime.render_r2_pvc_acceptance_v63 import (
    PVC_ACCEPTANCE_SCHEMA,
    build_pvc_mutation_arguments,
    run_v63_render_r2_pvc_acceptance,
)
from unified_runtime.render_r2_pvc_acceptance_validator_v63 import (
    validate_v63_render_r2_pvc_acceptance,
)


GIT_SHA = "6" * 40
INVESTIGATION_ID = "INV-20260903T000000Z-aaaaaaaaaaaa"
EVENT_TYPES = {
    "append_candidate_discovery": "V63_CANDIDATE_DISCOVERED",
    "create_product_opportunity": "V63_PRODUCT_OPPORTUNITY_CREATED",
    "promote_opportunity_anchor": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
}
CORRELATIONS = {
    "append_candidate_discovery": "MUTCORR-pvc-candidate-000001",
    "create_product_opportunity": "MUTCORR-pvc-opportunity-0001",
    "promote_opportunity_anchor": "MUTCORR-pvc-anchor-000000001",
}


class _FakeAcceptanceClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.replaced = False
        self.restore_generation = None
        self.profile = get_product_profile("PVC")

    def read_health(self) -> dict:
        generation = 9
        return {
            "status": "ok",
            "object_store_persistence_enabled": True,
            "remote_post_handler_checkpoint_enabled": True,
            "deployment_identity": {
                "schema": "cbi.remote-deployment-identity.v6.3",
                "git_sha": GIT_SHA,
                "git_sha_source": "RENDER_GIT_COMMIT",
                "acceptance_pin_required": True,
                "remote_entrypoint": "mcp/server_v61_remote.py",
                "runtime_entrypoint": "mcp/server_v61_backup_recovery.py",
                "object_store_mode": "r2",
                "object_state_schema": "cbi.object-store-state.v2",
                "object_state_generation": generation,
                "restore_generation": self.restore_generation,
                "restore_source": "object_state_v2" if self.replaced else None,
            },
            "object_store_persistence": {
                "generation": generation,
                "recovery_state_schema": "cbi.object-store-state.v2",
            },
        }

    def discover(self) -> dict:
        return {
            "resultType": "complete",
            "supportedVersions": ["2026-07-28"],
            "capabilities": {"tools": {}},
        }

    def initialize(self) -> dict:
        return {"protocolVersion": "2025-06-18"}

    def required_v63_mutation_surface(self) -> dict:
        return {
            "required_tools": list(EVENT_TYPES),
            "observed_tools": [
                "start_investigation",
                "plan_candidate_expansion",
                *EVENT_TYPES,
            ],
            "deployment_git_sha": GIT_SHA,
            "protocol_version": "2026-07-28",
        }

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "start_investigation":
            return {
                "status": "STARTED",
                "investigation_id": INVESTIGATION_ID,
            }
        if name == "plan_candidate_expansion":
            return {
                "status": "PLANNED",
                "product_profile_id": "PVC",
                "branch_groups": ["TRADE_GRAPH", "APPLICATION_GRAPH"],
                "planning_is_execution_proof": False,
            }
        replayed = self.replaced
        if name == "append_candidate_discovery":
            return {
                "status": "DISCOVERED",
                "candidate_id": "CAND-V63-R2-PVC-001",
                "mutation_meta": {"replayed": replayed},
            }
        if name == "create_product_opportunity":
            return {
                "status": "CREATED",
                "opportunity_id": "OPP-V63-R2-PVC-001",
                "product_profile_id": "PVC",
                "product_profile_version": self.profile["profile_version"],
                "product_profile_sha256": self.profile["profile_sha256"],
                "mutation_meta": {"replayed": replayed},
            }
        if name == "promote_opportunity_anchor":
            return {
                "status": "PROMOTED",
                "opportunity_id": "OPP-V63-R2-PVC-001",
                "anchor_id": "ANCHOR-OPP-V63-R2-PVC-001",
                "anchor_eligibility_snapshot": arguments["anchor_eligibility"],
                "cycle_dedup_snapshot": {"cycle_dedup_complete": True},
                "mutation_meta": {"replayed": replayed},
            }
        raise AssertionError(f"unexpected tool call {name}")


class _FakeReplacementController:
    def __init__(self, client: _FakeAcceptanceClient) -> None:
        self.client = client
        arguments = build_pvc_mutation_arguments(INVESTIGATION_ID)
        self.request_hashes = {
            tool: canonical_v63_wal_request_sha256(tool, args)
            for tool, args in arguments.items()
        }

    def _evidence(self) -> dict:
        events = {}
        wal = {}
        for index, tool in enumerate(EVENT_TYPES, start=10):
            correlation = CORRELATIONS[tool]
            request_sha = self.request_hashes[tool]
            events[tool] = {
                "count": 1,
                "seq": index,
                "event_type": EVENT_TYPES[tool],
                "correlation_id": correlation,
                "request_sha256": request_sha,
            }
            wal[tool] = {
                "status": "COMMITTED",
                "correlation_id": correlation,
                "request_sha256": request_sha,
            }
        return {
            "schema": "cbi.render-r2-persistence-probe.v6.3",
            "generation": 9,
            "events": events,
            "wal": wal,
        }

    def collect(self, investigation_id: str) -> dict:
        if investigation_id != INVESTIGATION_ID:
            raise AssertionError("wrong investigation id")
        return self._evidence()

    def replace_instance(self) -> dict:
        self.client.replaced = True
        self.client.restore_generation = 9
        return {
            "instance_before": "local-http-active-a",
            "instance_after": "local-http-active-b",
            "restored_generation": 9,
            "restore_source": "object_state_v2",
        }


class V63RenderR2PVCAcceptanceTests(unittest.TestCase):
    def _run(self):
        client = _FakeAcceptanceClient()
        controller = _FakeReplacementController(client)
        receipt = run_v63_render_r2_pvc_acceptance(client, controller)
        return client, controller, receipt

    def test_runner_exposes_execution_dependencies_only_not_caller_verdicts(self) -> None:
        params = list(inspect.signature(run_v63_render_r2_pvc_acceptance).parameters)
        self.assertEqual(params, ["client", "replacement_controller"])

    def test_runner_executes_canonical_pvc_scenario_replacement_and_same_request_replays(self) -> None:
        client, _controller, receipt = self._run()
        self.assertEqual(receipt["schema"], PVC_ACCEPTANCE_SCHEMA)
        self.assertIs(receipt["production_ready"], False)
        self.assertEqual(receipt["product_profile"]["profile_id"], "PVC")
        canonical = get_product_profile("PVC")
        self.assertEqual(
            receipt["product_profile"]["profile_sha256"],
            canonical["profile_sha256"],
        )
        names = [name for name, _args in client.calls]
        self.assertEqual(
            names,
            [
                "start_investigation",
                "plan_candidate_expansion",
                "append_candidate_discovery",
                "create_product_opportunity",
                "promote_opportunity_anchor",
                "append_candidate_discovery",
                "create_product_opportunity",
                "promote_opportunity_anchor",
            ],
        )
        for tool in EVENT_TYPES:
            self.assertIs(receipt["replay_responses"][tool]["mutation_meta"]["replayed"], True)
        self.assertNotEqual(
            receipt["replacement"]["instance_before"],
            receipt["replacement"]["instance_after"],
        )
        self.assertEqual(receipt["replacement"]["restored_generation"], 9)
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn("idempotency_key", serialized.casefold())
        self.assertNotIn("bearer_token", serialized.casefold())
        self.assertNotIn("secret_access_key", serialized.casefold())

    def test_validator_derives_verified_from_observed_sha_r2_exact_evidence_and_no_duplicates(self) -> None:
        _client, _controller, receipt = self._run()
        result = validate_v63_render_r2_pvc_acceptance(receipt)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["blockers"], [])
        self.assertIs(result["production_ready"], False)
        self.assertEqual(result["verified_mutation_count"], 3)

    def test_validator_fails_closed_on_each_required_external_proof_class(self) -> None:
        _client, _controller, receipt = self._run()
        mutations = list(EVENT_TYPES)

        cases = []
        missing_sha = copy.deepcopy(receipt)
        missing_sha["health_before"]["deployment_identity"].pop("git_sha", None)
        cases.append((missing_sha, "DEPLOYMENT_GIT_SHA"))

        missing_lineage = copy.deepcopy(receipt)
        missing_lineage["replacement"].pop("restored_generation", None)
        cases.append((missing_lineage, "R2_RESTORE_LINEAGE"))

        duplicate = copy.deepcopy(receipt)
        duplicate["evidence_after"]["events"][mutations[0]]["count"] = 2
        cases.append((duplicate, "DUPLICATE_BUSINESS_EVENT"))

        wrong_correlation = copy.deepcopy(receipt)
        wrong_correlation["evidence_after"]["wal"][mutations[1]]["correlation_id"] = "MUTCORR-wrong"
        cases.append((wrong_correlation, "EXACT_CORRELATION"))

        wrong_hash = copy.deepcopy(receipt)
        wrong_hash["evidence_after"]["events"][mutations[2]]["request_sha256"] = "f" * 64
        cases.append((wrong_hash, "EXACT_REQUEST_HASH"))

        secret = copy.deepcopy(receipt)
        secret["debug"] = {"idempotency_key": "must-not-escape"}
        cases.append((secret, "SENSITIVE_FIELD_EXPOSED"))

        for candidate, expected in cases:
            with self.subTest(expected=expected):
                result = validate_v63_render_r2_pvc_acceptance(candidate)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertTrue(
                    any(expected in blocker for blocker in result["blockers"]),
                    result,
                )
                self.assertIs(result["production_ready"], False)


if __name__ == "__main__":
    unittest.main()
