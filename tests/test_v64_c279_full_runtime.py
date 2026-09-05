from __future__ import annotations

import json
import os
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch


class V64C279FullRuntimeRegression(unittest.TestCase):
    def test_c279_canonical_route_can_prepare_outreach_full_runtime(self):
        bridge_path = os.environ.get("CBI_V64_C279_BRIDGE_EVIDENCE")
        source_root_value = os.environ.get("CBI_V64_C279_SOURCE_RUNTIME_ROOT")
        if not bridge_path or not source_root_value:
            self.skipTest("private authoritative C279 bridge/runtime root not supplied")

        bridge = json.loads(Path(bridge_path).read_text(encoding="utf-8"))
        source_root = Path(source_root_value).expanduser().resolve()
        investigation_id = str(bridge["investigation_id"])
        durable = dict(bridge.get("durable_state") or {})
        expected_seq = int(durable["last_safe_seq"])
        expected_hash = str(durable["last_safe_event_hash"])

        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-") as temp_dir:
            isolated_root = Path(temp_dir) / "runtime"
            shutil.copytree(source_root, isolated_root)
            sessions_root = isolated_root / "sessions"
            self.assertTrue((sessions_root / f"{investigation_id}.jsonl").is_file())

            runtime_env = {"CBI_SESSION_ROOT": str(sessions_root)}
            for env_name, relative in (
                ("CBI_CANONICAL_ROOT", "canonical"),
                ("CBI_PENDING_ROOT", "pending"),
            ):
                candidate = isolated_root / relative
                if candidate.exists():
                    runtime_env[env_name] = str(candidate)

            with patch.dict(os.environ, runtime_env, clear=False):
                from unified_runtime import UnifiedRuntime

                runtime = UnifiedRuntime(sessions_root)
                state = runtime.get_investigation_state({"investigation_id": investigation_id})
                self.assertEqual(state["last_safe_seq"], expected_seq)
                self.assertEqual(state["last_safe_event_hash"], expected_hash)

                readiness = runtime.evaluate_outreach_readiness({"investigation_id": investigation_id})
                rank = {
                    "BLOCKED": 0,
                    "IDENTITY_ONLY": 1,
                    "COMPANY_ROUTE_READY": 2,
                    "NAMED_ROUTE_READY": 3,
                    "FOLLOW_UP_READY": 4,
                    "SEND_READY": 5,
                }
                actual_readiness = str(readiness.get("outreach_readiness") or readiness.get("readiness"))
                self.assertGreaterEqual(rank.get(actual_readiness, -1), rank["COMPANY_ROUTE_READY"])
                routes = [row for row in (readiness.get("canonical_route_view") or []) if isinstance(row, dict)]
                self.assertTrue(routes)

                named_ids = set(
                    dict(bridge.get("named_route") or {}).get("observation_ids") or []
                )
                route = next(
                    (row for row in routes if str(row.get("observation_id") or "") in named_ids),
                    routes[0],
                )
                closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
                self.assertTrue(closure.get("closed"))
                self.assertTrue(closure.get("closure_id"))

                start = runtime._v6_state(investigation_id)["start"]
                body = (
                    "Hello, I’m contacting your company from XingHuai New Materials. We manufacture PVC foam board "
                    "and related rigid panel materials for distribution, cabinetry, interior fabrication, signage and "
                    "general sheet applications. I would like to understand whether your purchasing team is open to "
                    "evaluating an additional qualified supply source. We can provide a concise product overview and "
                    "then prepare technical information only against requirements that your team confirms. Could you "
                    "please direct this message to the colleague responsible for purchasing or sourcing sheet materials? "
                    "If this category is not relevant, no further action is needed. Best regards, Mark Zhou"
                )
                prepared = runtime.prepare_outreach({
                    "investigation_id": investigation_id,
                    "closure_id": closure["closure_id"],
                    "route": route,
                    "history_digest": start.get("history_digest"),
                    "authority_digest": start.get("authority_digest"),
                    "subject": "PVC sheet sourcing contact",
                    "body": body,
                    "stage": "FIRST_TOUCH",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=15)
                    ).isoformat().replace("+00:00", "Z"),
                })
                self.assertTrue(prepared.get("prepared"), prepared)
                self.assertEqual(prepared.get("block_reasons") or [], [])
                self.assertFalse(prepared.get("sends_message"))


if __name__ == "__main__":
    unittest.main()

