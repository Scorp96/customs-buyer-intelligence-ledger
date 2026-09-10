from __future__ import annotations

from pathlib import Path
import unittest


INSTALLER = Path("scripts/install_astra_worker.ps1")


class ServicePythonContractTests(unittest.TestCase):
    def test_service_python_is_machine_scope_stable_311_x64(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        lowered = text.lower()

        self.assertIn("[string]$pythonexecutable", lowered)
        self.assertIn("$env:programfiles", lowered)
        self.assertIn("python311", lowered)
        self.assertNotIn("get-command python.exe", lowered)
        self.assertNotIn("get-command python -erroraction", lowered)

        self.assertIn("resolve-path -literalpath $pythonexecutable", lowered)
        self.assertIn("startswith", lowered)
        self.assertIn("program files", lowered)

        self.assertIn("sys.version_info.major", lowered)
        self.assertIn("sys.version_info.minor", lowered)
        self.assertIn("sys.version_info.releaselevel", lowered)
        self.assertIn("struct.calcsize", lowered)
        self.assertIn("3.11", lowered)
        self.assertIn("final", lowered)
        self.assertIn("64", lowered)


if __name__ == "__main__":
    unittest.main()
