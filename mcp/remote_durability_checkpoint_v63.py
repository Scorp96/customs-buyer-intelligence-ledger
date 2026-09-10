#!/usr/bin/env python3
"""Remote-only post-handler durability checkpoint for v6.3 mutation adapters.

The accepted v6.1 adapter owns PREPARED/terminal WAL semantics.  This module
adds no second journal and does not alter local/stdin execution.  A remote
runtime may install one checkpoint around the adapter's business handler so
complete recovery state can reach object storage after the side effect but
before the adapter's cold-crash probe or terminal receipt.
"""

from __future__ import annotations

import os
from typing import Any, Callable


_ORIGINAL_ATTR = "_cbi_v63_remote_durability_original_invoke"
_WRAPPER_ATTR = "_cbi_v63_remote_durability_checkpoint_wrapper"


def install_remote_durability_checkpoint(
    adapter: Any,
    checkpoint: Callable[[], None],
    *,
    fatal_exit: Callable[[int], Any] = os._exit,
) -> Callable[..., Any]:
    """Install one remote durability checkpoint around ``adapter._invoke_mutation``.

    The wrapper delegates all write-ahead/idempotency/recovery semantics to the
    existing adapter.  Only the business handler is wrapped.  Therefore the
    ordering is mechanically:

        PREPARED -> handler side effect -> checkpoint -> adapter crash/terminal

    A checkpoint failure is indeterminate after side effect.  It must not flow
    through the adapter's ``except Exception`` path because that would write a
    false terminal COMMITTED_ERROR receipt.  Instead the remote process exits
    with code 92, leaving the local PREPARED intent untouched and preventing a
    success acknowledgement.  ``SystemExit`` is the fail-closed fallback if a
    supplied fatal-exit callback unexpectedly returns.

    Repeated installation is idempotent and returns the same original invoke
    callable without stacking another checkpoint wrapper.
    """

    if not callable(checkpoint):
        raise TypeError("checkpoint must be callable")
    if not callable(fatal_exit):
        raise TypeError("fatal_exit must be callable")

    installed_original = getattr(adapter, _ORIGINAL_ATTR, None)
    if callable(installed_original):
        return installed_original

    original = getattr(adapter, "_invoke_mutation", None)
    if not callable(original):
        raise TypeError("adapter._invoke_mutation must be callable")

    def checkpointed_invoke(
        tool_name: str,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not callable(handler):
            raise TypeError("mutation handler must be callable")

        def checkpointed_handler(args: dict[str, Any]) -> dict[str, Any]:
            result = handler(args)
            try:
                checkpoint()
            except Exception:
                fatal_exit(92)
                # A real os._exit never returns.  If a replacement callback does,
                # use BaseException semantics so the adapter cannot convert this
                # post-side-effect durability failure into COMMITTED_ERROR.
                raise SystemExit(92)
            return result

        return original(tool_name, checkpointed_handler, arguments)

    setattr(adapter, _ORIGINAL_ATTR, original)
    setattr(adapter, _WRAPPER_ATTR, checkpointed_invoke)
    setattr(adapter, "_invoke_mutation", checkpointed_invoke)
    return original
