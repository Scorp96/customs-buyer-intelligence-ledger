from __future__ import annotations

import ast
import unittest
from pathlib import Path


class AuthoritativeSourceEvidenceRemoteWiringTest(unittest.TestCase):
    def test_remote_entrypoint_installs_operator_read_tool_after_persistence_binding(self):
        path = Path(__file__).resolve().parents[1] / "mcp" / "server_v61_remote.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported = False
        install_calls: list[ast.Call] = []
        persistence_assign_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "mcp.authoritative_source_evidence_v64":
                imported = any(alias.name == "install_remote_authoritative_source_evidence_tool" for alias in node.names)
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "_PERSISTENCE" for target in node.targets):
                    persistence_assign_line = node.lineno
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "install_remote_authoritative_source_evidence_tool":
                install_calls.append(node)

        self.assertTrue(imported)
        self.assertIsNotNone(persistence_assign_line)
        self.assertEqual(len(install_calls), 1)
        call = install_calls[0]
        self.assertGreater(call.lineno, persistence_assign_line)
        keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}
        self.assertEqual(keywords.get("server_module"), "_production._v61._server")
        self.assertEqual(keywords.get("persistence"), "_PERSISTENCE")
        self.assertEqual(keywords.get("runtime"), "_RUNTIME")
        self.assertEqual(keywords.get("live_root"), "_LIVE_ROOT")


if __name__ == "__main__":
    unittest.main()
