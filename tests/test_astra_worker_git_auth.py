from __future__ import annotations

import base64
from pathlib import Path
import shutil
import tempfile
import unittest

from astra_worker.config import RepositoryBinding
from astra_worker.git_workspace import GitWorkspaceManager


@unittest.skipUnless(shutil.which("git"), "Git executable required")
class GitHubGitAuthTests(unittest.TestCase):
    def test_github_https_uses_basic_auth_for_git_smart_http(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binding = RepositoryBinding(
                repository_id="cbi-primary",
                github_repository="Scorp96/customs-buyer-intelligence-ledger",
                expected_origin="https://github.com/Scorp96/customs-buyer-intelligence-ledger.git",
                mirror_root=root / "repos" / "cbi-primary.git",
                allowed_base_refs_exact=("cbi-v6-3-demand-expansion",),
                allowed_base_ref_prefixes=("astra-",),
                ephemeral_branch_prefix="astra-worker/",
            )
            manager = GitWorkspaceManager(
                binding,
                token="unit-test-token",
                git_executable=shutil.which("git") or "git",
            )

            env = manager._git_env()
            count = int(env["GIT_CONFIG_COUNT"])
            config = {
                env[f"GIT_CONFIG_KEY_{index}"]: env[f"GIT_CONFIG_VALUE_{index}"]
                for index in range(count)
            }
            header = config["http.https://github.com/.extraheader"]

            self.assertTrue(header.startswith("AUTHORIZATION: basic "))
            encoded = header.removeprefix("AUTHORIZATION: basic ")
            clear = base64.b64decode(encoded).decode("utf-8")
            self.assertEqual(clear, "x-access-token:unit-test-token")
            self.assertNotIn("Bearer", header)


if __name__ == "__main__":
    unittest.main()
