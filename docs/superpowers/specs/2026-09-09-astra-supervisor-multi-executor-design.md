# ASTRA Supervisor Multi-Executor Design

## Goal

Keep GPT-5.6 Sol/ASTRA as the independent planning, review, and governance layer while removing Codex allowance as a single point of failure for CBI engineering work.

## Verified repository context

- The active CBI development line is `cbi-v6-3-demand-expansion`.
- CBI already has its own MCP/runtime stack and GitHub CI. This work must not rewrite the CBI evidence/runtime core.
- `codex-with-chatgpt` is treated only as an optional read-only local-workspace bridge. It is not vendored, forked, or promoted into the CBI runtime.

## Architecture

ASTRA is a supervisor, not an executor. It decides what should happen, which executor should do it, and whether the result is acceptable.

```text
GPT-5.6 Sol
    |
ASTRA Supervisor
    |
    +-- GitHub executor: remote branch/file/PR mutations + GitHub Actions
    +-- Codex executor: interactive local implementation when allowance is available
    +-- Local executor: explicit, fail-closed manifest application for local-only work
    |
optional codex-with-chatgpt bridge
    +-- read local workspace/diff/test output only
```

## Anti-path-dependence decision

Do not build another ChatGPT-to-workspace bridge. Reuse a mature read-only bridge when local uncommitted state must be visible. For repository-authoritative work, prefer the existing GitHub connection because it can mutate isolated branches and use Actions without consuming Codex allowance.

## Executor selection semantics

ASTRA classifies engineering work as one of:

- `REPOSITORY_EDIT`: authoritative state is in GitHub. Prefer GitHub, then Codex, then Local.
- `LOCAL_WORKSPACE`: the task depends on uncommitted/local-only state. Prefer Codex, then Local. GitHub is not eligible because it cannot see that state.
- `REVIEW_ONLY`: ASTRA performs the review and selects no executor.

Executor availability is an input, never inferred from optimism. If no eligible executor is available, fail closed.

## Git safety invariants

- Never write directly to `main`, `master`, or any branch named `production` through the Local Executor.
- CBI production/runtime branches are not modified by this feature.
- Remote implementation work starts from an isolated branch and is reviewed before merge.
- The Local Executor requires an exact expected branch and a clean working tree before `--apply`.
- Dry-run is the default.

## Local Executor v1

The Local Executor is intentionally narrow and auditable. It consumes a JSON manifest containing ordered operations:

- `write_text`: replace/create one UTF-8 text file under the repository root.
- `delete_file`: delete one file under the repository root.
- `run`: run an argv vector without a shell.

Safety rules:

- every path is resolved under repository root;
- `.git` is never writable;
- path traversal and absolute paths are rejected;
- commands run with `shell=False`;
- v1 command policy only permits Python `unittest`/`compileall` and read-only Git inspection commands;
- no package installation, network command, `git push`, shell, PowerShell, cmd, or arbitrary `python -c`;
- all operations are validated before the first mutation;
- command failure stops later operations and produces a structured result.

The Local Executor is a transition-grade fallback, not a general unrestricted shell agent. Broader write/commit capabilities require a separate security review.

## Supervisor contract

ASTRA maintains, for each substantial engineering task:

- final goal;
- current stage;
- verified facts;
- completed work;
- current plan;
- temporary compromises;
- unverified items;
- risks;
- next action;
- chosen executor and rationale;
- verification evidence;
- success and stop conditions.

ASTRA must independently review diffs/test evidence rather than allowing an executor to self-approve.

## `codex-with-chatgpt` boundary

The integration is documentation/configuration only. CBI does not copy third-party source code into this repository. When used locally, the bridge remains read-only from ChatGPT to the workspace and exists to expose local files, Git diff, and execution output. Mutation authority remains with the selected executor.

## Success criteria

Phase 1 is successful when:

1. executor selection is deterministic and tested;
2. Local Executor dry-run cannot mutate files;
3. Local Executor rejects protected branches, dirty trees, path escape, `.git` writes, and disallowed commands;
4. an allowed manifest can write a repository file and run a local unittest on a non-protected clean branch;
5. the ASTRA skill documents the supervisor/executor split and does not claim that the bridge provides unlimited Codex usage;
6. CI passes on Linux and Windows.

## Stop conditions

Stop and redesign before merge if:

- implementing this requires changes to CBI evidence/WAL/R2/runtime semantics;
- the Local Executor needs an unrestricted shell to be useful;
- GitHub remote execution cannot be kept isolated from production branches;
- bridge integration requires session-token scraping or unofficial ChatGPT web APIs.
