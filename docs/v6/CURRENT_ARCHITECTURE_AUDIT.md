# Current Architecture Audit — v5.4.1 Baseline

## Scope

This audit describes the production baseline captured before the v6 reconstruction. It is an engineering record, not a claim about newly researched buyers.

## Preserved strengths

- Canonical resolution supports exact account ID, tax ID, alias/name, address and external identifiers with ambiguity instead of guessing.
- Investigation, Evidence, Information, Pivot, Peer, Closure, outreach and CRM receipts are append-only and chain-hashed.
- Writes are flushed and synchronized; v6 additionally serializes concurrent session writers.
- Public URL and non-URL Evidence have different locator rules. Self-authored audit strings are not valid raw proof.
- Route ownership, masked/guessed contact, WhatsApp/Zalo channel proof, opt-out, stage regression and one-time draft tokens are guarded.
- Artifact Tool CRM receipts require workbook identity, before/after hashes, semantic diff, assertions and post-commit re-import.
- `ANSWER_FIRST` already separates immediate useful research from expensive persistence and CRM work.

## Material architecture defects

| Area | v5.4.1 behavior | Production consequence | v6 disposition |
|---|---|---|---|
| Completion | Source Family checklist plus queue/Pivot closure | Work volume can dominate decision value | Claim-driven Decision Saturation |
| Source profile | Treated as immutable mandatory coverage | Low-value families can consume time; useful new routes are awkward | Search playbook; EIV chooses next work |
| Commercial grade | Contact and CRM gates could cap A/A+ | Commercial value was conflated with operational readiness | Four independent dimensions |
| Peer promotion | Full contact coverage was part of promotion proof | High-value Peer may be rejected before it becomes an Anchor | Contact is optional for Anchor eligibility |
| Evidence ingestion | One receipt-oriented call per action | High MCP overhead for research-heavy tickets | Batch Evidence Compiler, 1–1000 observations |
| Transport recovery | Runtime pending journal is local but callable only through the Runtime route | A tunnel outage can prevent both primary append and fallback call | Independent host queue plus idempotent replay |
| Portfolio | Single-investigation focus | No global allocation of research cost | Portfolio Scheduler and Budget Controller |
| Runtime shape | Large compatibility monolith and hand-maintained MCP descriptors | Coupling and registry drift risk | v6 governance overlay plus compatibility adapter |
| Migration | Version changes reused the same production paths | Higher rollback and provenance risk | Copy → migrate → verify → external switch |

## Root-cause clarification

The v5 session log was already filesystem-durable. A message such as `Session terminated` primarily indicated transport/session failure, not proof that the JSONL state was deleted. The practical failure was broader: when all MCP tools were unavailable, the caller could neither confirm the durable state nor invoke the Runtime-owned pending journal. v6 therefore makes state resumption explicit and adds a host queue that does not require a live MCP process.

## Risk inventory

- `core.py` combined validation, state reduction, closure, CRM and outreach concerns.
- MCP tool order was duplicated between a tuple, descriptors and handlers.
- Legacy SourceAttempt and ProviderReceipt APIs remain valuable but encode source-family-era semantics.
- Old production sessions can contain correct history without the v6 Claim catalog or compiled-observation events.
- Existing tests encode some v5.4.1 policy assertions and must be retained as compatibility tests, not v6 product policy.

## Reconstruction decision

Keep the stable v5 implementation as a compatibility adapter. Place v6 governance before it in the public Runtime method resolution order. New investigations receive a durable v6 extension event. Legacy sessions are never modified merely by read operations; explicit `resume_investigation` or copy migration adds the v6 overlay.

