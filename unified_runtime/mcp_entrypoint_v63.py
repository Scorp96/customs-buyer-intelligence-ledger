from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


_ENTRYPOINT_RE = re.compile(r"mcp[\\/](server_v61[^\\/\s\"']*\.py)")


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def resolve_active_mcp_entrypoint(repo_root: str | Path) -> str | None:
    root = Path(repo_root).resolve()
    path = root / ".mcp.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    matches: list[str] = []
    for text in _walk_strings(payload):
        for match in _ENTRYPOINT_RE.finditer(text):
            rel = f"mcp/{match.group(1)}"
            if rel not in matches:
                matches.append(rel)
    return matches[0] if len(matches) == 1 else None
