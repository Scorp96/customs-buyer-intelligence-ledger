from __future__ import annotations

import json
import unittest

import tests.test_v61_sync_wal_recovery as sync_tests


class SyncRecoveryDiagnostic(unittest.TestCase):
    def test_dump_pending_child_handler_crash_material(self) -> None:
        case = sync_tests.V61SyncWalRecoveryTests(
            methodName="test_pending_child_handler_crash_recovers_from_correlated_target_event"
        )
        case.setUp()
        try:
            h, _ = case._pending_fixture()
            arguments = {
                "investigation_id": h.investigation_id,
                "limit": 10,
                "idempotency_key": "sync-pending-handler-crash-diag-0001",
            }
            crashing = case._spawn(crash_after_child_handler="sync_pending_receipts")
            case._crash_call(crashing, 2, "sync_pending_receipts", arguments, 92)

            events = h.runtime.store.read(h.investigation_id)
            info_events = [
                event for event in events
                if event.get("event_type") == "INFORMATION_RECORD_APPENDED"
            ]
            child_root = case.root / "mcp-idempotency-v61" / "sync-item-wal"
            child_rows = []
            if child_root.is_dir():
                for path in sorted(child_root.glob("*.json")):
                    child_rows.append(json.loads(path.read_text(encoding="utf-8")))

            print("SYNC_DIAG_INFO_EVENTS=" + json.dumps(info_events, sort_keys=True))
            print("SYNC_DIAG_CHILD_ROWS=" + json.dumps(child_rows, sort_keys=True))
            self.assertEqual(len(info_events), 1)
            self.assertEqual(len(child_rows), 1)
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
