from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "mcp" / "server_v61_remote.py"
COMPOSE = ROOT / "deploy" / "cloud" / "docker-compose.yml"
DOCKERIGNORE = ROOT / ".dockerignore"
EXPORTER = ROOT / "scripts" / "export_cloud_runtime_bundle.py"
IMPORTER = ROOT / "scripts" / "import_cloud_runtime_bundle.py"


class RemoteEntrypointRootBindingTests(unittest.TestCase):
    def test_remote_entrypoint_requires_explicit_session_root_before_production_import(self) -> None:
        text = ENTRY.read_text(encoding="utf-8-sig")
        guard = text.index("_EXPECTED_ROOT = _require_explicit_durable_root()")
        production_import = text.index("from mcp import server_v61_backup_recovery as _production")
        self.assertLess(guard, production_import)
        self.assertIn('os.environ.get("CBI_SESSION_ROOT")', text)
        self.assertIn("CBI_SESSION_ROOT is required for remote production startup", text)
        self.assertIn("CBI_SESSION_ROOT must be an absolute path", text)

    def test_remote_entrypoint_reuses_accepted_backup_recovery_stack(self) -> None:
        text = ENTRY.read_text(encoding="utf-8-sig")
        self.assertIn("server_v61_backup_recovery", text)
        self.assertIn("_production._RUNTIME", text)
        self.assertIn("_production._v61._server.handle", text)
        self.assertNotIn("UnifiedRuntime(", text)

    def test_compose_binds_only_loopback_by_default(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8-sig")
        self.assertIn('127.0.0.1:${CBI_LOOPBACK_PORT:-8787}:8787', text)
        self.assertIn("CBI_REMOTE_AUTH_MODE", text)
        self.assertIn("CBI_REMOTE_BEARER_TOKEN", text)
        self.assertIn("read_only: true", text)
        self.assertIn("no-new-privileges:true", text)
        self.assertIn("cap_drop:", text)

    def test_docker_context_excludes_private_runtime_material(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8-sig")
        required = {
            "private-golden/",
            "private-acceptance/",
            ".cbi-private-golden*.json",
            "CBI_Cloud_Runtime_Export_*.tar.gz",
            "cbi-cloud-runtime/",
            ".env",
            "*.pem",
            "*.key",
            ".git",
        }
        actual = {line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")}
        self.assertTrue(required.issubset(actual), sorted(required - actual))

    def test_export_has_no_warning_bypass_and_checks_source_quiescence(self) -> None:
        text = EXPORTER.read_text(encoding="utf-8-sig")
        self.assertNotIn("allow-snapshot-warnings", text)
        self.assertIn("CLOUD_MIGRATION_EXPORT_PRE_ARCHIVE_CHECK", text)
        self.assertIn("CLOUD_MIGRATION_EXPORT_POST_ARCHIVE_CHECK", text)
        self.assertIn("source_stable_through_export", text)
        self.assertIn("output.unlink()", text)

    def test_import_requires_trusted_archive_hash_and_has_no_health_bypass(self) -> None:
        text = IMPORTER.read_text(encoding="utf-8-sig")
        self.assertIn('"--expected-sha256"', text)
        self.assertIn("required=True", text)
        self.assertIn("hmac.compare_digest", text)
        self.assertNotIn("skip-runtime-health", text)
        self.assertIn("CLOUD_IMPORT_BASELINE", text)
        self.assertIn("validate_snapshot", text)
        self.assertIn("duplicate archive member forbidden", text)


if __name__ == "__main__":
    unittest.main()
