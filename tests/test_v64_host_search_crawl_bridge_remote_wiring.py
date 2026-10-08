from __future__ import annotations

import ast
import unittest
from pathlib import Path


class HostSearchCrawlBridgeRemoteWiringTests(unittest.TestCase):
    def test_remote_entrypoint_installs_bridge_after_production_server_import(self) -> None:
        path = Path(__file__).resolve().parents[1] / "mcp" / "server_v61_remote.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported = False
        install_calls: list[ast.Call] = []
        runtime_assign_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "mcp.host_search_crawl_bridge_v64":
                imported = any(
                    alias.name == "install_remote_host_search_crawl_bridge_tool"
                    for alias in node.names
                )
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "_RUNTIME" for target in node.targets):
                    runtime_assign_line = node.lineno
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "install_remote_host_search_crawl_bridge_tool"
            ):
                install_calls.append(node)

        self.assertTrue(imported)
        self.assertIsNotNone(runtime_assign_line)
        self.assertEqual(len(install_calls), 1)
        call = install_calls[0]
        self.assertGreater(call.lineno, runtime_assign_line)
        keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}
        self.assertEqual(keywords.get("server_module"), "_production._v61._server")

    def test_health_exposes_bridge_boundary_without_claiming_server_search(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "mcp" / "server_v61_remote.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"host_search_crawl_bridge"', source)
        self.assertIn('"server_performs_web_search": False', source)
        self.assertIn('"durable_mutation_performed": False', source)


if __name__ == "__main__":
    unittest.main()
