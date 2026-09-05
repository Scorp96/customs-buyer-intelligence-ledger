from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mcp import remote_transport
from mcp import render_bootstrap


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "render.yaml"
DOCKERFILE = ROOT / "deploy" / "cloud" / "Dockerfile"


class RenderCloudRuntimeTests(unittest.TestCase):
    def test_remote_port_prefers_explicit_then_cbi_then_platform_port(self) -> None:
        with mock.patch.dict(os.environ, {"CBI_REMOTE_PORT": "9101", "PORT": "9102"}, clear=False):
            self.assertEqual(remote_transport._resolved_port(9100), 9100)
            self.assertEqual(remote_transport._resolved_port(), 9101)
        with mock.patch.dict(os.environ, {"PORT": "9102"}, clear=True):
            self.assertEqual(remote_transport._resolved_port(), 9102)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(remote_transport._resolved_port(), 8787)

    def test_remote_port_rejects_invalid_value(self) -> None:
        with mock.patch.dict(os.environ, {"PORT": "70000"}, clear=True):
            with self.assertRaises(RuntimeError):
                remote_transport._resolved_port()

    def test_render_bootstrap_state_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name) / "live"
            self.assertEqual(render_bootstrap._state(root), "bootstrap")
            root.mkdir()
            self.assertEqual(render_bootstrap._state(root), "bootstrap")
            (root / "sessions").mkdir()
            self.assertEqual(render_bootstrap._state(root), "invalid")
            (root / "export-manifest.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(render_bootstrap._state(root), "live")

    def test_render_blueprint_is_free_fail_closed_preview(self) -> None:
        text = BLUEPRINT.read_text(encoding="utf-8-sig")
        for required in (
            "type: web",
            "name: cbi-v61-preview",
            "runtime: docker",
            "region: singapore",
            "plan: free",
            "dockerfilePath: ./deploy/cloud/Dockerfile",
            "dockerCommand: python -B -Xutf8 mcp/render_bootstrap.py",
            "autoDeployTrigger: checksPass",
            "healthCheckPath: /healthz",
            "CBI_RENDER_LIVE_ROOT",
            "value: /var/lib/cbi/live",
            "CBI_SESSION_ROOT",
            "value: /var/lib/cbi/live/sessions",
            "CBI_BACKUP_ROOT",
            "value: /var/lib/cbi/live/backups-v61",
            "CBI_REMOTE_PUBLIC_BASE_URL",
            "value: https://cbi-v61-preview.onrender.com",
            "CBI_REMOTE_AUTH_MODE",
            "value: bearer",
            "CBI_REMOTE_BEARER_TOKEN",
            "sync: false",
            "CBI_REMOTE_GITHUB_ALLOWED_LOGINS",
            "value: Scorp96",
        ):
            self.assertIn(required, text)
        self.assertNotIn("disk:", text)
        self.assertNotIn("mountPath:", text)
        self.assertNotIn("sizeGB:", text)
        self.assertNotIn("generateValue: true", text)
        self.assertNotIn("CBI_REMOTE_AUTH_MODE\n        value: none", text)

    def test_docker_image_supports_render_ssh_without_root_runtime(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8-sig")
        self.assertIn("--shell /bin/bash cbi", text)
        self.assertIn("/home/cbi/.ssh", text)
        self.assertIn("chmod 0700 /home/cbi/.ssh", text)
        self.assertIn("USER cbi", text)
        self.assertNotIn("ENV CBI_REMOTE_PORT=", text)
        self.assertIn("os.environ.get('PORT')", text)


if __name__ == "__main__":
    unittest.main()
