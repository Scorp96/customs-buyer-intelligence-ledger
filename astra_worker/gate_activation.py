from __future__ import annotations

import re


class ActivationError(ValueError):
    """Raised when a default-branch gate shim cannot be rendered safely."""


_CONTROL_PLANE_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
_SETUP_PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
_REPOSITORY = "Scorp96/customs-buyer-intelligence-ledger"


def _validated_sha(control_plane_sha: str) -> str:
    if not isinstance(control_plane_sha, str) or _CONTROL_PLANE_SHA_RE.fullmatch(control_plane_sha) is None:
        raise ActivationError("control-plane ref must be one exact 40-hex commit SHA")
    return control_plane_sha.lower()


def render_task_gate_workflow(control_plane_sha: str) -> str:
    sha = _validated_sha(control_plane_sha)
    return f"""name: ASTRA task signing gate (pinned Phase 2A)\n\non:\n  issues:\n    types: [opened, edited, labeled]\n\npermissions:\n  contents: read\n  issues: write\n\nconcurrency:\n  group: astra-task-sign-${{{{ github.event.issue.number }}}}\n  cancel-in-progress: false\n\njobs:\n  sign:\n    if: contains(github.event.issue.labels.*.name, 'astra-task/proposed')\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - name: Checkout immutable reviewed Phase 2A gate code\n        uses: {_CHECKOUT_ACTION}\n        with:\n          repository: {_REPOSITORY}\n          ref: {sha}\n          persist-credentials: false\n\n      - name: Set up Python\n        uses: {_SETUP_PYTHON_ACTION}\n        with:\n          python-version: '3.11'\n\n      - name: Sign eligible ASTRA task\n        run: python scripts/astra_task_gate.py --event \"$GITHUB_EVENT_PATH\"\n        env:\n          GITHUB_TOKEN: ${{{{ github.token }}}}\n          ASTRA_TASK_HMAC_KEY_B64: ${{{{ secrets.ASTRA_TASK_HMAC_KEY_B64 }}}}\n          ASTRA_ALLOWED_PROPOSERS: Scorp96\n          ASTRA_WORKER_ID: scorp-windows-01\n          ASTRA_REPOSITORY_ID: cbi-primary\n          ASTRA_ALLOWED_BASE_REFS_EXACT: cbi-v6-3-demand-expansion\n          ASTRA_ALLOWED_BASE_REF_PREFIXES: astra-\n          ASTRA_MAX_TASK_AGE_SECONDS: '1800'\n"""


def render_receipt_gate_workflow(control_plane_sha: str) -> str:
    sha = _validated_sha(control_plane_sha)
    return f"""name: ASTRA receipt verification gate (pinned Phase 2A)\n\non:\n  issue_comment:\n    types: [created]\n\npermissions:\n  contents: read\n  issues: write\n\nconcurrency:\n  group: astra-receipt-verify-${{{{ github.event.issue.number }}}}\n  cancel-in-progress: false\n\njobs:\n  verify:\n    if: startsWith(github.event.comment.body, 'ASTRA_RECEIPT_V1 ')\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - name: Checkout immutable reviewed Phase 2A gate code\n        uses: {_CHECKOUT_ACTION}\n        with:\n          repository: {_REPOSITORY}\n          ref: {sha}\n          persist-credentials: false\n\n      - name: Set up Python\n        uses: {_SETUP_PYTHON_ACTION}\n        with:\n          python-version: '3.11'\n\n      - name: Verify ASTRA worker receipt\n        run: python scripts/astra_receipt_gate.py --event \"$GITHUB_EVENT_PATH\"\n        env:\n          GITHUB_TOKEN: ${{{{ github.token }}}}\n          ASTRA_TASK_HMAC_KEY_B64: ${{{{ secrets.ASTRA_TASK_HMAC_KEY_B64 }}}}\n          ASTRA_RECEIPT_HMAC_KEY_B64: ${{{{ secrets.ASTRA_RECEIPT_HMAC_KEY_B64 }}}}\n"""
