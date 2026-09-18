# CBI v6.4 Crawler Execution Bridge — Round 2

**Date:** 2026-09-18

## Goal

Add a local browser escalation layer on top of Round 1 so CBI can recover useful public content from JS-heavy or sparse pages without using any paid crawling API.

## Open-source execution stack

- Crawl4AI 0.9.3 for the normal crawl path
- Playwright + local Chromium for browser escalation
- Existing CBI v6.3/v6.4 planner, Evidence, Receipt and route-safety rules

No TinyFish, Firecrawl hosted API, Apify Cloud, paid proxy API, or external LLM extraction API is required.

## Round 2 additions

### 1. Browser escalation

The normal crawler runs first. A page escalates to Playwright only when one of these conditions is observed:

- the primary fetch failed;
- rendered text is materially sparse;
- the page looks like a JS/SPA shell;
- the page has little content and no usable links.

The browser result replaces the normal result only when its deterministic page-quality score is better.

### 2. Safe dynamic interaction

The Playwright backend may:

- render JavaScript;
- wait briefly for dynamic content;
- reuse one browser context across the crawl session;
- scroll the page in bounded steps;
- click a bounded number of visible expandable controls when their labels match research intent such as Contact, Team, Procurement, Purchasing, Compras, Importaciones, More or Details.

It will not deliberately click actions associated with:

- buy/checkout/cart/payment;
- login/sign-in/register;
- submit/send;
- delete/remove;
- subscription or other transactional actions.

It does not bypass CAPTCHA, login, paywalls or access controls.

### 3. Task-driven link ranking

Round 1 ranked mainly from URL paths. Round 2 also consumes visible link labels and derives dynamic goal terms from the existing CBI task fields:

- query;
- source_family;
- route_target;
- branch / branch_group.

This lets an opaque URL such as /page?id=42 outrank /products when the anchor text says "Equipo de Compras e Importaciones" and the task is looking for a contact route.

Keywords influence crawl priority only; they are never Evidence.

### 4. Retry and timeout policy

A resilient wrapper now supplies:

- bounded per-fetch timeout;
- bounded retries;
- short retry delay;
- fail-closed error pages after exhaustion;
- receipt diagnostics for every retry and timeout.

### 5. Receipt diagnostics

The existing CrawlExecutionBridge now records optional backend diagnostics, including:

- browser escalation count;
- reason for each escalation;
- which backend won;
- primary vs browser text size;
- retry attempts and timeout state.

The existing route ownership guard remains unchanged: scraped contact data is not promoted to an Account-owned verified route unless official-domain ownership was already proven separately.

## Local usage

Install the open-source crawler/browser runtime:

```bash
python -m pip install -r requirements-crawler.txt
crawl4ai-setup
python -m playwright install chromium
```

Execute with browser escalation:

```bash
python scripts/run_crawler_bridge.py \
  --seed-url https://example.com \
  --task-json '{"task_id":"V63CONTACT-DEMO","source_family":"official_contact","query":"procurement purchasing compras"}' \
  --browser-escalation \
  --official-domain-verified
```

Do not pass --official-domain-verified unless the investigated Account's ownership of the domain is already supported by CBI/host evidence.

## Round 2 acceptance tests

- healthy primary content does not launch the browser;
- sparse/JS-shell primary content escalates;
- inferior/blocked browser output cannot overwrite a better primary result;
- browser interaction allow/block policy is deterministic;
- transient failures retry within a fixed bound;
- timeouts fail closed;
- dynamic link labels and task terms influence crawl order;
- crawler receipt includes backend diagnostics;
- existing Round 1 route-safety tests remain green.

## Deliberate boundaries

Round 2 does not yet:

- expose crawler execution as a production MCP tool;
- alter the production Docker/Render image;
- perform broad search-engine seed discovery;
- use paid proxies or CAPTCHA solving;
- log into social networks;
- mutate Closure, CRM, WAL or outreach gates.

Those belong to Round 3 production/MCP integration.
