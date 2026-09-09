from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp import server_v61 as adapter


class MutationWalAuditMcpTests(unittest.TestCase):
    def _descriptor(self) -> dict:
        matches = [
            item
            for item in adapter._server.tool_descriptors()
            if isinstance(item, dict) and item.get("name") == "get_mutation_wal_audit"
        ]
        self.assertEqual(len(matches), 1, "WAL audit must be exposed exactly once on the active MCP surface")
        return matches[0]

    def test_descriptor_is_read_only_bounded_and_has_no_idempotency_contract(self) -> None:
        tool = self._descriptor()
        self.assertIn("read-only", str(tool.get("description") or "").lower())
        schema = tool.get("inputSchema")
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema.get("type"), "object")
        self.assertIs(schema.get("additionalProperties"), False)
        props = schema.get("properties") or {}
        self.assertEqual(props["status"]["enum"], ["COMMITTED_ERROR", "COMMITTED"])
        self.assertEqual(props["status"].get("default"), "COMMITTED_ERROR")
        self.assertEqual(props["limit"].get("minimum"), 1)
        self.assertEqual(props["limit"].get("maximum"), 500)
        self.assertEqual(props["limit"].get("default"), 100)
        self.assertNotIn("idempotency_key", props)
        self.assertNotIn("expected_state_version", props)
        self.assertNotIn("get_mutation_wal_audit", adapter._MUTATING_TOOLS)

    def test_active_handler_is_direct_read_only_audit_handler(self) -> None:
        handler = adapter._server.TOOL_HANDLERS.get("get_mutation_wal_audit")
        self.assertIs(handler, adapter._mutation_wal_audit)
        with tempfile.TemporaryDirectory(prefix="cbi-v64-wal-mcp-") as td:
            root = Path(td)
            before = sorted(root.iterdir())
            with mock.patch.object(adapter, "_journal_path", return_value=root):
                result = handler({})
            after = sorted(root.iterdir())
        self.assertEqual(before, after)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["count"], 0)

    def test_descriptor_survives_v63_surface_composition(self) -> None:
        names = [
            str(item.get("name") or "")
            for item in adapter._server.tool_descriptors()
            if isinstance(item, dict)
        ]
        self.assertEqual(names.count("get_mutation_wal_audit"), 1)
        self.assertIn("get_product_profiles", names, "v6.3 tool composition must remain intact")


if __name__ == "__main__":
    unittest.main()
