from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63
from tests.test_v63_render_r2_cross_instance_recovery import (
    _MemoryObjectClient,
    _build_quiescent_migration_archive,
    _sha256_file,
)
from unified_runtime.exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from unified_runtime.exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from unified_runtime.render_r2_acceptance_client_v63 import (
    RenderR2AcceptanceClient,
    RenderR2AcceptanceClientConfig,
)
from unified_runtime.render_r2_pvc_acceptance_v63 import (
    MUTATION_EVENT_TYPES,
    PERSISTENCE_PROBE_SCHEMA,
    run_v63_render_r2_pvc_acceptance,
)
from unified_runtime.render_r2_pvc_acceptance_validator_v63 import (
    validate_v63_render_r2_pvc_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]
GIT_SHA = "7" * 40
BEARER = "v63-local-active-http-bearer-0123456789abcdef"
PREFIX = "cbi-v63-local-active-http-pvc"


class _ActiveState:
    def __init__(
        self,
        root: Path,
        harness: ExactCheckoutMcpHarness,
        manager: RecoveryObjectStoreStateManagerV63,
    ) -> None:
        self.root = root
        self.harness = harness
        self.manager = manager
        self.rpc_id = 100
        self.instance_id = "local-http-active-a"
        self.restore_generation: int | None = None
        self.restore_source: str | None = None

    def next_rpc_id(self) -> int:
        self.rpc_id += 1
        return self.rpc_id

    def health(self) -> dict:
        persistence = self.manager.health()
        pointer = self.manager.pointer
        generation = getattr(pointer, "generation", None)
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
                "object_state_schema": persistence.get("recovery_state_schema"),
                "object_state_generation": generation,
                "restore_generation": self.restore_generation,
                "restore_source": self.restore_source,
            },
            "object_store_persistence": {
                "generation": generation,
                "recovery_state_schema": persistence.get("recovery_state_schema"),
            },
        }


class _ActiveHttpBridge:
    def __init__(self, state: _ActiveState) -> None:
        self.state = state
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def _json(self, status: int, value: object) -> None:
                body = json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/healthz":
                    self._json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
                    return
                self._json(HTTPStatus.OK, bridge.state.health())

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/mcp":
                    self._json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
                    return
                if self.headers.get("Authorization") != f"Bearer {BEARER}":
                    self._json(HTTPStatus.UNAUTHORIZED, {"status": "unauthorized"})
                    return
                length = int(self.headers.get("Content-Length") or "0")
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                request_id = request.get("id")
                method = str(request.get("method") or "")
                params = request.get("params")
                params = dict(params) if isinstance(params, dict) else {}

                if method == "server/discover":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "resultType": "complete",
                                "supportedVersions": ["2026-07-28"],
                                "capabilities": {"tools": {}},
                            },
                        },
                    )
                    return

                response = bridge.state.harness._rpc(
                    bridge.state.next_rpc_id(),
                    method,
                    params,
                )
                if method == "tools/call" and "error" not in response:
                    bridge.state.manager.sync_if_changed(bridge.state.root)
                outgoing = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                }
                if "error" in response:
                    outgoing["error"] = response["error"]
                else:
                    outgoing["result"] = response.get("result")
                self._json(HTTPStatus.OK, outgoing)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "_ActiveHttpBridge":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _ReplacementController:
    def __init__(
        self,
        tmp: Path,
        object_client: _MemoryObjectClient,
        state: _ActiveState,
    ) -> None:
        self.tmp = tmp
        self.object_client = object_client
        self.state = state

    def collect(self, investigation_id: str) -> dict:
        reader = ExactCheckoutPersistenceReader(self.state.root)
        events: dict[str, dict] = {}
        wal: dict[str, dict] = {}
        for tool, expected_event_type in MUTATION_EVENT_TYPES.items():
            evidence = reader.normalize_mutation_evidence(investigation_id, tool)
            event_rows = list(evidence.get("events") or [])
            wal_rows = list(evidence.get("wal_records") or [])
            if len(event_rows) != 1 or len(wal_rows) != 1:
                raise AssertionError(
                    f"{tool} evidence cardinality events={len(event_rows)} wal={len(wal_rows)}"
                )
            event = event_rows[0]
            wal_row = wal_rows[0]
            events[tool] = {
                "count": len(event_rows),
                "seq": event.get("seq"),
                "event_type": event.get("event_type") or expected_event_type,
                "correlation_id": event.get("correlation_id"),
                "request_sha256": event.get("request_sha256"),
            }
            wal[tool] = {
                "status": wal_row.get("status"),
                "correlation_id": wal_row.get("correlation_id"),
                "request_sha256": wal_row.get("request_sha256"),
            }
        return {
            "schema": PERSISTENCE_PROBE_SCHEMA,
            "generation": self.state.manager.pointer.generation,
            "events": events,
            "wal": wal,
        }

    def replace_instance(self) -> dict:
        before = self.state.instance_id
        restored_generation = self.state.manager.pointer.generation
        self.state.harness.stop()

        root_b = self.tmp / "instance-b"
        manager_b = RecoveryObjectStoreStateManagerV63(
            self.object_client,
            prefix=PREFIX,
        )
        if not manager_b.restore_into(root_b):
            raise AssertionError("R2 replacement restore returned false")
        manager_b.attach_existing(root_b)
        harness_b = ExactCheckoutMcpHarness(ROOT, root_b)
        harness_b.start()

        self.state.root = root_b
        self.state.manager = manager_b
        self.state.harness = harness_b
        self.state.instance_id = "local-http-active-b"
        self.state.restore_generation = restored_generation
        self.state.restore_source = "object_state_v2"
        return {
            "instance_before": before,
            "instance_after": self.state.instance_id,
            "restored_generation": restored_generation,
            "restore_source": "object_state_v2",
        }


class V63RenderR2PVCAcceptanceActiveHttpIntegrationTests(unittest.TestCase):
    def test_pvc_acceptance_runs_over_http_against_active_mcp_and_survives_r2_replacement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v63-pvc-active-http-") as tmp_name:
            tmp = Path(tmp_name)
            root_a = tmp / "instance-a"
            object_client = _MemoryObjectClient()

            harness_a = ExactCheckoutMcpHarness(ROOT, root_a)
            harness_a.start()
            self.addCleanup(harness_a.stop)

            migration_dir = tmp / "migration"
            migration_dir.mkdir()
            migration = _build_quiescent_migration_archive(root_a, migration_dir)
            seed = RecoveryObjectStoreStateManagerV63(object_client, prefix=PREFIX)
            seed.seed_migration_archive(migration, _sha256_file(migration))
            manager_a = RecoveryObjectStoreStateManagerV63(object_client, prefix=PREFIX)
            manager_a.attach_existing(root_a)

            # Upgrade the quiescent v1 seed to recovery-state v2 before health
            # pinning. Empty WAL authority is explicit rather than inferred.
            (root_a / "mcp-idempotency-v61").mkdir(exist_ok=True)
            self.assertTrue(manager_a.sync_if_changed(root_a))
            self.assertEqual(
                manager_a.health()["recovery_state_schema"],
                "cbi.object-store-state.v2",
            )

            state = _ActiveState(root_a, harness_a, manager_a)
            controller = _ReplacementController(tmp, object_client, state)
            self.addCleanup(lambda: state.harness.stop())

            with _ActiveHttpBridge(state) as bridge:
                client = RenderR2AcceptanceClient(
                    RenderR2AcceptanceClientConfig(
                        base_url=bridge.base_url,
                        bearer_token=BEARER,
                        expected_git_sha=GIT_SHA,
                        timeout_seconds=10,
                    )
                )
                receipt = run_v63_render_r2_pvc_acceptance(client, controller)

            validation = validate_v63_render_r2_pvc_acceptance(receipt)
            self.assertEqual(validation["status"], "VERIFIED", validation)
            self.assertEqual(validation["blockers"], [])
            self.assertEqual(validation["verified_mutation_count"], 3)
            self.assertIs(validation["production_ready"], False)
            self.assertEqual(receipt["product_profile"]["profile_id"], "PVC")
            self.assertEqual(receipt["replacement"]["instance_after"], "local-http-active-b")
            self.assertEqual(
                receipt["health_after"]["deployment_identity"]["restore_source"],
                "object_state_v2",
            )
            serialized = json.dumps(receipt, sort_keys=True).casefold()
            self.assertNotIn("idempotency_key", serialized)
            self.assertNotIn("bearer_token", serialized)
            self.assertNotIn("secret_access_key", serialized)


if __name__ == "__main__":
    unittest.main()
