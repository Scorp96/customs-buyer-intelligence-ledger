from __future__ import annotations

import os

from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63
from unified_runtime.backup_object_store_v64 import BackupObjectStoreReplica


def backup_replica_from_env() -> BackupObjectStoreReplica | None:
    """Build the v6.4 backup replica from the existing R2/S3 configuration.

    Construction reuses the recovery manager's client and prefix only.  It does
    not read or advance the hot object-state pointer, and it never returns
    credentials through the backup manager/health surface.
    """

    state_manager = RecoveryObjectStoreStateManagerV63.from_env()
    if state_manager is None:
        return None
    retention = int(os.environ.get("CBI_BACKUP_OBJECT_STORE_RETENTION") or "20")
    return BackupObjectStoreReplica(
        state_manager.client,
        prefix=state_manager.prefix,
        retention=retention,
    )
