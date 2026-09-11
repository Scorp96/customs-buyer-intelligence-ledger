# CBI v6.5 Social + Global Radar Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use the approved TDD/execution workflow task-by-task.

**Goal:** Add a read-only, deterministic Social/Radar candidate intake contract on top of CBI v6.4 without changing production scoring, WAL, CRM, or outreach semantics.

**Architecture:** A standalone schema plus pure validator/normalizer accepts evidence-bound candidate bundles from Instagram, TikTok and Global Radar. The first release slice performs no production mutation; later runtime wiring must reuse existing guarded CBI Investigation/Evidence mutation paths.

**Tech Stack:** Python stdlib, JSON Schema document, existing CBI unittest suite.

**Spec:** `docs/superpowers/specs/2026-09-11-cbi-v65-social-radar-intake-design.md`

## Global Constraints

- Base is production `1f920c2db63b1e17b4b12da8af73cbb1f1474b8c`.
- No CRM write or outreach send.
- No new unguarded production mutation path.
- Direct evidence and inference stay separate.
- Source bundles cannot assert final CBI `A` or `A+` authority.
- Deterministic fingerprinting must be stable across JSON key order.

---

### Task 1: Pure intake validator and fingerprint

**Files:**
- Create: `skills/investigate-customs-buyers/references/social-radar-candidate-schema.json`
- Create: `skills/investigate-customs-buyers/scripts/social_radar_intake.py`
- Create: `tests/test_social_radar_intake.py`

**Interfaces:**
- Produces: `validate_and_normalize_social_radar_candidate(bundle: dict) -> dict`
- Produces: `candidate_fingerprint(bundle: dict) -> str`

- [ ] **Step 1: Write failing tests** proving Instagram-only and Radar-only valid bundles normalize successfully; inference-only bundles fail; source `final_grade` values `A`/`A+` fail; fingerprint is invariant to key order.
- [ ] **Step 2: Run RED:** `python -m unittest tests.test_social_radar_intake -v` and require import/behavior failure.
- [ ] **Step 3: Add schema and minimal validator.** Validator must reject unknown schema version, missing direct evidence, unsupported platforms/stages, invalid confidence outside `[0,1]`, inference references to unknown evidence IDs, and final-authority fields.
- [ ] **Step 4: Run GREEN:** `python -m unittest tests.test_social_radar_intake -v`.
- [ ] **Step 5: Run regression subset:** `python -m unittest tests.test_social_radar_intake tests.test_v63_mcp_active_surface -v` when the existing test module is present; otherwise run the new test plus `python -m compileall -q skills/investigate-customs-buyers/scripts`.

### Task 2: Social + Radar producer compatibility fixtures

**Files:**
- Create: `tests/fixtures/social_radar/instagram_candidate.json`
- Create: `tests/fixtures/social_radar/tiktok_candidate.json`
- Create: `tests/fixtures/social_radar/radar_candidate.json`
- Create: `tests/fixtures/social_radar/mixed_candidate.json`
- Modify: `tests/test_social_radar_intake.py`

**Interfaces:**
- Consumes Task 1 validator.
- Produces fixture contract that Social Buyer Intelligence must emit.

- [ ] **Step 1:** Add fixture-loading tests for all four source combinations.
- [ ] **Step 2:** Add negative fixture proving a TikTok/Instagram inference cannot masquerade as verified purchase history.
- [ ] **Step 3:** Run all intake tests and compileall.

### Task 3: CBI research handoff mapping without mutation

**Files:**
- Create: `skills/investigate-customs-buyers/scripts/social_radar_handoff.py`
- Create: `tests/test_social_radar_handoff.py`

**Interfaces:**
- Consumes normalized Task 1 bundle.
- Produces `build_social_radar_research_handoff(bundle: dict) -> dict` with direct evidence, inference ledger, routes, discovery provenance and recommended CBI research priority.

- [ ] **Step 1:** Write RED tests requiring zero CRM/outreach side effects and preservation of every route/evidence source.
- [ ] **Step 2:** Implement pure mapping only; no Runtime construction and no MCP mutation call.
- [ ] **Step 3:** Run focused tests, privacy scan, compileall, then full repository unittest before any PR readiness claim.
