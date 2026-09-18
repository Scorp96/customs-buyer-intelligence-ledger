from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "render.v63-acceptance.yaml"


class V63RenderR2AcceptanceBlueprintTests(unittest.TestCase):
    def _source(self) -> str:
        self.assertTrue(
            BLUEPRINT.is_file(),
            "isolated v6.3 Render/R2 acceptance Blueprint is missing",
        )
        return BLUEPRINT.read_text(encoding="utf-8")

    @staticmethod
    def _env_fragment(source: str, key: str) -> str:
        lines = source.splitlines()
        marker = f"- key: {key}"
        start = None
        for index, line in enumerate(lines):
            if line.strip() == marker:
                start = index
                break
        if start is None:
            raise AssertionError(f"Blueprint environment key missing: {key}")
        collected = [lines[start]]
        for line in lines[start + 1 :]:
            if line.strip().startswith("- key:"):
                break
            collected.append(line)
        return "\n".join(collected)

    def test_blueprint_is_feature_only_manual_and_uses_real_bootstrap(self) -> None:
        source = self._source()
        self.assertIn("name: cbi-v63-r2-acceptance-20260903-r01", source)
        self.assertIn("branch: cbi-v6-3-demand-expansion", source)
        self.assertIn("autoDeployTrigger: off", source)
        self.assertIn("runtime: docker", source)
        self.assertIn("dockerCommand: python -B -Xutf8 mcp/render_bootstrap.py", source)
        self.assertIn("healthCheckPath: /healthz", source)
        self.assertIn("plan: free", source)
        self.assertNotIn("plan: 0.5c-512mb", source)
        self.assertNotIn("cbi-v6-cloud-runtime-20260901", source)
        self.assertNotIn("cbi-v61-preview", source)
        self.assertNotIn("disk:", source)
        self.assertNotIn("diskMountPath", source)

    def test_blueprint_is_r2_backed_with_isolated_prefix_and_no_embedded_secrets(self) -> None:
        source = self._source()
        expected_values = {
            "CBI_OBJECT_STORE_MODE": "r2",
            "CBI_OBJECT_STORE_REGION": "auto",
            "CBI_OBJECT_STORE_PREFIX": "cbi-v63-acceptance-20260903-r01",
            "CBI_V63_ACCEPTANCE_PIN_DEPLOYMENT_SHA": '"true"',
            "CBI_REMOTE_AUTH_MODE": "bearer",
            "CBI_REMOTE_PUBLIC_BASE_URL": "https://cbi-v63-r2-acceptance-20260903-r01.onrender.com",
        }
        for key, value in expected_values.items():
            fragment = self._env_fragment(source, key)
            self.assertIn(f"value: {value}", fragment, key)

        for key in {
            "CBI_OBJECT_STORE_ENDPOINT",
            "CBI_OBJECT_STORE_BUCKET",
            "CBI_OBJECT_STORE_ACCESS_KEY_ID",
            "CBI_OBJECT_STORE_SECRET_ACCESS_KEY",
            "CBI_REMOTE_BEARER_TOKEN",
        }:
            fragment = self._env_fragment(source, key)
            self.assertIn("sync: false", fragment, key)
            self.assertNotIn("value:", fragment, key)

        self.assertNotIn("cbi-v61/", source)
        self.assertNotIn("customer", source.casefold())
        self.assertNotIn("idempotency_key", source.casefold())


if __name__ == "__main__":
    unittest.main()
