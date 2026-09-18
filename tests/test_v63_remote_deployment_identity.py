from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V63RemoteDeploymentIdentityTests(unittest.TestCase):
    def _environment(
        self,
        root: Path,
        *,
        git_sha: str,
        pin: bool,
    ) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(
            {
                "CBI_SESSION_ROOT": str(root / "sessions"),
                "CBI_HOST_PENDING_ROOT": str(root / "host-pending"),
                "CBI_OBJECT_STORE_MODE": "none",
                "CBI_V63_ACCEPTANCE_PIN_DEPLOYMENT_SHA": "true" if pin else "false",
                "RENDER_GIT_COMMIT": git_sha,
                "CBI_OBJECT_STORE_SECRET_ACCESS_KEY": "never-expose-secret",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return environment

    def _health_process(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-Xutf8",
                "-c",
                (
                    "import json; "
                    "from mcp import server_v61_remote as remote; "
                    "print(json.dumps(remote._health(), sort_keys=True))"
                ),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    def test_health_exposes_safe_exact_deployment_and_persistence_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v63-remote-identity-") as tmp_name:
            sha = "1234567890abcdef1234567890abcdef12345678"
            completed = self._health_process(
                self._environment(Path(tmp_name), git_sha=sha, pin=True)
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            health = json.loads(completed.stdout.strip().splitlines()[-1])
            identity = health["deployment_identity"]
            self.assertEqual(identity["schema"], "cbi.remote-deployment-identity.v6.3")
            self.assertEqual(identity["git_sha"], sha)
            self.assertEqual(identity["git_sha_source"], "RENDER_GIT_COMMIT")
            self.assertTrue(identity["acceptance_pin_required"])
            self.assertEqual(identity["remote_entrypoint"], "mcp/server_v61_remote.py")
            self.assertEqual(
                identity["runtime_entrypoint"],
                "mcp/server_v61_backup_recovery.py",
            )
            self.assertEqual(identity["object_store_mode"], "none")
            self.assertIsNone(identity["object_state_schema"])
            self.assertIsNone(identity["object_state_generation"])
            self.assertIsNone(identity["restore_generation"])
            self.assertIsNone(identity["restore_source"])
            serialized = json.dumps(health, sort_keys=True)
            self.assertNotIn("never-expose-secret", serialized)
            self.assertNotIn("access_key", serialized.casefold())
            self.assertNotIn("idempotency_key", serialized.casefold())

    def test_acceptance_pinning_rejects_malformed_render_git_commit_at_startup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v63-remote-bad-sha-") as tmp_name:
            completed = self._health_process(
                self._environment(Path(tmp_name), git_sha="not-a-git-sha", pin=True)
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "DEPLOYMENT_GIT_SHA_INVALID_OR_MISSING",
                completed.stderr,
            )


if __name__ == "__main__":
    unittest.main()
