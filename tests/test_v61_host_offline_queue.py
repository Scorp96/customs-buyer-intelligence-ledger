from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "mcp" / "server_v61.py"
OFFLINE_WRITER = ROOT / "scripts" / "queue_host_bundle_offline.py"


class V61HostOfflineQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-host-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.queue_root = self.root / "host-pending"
        self.previous_queue_root = os.environ.get("CBI_HOST_PENDING_ROOT")
        os.environ["CBI_HOST_PENDING_ROOT"] = str(self.queue_root)
        self.addCleanup(self._restore_environment)
        self.runtime = UnifiedRuntime(self.session_root)
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-OFFLINE-SYNTH",
                "country": "United States",
                "name": "Offline Queue Synthetic Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = started["investigation_id"]

    def _restore_environment(self) -> None:
        if self.previous_queue_root is None:
            os.environ.pop("CBI_HOST_PENDING_ROOT", None)
        else:
            os.environ["CBI_HOST_PENDING_ROOT"] = self.previous_queue_root

    def payload(self) -> dict:
        return {
            "investigation_id": self.investigation_id,
            "bundle": {
                "bundle_id": "BUNDLE-OFFLINE-CHAOS-001",
                "observations": [
                    {
                        "claim_key": "identity.legal_entity",
                        "result": "POSITIVE",
                        "owner_type": "ACCOUNT",
                        "owner_id": "C-OFFLINE-SYNTH",
                        "value": {"legal_entity": "Offline Queue Synthetic Buyer LLC"},
                        "source": {
                            "source_family": "synthetic_offline_registry",
                            "source_type": "OFFICIAL",
                            "reference_type": "PUBLIC_URL",
                            "url": "https://example.invalid/offline/legal",
                            "locator": "https://example.invalid/offline/legal#entity",
                            "raw_excerpt": "Synthetic offline queue legal entity fixture",
                            "authority_level": "A1_OFFICIAL_PRIMARY",
                            "freshness": "CURRENT_CONFIRMED",
                            "observed_at": "2026-08-28T00:00:00Z",
                        },
                        "boundary": "Synthetic offline-host durability fixture only.",
                    }
                ],
            },
        }

    def _kill_mcp_transport(self) -> None:
        environment = dict(os.environ)
        environment.update({
            "CBI_SESSION_ROOT": str(self.session_root),
            "CBI_HOST_PENDING_ROOT": str(self.queue_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(MCP_SERVER), "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdin is None or process.stdin.closed)
        self.assertTrue(process.stdout is None or process.stdout.closed)
        self.assertTrue(process.stderr is None or process.stderr.closed)

    def _offline_queue(self, payload_path: Path) -> dict:
        environment = dict(os.environ)
        environment.update({
            "CBI_HOST_PENDING_ROOT": str(self.queue_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-Xutf8",
                str(OFFLINE_WRITER),
                "--queue-root",
                str(self.queue_root),
                "--payload",
                str(payload_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=15,
        )
        return json.loads(completed.stdout)

    def test_host_persists_bundle_after_mcp_death_and_runtime_replays_exactly_once(self) -> None:
        self._kill_mcp_transport()
        payload_path = self.root / "offline-bundle.json"
        payload_path.write_text(json.dumps(self.payload()), encoding="utf-8")
        first = self._offline_queue(payload_path)
        self.assertTrue(first["queued"])
        self.assertFalse(first["deduplicated"])
        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(first["transport"], "LOCAL_FILESYSTEM_NO_MCP")
        replay = self._offline_queue(payload_path)
        self.assertFalse(replay["queued"])
        self.assertTrue(replay["deduplicated"])
        self.assertEqual(replay["request_sha256"], first["request_sha256"])
        restarted = UnifiedRuntime(self.session_root)
        synced = restarted.sync_pending_bundles({
            "investigation_id": self.investigation_id,
            "limit": 10,
        })
        self.assertEqual(synced["processed"], 1)
        self.assertEqual(synced["counts"], {"SYNCED": 1})
        self.assertEqual(synced["outcomes"][0]["result"]["bundle_id"], "BUNDLE-OFFLINE-CHAOS-001")
        second_sync = restarted.sync_pending_bundles({
            "investigation_id": self.investigation_id,
            "limit": 10,
        })
        self.assertEqual(second_sync["processed"], 0)
        state = restarted.get_investigation_state({"investigation_id": self.investigation_id})
        self.assertEqual(state["observation_count"], 1)
        self.assertEqual(state["bundle_count"], 1)
        health = restarted.get_runtime_health({})
        self.assertEqual(health["host_pending_bundles"].get("PENDING", 0), 0)
        self.assertEqual(health["host_pending_bundles"].get("SYNCED", 0), 1)


if __name__ == "__main__":
    unittest.main()
