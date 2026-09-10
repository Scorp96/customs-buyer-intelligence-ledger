import tempfile
import unittest
from pathlib import Path

from unified_runtime.adapter_source_probe_v63 import inspect_production_adapter_structure
from unified_runtime.mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES


BASE_SERVER = '''
_MUTATING_TOOLS = {
    "append_peer_discovery",
    "promote_anchor",
    "resolve_or_create_account",
    "append_information_record",
}

TOOL_DEFINITIONS = [
    {"name": "append_peer_discovery", "inputSchema": {"type": "object"}},
    {"name": "promote_anchor", "inputSchema": {"type": "object"}},
    {"name": "resolve_or_create_account", "inputSchema": {"type": "object"}},
    {"name": "append_information_record", "inputSchema": {"type": "object"}},
]

def _invoke_mutation(tool_name, handler, arguments):
    return handler(arguments)

def _peer_handler(arguments):
    return _invoke_mutation("append_peer_discovery", runtime.append_peer_discovery, arguments)

def _promote_handler(arguments):
    return _invoke_mutation("promote_anchor", runtime.promote_anchor, arguments)

def _canonical_handler(arguments):
    return _invoke_mutation("resolve_or_create_account", runtime.resolve_or_create_account, arguments)

def _info_handler(arguments):
    return _invoke_mutation("append_information_record", runtime.append_information_record, arguments)

HANDLERS = {
    "append_peer_discovery": _peer_handler,
    "promote_anchor": _promote_handler,
    "resolve_or_create_account": _canonical_handler,
    "append_information_record": _info_handler,
}
'''


class V63AdapterSourceProbeTests(unittest.TestCase):
    def _repo(self, root: Path, source: str = BASE_SERVER) -> Path:
        repo = root / "repo"
        (repo / "mcp").mkdir(parents=True)
        (repo / "mcp" / "server_v61.py").write_text(source, encoding="utf-8")
        (repo / "mcp" / "server_v61_backup_recovery.py").write_text(
            'from .server_v61 import *\n', encoding='utf-8'
        )
        (repo / ".mcp.json").write_text(
            '{"command":"python mcp/server_v61_backup_recovery.py --stdio"}\n', encoding='utf-8'
        )
        return repo

    def test_detects_invoke_mutation_registry_and_precedent_handlers(self):
        with tempfile.TemporaryDirectory() as td:
            result = inspect_production_adapter_structure(self._repo(Path(td)))
            self.assertTrue(result["python_ast_valid"])
            self.assertTrue(result["invoke_mutation_present"])
            self.assertEqual(result["invoke_mutation_signature"], ["tool_name", "handler", "arguments"])
            self.assertIn("_MUTATING_TOOLS", result["mutation_registry_candidates"])
            self.assertEqual(
                set(result["precedent_handler_map"]),
                {
                    "append_peer_discovery",
                    "promote_anchor",
                    "resolve_or_create_account",
                    "append_information_record",
                },
            )
            self.assertEqual(result["runtime_object_candidates"], ["runtime"])
            self.assertTrue(result["runtime_object_proven"])
            self.assertTrue(result["safe_for_adapter_codegen"])

    def test_missing_precedent_handler_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE_SERVER.replace(
                'def _info_handler(arguments):\n    return _invoke_mutation("append_information_record", runtime.append_information_record, arguments)\n',
                '',
            )
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertFalse(result["safe_for_adapter_codegen"])
            self.assertIn("PRECEDENT_HANDLER_MAPPING_INCOMPLETE", result["blockers"])

    def test_ambiguous_mutation_registry_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE_SERVER + '\nOTHER_TOOLS = {"append_peer_discovery", "promote_anchor", "resolve_or_create_account", "append_information_record"}\n'
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertFalse(result["safe_for_adapter_codegen"])
            self.assertIn("MUTATION_REGISTRY_AMBIGUOUS", result["blockers"])

    def test_syntax_error_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            result = inspect_production_adapter_structure(self._repo(Path(td), "def broken(:\n"))
            self.assertFalse(result["python_ast_valid"])
            self.assertFalse(result["safe_for_adapter_codegen"])
            self.assertIn("PRODUCTION_ADAPTER_AST_INVALID", result["blockers"])


    def test_detects_literal_tool_and_dispatch_registries(self):
        with tempfile.TemporaryDirectory() as td:
            result = inspect_production_adapter_structure(self._repo(Path(td)))
            self.assertEqual(result["mcp_tool_registry_candidates"], ["TOOL_DEFINITIONS"])
            self.assertEqual(result["mcp_dispatch_registry_candidates"], ["HANDLERS"])
            self.assertTrue(result["mcp_tool_registry_proven"])
            self.assertTrue(result["mcp_dispatch_registry_proven"])
            self.assertTrue(result["safe_for_adapter_codegen"])

    def test_missing_tool_descriptor_registry_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            start = BASE_SERVER.index("TOOL_DEFINITIONS = [")
            end = BASE_SERVER.index("\n\ndef _invoke_mutation", start)
            source = BASE_SERVER[:start] + "TOOL_DEFINITIONS = build_tools()\n" + BASE_SERVER[end:]
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertFalse(result["safe_for_adapter_codegen"])
            self.assertIn("MCP_TOOL_REGISTRY_NOT_PROVEN", result["blockers"])

    def test_missing_dispatch_registry_blocks_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            start = BASE_SERVER.index("HANDLERS = {")
            source = BASE_SERVER[:start] + "HANDLERS = build_handlers()\n"
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertFalse(result["safe_for_adapter_codegen"])
            self.assertIn("MCP_DISPATCH_REGISTRY_NOT_PROVEN", result["blockers"])

    def test_ambiguous_mcp_registries_block_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE_SERVER + "\nOTHER_TOOL_DEFINITIONS = TOOL_DEFINITIONS\n"
            # assignment-by-name alias is intentionally not accepted as a literal registry.
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertTrue(result["safe_for_adapter_codegen"])
            source2 = BASE_SERVER + "\nOTHER_TOOLS = [\n" + \
                "    {\"name\": \"append_peer_discovery\", \"inputSchema\": {}},\n" + \
                "    {\"name\": \"promote_anchor\", \"inputSchema\": {}},\n" + \
                "    {\"name\": \"resolve_or_create_account\", \"inputSchema\": {}},\n" + \
                "    {\"name\": \"append_information_record\", \"inputSchema\": {}},\n]\n"
            other = Path(td) / "other"
            result2 = inspect_production_adapter_structure(self._repo(other, source2))
            self.assertFalse(result2["safe_for_adapter_codegen"])
            self.assertIn("MCP_TOOL_REGISTRY_AMBIGUOUS", result2["blockers"])

    def test_v63_handlers_require_exact_runtime_targets(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE_SERVER + '\n_MUTATING_TOOLS_V63 = {"append_candidate_discovery", "create_product_opportunity", "promote_opportunity_anchor"}\n\ndef _candidate_handler(arguments):\n    return _invoke_mutation("append_candidate_discovery", runtime.append_candidate_discovery, arguments)\n\ndef _opportunity_handler(arguments):\n    return _invoke_mutation("create_product_opportunity", runtime.create_product_opportunity, arguments)\n\ndef _anchor_handler(arguments):\n    return _invoke_mutation("promote_opportunity_anchor", runtime.promote_opportunity_anchor, arguments)\n'
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertEqual(
                set(result["v63_handler_map"]),
                {"append_candidate_discovery", "create_product_opportunity", "promote_opportunity_anchor"},
            )
            self.assertTrue(result["v63_handler_binding_complete"])

    def test_full_v63_tool_surface_requires_descriptors_dispatch_and_direct_read_only_handlers(self):
        with tempfile.TemporaryDirectory() as td:
            descriptors = "\n".join(
                f"    {{'name': {name!r}, 'inputSchema': {{'type':'object'}}}},"
                for name in (*V63_READ_ONLY_TOOL_NAMES, *V63_MUTATION_TOOL_NAMES)
            )
            read_handlers = ""
            dispatch_entries = ""
            for name in V63_READ_ONLY_TOOL_NAMES:
                handler = f"_v63_ro_{name}"
                read_handlers += f"\ndef {handler}(arguments):\n    return runtime.{name}(arguments)\n"
                dispatch_entries += f"    {name!r}: {handler},\n"
            mutation_handlers = (
                "\ndef _candidate_handler(arguments):\n    return _invoke_mutation('append_candidate_discovery', runtime.append_candidate_discovery, arguments)\n"
                "def _opportunity_handler(arguments):\n    return _invoke_mutation('create_product_opportunity', runtime.create_product_opportunity, arguments)\n"
                "def _anchor_handler(arguments):\n    return _invoke_mutation('promote_opportunity_anchor', runtime.promote_opportunity_anchor, arguments)\n"
            )
            dispatch_entries += (
                "    'append_candidate_discovery': _candidate_handler,\n"
                "    'create_product_opportunity': _opportunity_handler,\n"
                "    'promote_opportunity_anchor': _anchor_handler,\n"
            )
            source = BASE_SERVER.replace(
                "]\n\ndef _invoke_mutation",
                descriptors + "\n]\n\ndef _invoke_mutation",
                1,
            )
            source += mutation_handlers + read_handlers
            # replace dispatch with an expanded literal registry.
            start = source.index("HANDLERS = {")
            end = source.index("}\n", start) + 2
            source = source[:start] + "HANDLERS = {\n" + (
                "    'append_peer_discovery': _peer_handler,\n"
                "    'promote_anchor': _promote_handler,\n"
                "    'resolve_or_create_account': _canonical_handler,\n"
                "    'append_information_record': _info_handler,\n"
            ) + dispatch_entries + "}\n" + source[end:]
            # mutation inventory must include all durable v6.3 tools.
            source += "\nV63_MUTATING_TOOLS = " + repr(set(V63_MUTATION_TOOL_NAMES)) + "\n"
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertTrue(result["v63_handler_binding_complete"])
            self.assertTrue(result["v63_tool_descriptor_complete"])
            self.assertTrue(result["v63_dispatch_binding_complete"])
            self.assertTrue(result["v63_read_only_handler_binding_complete"])
            self.assertTrue(result["v63_tool_surface_complete"])

    def test_wrong_v63_runtime_target_blocks_binding_complete(self):
        with tempfile.TemporaryDirectory() as td:
            source = BASE_SERVER + '\ndef _candidate_handler(arguments):\n    return _invoke_mutation("append_candidate_discovery", runtime.append_peer_discovery, arguments)\n'
            result = inspect_production_adapter_structure(self._repo(Path(td), source))
            self.assertFalse(result["v63_handler_binding_complete"])
            self.assertIn("V63_HANDLER_BINDING_INCOMPLETE", result["postpatch_blockers"])


if __name__ == "__main__":
    unittest.main()

DELEGATED_SERVER = '''\
from mcp import server as _server
_MUTATING_TOOLS = {"append_peer_discovery", "promote_anchor", "resolve_or_create_account", "append_information_record"}
_ORIGINAL_TOOL_DESCRIPTORS = _server.tool_descriptors
_ORIGINAL_HANDLERS = dict(_server.TOOL_HANDLERS)

def _invoke_mutation(tool_name, handler, arguments):
    # PREPARED COMMITTED MUTATION_RECONCILIATION_REQUIRED request_sha256
    return handler(arguments)

def _wrap_handler(tool_name, handler):
    def wrapped(arguments):
        return _invoke_mutation(tool_name, handler, arguments)
    return wrapped

def hardened_tool_descriptors():
    return _ORIGINAL_TOOL_DESCRIPTORS()

_server.tool_descriptors = hardened_tool_descriptors
for _name in _MUTATING_TOOLS:
    if _name in _ORIGINAL_HANDLERS:
        _server.TOOL_HANDLERS[_name] = _wrap_handler(_name, _ORIGINAL_HANDLERS[_name])

def main():
    return _server.main()
'''


class V63DelegatedAdapterSourceProbeTests(unittest.TestCase):
    def _repo(self, root: Path, source: str = DELEGATED_SERVER) -> Path:
        (root / 'mcp').mkdir(parents=True)
        (root / 'mcp' / 'server_v61.py').write_text(source, encoding='utf-8')
        return root

    def test_delegated_production_adapter_is_codegen_safe(self):
        with tempfile.TemporaryDirectory() as td:
            result = inspect_production_adapter_structure(self._repo(Path(td)))
            self.assertTrue(result['safe_for_adapter_codegen'])
            self.assertEqual(result['adapter_codegen_mode'], 'DELEGATED_SERVER_OVERLAY')
            self.assertEqual(result['mcp_tool_registry_candidates'], ['_server.tool_descriptors'])
            self.assertEqual(result['mcp_dispatch_registry_candidates'], ['_server.TOOL_HANDLERS'])
            self.assertEqual(result['runtime_object_candidates'], ['_server.RUNTIME'])
            self.assertEqual(result['blockers'], [])
            for tool in ('append_peer_discovery','promote_anchor','resolve_or_create_account','append_information_record'):
                self.assertIn(tool, result['precedent_handler_map'])

    def test_incomplete_delegation_does_not_bypass_literal_guards(self):
        bad = DELEGATED_SERVER.replace('_server.tool_descriptors = hardened_tool_descriptors\n','')
        with tempfile.TemporaryDirectory() as td:
            result = inspect_production_adapter_structure(self._repo(Path(td), bad))
            self.assertFalse(result['safe_for_adapter_codegen'])
            self.assertNotEqual(result.get('adapter_codegen_mode'), 'DELEGATED_SERVER_OVERLAY')
            self.assertIn('MCP_TOOL_REGISTRY_NOT_PROVEN', result['blockers'])
