# ASTRA Supervisor Multi-Executor Design

## Goal

Keep GPT-5.6 Sol/ASTRA as the independent planning, review, and governance layer while removing Codex execution availability or allowance as a single point of failure for CBI engineering work.

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

Do not build another ChatGPT-to-workspace bridge. Reuse a mature read-only bridge when local uncommitted state must be visible. For repository-authoritative work, prefer the existing GitHub connection because it can mutate isolated branches and use Actions without requiring Codex to execute those repository-authoritative steps. This design does not assume that ChatGPT and Codex quotas or agentic allowances are universally independent.

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
- Inherited `GIT_*` control variables must not redirect branch or clean-tree inspection to another repository.
- Git inspection must suppress known configuration-driven external helpers used by status/diff/show/log paths: `core.fsmonitor`, external diff, and textconv.
- Dry-run is the default.

## Local Executor v1

The Local Executor is intentionally narrow and auditable. It consumes a JSON manifest containing ordered operations:

- `write_text`: replace/create one UTF-8 text file under the repository root.
- `delete_file`: delete one file under the repository root.
- `run`: run an argv vector without a shell.

Safety rules:

- every manifest file path and command path target is resolved under repository root;
- every path component named `.git` is inaccessible to file mutation or command working directories;
- path traversal and absolute paths are rejected;
- commands run with `shell=False`;
- Python executable names are matched exactly and v1 only permits constrained `unittest`/`compileall` forms;
- a manifest may not nominate an arbitrary executable path merely because its basename looks like `python` or `git`; path-form executables are rejected except for the exact current Python interpreter path needed by the supported invocation contract;
- inherited `GIT_*` environment variables are stripped before Git inspection or manifest Git execution, then only bounded noninteractive Git controls are reintroduced;
- Git branch/clean-tree inspection forces `core.fsmonitor=false`, preventing a repository-configured fsmonitor helper from executing during the safety gate;
- manifest `git diff`, `git log`, and `git show` execution is forced through `--no-ext-diff` and `--no-textconv`, preventing repository-configured external diff/textconv helpers from executing through those allowlisted commands;
- Git is limited to read-only inspection subcommands and rejects output-to-file, external-diff, no-index, textconv and file-fed pathspec escape surfaces;
- no package installation, network command, `git push`, shell, PowerShell, cmd, or arbitrary `python -c`;
- all operations are validated before the first mutation;
- command failure stops later operations and produces a structured result.

The Local Executor is a transition-grade fallback, not a general unrestricted shell agent and not an OS sandbox. An allowlisted test or repository module is still trusted repository code and may itself have side effects when executed. Phase 1 also assumes the local OS account, executable search path and installed Python/Git binaries are trusted; it is not designed to defend against a compromised local `PATH` or a replaced interpreter/Git binary. Broader write/commit capabilities or unattended remote invocation require a separate security review.

## Trust boundary for any future unattended local control plane

Phase 1 requires explicit local invocation. If a later phase exposes Local Executor through an always-on service or remote bridge, the following become non-negotiable prerequisites rather than optional hardening:

- the service must pin one or more allowed repository roots in trusted local configuration; a remote manifest must not be allowed to choose an arbitrary `repository_root`;
- authentication and authorization must be independent of ChatGPT webpage/session tokens;
- remote callers must not gain unrestricted shell, package installation, arbitrary Python, network-command, credential or Git push access;
- apply requests must remain branch-bound, clean-tree-bound, auditable and replay-safe;
- the service must establish a trusted executable environment rather than inheriting an attacker-controlled `PATH`;
- the service must fail closed when local state, branch identity or authorization cannot be proved.

This future control plane is deliberately out of Phase 1 because it changes the threat model from an explicitly invoked local tool to a remotely reachable mutation authority.

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
3. Local Executor rejects protected branches, dirty trees, path escape, nested `.git` access, disallowed executable lookalikes, user-selected executable-path spoofing and unsafe Git output/external-diff options;
4. inherited `GIT_DIR` / `GIT_WORK_TREE` cannot redirect branch or clean-tree gates to another repository;
5. repository-configured `core.fsmonitor`, external diff and textconv helpers cannot execute through the Local Executor's safety gates or allowlisted Git diff/show/log commands;
6. command path targets for `unittest`/`compileall` remain inside the declared repository root;
7. an allowed manifest can write a repository file and run a local unittest on a non-protected clean branch;
8. the ASTRA skill documents the supervisor/executor split and does not claim that the bridge provides unlimited Codex usage or universally separate quota pools;
9. focused CI passes on Linux and Windows and a full CBI regression run passes without ASTRA changing CBI runtime/evidence/WAL/R2 semantics.

## Stop conditions

Stop and redesign before merge if:

- implementing this requires changes to CBI evidence/WAL/R2/runtime semantics;
- the Local Executor needs an unrestricted shell to be useful;
- GitHub remote execution cannot be kept isolated from production branches;
- bridge integration requires session-token scraping or unofficial ChatGPT web APIs;
- unattended local execution requires trusting a remotely supplied arbitrary repository root;
- Phase 2 would inherit a remotely controllable executable search path or other unproved local execution authority.
