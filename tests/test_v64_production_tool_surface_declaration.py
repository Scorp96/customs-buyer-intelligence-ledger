from __future__ import annotations

import importlib
import unittest

from mcp import server_v61 as adapter
from unified_runtime import CBI_MCP_TOOL_NAMES
from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors


class ProductionToolSurfaceDeclarationTests(unittest.TestCase):
    def _adapter_names(self) -> tuple[str, ...]:
        try:
            module = importlib.import_module("unified_runtime.production_tool_surface_v64")
        except ModuleNotFoundError:
            self.fail("v6.4 production adapter tool declaration module must exist")
        names = getattr(module, "V64_PRODUCTION_ADAPTER_TOOL_NAMES", None)
        self.assertIsInstance(names, tuple)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(isinstance(name, str) and name for name in names))
        return names

    def test_wal_audit_is_adapter_only_not_core_runtime_tool(self) -> None:
        adapter_names = self._adapter_names()
        self.assertIn("get_mutation_wal_audit", adapter_names)
        self.assertNotIn("get_mutation_wal_audit", CBI_MCP_TOOL_NAMES)

    def test_declared_production_surface_matches_active_composed_surface(self) -> None:
        declared = set(CBI_MCP_TOOL_NAMES)
        declared.update(
            str(item.get("name") or "")
            for item in build_v63_tool_descriptors()
            if isinstance(item, dict) and str(item.get("name") or "")
        )
        declared.update(self._adapter_names())
        active = {
            str(item.get("name") or "")
            for item in adapter._server.tool_descriptors()
            if isinstance(item, dict) and str(item.get("name") or "")
        }
        self.assertEqual(declared, active)

    def test_every_adapter_only_name_has_a_direct_handler(self) -> None:
        for name in self._adapter_names():
            with self.subTest(name=name):
                self.assertIn(name, adapter._server.TOOL_HANDLERS)
                self.assertNotIn(name, adapter._MUTATING_TOOLS)


if __name__ == "__main__":
    unittest.main()
