---
status: draft
summary: Two small extra fictional mock pairs (partial, out-of-range), a fixture-validation test, one mock-mode end-to-end smoke test, and a contracts README table update. No palette work, no builder script.
date: 2026-10-10
---
# PRD: 06 Fixtures and hardening

Repo/branch: iaudit / `feat/review-ui` · Depends on: 02-contract-core, 03-transport-mock-errors, 04-review-shell-left-pane, 05-claim-detail-right-pane · Owns: new files in `docs/contracts/examples/`, the examples row of `docs/contracts/README.md`, `frontend/src/fixtures/*.test.ts`, `frontend/src/e2e/*.test.tsx`

## TL;DR
Add two small hand-authored fictional pairs (`partial`, `out-of-range`) next to the existing `default` pair, prove every pair against the schemas and SP02 checks, and add one mock-mode smoke test. No new features, no contract change.

## Problem
SP02-05 are unit-tested on inline data and the single worked example (one section, five claims, no warnings, `complete`). The warnings/partial state and the span-flag state have no mock data, and nothing proves the whole flow works end to end in mock mode.

## Goals / Non-Goals
**Goals**: mock pairs for partial and out-of-range; automated validity check of every pair; one smoke test.

**Non-Goals**: contract/schema changes (`schema_version` stays `1.0.0`); real or real-sounding content (all fictional); builder script; palette/colour-blindness work (SP01 holds the final palette); `long`, unicode, shared-turn, no-claims, empty-evidence, out-of-scope pairs; manual checklist doc; Playwright; CI; perf checks. Bugs found go back to the owning SP.

## Requirements

**R1 Fixtures** in `docs/contracts/examples/`, naming per PRD 03 R4 (`<slug>.request.json` + `<slug>.response.json`; existing `request.json`/`response.json` = pair `default`). Hand-authored (small; offsets taken from the default example's text) and caught by R3 if wrong. Each `request_id` unique across pairs.
| Slug | Content |
|---|---|
| `default` | existing; already covers all 5 verdicts, one section, evidence in several turns |
| `partial` | `status: partial`; 2 sections; `section_not_processed` warning for one (no claims there) plus one other warning; 2-3 claims in the processed section |
| `out-of-range` | A few claims; exactly one claim span past the section length (flagged), the others valid; may also carry a `span_out_of_range` warning for it |
Rules: every response satisfies the response schema; every pair except `out-of-range` has zero SP02 flags. `out-of-range` deliberately breaks contract rule 1 and is the only such pair. Explanations use mission wording ("potential concern", "not substantiated by the supplied interview"); no real names.

**R2 Contract README.** Update the examples row of `docs/contracts/README.md` to mention `partial.*` and `out-of-range.*` and that `out-of-range` intentionally breaks rule 1 to test consumers. Doc-only: no `schema_version` bump. Same commit as the fixtures.

**R3 Fixture validation test** (`frontend/src/fixtures/fixtures.test.ts`, node env). Glob all pairs via `@contracts`. For each: `validateRequest` ok; `validateResponse(raw, request)` ok; `analyzeResponse` flags match a literal table in the test (none, except the exact flagged claim id for `out-of-range`); `request_id`s unique; no orphan request or response file. Literal expectations: `partial` warning codes, `default` claim count and one-per-verdict counts.

**R4 Smoke test** (`frontend/src/e2e/mock-flow.test.tsx`, Vitest + Testing Library + jsdom): mock mode on, `fetch` stubbed to throw (proves no network). Render `<App />`, upload the default request as a `File`, await the review shell; assert: first claim selected, right pane shows verdict then explanation, clicking another claim changes the pane, a verdict count click shows ‹ 1 of N ›. Repeat upload for `partial` (warnings banner visible, not-processed section marked) and `out-of-range` (warning badge, rest of page intact), and an invalid request file (error screen, no POST). Console errors fail the test.

## Architecture
```
docs/contracts/examples/<slug>.{request,response}.json   (SP03 mock loader reads via glob)
frontend/src/fixtures/fixtures.test.ts    all pairs vs schemas + SP02
frontend/src/e2e/mock-flow.test.tsx       App-level smoke via mock mode
```
The same JSON feeds mock mode and tests; a fixture bug is caught by R3 first.

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| 1 | Fixture location | `docs/contracts/examples/` | `frontend/fixtures/` | Mock mode serves from there; backend can reuse |
| 2 | Offset authoring | Hand-authored + validation test | Builder script | Fixtures are small; R3 catches mistakes |
| 3 | Non-conforming pair | One (`out-of-range`), labelled in README | Inline mutation only | Needed for e2e badge check |
| 4 | README edit | Doc-only, no version bump | Bump patch | Wording-only stays same version |
| 5 | Smoke test tool | Vitest + Testing Library | Playwright | Already installed; light on memory |
| 6 | Mock pair selection | Per PRD 03 (`request_id`, else deep-equal) | Filename; dropdown | Owned by SP03 |
| 7 | Content | Fully fictional | Real transcripts | Safety; mission |

## Risks / Open Questions
- [RESOLVED: PRD 03 R4 convention adopted] Mock naming and selection.
- [RESOLVED: README note made here (R2)] Contract README wording.
- [RESOLVED: dropped; hand-authored fixtures + validation test] Builder script.
- [RESOLVED: cut, no colour-blindness checking] Colourblind tooling.
- [RESOLVED: input is normalized English, no emoji; no unicode fixtures] Unicode/lone-surrogate fixtures.
- [DEFERRED] `long` fixture, perf checks, Playwright/visual regression, manual checklist doc.

## Acceptance Criteria
- `partial` and `out-of-range` exist, pass R3; `out-of-range` flags exactly its one expected claim.
- Smoke test passes with network stubbed and no console errors.
- `docs/contracts/README.md` lists the new pairs and flags `out-of-range`; `git diff` on `*.schema.json` empty.
- `npm ci && typecheck && test && build` pass.
