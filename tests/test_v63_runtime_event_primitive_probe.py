import tempfile
import unittest
from pathlib import Path

from unified_runtime.runtime_event_primitive_probe_v63 import probe_v63_runtime_event_primitives


class V63RuntimeEventPrimitiveProbeTests(unittest.TestCase):
    def _repo(self, source: str):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "unified_runtime").mkdir()
        (root / "unified_runtime" / "v6.py").write_text(source, encoding="utf-8")
        return td, root

    def test_shared_existing_append_primitive_is_discovered_without_hardcoded_name(self):
        td, root = self._repo('''\
class V6RuntimeMixin:
    def append_peer_discovery(self, arguments):
        payload = {"peer": arguments}
        return self.store.append(arguments["investigation_id"], "V6_PEER_DISCOVERED", payload)

    def promote_anchor(self, arguments):
        payload = {"promotion": arguments}
        return self.store.append(arguments["investigation_id"], "V6_ANCHOR_PROMOTED", payload)

    def append_information_record(self, arguments):
        return self.store.append(arguments["investigation_id"], "INFORMATION_RECORD_APPENDED", arguments)
''')
        self.addCleanup(td.cleanup)
        result = probe_v63_runtime_event_primitives(root)
        self.assertEqual(result["status"], "SHARED_DURABLE_PRIMITIVE_PROVEN")
        self.assertEqual(result["shared_primitive"], "self.store.append")
        self.assertEqual(
            set(result["precedent_methods"]),
            {"append_peer_discovery", "promote_anchor", "append_information_record"},
        )
        self.assertEqual(result["event_literals"]["append_peer_discovery"], ["V6_PEER_DISCOVERED"])
        self.assertFalse(result["backend_codegen_allowed"])
        self.assertIn("CORRELATION_PROPAGATION_NOT_YET_PROVEN", result["remaining_blockers"])

    def test_different_mutation_primitives_fail_closed(self):
        td, root = self._repo('''\
class V6RuntimeMixin:
    def append_peer_discovery(self, arguments):
        return self.store.append(arguments["investigation_id"], "V6_PEER_DISCOVERED", arguments)
    def promote_anchor(self, arguments):
        return self.log.write(arguments["investigation_id"], "V6_ANCHOR_PROMOTED", arguments)
    def append_information_record(self, arguments):
        return self.store.append(arguments["investigation_id"], "INFORMATION_RECORD_APPENDED", arguments)
''')
        self.addCleanup(td.cleanup)
        result = probe_v63_runtime_event_primitives(root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("NO_UNIQUE_SHARED_DURABLE_PRIMITIVE", result["blockers"])

    def test_missing_precedent_method_or_runtime_source_fails_closed(self):
        td, root = self._repo('''\
class V6RuntimeMixin:
    def append_peer_discovery(self, arguments):
        return self.store.append(arguments["investigation_id"], "V6_PEER_DISCOVERED", arguments)
''')
        self.addCleanup(td.cleanup)
        result = probe_v63_runtime_event_primitives(root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("PRECEDENT_METHODS_INCOMPLETE", result["blockers"])

        with tempfile.TemporaryDirectory() as empty:
            result = probe_v63_runtime_event_primitives(Path(empty))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("RUNTIME_SOURCE_NOT_FOUND", result["blockers"])

    def test_helper_wrapped_shared_primitive_is_not_falsely_claimed(self):
        td, root = self._repo('''\
class V6RuntimeMixin:
    def append_peer_discovery(self, arguments):
        return self._append_peer_event(arguments)
    def promote_anchor(self, arguments):
        return self._append_promotion_event(arguments)
    def append_information_record(self, arguments):
        return self._append_information_event(arguments)
''')
        self.addCleanup(td.cleanup)
        result = probe_v63_runtime_event_primitives(root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("NO_UNIQUE_SHARED_DURABLE_PRIMITIVE", result["blockers"])
        self.assertFalse(result["backend_codegen_allowed"])


if __name__ == "__main__":
    unittest.main()
