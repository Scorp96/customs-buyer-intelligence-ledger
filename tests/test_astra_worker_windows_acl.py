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

    def test_hardener_replaces_preexisting_explicit_aces_across_state_tree(self) -> None:
        import astra_worker.windows_security as windows_security

        hardener = getattr(windows_security, "harden_worker_acl", None)
        self.assertIsNotNone(
            hardener,
            "production ACL hardener must replace preexisting explicit ACEs",
        )

        service_sid = self._current_user_sid()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ASTRAWorker"
            child = root / "repos"
            root.mkdir()
            child.mkdir()
            payload = child / "existing.bin"
            payload.write_bytes(b"existing")

            # Model a pre-existing installation tree that already contains an
            # unrelated explicit grant. /grant:r for the three trusted SIDs does
            # not remove this other trustee, which is the real-host failure mode.
            for current in (root, child, payload):
                self._icacls(current, "/inheritance:r")
                self._icacls(current, "/grant", "*S-1-5-32-545:R")

            hardener(root, service_sid, enforce_programdata=False)
            windows_security.verify_worker_acl(
                root,
                service_sid,
                enforce_programdata=False,
            )


if __name__ == "__main__":
    unittest.main()
