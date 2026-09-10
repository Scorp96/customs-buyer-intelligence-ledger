# ASTRA Phase 2A Default-Branch Gate Amendment

## Verified repository constraint

Repository `Scorp96/customs-buyer-intelligence-ledger` has default branch `main`.

GitHub `issues` and `issue_comment` event workflows only trigger when the workflow file exists on the repository default branch. Therefore the Phase 2A task-signing and receipt-verification workflows cannot become operational merely by merging worker/control-plane code into `cbi-v6-3-demand-expansion` or another non-default branch.

## Amendment to the Phase 2A design

Phase 2A keeps all worker/control-plane implementation, tests, protocol logic, signer logic, receipt-verifier logic, and CBI integration code on the normal Phase 2A development/CBI branch lineage.

Operational gate activation is a separate deployment step:

1. Phase 2A worker/control-plane code reaches an exact reviewed, CI-green release commit SHA.
2. A separate branch is created from `main`.
3. That branch adds only two minimal GitHub Actions workflow files under `.github/workflows/`:
   - task-signing gate triggered by `issues`;
   - receipt-verification gate triggered by `issue_comment`.
4. Each workflow checks out the exact reviewed Phase 2A release commit SHA, not a mutable feature branch name, before executing `scripts/astra_task_gate.py` or `scripts/astra_receipt_gate.py`.
5. The activation branch is opened as a separate PR against `main` and remains human-reviewed. It is never auto-merged by the worker.
6. Updating signer/verifier implementation later requires a new reviewed Phase 2A release SHA and a new activation PR that updates the pinned SHA in the default-branch workflows.

## Trust implications

- `main` receives only the event-trigger shims; it does not receive or execute CBI business-runtime changes as part of this activation.
- The shims use repository-level Actions secrets but execute signer/verifier Python from an immutable reviewed commit.
- A GitHub issue body or worker comment still never supplies executable code or a checkout ref.
- The workflow checkout ref is a literal 40-hex commit SHA generated at release/activation time and cannot be changed by the event payload.
- The activation PR is a deployment gate, separate from the Phase 2A implementation PR.

## Stop conditions

Stop deployment if:

- the default-branch workflow would checkout a mutable branch/tag instead of an exact reviewed commit SHA;
- activation requires copying CBI business/runtime code into `main`;
- the task/receipt event payload can choose workflow code, checkout ref, or secret names;
- the activation PR would receive source push/merge authority from the Windows worker.
