import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_v63_release_evidence_assembler import V63ReleaseEvidenceAssemblerTests


class V63ReleaseEvidenceCliTests(unittest.TestCase):
    def _bundle(self):
        helper = V63ReleaseEvidenceAssemblerTests()
        return helper._bundle()

    def _run(self, bundle):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "release-evidence.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            return subprocess.run(
                [sys.executable, "scripts/run_v63_release_evidence_gate.py", "--evidence", str(path)],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_complete_source_bound_bundle_exits_zero(self):
        proc = self._run(self._bundle())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["production_ready"])
        self.assertEqual(result["status"], "PRODUCTION_READY")

    def test_missing_live_recovery_report_exits_nonzero(self):
        bundle = self._bundle()
        bundle.pop("recovery_overlay_acceptance_report")
        proc = self._run(bundle)
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["production_ready"])
        self.assertIn("V63_LIVE_RECOVERY_OVERLAY_ACCEPTANCE_NOT_VERIFIED", result["production_gate"]["blockers"])

    def test_caller_boolean_cannot_override_missing_render_report(self):
        bundle = self._bundle()
        bundle.pop("render_deploy_evidence_report")
        bundle["render_deploy_verified"] = True
        proc = self._run(bundle)
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["production_ready"])
        self.assertIn("RENDER_DEPLOY_NOT_VERIFIED", result["production_gate"]["blockers"])


if __name__ == "__main__": unittest.main()
