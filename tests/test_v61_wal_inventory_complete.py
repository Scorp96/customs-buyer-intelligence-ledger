from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server_v61_sync_recovery.py"


class V61WalInventoryCompleteTests(unittest.TestCase):
    def test_every_guarded_production_mutation_has_automatic_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v61-wal-inventory-") as temp:
            environment = dict(os.environ)
            environment.update({
                "CBI_SESSION_ROOT": str(Path(temp) / "sessions"),
                "CBI_HOST_PENDING_ROOT": str(Path(temp) / "host-pending"),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            process = subprocess.Popen(
                [sys.executable, "-B", "-Xutf8", str(SERVER), "--stdio"],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            try:
                assert process.stdin is not None and process.stdout is not None
                for request in (
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18"},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "get_runtime_contract", "arguments": {}},
                    },
                ):
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                    response = json.loads(process.stdout.readline())
                    self.assertNotIn("error", response)
                    if request["id"] == 2:
                        contract = response["result"]["structuredContent"]
                wal = contract["production_adapter_mutation_wal"]
                guarded = wal["guarded_mutation_tools"]
                automatic = wal["automatic_reconciliation_tools"]
                self.assertEqual(wal["unreconciled_mutation_tools"], [])
                self.assertTrue(wal["exact_automatic_reconciliation_complete"])
                self.assertTrue(wal["completeness_is_computed_from_live_inventory"])
                self.assertEqual(set(guarded), set(automatic))
                self.assertEqual(len(guarded), 23)
                self.assertIn("plan_provider_calls", guarded)
                self.assertIn("evaluate_investigation_closure", guarded)
                self.assertIn("sync_pending_receipts", guarded)
                self.assertIn("sync_pending_bundles", guarded)
                self.assertIn("sync_pending_research_bundles", guarded)
            finally:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()


if __name__ == "__main__":
    unittest.main()
