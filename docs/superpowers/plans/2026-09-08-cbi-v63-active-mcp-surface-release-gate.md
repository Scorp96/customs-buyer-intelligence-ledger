# CBI v6.3 Active MCP Surface Release Gate Plan

**Goal:** Prevent v6.3 production release when the active MCP tool surface does not actually expose the v6.3 tools declared by the runtime schema.

## Execution

- [x] Verify fresh production and v6.3 Git refs.
- [x] Confirm production is a descendant of v6.3 and retains later CI portability fixes.
- [x] Add a fail-closed active MCP tool-set check sourced from `mcp_schema_v63.py`.
- [x] Add source-SHA-bound `cbi.v63-mcp-surface-evidence.v1` validation to the release assembler.
- [x] Add focused regression tests for complete, missing, absent, and stale MCP-surface evidence.
- [ ] Run authoritative GitHub Actions / repository full regression on the feature branch.
- [ ] Capture the actual active production MCP `tools/list` after adapter activation.
- [ ] Re-run existing recovery/backend/Render/R2/backup/real-PVC gates before any production promotion.

## Safety constraints

No production branch mutation, Render/R2 deployment, CRM mutation, buyer-state mutation, outreach send, duplicate WAL, or external scoring/closure layer is introduced by this change.
