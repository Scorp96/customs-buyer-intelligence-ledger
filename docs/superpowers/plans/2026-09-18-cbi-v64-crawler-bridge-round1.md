# CBI v6.4 Crawler Execution Bridge — Round 1

**Date:** 2026-09-18

## Goal

Close the existing v6.3 Planner → Executor gap without adding any paid crawling API.

Round 1 keeps the current CBI evidence/governance model intact and adds a local execution bridge that can consume existing `call_id` / `task_id` research tasks plus a known seed URL, crawl the same company site, prioritize commercially useful pages, and return receipt-shaped output for the current Evidence/SourceAttempt flow.

## Open-source stack

- Crawl4AI 0.9.3, self-hosted
- Crawl4AI's local browser runtime
- No hosted Crawl4AI API
- No TinyFish/Firecrawl/Apify paid API dependency

Install locally:

```bash
python -m pip install -r requirements-crawler.txt
crawl4ai-setup
crawl4ai-doctor
```

## Round 1 behavior

`unified_runtime/crawler_execution_bridge.py` adds:

- `Crawl4AIBackend`: lazy local adapter around `AsyncWebCrawler`;
- `CrawlExecutionBridge`: executes one existing v6.3 source/contact task against a known company seed URL;
- same-site traversal only;
- deterministic link prioritization for Contact / About / Team / Procurement / Purchasing / Import / Products paths in English, Spanish and Portuguese;
- email, phone and explicit WhatsApp-link extraction;
- deterministic Evidence IDs and aggregate content SHA-256;
- contact receipts compatible with current `evaluate_contact_coverage` fields;
- ordinary source receipts compatible with the existing public-source receipt shape;
- fail-closed route ownership: a discovered route is not marked verified/account-owned unless `official_domain_verified=True` is explicitly supplied.

## Deliberate boundaries

Round 1 does **not**:

- perform search-engine discovery for the seed URL;
- call any paid API;
- treat keywords as Evidence;
- bypass logins, access controls, CAPTCHAs or anti-bot controls;
- promote directory/social contact data to Buyer-owned routes without official-domain proof;
- expose new MCP tools yet;
- modify Closure, CRM, WAL, send gates or production deployment;
- add custom Playwright click/scroll/session logic beyond Crawl4AI's normal local browser operation.

Those are later rounds.

## Data flow

```text
v6.3 source/contact planner
        ↓
existing task (call_id or task_id)
        ↓
known verified seed URL
        ↓
CrawlExecutionBridge
        ↓
Crawl4AI local fetch
        ↓
same-site prioritized traversal
        ↓
page + route Evidence candidates
        ↓
receipt-shaped result
        ↓
existing CBI Evidence / SourceAttempt / contact coverage pipeline
```

## Safety invariant

`official_domain_verified=False` is the default. Therefore an email or phone scraped from a directory, mirror, reseller, social profile or uncertain domain may be retained as a lead candidate but cannot become an Account-owned verified route through this bridge alone.

## Round 1 acceptance

Focused tests cover:

1. same-site traversal and priority ordering;
2. exclusion of external links;
3. email and phone extraction;
4. explicit WhatsApp-link extraction;
5. verified official-domain route projection;
6. unverified-domain fail-closed ownership;
7. public-source page evidence without contacts;
8. crawl failure → BLOCKED;
9. non-http(s) seed rejection.

## Next round

Round 2 will add explicit Playwright escalation, JS interaction, click/expand/scroll behavior, session handling, deeper keyword/semantic prioritization, timeout/retry policy and browser-specific failure receipts.
