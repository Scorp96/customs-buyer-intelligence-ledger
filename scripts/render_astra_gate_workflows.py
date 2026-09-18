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
        prog="render-astra-gate-workflows",
        description="Render immutable default-branch ASTRA gate workflow shims.",
    )
    parser.add_argument(
        "--control-plane-sha",
        required=True,
        help="reviewed Phase 2A exact 40-hex commit SHA",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="directory that receives the two generated workflow files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        task = render_task_gate_workflow(args.control_plane_sha)
        receipt = render_receipt_gate_workflow(args.control_plane_sha)
    except ActivationError as exc:
        sys.stderr.write(f"ASTRA gate render failed closed: {exc}\n")
        return 2

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "astra-task-sign.yml").write_text(task, encoding="utf-8", newline="\n")
    (output_dir / "astra-receipt-verify.yml").write_text(
        receipt, encoding="utf-8", newline="\n"
    )
    sys.stdout.write(f"ASTRA_GATE_RENDER_OK={args.control_plane_sha.lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
