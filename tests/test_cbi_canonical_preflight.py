from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "cbi_canonical_preflight.py"


class CbiCanonicalPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-canonical-preflight-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.input_path = self.root / "buyer.json"
        self.input_record = {
            "数据源": "美国(进口)",
            "日期": "2026-08-17",
            "主单号": "SYNTH-MBL-PREFLIGHT",
            "分单号": "SYNTH-HBL-PREFLIGHT",
            "供应商": "Synthetic Supplier Ltd",
            "采购商": "Synthetic Existing Buyer LLC",
            "采购商地址": "1111 Example Dr San Bruno, CA 94066",
            "产品": "Synthetic PVC Foam Sheet",
        }
        self.input_path.write_text(
            json.dumps(self.input_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_preflight(self, *arguments: str) -> tuple[int, dict]:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                "-Xutf8",
                str(PREFLIGHT),
                "--session-root",
                str(self.session_root),
                *arguments,
                str(self.input_path),
            ],
            cwd=str(ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"preflight emitted invalid JSON. rc={proc.returncode} "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ) from exc
        return proc.returncode, payload

    @staticmethod
    def tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
        if not root.exists():
            return {}
        result: dict[str, tuple[int, str]] = {}
        for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            result[str(path.relative_to(root))] = (
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
        return result

    def test_empty_runtime_preflight_is_not_found_and_creates_nothing(self) -> None:
        self.assertFalse(self.session_root.exists())
        code, payload = self.run_preflight()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["schema"], "cbi.canonical-preflight.v1")
        self.assertEqual(payload["status"], "NOT_FOUND")
        self.assertEqual(
            payload["recommendation"],
            "NO_RUNTIME_MATCH_CHECK_CRM_BEFORE_CREATE",
        )
        self.assertFalse(payload["runtime_mutation_performed"])
        self.assertFalse(payload["wal_mutation_performed"])
        self.assertFalse(payload["persistent_write_performed"])
        self.assertTrue(payload["read_set_unchanged"])
        self.assertTrue(payload["buyer_country_resolution"]["inferred"])
        self.assertFalse(self.session_root.exists())

    def test_existing_requested_account_matches_byte_for_byte_read_only(self) -> None:
        runtime = UnifiedRuntime(self.session_root)
        created = runtime.resolve_or_create_account(
            {
                "candidate": {
                    "name": "Synthetic Existing Buyer LLC",
                    "country": "United States",
                    "address": "1111 Example Dr San Bruno, CA 94066",
                },
                "requested_account_id": "C157",
                "create_if_missing": True,
            }
        )
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(created["match"]["account_id"], "C157")

        before = self.tree_snapshot(self.session_root)
        code, payload = self.run_preflight("--requested-account-id", "C157")
        after = self.tree_snapshot(self.session_root)

        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "MATCHED")
        self.assertEqual(
            payload["canonical_resolution"]["match"]["account_id"],
            "C157",
        )
        self.assertIn(
            "EXACT_ACCOUNT_ID",
            payload["canonical_resolution"]["match"]["reasons"],
        )
        self.assertEqual(
            payload["recommendation"],
            "EXISTING_RUNTIME_ACCOUNT_MATCHED",
        )
        self.assertTrue(payload["read_set_unchanged"])
        self.assertFalse(payload["runtime_mutation_performed"])
        self.assertFalse(payload["wal_mutation_performed"])
        self.assertFalse(payload["persistent_write_performed"])
        self.assertEqual(before, after)

    def test_requested_missing_id_does_not_allocate_or_write(self) -> None:
        runtime = UnifiedRuntime(self.session_root)
        runtime.resolve_or_create_account(
            {
                "candidate": {
                    "name": "Different Existing Buyer LLC",
                    "country": "United States",
                    "address": "200 Different Ave, Denver, CO 80202",
                },
                "requested_account_id": "C001",
                "create_if_missing": True,
            }
        )
        before = self.tree_snapshot(self.session_root)

        code, payload = self.run_preflight("--requested-account-id", "C157")
        after = self.tree_snapshot(self.session_root)

        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "NOT_FOUND")
        self.assertEqual(
            payload["recommendation"],
            "REQUESTED_ID_NOT_IN_RUNTIME_RECONCILE_BEFORE_COMMIT",
        )
        self.assertTrue(payload["read_set_unchanged"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
