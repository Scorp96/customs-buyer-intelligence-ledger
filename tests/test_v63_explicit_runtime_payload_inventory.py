from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class V63ExplicitRuntimePayloadInventoryTests(unittest.TestCase):
    def test_payload_inventory_does_not_absorb_existing_production_runtime_files(self) -> None:
        from unified_runtime import production_integration_runner as runner

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "unified_runtime"
            source.mkdir()
            for name in (
                "demand_expansion.py",
                "production_integration_runner.py",
                "research_orchestration_hardening.py",
                "v6.py",
                "core.py",
            ):
                (source / name).write_text("# fixture\n", encoding="utf-8")

            with patch.object(runner, "_source_runtime_root", return_value=source):
                names = [path.name for path in runner._payload_paths()]

        self.assertIn("demand_expansion.py", names)
        self.assertIn("production_integration_runner.py", names)
        self.assertNotIn("research_orchestration_hardening.py", names)
        self.assertNotIn("v6.py", names)
        self.assertNotIn("core.py", names)


if __name__ == "__main__":
    unittest.main()
