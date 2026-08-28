from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class V6WindowsPortabilityTests(unittest.TestCase):
    def test_mcp_launcher_discovers_python_dynamically(self) -> None:
        config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual(server["command"], "powershell.exe")
        command = server["args"][-1]
        self.assertIn("Programs\\Python", command)
        self.assertIn(".cache\\codex-runtimes", command)
        self.assertNotIn("C:\\Users\\scorp", command)

    def test_cold_copy_runs_from_utf8_chinese_and_space_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v6-portable-") as temp:
            destination = Path(temp) / "中文 路径" / "customs-buyer-intelligence"
            shutil.copytree(
                PLUGIN_ROOT,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            environment = dict(os.environ)
            environment["CBI_SESSION_ROOT"] = str(Path(temp) / "会话 数据")
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.Popen(
                [sys.executable, "-B", "-Xutf8", str(destination / "mcp" / "server.py"), "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            try:
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write(json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                }) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                self.assertEqual(response["result"]["serverInfo"]["version"], "6.1.0")
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
                process.stdin.flush()
                tools = json.loads(process.stdout.readline())["result"]["tools"]
                self.assertEqual(len(tools), 42)
            finally:
                if process.stdin:
                    process.stdin.close()
                process.terminate()
                process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
