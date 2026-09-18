from __future__ import annotations

import unittest

from tests.test_v63_render_r2_pvc_acceptance import (
    _FakeAcceptanceClient,
    _FakeReplacementController,
)
from unified_runtime.render_r2_pvc_acceptance_v63 import (
    run_v63_render_r2_pvc_acceptance,
)
from unified_runtime.render_r2_pvc_acceptance_validator_v63 import (
    validate_v63_render_r2_pvc_acceptance,
)


class V63RenderR2ValidatorMigrationBootTests(unittest.TestCase):
    @staticmethod
    def _migration_boot_receipt() -> dict:
        client = _FakeAcceptanceClient()
        controller = _FakeReplacementController(client)
        receipt = run_v63_render_r2_pvc_acceptance(client, controller)

        before_identity = receipt["health_before"]["deployment_identity"]
        before_identity["object_state_schema"] = None
        before_identity["object_state_generation"] = 0
        before_identity["restore_generation"] = None
        before_identity["restore_source"] = "migration_v1"

        before_persistence = receipt["health_before"]["object_store_persistence"]
        before_persistence["generation"] = 0
        before_persistence["archive_format"] = "migration_v1"
        before_persistence["recovery_state_schema"] = None

        receipt["evidence_before"]["archive_format"] = "object_state_v2"
        receipt["evidence_after"]["archive_format"] = "object_state_v2"
        return receipt

    def test_validator_accepts_legacy_migration_boot_after_mutations_upgrade_r2_to_v2(self) -> None:
        receipt = self._migration_boot_receipt()

        result = validate_v63_render_r2_pvc_acceptance(receipt)

        self.assertEqual(result["status"], "VERIFIED", result)
        self.assertEqual(result["blockers"], [], result)
        self.assertEqual(result["verified_mutation_count"], 3)
        self.assertIs(result["production_ready"], False)

    def test_validator_still_blocks_when_pre_replacement_evidence_is_not_v2(self) -> None:
        receipt = self._migration_boot_receipt()
        receipt["evidence_before"]["archive_format"] = "migration_v1"

        result = validate_v63_render_r2_pvc_acceptance(receipt)

        self.assertEqual(result["status"], "BLOCKED", result)
        self.assertIn("R2_EVIDENCE_BEFORE_ARCHIVE_FORMAT_INVALID", result["blockers"])
        self.assertIs(result["production_ready"], False)


if __name__ == "__main__":
    unittest.main()
