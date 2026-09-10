import copy
import unittest

from tests.test_v63_production_gate import V63ProductionGateTests
from tests.test_v63_release_evidence_assembler import V63ReleaseEvidenceAssemblerTests
from tests.test_v63_render_r2_pvc_acceptance import (
    _FakeAcceptanceClient,
    _FakeReplacementController,
)
from unified_runtime.production_gate_v63 import evaluate_v63_production_gate
from unified_runtime.release_evidence_v63 import evaluate_v63_release_evidence_bundle
from unified_runtime.render_r2_pvc_acceptance_v63 import run_v63_render_r2_pvc_acceptance


class V63ReleaseRenderR2DependencyTests(unittest.TestCase):
    def _render_receipt(self, *, real_render: bool) -> dict:
        client = _FakeAcceptanceClient()
        controller = _FakeReplacementController(client)
        receipt = run_v63_render_r2_pvc_acceptance(client, controller)
        if real_render:
            receipt = copy.deepcopy(receipt)
            receipt["replacement"]["instance_before"] = "dep-render-acceptance-a"
            receipt["replacement"]["instance_after"] = "dep-render-acceptance-b"
            for phase in ("health_before", "health_after"):
                identity = receipt[phase]["deployment_identity"]
                identity["remote_entrypoint"] = "mcp/server_v61_remote.py"
                identity["runtime_entrypoint"] = "mcp/server_v61_backup_recovery.py"
        return receipt

    def _bundle_with_render_receipt(self, *, real_render: bool = True) -> dict:
        helper = V63ReleaseEvidenceAssemblerTests()
        bundle = helper._bundle()
        for key in (
            "render_deploy_verified",
            "r2_restore_verified",
            "real_pvc_acceptance_verified",
            "render_deploy_evidence_report",
            "r2_restore_evidence_report",
            "real_pvc_acceptance_evidence_report",
        ):
            bundle.pop(key, None)
        bundle["render_r2_pvc_acceptance_report"] = self._render_receipt(
            real_render=real_render
        )
        return bundle

    def test_production_gate_uses_single_render_r2_pvc_dependency(self) -> None:
        payload = V63ProductionGateTests().healthy_payload()
        for key in (
            "render_deploy_verified",
            "r2_restore_verified",
            "real_pvc_acceptance_verified",
        ):
            payload.pop(key, None)
        payload["render_r2_pvc_acceptance_verified"] = True

        result = evaluate_v63_production_gate(payload)

        self.assertTrue(result["production_ready"], result)
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["checked_render_r2_pvc_acceptance"])

    def test_production_gate_fails_closed_when_render_r2_pvc_receipt_not_verified(self) -> None:
        payload = V63ProductionGateTests().healthy_payload()
        for key in (
            "render_deploy_verified",
            "r2_restore_verified",
            "real_pvc_acceptance_verified",
        ):
            payload.pop(key, None)
        payload["render_r2_pvc_acceptance_verified"] = False

        result = evaluate_v63_production_gate(payload)

        self.assertFalse(result["production_ready"])
        self.assertIn(
            "V63_RENDER_R2_PVC_ACCEPTANCE_NOT_VERIFIED",
            result["blockers"],
        )

    def test_release_assembler_derives_external_gate_from_render_r2_pvc_receipt(self) -> None:
        result = evaluate_v63_release_evidence_bundle(
            self._bundle_with_render_receipt(real_render=True)
        )

        self.assertTrue(result["production_ready"], result)
        validation = result["component_validations"]["render_r2_pvc_acceptance"]
        self.assertTrue(validation["verified"], validation)
        self.assertTrue(
            result["derived_gate_payload"]["render_r2_pvc_acceptance_verified"]
        )

    def test_release_assembler_rejects_local_mock_receipt_as_real_render_proof(self) -> None:
        result = evaluate_v63_release_evidence_bundle(
            self._bundle_with_render_receipt(real_render=False)
        )

        self.assertFalse(result["production_ready"])
        validation = result["component_validations"]["render_r2_pvc_acceptance"]
        self.assertFalse(validation["verified"])
        self.assertIn(
            "REAL_RENDER_INSTANCE_REPLACEMENT_NOT_PROVEN",
            validation["blockers"],
        )
        self.assertIn(
            "V63_RENDER_R2_PVC_ACCEPTANCE_NOT_VERIFIED",
            result["production_gate"]["blockers"],
        )

    def test_caller_boolean_cannot_replace_missing_render_r2_pvc_receipt(self) -> None:
        bundle = self._bundle_with_render_receipt(real_render=True)
        bundle.pop("render_r2_pvc_acceptance_report")
        bundle["render_r2_pvc_acceptance_verified"] = True

        result = evaluate_v63_release_evidence_bundle(bundle)

        self.assertFalse(result["production_ready"])
        self.assertIn(
            "V63_RENDER_R2_PVC_ACCEPTANCE_NOT_VERIFIED",
            result["production_gate"]["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
