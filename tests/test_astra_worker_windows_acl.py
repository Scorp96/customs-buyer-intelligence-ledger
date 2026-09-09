from __future__ import annotations

import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Windows ACL contract")
class WindowsAclContractTests(unittest.TestCase):
    def _current_user_sid(self) -> str:
        completed = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
        )
        row = next(csv.reader([completed.stdout.strip()]))
        sid = row[1].strip()
        self.assertTrue(sid.startswith("S-1-5-"))
        return sid

    def _icacls(self, path: Path, *args: str) -> None:
        subprocess.run(
            ["icacls.exe", str(path), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_exact_service_system_admin_acl_passes_and_extra_user_grant_fails(self) -> None:
        from astra_worker.windows_security import WindowsSecurityError, verify_worker_acl

        service_sid = self._current_user_sid()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ASTRAWorker"
            root.mkdir()
            self._icacls(root, "/inheritance:r")
            self._icacls(
                root,
                "/grant:r",
                f"*{service_sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            )
            verify_worker_acl(root, service_sid, enforce_programdata=False)

            self._icacls(root, "/grant", "*S-1-5-32-545:(OI)(CI)R")
            with self.assertRaises(WindowsSecurityError):
                verify_worker_acl(root, service_sid, enforce_programdata=False)


if __name__ == "__main__":
    unittest.main()
