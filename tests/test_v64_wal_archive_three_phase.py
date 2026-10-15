"""Three-phase WAL archival process-crash acceptance (synthetic, offline).

Uses real subprocess os._exit() at each boundary. Production WAL and external
pin registries are never touched; fixture Host pin registry is in a distinct
temporary directory and is NOT a production trusted authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from unified_runtime.core import canonical_json, digest
from unified_runtime.wal_archive_three_phase_v64 import (
    archive_postcommit_three_phase, verify_three_phase_snapshot,
)

class ThreePhaseWALArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-wal-3phase-")
        self.root = Path(self.temp.name)
        self.live = self.root / "live"
        self.snaps = self.root / "snapshots"
        self.pins = self.root / "trusted-pin-fixture"
        for path in (self.live, self.snaps, self.pins):
            path.mkdir()
        self.request_hash = "a" * 64
        self.name = "append_execution_receipt-" + "b" * 64 + ".json"
        self.path = self.live / self.name
        self.result = {"accepted": True, "attempt_id": "SYN-1"}
        self.row = {
            "schema": "cbi.mutation-wal.v6.1",
            "tool": "append_execution_receipt", "status": "COMMITTED",
            "request_sha256": self.request_hash,
            "result": self.result, "result_sha256": digest(self.result),
        }
        self.write_wal()

    def tearDown(self):
        self.temp.cleanup()

    def write_wal(self):
        self.path.write_text(canonical_json(self.row) + "\n", encoding="utf8")

    def pin_path(self, filename=None):
        return self.pins / ((filename or self.name) + ".sha256")

    def writer(self, filename, content_hash):
        with os.fdopen(
            os.open(self.pin_path(filename), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "w", encoding="ascii"
        ) as handle:
            handle.write(content_hash + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def reader(self, filename):
        p = self.pin_path(filename)
        return p.read_text(encoding="ascii").strip() if p.exists() else None

    def archive(self, **kw):
        args = {
            "terminal_wal_path": self.path, "snapshot_root": self.snaps,
            "expected_request_sha256": self.request_hash,
            "trusted_pin_writer": self.writer, "trusted_pin_reader": self.reader,
        }
        args.update(kw)
        return archive_postcommit_three_phase(**args)

    def verify(self):
        return verify_three_phase_snapshot(
            snapshot_root=self.snaps, filename=self.name,
            trusted_pin_reader=self.reader,
        )

    def crash_subprocess(self, phase):
        script = '''
import os, sys
from pathlib import Path
from unified_runtime.wal_archive_three_phase_v64 import archive_postcommit_three_phase
root, phase = Path(sys.argv[1]), sys.argv[2]
filename = "append_execution_receipt-" + "b"*64 + ".json"
pins = root/"trusted-pin-fixture"
def write_pin(filename, checksum):
    p = pins/(filename+".sha256")
    with os.fdopen(os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),"w") as h:
        h.write(checksum+"\\n")
        h.flush()
        os.fsync(h.fileno())
    return True
def read_pin(filename):
    p = pins/(filename+".sha256")
    return p.read_text().strip() if p.exists() else None
def stop_here(at):
    if at == phase:
        os._exit(93)
archive_postcommit_three_phase(
    terminal_wal_path=root/"live"/filename,
    snapshot_root=root/"snapshots",
    expected_request_sha256="a"*64,
    trusted_pin_writer=write_pin,
    trusted_pin_reader=read_pin,
    phase_hook=stop_here,
)
'''
        proc = subprocess.run(
            [sys.executable, "-B", "-Xutf8", "-c", script, str(self.root), phase],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(proc.returncode, 93, (proc.stdout, proc.stderr))
        return proc

    def test_valid_three_phases_end_with_pinned_snapshot(self):
        d=self.archive()
        self.assertEqual(len(d),64)
        self.assertEqual(self.reader(self.name), d)
        self.assertEqual(self.verify(), self.path.read_bytes())

    def test_default_missing_external_pin_blocks_verification(self):
        with self.assertRaises(OSError):
            self.verify()

    def test_mid_write_process_crash_leaves_only_staged_fragment(self):
        self.crash_subprocess("MID_WRITE")
        self.assertFalse((self.snaps/self.name).exists())
        self.assertIsNone(self.reader(self.name))
        self.assertTrue(any(self.snaps.glob(".pending-wal-*")))
        with self.assertRaises(OSError):
            self.verify()

    def test_post_fsync_pre_publish_process_crash_quarantines_staging(self):
        self.crash_subprocess("STAGED")
        self.assertFalse((self.snaps/self.name).exists())
        self.assertIsNone(self.reader(self.name))
        self.assertTrue(any(self.snaps.glob(".pending-wal-*")))
        with self.assertRaises(OSError):
            self.verify()

    def test_published_unpinned_crash_never_becomes_proven(self):
        self.crash_subprocess("PUBLISHED")
        self.assertTrue((self.snaps/self.name).exists())
        self.assertIsNone(self.reader(self.name))
        with self.assertRaises(OSError):
            self.verify()
        with self.assertRaises(FileExistsError):
            self.archive()
        self.assertIsNone(self.reader(self.name))

    def test_post_pin_pre_return_crash_is_independently_verifiable(self):
        self.crash_subprocess("PIN_PERSISTED")
        self.assertIsNotNone(self.reader(self.name))
        self.assertEqual(self.verify(), self.path.read_bytes())
        with self.assertRaises(FileExistsError):
            self.archive()

    def test_callback_does_not_ack_pin_blocks_return(self):
        with self.assertRaises(OSError):
            self.archive(trusted_pin_writer=lambda n,d: False)
        with self.assertRaises(OSError):
            self.verify()

    def test_callback_wrong_pin_readback_blocks_return(self):
        with self.assertRaises(OSError):
            self.archive(trusted_pin_reader=lambda n: "f"*64)
        self.assertEqual(self.verify(), self.path.read_bytes())

    def test_prepared_wal_cannot_start_archive(self):
        self.row["status"]="PREPARED";self.write_wal()
        with self.assertRaises(ValueError):
            self.archive()
        self.assertEqual(list(self.snaps.iterdir()), [])

    def test_committed_error_cannot_start_archive(self):
        self.row["status"]="COMMITTED_ERROR";self.write_wal()
        with self.assertRaises(ValueError):
            self.archive()
        self.assertEqual(list(self.snaps.iterdir()), [])

    def test_corrupted_result_digest_rejected(self):
        self.row["result_sha256"]="f"*64;self.write_wal()
        with self.assertRaises(ValueError):
            self.archive()

    def test_wrong_original_request_fails_before_stage(self):
        with self.assertRaises(ValueError):
            self.archive(expected_request_sha256="f"*64)
        self.assertEqual(list(self.snaps.iterdir()), [])

    def test_snapshot_pin_tampering_detected(self):
        self.archive()
        self.pin_path().write_text("f"*64+"\n")
        with self.assertRaises(ValueError):
            self.verify()

    def test_snapshot_bytes_tampering_detected(self):
        self.archive()
        p=self.snaps/self.name
        p.write_bytes(p.read_bytes()+b"tamper")
        with self.assertRaises(ValueError):
            self.verify()

    def test_create_only_conflicting_snapshot_never_overwritten(self):
        (self.snaps/self.name).write_bytes(b"forged")
        with self.assertRaises(FileExistsError):
            self.archive()
        self.assertEqual((self.snaps/self.name).read_bytes(),b"forged")

    def test_snapshot_symlink_not_followed(self):
        try:
            (self.snaps/self.name).symlink_to(self.path)
        except OSError:
            self.skipTest("Creating symlinks not permitted")
        with self.assertRaises(FileExistsError):
            self.archive()

    def test_missing_pin_authority_not_substituted_with_user_flags(self):
        with self.assertRaises(ValueError):
            self.archive(trusted_pin_reader=None)
        self.assertEqual(list(self.snaps.iterdir()),[])

    def test_two_concurrent_publishers_never_overwrite_final(self):
        winners=[]
        losers=[]
        def do_archive():
            try:
                winners.append(self.archive())
            except FileExistsError:
                losers.append("COLLISION")
        a=threading.Thread(target=do_archive)
        b=threading.Thread(target=do_archive)
        a.start();b.start();a.join(10);b.join(10)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual(len(winners),1)
        self.assertEqual(len(losers),1)
        self.assertEqual(self.verify(),self.path.read_bytes())

    def test_archival_never_modifies_live_terminal_wal(self):
        before=self.path.read_bytes()
        self.archive()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.verify(),before)

    def test_external_pin_missing_after_publication_requires_reconciliation(self):
        self.crash_subprocess("PUBLISHED")
        with self.assertRaises(OSError):
            self.verify()
        self.assertTrue((self.snaps/self.name).is_file())
        self.assertFalse(self.pin_path().exists())

    def test_external_pin_dir_separate_from_snapshots(self):
        self.archive()
        self.assertNotEqual(self.snaps.resolve(),self.pins.resolve())
        self.assertTrue(self.pin_path().is_file())

if __name__ == "__main__":
    unittest.main()
