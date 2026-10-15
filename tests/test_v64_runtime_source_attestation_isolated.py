"""Synthetic fail-closed regression + real isolated remote-process dispatch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from mcp.runtime_source_attestation_v64 import (
    _ALLOWED, TOOL_NAME, measure_loaded_sources, install_isolated_attestation
)

ROOT = Path(__file__).resolve().parents[1]
PIN = "a" * 40

def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()

class SourceAttestationIsolatedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cbi-source-attest-ci-")
        self.root = Path(self.tmp.name)
        self.loaded = {}
        self.expected = {}
        for index, (module, relative) in enumerate(_ALLOWED.items()):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = ("# SYNTHETIC ONLY %d\n" % index).encode()
            path.write_bytes(data)
            self.loaded[module] = SimpleNamespace(__file__=str(path))
            self.expected[module] = blob(data)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, loaded=None, expected=None, git_commit=PIN):
        return measure_loaded_sources(root=self.root, git_commit=git_commit,
            expected_blobs=self.expected if expected is None else expected,
            loaded=self.loaded if loaded is None else loaded)

    def test_exact_all_modules_match(self):
        r = self.check()
        self.assertEqual(r["status"], "MATCH", r)
        self.assertEqual(r["measurement_count"], len(_ALLOWED))
        self.assertTrue(all(x["result"] == "MATCH" for x in r["measurements"]))
        self.assertFalse(r["external_pin_independence_proven"])

    def test_one_byte_tamper_denied(self):
        module, relative = next(iter(_ALLOWED.items()))
        (self.root / relative).write_bytes(b"# TAMPERED\n")
        r = self.check()
        self.assertIn("MODULE_GIT_BLOB_MISMATCH:"+module, r["blockers"])

    def test_unloaded_module_denied(self):
        module = next(iter(_ALLOWED))
        loaded = dict(self.loaded)
        loaded.pop(module)
        self.assertIn("MODULE_NOT_LOADED:"+module, self.check(loaded=loaded)["blockers"])

    def test_substituted_module_path_denied(self):
        module = next(iter(_ALLOWED))
        wrong = self.root / "other.py"
        wrong.write_bytes(b"untrusted")
        loaded = dict(self.loaded)
        loaded[module] = SimpleNamespace(__file__=str(wrong))
        self.assertIn("MODULE_ORIGIN_MISMATCH:"+module, self.check(loaded=loaded)["blockers"])

    def test_symlink_escape_denied(self):
        module, relative = next(iter(_ALLOWED.items()))
        external = self.root.parent / (self.root.name + "-outside.py")
        external.write_bytes(b"external")
        try:
            p = self.root / relative
            p.unlink()
            p.symlink_to(external)
            self.assertIn("MODULE_ORIGIN_MISMATCH:"+module, self.check()["blockers"])
        finally:
            external.unlink(missing_ok=True)

    def test_missing_hash_is_rejected(self):
        bad = dict(self.expected)
        bad.pop(next(iter(bad)))
        self.assertEqual(self.check(expected=bad)["blockers"], ["EXPECTED_BLOB_INVENTORY_INVALID"])

    def test_invalid_expected_commit_denied(self):
        self.assertEqual(self.check(git_commit="unverified")["blockers"], ["EXPECTED_COMMIT_INVALID"])

    def test_never_returns_raw_source_or_secret(self):
        module, relative = next(iter(_ALLOWED.items()))
        marker = b"NEVER_EXPORT_TEST_SECRET_LITERAL"
        (self.root / relative).write_bytes(marker)
        payload = json.dumps(self.check(), sort_keys=True)
        self.assertNotIn(marker.decode(), payload)
        self.assertNotIn(str(self.root), payload)
        self.assertNotIn("idempotency_key", payload)
        self.assertNotIn("access_key", payload)

class RemoteInProcessOptInTests(unittest.TestCase):
    def run_remote(self, *, enabled=True, pin=True, wrong_commit=False):
        with tempfile.TemporaryDirectory(prefix="cbi-remote-attest-") as temp:
            env = dict(os.environ)
            env.update({
                "CBI_SESSION_ROOT": str(Path(temp) / "sessions"),
                "CBI_HOST_PENDING_ROOT": str(Path(temp) / "host-pending"),
                "CBI_OBJECT_STORE_MODE": "none",
                "CBI_V63_ACCEPTANCE_PIN_DEPLOYMENT_SHA": "true" if pin else "false",
                "CBI_ISOLATED_SOURCE_ATTESTATION": "true" if enabled else "false",
                "RENDER_GIT_COMMIT": PIN,
                "CBI_OBJECT_STORE_SECRET_ACCESS_KEY": "DO_NOT_LOG_THIS_VALUE",
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            code = """
import json
from pathlib import Path
from mcp import server_v61_remote as remote
from mcp.runtime_source_attestation_v64 import TOOL_NAME, _ALLOWED
from mcp.runtime_source_attestation_v64 import _blocked
from mcp.runtime_source_attestation_v64 import hashlib
server = remote._production._v61._server
tools = [v['name'] for v in server.tool_descriptors()]
record = {'registered': TOOL_NAME in tools, 'public': remote._public_health()}
if TOOL_NAME in server.TOOL_HANDLERS:
    def gitblob(content):
        return hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\\x00' + content).hexdigest()
    expected = {name: gitblob((remote.ROOT / path).read_bytes()) for name,path in _ALLOWED.items()}
    supplied = 'b'*40 if """ + ("True" if wrong_commit else "False") + """ else 'a'*40
    result = server.TOOL_HANDLERS[TOOL_NAME]({'expected_git_commit': supplied, 'expected_blobs': expected})
    record['attestation'] = {'status': result['status'], 'blockers': result['blockers'], 'measurements':result.get('measurement_count')}
print(json.dumps(record, sort_keys=True))
"""
            return subprocess.run([sys.executable, "-B", "-Xutf8", "-c", code],
                cwd=ROOT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=40, check=False)

    def test_opt_in_loads_in_real_remote_process(self):
        process = self.run_remote()
        self.assertEqual(process.returncode, 0, process.stderr)
        obj = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertTrue(obj["registered"])
        self.assertEqual(obj["attestation"]["status"], "MATCH", obj["attestation"])
        self.assertEqual(obj["attestation"]["measurements"], len(_ALLOWED))
        self.assertEqual(set(obj["public"]), {"status", "service"})
        self.assertNotIn("DO_NOT_LOG_THIS_VALUE", process.stdout)

    def test_default_disabled_has_no_new_tool(self):
        process = self.run_remote(enabled=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        obj = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertFalse(obj["registered"])
        self.assertNotIn("attestation", obj)

    def test_enable_without_sha_acceptance_pin_is_rejected(self):
        process = self.run_remote(pin=False)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("ISOLATED_SOURCE_ATTESTATION_REQUIRES_DEPLOYMENT_SHA_PIN", process.stderr)

    def test_mismatched_deployment_commit_rejected(self):
        process = self.run_remote(wrong_commit=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        obj = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertEqual(obj["attestation"]["status"], "BLOCKED")
        self.assertEqual(obj["attestation"]["blockers"], ["DEPLOYMENT_GIT_SHA_NOT_PINNED_OR_MISMATCH"])

if __name__ == "__main__":
    unittest.main()
