from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from astra_worker.gate_activation import (
    ActivationError,
    render_receipt_gate_workflow,
    render_task_gate_workflow,
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render immutable default-branch ASTRA gate workflow shims",
    )
    parser.add_argument("--control-plane-sha", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        task = render_task_gate_workflow(args.control_plane_sha)
        receipt = render_receipt_gate_workflow(args.control_plane_sha)
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "astra-task-sign.yml").write_text(task, encoding="utf-8", newline="\n")
        (output_dir / "astra-receipt-verify.yml").write_text(receipt, encoding="utf-8", newline="\n")
        return 0
    except (ActivationError, OSError) as exc:
        sys.stderr.write(f"ASTRA gate rendering failed closed: {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
