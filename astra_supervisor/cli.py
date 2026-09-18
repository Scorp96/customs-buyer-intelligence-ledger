from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .local_executor import LocalExecutionError, LocalExecutor
from .manifest import ExecutionManifest, ManifestValidationError


def _write_payload(payload: dict, result_path: str | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if result_path:
        Path(result_path).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ASTRA fail-closed local executor")
    parser.add_argument("--manifest", required=True, help="Path to execution manifest JSON")
    parser.add_argument("--apply", action="store_true", help="Apply the manifest; default is dry-run")
    parser.add_argument("--result", help="Optional path for structured result JSON")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        manifest = ExecutionManifest.from_dict(payload)
        result = LocalExecutor().execute(manifest, apply=args.apply)
        _write_payload(result.to_dict(), args.result)
        return 0 if result.success else 1
    except (
        OSError,
        json.JSONDecodeError,
        ManifestValidationError,
        LocalExecutionError,
        ValueError,
    ) as exc:
        failure = {
            "task_id": None,
            "success": False,
            "applied": False,
            "steps": [],
            "error": str(exc),
        }
        _write_payload(failure, args.result)
        return 2


if __name__ == "__main__":
    sys.exit(main())
