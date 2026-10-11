---
status: draft
summary: Three tasks: two fictional fixture pairs with README update, fixture validation test, mock-mode end-to-end smoke test.
date: 2026-10-10
---
# Tasks: 06 Fixtures and hardening

Source of truth: docs/agent_files/feat-review-ui-20261010-2330/06-fixtures-hardening/PRD.md. Adds the `partial` and `out-of-range` mock pairs, proves all pairs against schemas and 02's checks, and adds one App-level smoke test. No contract or schema change. Depends on 02, 03, 04, 05.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Fixture pairs and contracts README | none | done |
| 2 | Fixture validation test | 1 | todo |
| 3 | Mock-flow smoke test | 1, 2, 04, 05 | todo |

## Task 1 — Fixture pairs and contracts README
What it is / what it means: Hand-authored fictional mock data for the warnings and span-flag states (PRD R1, R2; Decisions 1-4, 7).
What changes at a high level: Add `partial.request.json`/`partial.response.json` (status `partial`, 2 sections, `section_not_processed` plus one other warning, 2-3 claims in the processed section) and `out-of-range.*` (a few claims, exactly one span past the section length) to `docs/contracts/examples/`, using 03/T2's naming convention, unique `request_id`s, offsets from the default example, mission wording, no real names. Update the examples row of `docs/contracts/README.md` to list both and say `out-of-range` intentionally breaks rule 1. No `schema_version` bump.
Done when: both pairs exist, schemas unchanged (`git diff` empty on `*.schema.json`), README row updated in the same commit.

## Task 2 — Fixture validation test
What it is / what it means: Automated proof every pair is valid (PRD R3).
What changes at a high level: Add `frontend/src/fixtures/fixtures.test.ts` (node env) that globs all pairs via `@contracts` and checks `validateRequest`, `validateResponse(raw, request)`, `analyzeResponse` flags against a literal table (none, except the one flagged claim id in `out-of-range`), unique `request_id`s, no orphan files, `partial` warning codes, and `default` claim count with one claim per verdict.
Done when: test passes; fixing a deliberately wrong offset makes it fail clearly (fixture bugs are caught here first).

## Task 3 — Mock-flow smoke test
What it is / what it means: One end-to-end check that the whole flow works in mock mode with no network (PRD R4; Decision 5).
What changes at a high level: Add `frontend/src/e2e/mock-flow.test.tsx` (Vitest + Testing Library + jsdom): mock mode on, `fetch` stubbed to throw, console errors fail the test. Render `<App />` and upload `default` (first claim selected, verdict then explanation in right pane, selecting another claim changes it, a verdict count click shows ‹ 1 of N ›); repeat for `partial` (warnings banner, not-processed section marked), `out-of-range` (warning badge, rest intact), and an invalid request file (error screen, no POST). Bugs found go back to the owning sub-project.
Done when: test passes; `npm ci`, typecheck, test and build pass.
