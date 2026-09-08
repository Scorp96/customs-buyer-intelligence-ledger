from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime.mcp_surface_evidence_v63 import capture_v63_active_mcp_surface_evidence


ARTIFACT_NAME = "V63_ACTIVE_MCP_SURFACE_EVIDENCE.json"


def _atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture source-bound active CBI v6.3 MCP tools/list evidence.")
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    evidence = capture_v63_active_mcp_surface_evidence(
        ROOT,
        expected_git_sha=args.expected_git_sha,
    )
    output_path = Path(args.output_dir).resolve() / ARTIFACT_NAME
    _atomic_json_write(output_path, evidence)
    print(json.dumps({
        "status": "VERIFIED",
        "artifact": str(output_path),
        "git_sha": evidence["git_sha"],
        "production_source_snapshot_sha256": evidence["production_source_snapshot_sha256"],
        "tool_count": len(evidence["tool_names"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
