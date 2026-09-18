# CBI v6.4 Crawler Execution Bridge — Round 3

**Date:** 2026-09-18

## Goal

Expose the open-source crawler stack as a real production MCP capability and package it into the remote Docker/Render runtime without introducing a paid crawling API.

## Production MCP tool

Round 3 adds one adapter-owned read-only tool:

- `execute_public_crawl`

The tool accepts:

- an existing CBI research task containing `task_id` or `call_id`;
- one public http(s) seed URL;
- bounded page, timeout and retry controls;
- optional browser escalation.

The tool executes the Round 1/2 stack:

```text
CBI planner task
    ↓
execute_public_crawl
    ↓
Crawl4AI local primary path
    ↓
Playwright local escalation when needed
    ↓
Receipt-shaped evidence candidates + diagnostics
```

It does not create an outreach draft, send a message, mutate the ledger, or promote a scraped route to verified Account ownership.

## Public-network guard

The production tool rejects:

- non-http(s) URLs;
- embedded URL credentials;
- localhost/local/internal hostnames;
- loopback, private, link-local, reserved or otherwise non-global literal IP targets;
- DNS names that resolve to non-public IP addresses.

Route ownership remains fail-closed. The production tool always executes the bridge with `official_domain_verified=False`; ownership must be established later through the existing CBI evidence path.

## Runtime switch

Crawler execution is controlled by:

`CBI_CRAWLER_ENABLED=1`

The MCP tool remains visible when disabled, but returns a structured `CRAWLER_DISABLED` result instead of attempting execution.

Runtime health now reports:

- crawler enabled/disabled state;
- Crawl4AI package presence;
- Playwright package presence;
- browser escalation support;
- `paid_api_required=false`;
- `public_network_only=true`.

## Docker runtime

`deploy/cloud/Dockerfile` now installs:

- Crawl4AI 0.9.3;
- Playwright;
- Chromium and required system libraries.

Browsers are installed to the shared `/ms-playwright` path so the non-root `cbi` runtime user can launch them.

The image enables the crawler by default:

`CBI_CRAWLER_ENABLED=1`

## Render

`render.yaml` enables the same crawler runtime switch for the remote service. The crawler uses only the container's local open-source runtime; no TinyFish, Firecrawl Hosted, Apify Cloud or other paid crawler endpoint is configured.

## Round 3 CI

The dedicated production smoke workflow verifies:

1. MCP descriptor and handler registration;
2. read-only/non-mutating contract;
3. private/local URL rejection;
4. production tool-surface declaration consistency;
5. Round 1/2 regression tests;
6. production Docker image build;
7. real Chromium launch inside the production image;
8. remote HTTP MCP `tools/list` includes `execute_public_crawl`;
9. remote health reports Crawl4AI + Playwright ready;
10. a real remote MCP call crawls `https://example.com/` through `execute_public_crawl`;
11. the returned route scope remains `UNVERIFIED` and route ownership is not promoted.

## Deliberate boundaries

Round 3 is still a release-candidate integration step. It does not by itself:

- merge to `main`;
- change the plugin manifest from the existing production version to final v6.4;
- deploy the release candidate to the live Render service;
- add paid proxy/CAPTCHA services;
- log into social platforms;
- bypass website access controls.

Final version promotion, full regression closure, release gates, image/resource hardening and production rollout belong to Round 4.
