"""Fail-closed Source Family receipt binding for read-only projections.

A typed/plausible JSON receipt is NOT evidence. Without an independently
supplied, trusted ledger-origin/ownership verifier, callers receive only
incomplete coverage. There is no user-facing "verified=true" bypass.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

ReceiptVerifier = Callable[[dict[str, Any], dict[str, Any]], bool]

def receipt_is_owned_and_verified(
    task: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    identity_fields: tuple[str, ...],
    verifier: ReceiptVerifier | None,
) -> bool:
    if not isinstance(task, dict) or not isinstance(receipt, dict):
        return False
    if not callable(verifier):
        return False
    # Bind every task scope to the claimed execution, not merely task_id.
    for name in identity_fields:
        wanted = task.get(name)
        actual = receipt.get(name)
        if not isinstance(wanted, str) or not wanted.strip():
            return False
        if not isinstance(actual, str) or actual != wanted:
            return False
    if receipt.get("execution_required") is False or receipt.get("receipt_required") is False:
        return False
    # The verifier must consult trusted, persisted host/WAL records and prove
    # the same owner plus source family, immutable raw proof and true execution.
    # Merely returning True from an untrusted/fixture callback is not a
    # production-grade attestation. No such verifier is wired by this change.
    try:
        return verifier(dict(task), dict(receipt)) is True
    except Exception:
        return False
