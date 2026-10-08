"""Public HTTP readiness must not disclose infrastructure/recovery identity.

The internal operator health callback remains rich and unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MinimalPublicHealthTests(unittest.TestCase):
    def _process(self) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="cbi-public-health-") as tmp:
            env = dict(os.environ)
            env.update({
                "CBI_SESSION_ROOT": str(Path(tmp) / "sessions"),
                "CBI_HOST_PENDING_ROOT": str(Path(tmp) / "pending"),
                "CBI_OBJECT_STORE_MODE": "none",
                "CBI_V63_ACCEPTANCE_PIN_DEPLOYMENT_SHA": "false",
                "RENDER_GIT_COMMIT": "1234567890abcdef1234567890abcdef12345678",
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            return subprocess.run(
                [sys.executable, "-B", "-Xutf8", "-c", (
                    "import json; from mcp import server_v61_remote as r; "
                    "print(json.dumps({'public':r._public_health(), 'private':r._health()},sort_keys=True))"
                )],
                cwd=ROOT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=30, check=False,
            )

    def test_public_health_is_minimal_internal_retains_rich_data(self):
        p = self._process()
        self.assertEqual(p.returncode, 0, p.stderr)
        d = json.loads(p.stdout.strip().splitlines()[-1])
        public, internal = d["public"], d["private"]
        self.assertEqual(public, {
            "status": "ok", "service": "customs-buyer-intelligence",
        })
        self.assertIn("deployment_identity", internal)
        self.assertIn("crawler_runtime", internal)
        self.assertIn("object_store_persistence_enabled", internal)
        for forbidden in ("deployment_identity", "crawler_runtime", "object_store_persistence",
                          "recovery_fingerprint_sha256", "instance_id", "git_sha"):
            self.assertNotIn(forbidden, public)

    def test_production_main_exposes_only_public_health_callback(self):
        # Do not import the server into the current unittest process:
        # remote import is deliberately guarded by an explicit durable root.
        source = (ROOT / "mcp/server_v61_remote.py").read_text(encoding="utf-8")
        self.assertIn("health=_public_health", source)
        self.assertNotIn("health=_health)", source)


if __name__ == "__main__":
    unittest.main()
