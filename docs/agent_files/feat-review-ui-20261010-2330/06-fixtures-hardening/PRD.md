---
status: draft
summary: Extra fictional mock example pairs (long, partial, out-of-range, unicode, empty-evidence, out-of-scope, no-claims), fixture validation test, final colourblind-checked palette, mock-mode end-to-end smoke test, and manual pre-release checks.
date: 2026-10-10
---
# PRD: 06 Fixtures and hardening

Repo/branch: iaudit / `feat/review-ui` · Depends on: 02-contract-core, 03-transport-mock-errors, 04-review-shell-left-pane, 05-claim-detail-right-pane · Owns: new files in `docs/contracts/examples/`, the examples rows of `docs/contracts/README.md`, `frontend/src/tokens/` palette values, `frontend/scripts/`, `frontend/src/fixtures/*.test.ts`, `frontend/src/e2e/*.test.tsx`, `docs/testing/review-ui.md`

## TL;DR
Close the initiative: add fictional example pairs that exercise every edge the UI promises to handle, prove each pair against the schemas and SP02 checks, lock the palette after a colourblind-simulation check, and add one mock-mode end-to-end smoke test plus a short manual checklist. No new features, no contract change.

## Problem
SP02-05 are unit-tested on inline data and the single worked example, which has one section, five short claims, no emoji, no warnings. Brainstorm risks still open: underline noise on long assessments, code-point bugs on real text, colours that fail for colourblind reviewers, and no proof the whole flow works in mock mode.

## Goals / Non-Goals
**Goals**
- Mock-mode-selectable pairs covering each edge listed in R1.
- Automated check that each pair is valid (or deliberately flagged in the documented way).
- Final palette hex + underline thickness, with a repeatable check.
- One end-to-end smoke test; manual checklist for what jsdom cannot see.

**Non-Goals**
- Contract/schema changes; `schema_version` stays `1.0.0`. Real clinical, real-person or real-sounding attributed content: all fixtures are fictional.
- Backend, CI pipeline, visual-regression tooling, Playwright suite, load testing beyond one budget check.
- New UI features. Fixes found here go back to the owning SP as bug fixes.

## Requirements

**R1 Fixtures** in `docs/contracts/examples/`. Naming follows SP03's convention; per PRD 03 R4: `<slug>.request.json` + `<slug>.response.json` (registry regex `^(?:(.+)\.)?(request|response)\.json$`), existing `request.json`/`response.json` = pair `default`; mock matches by exact `request_id`, else deep-equal when the request has none. Every `request_id` must be unique across pairs.
| Slug | Purpose | Key content |
|---|---|---|
| `long` | Underline-noise and perf check | 3 sections (one string `score`, one no `label`), about 40 claims spanning all verdicts (about 2,000+ chars of reasoning), 300+ turns, evidence far from claims so expansion is meaningful, cross-turn spans |
| `partial` | Warnings banner and partial state | `status: partial`, 4 sections, `section_not_processed` for one (no claims there), plus `ambiguous_speaker`, `input_truncated`, `other`; claims in processed sections only |
| `out-of-range` | Bounds handling | One claim span past section length, one claim whose evidence span is past turn length, one claim with an end-pointer `char: 0` cross-turn span, one overlap with a neighbour; a `span_out_of_range` warning for a flagged claim; the other claims valid and unaffected |
| `unicode` | Code-point correctness | Emoji (`👍`), astral CJK (`𠀋`), flag (2 code points), ZWJ family (span cuts mid-grapheme), combining accent, in both transcript and assessment; claims after each; an empty turn inside a cross-turn span |
| `empty-evidence` | Empty states | `insufficient_evidence` with `evidence: []` and one with only qualifying evidence; request has **no** `request_id`, turns without `role` or `timestamp` (header falls back to `#index`) |
| `out-of-scope` | Out-of-scope only | All claims `out_of_scope` with reasons, no concerns, one section |
| `no-claims` | Zero claims | `status: complete`, `claims: []` |
| `shared-turn` | Multi-role painting and expansion merging | Two excerpts of one claim sharing a turn with different roles; two excerpts 5 turns apart that merge after one expand each |
Rules: every response satisfies the response schema; every pair except `out-of-range` also satisfies SP02 checks with zero flags. `out-of-range` is **deliberately non-conforming to contract rule 1** (spans must lie inside the input) and is the only such pair; the contract README table marks it so. Pair offsets are computed, not hand-counted: a one-off builder script `frontend/scripts/build-fixtures.mjs` takes marked-up fictional text (`[[claim]]` markers) and emits JSON offsets by `Array.from` code points; generated JSON is committed, the builder is a dev tool (not run in CI or tests). Wording in explanations follows mission: "potential concern", "not substantiated by the supplied interview".

**R2 Contract README.** Add the new pairs to the file table in `docs/contracts/README.md` (one row "More fictional pairs" pointing at the slugs, and a sentence that `out-of-range` intentionally breaks rule 1 to test consumers). Doc-only: no schema or rule change, so no `schema_version` bump (Versioning: wording-only changes stay on the same version). Same commit as the fixtures.

**R3 Fixture validation test** (`frontend/src/fixtures/fixtures.test.ts`, node env). Glob all example pairs via `@contracts`. For each: `validateRequest` ok; `validateResponse(raw, request)` ok; `analyzeResponse` flags equal an explicit expectation table in the test (empty for all but `out-of-range`, where the exact flagged claim ids and `SpanIssue.code`s are listed); every non-flagged evidence/claim `walkSpan` succeeds; `request_id` mapping unique across pairs; each response has exactly one pair (no orphan file). Hand-written literal expectations (never recomputed with the same code): `unicode` substring table (e.g. claim X yields exactly `"👍"`; evidence Y yields `"𠀋"`), `long` claim count and counts per verdict, `partial` warning codes. `buildChunks` on `long` finishes within a generous budget (<100 ms, measured) - answers SP02's performance open item.

**R4 Palette lock.** Edit only `frontend/src/tokens/` values (hex, underline thickness) - no API change. Candidates start from the Okabe-Ito set (e.g. green `#009E73`, amber `#E69F00`, red `#D55E00`) tuned darker where needed for contrast, grey and neutral from a grey ramp; values unverified until the check runs. Method (`frontend/scripts/check-palette.mjs`, dev dependency `culori`): simulate protanopia, deuteranopia, tritanopia and greyscale on every verdict and role colour, compute CIEDE2000 between each pair that appears together (verdicts with each other; roles with each other), and contrast against white and the selected-claim background. Thresholds: pair deltaE >= 12 under each simulation for the three coloured verdicts and three roles (grey and neutral are separated by underline style and icon, so >= 6); non-text contrast >= 3:1 (underline, border); text on badge >= 4.5:1. The same thresholds are asserted by a Vitest test over the tokens so a later palette edit cannot silently regress. Visual confirmation: Chrome DevTools "Emulate vision deficiencies" on screenshots of the `long` and `shared-turn` fixtures, recorded in the manual checklist. If a pair cannot pass on colour alone, widen the other cue (underline style, icon, label) rather than skipping the check.

**R5 End-to-end smoke test** (`frontend/src/e2e/mock-flow.test.tsx`, Vitest + Testing Library + jsdom): with mock mode on and `fetch` stubbed to throw (proving no network), render `<App />`, upload the default request (a `File`), await the review shell, assert: first claim selected, right pane shows verdict + explanation in order, clicking a second claim changes the pane, a verdict count jumps and ‹ 1 of N › steps, a concern click dims others, expand adds turns. Repeat the upload for `partial` (warnings banner visible, `section_not_processed` section marked), `out-of-range` (warning badge, rest of page intact), `unicode` (highlighted text equals the literal emoji), `no-claims` (non-crashing empty review), and an invalid request file (error screen, no POST). Console errors fail the test.

**R6 Manual checklist** (`docs/testing/review-ui.md`, linked from `docs/testing/README.md`): what to eyeball before a release - underline noise on `long` at 1280 and 1024 px widths, colourblind emulation screenshots, one real backend round trip (timing and cancel, CORS; the brainstorm's synchronous-POST risk) once a backend exists, sticky headers, scroll behaviour. Includes a legend of every fixture and its intent. Run commands: `npm run dev` with `VITE_MOCK=true`.

## Architecture
```
docs/contracts/examples/<slug>.{request,response}.json   (data only; SP03 mock loader reads via glob)
frontend/scripts/   build-fixtures.mjs (dev only), check-palette.mjs
frontend/src/fixtures/fixtures.test.ts    all pairs vs schemas + SP02
frontend/src/e2e/mock-flow.test.tsx       App-level smoke via mock mode
frontend/src/tokens/                       final palette (values only)
```
Fixtures are the only shared artefact: the same JSON feeds mock mode, unit tests and manual review, so a fixture bug is caught by R3 first.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Where fixtures live | `docs/contracts/examples/` (contract-adjacent) | `frontend/fixtures/` | Locked: mock mode serves from contracts examples; the backend can reuse them |
| 2 | Offset authoring | Builder script from marked-up text | Hand-count offsets; ask an LLM for offsets | Hand counting emoji is exactly the bug under test; builder is deterministic |
| 3 | Intentionally non-conforming pair | One pair (`out-of-range`), labelled in README | Test only with inline mutation | Needed for manual and e2e look at the badge; README labelling prevents misuse as a model response |
| 4 | Contract README edit | Doc-only, no version bump | Bump patch; leave README unchanged | Versioning rule: wording-only stays same version; table would otherwise mislead |
| 5 | Colourblind method | Scripted simulation + deltaE thresholds + manual DevTools check | Eyeball a simulator website once | Repeatable, guards later edits; manual step covers rendering reality |
| 6 | Smoke test tool | Vitest + Testing Library | Playwright | Already installed (SP01); no browser download; machine is memory-limited; layout/visual items are on the manual list |
| 7 | Mock pair selection | Follow PRD 03 (`request_id`, else deep-equal) | By filename; dropdown | Owned by SP03; `empty-evidence` has no `request_id` to exercise the deep-equal path |
| 8 | Perf check | One assertion on `long`, loose budget | Benchmark suite | Light; catches order-of-magnitude regressions |
| 9 | Fixture content | Fully fictional, no real names or institutions | Anonymised real transcripts | Safety; mission forbids invented attribution as real |

## Manual steps
- Take and attach colourblind-emulation screenshots (DevTools) of `long` and `shared-turn`; owner decides final visual acceptance.
- Real backend round trip when a backend exists (not in this repo).

## Risks / Open Questions
- [RESOLVED: PRD 03 R4 convention adopted] Mock naming and selection. SP03 owns the registry invariant test; R3 here adds content checks on top.
- [RESOLVED: SP03 flagged the README wording] Contract README note is made here (R2).
- [OPEN] `culori` filters are an approximation (Machado/Vienot models) of colour deficiency; acceptable as a gate, not a clinical claim. Confirm acceptable.
- [OPEN] Whether the builder script should live in `docs/contracts/` for backend reuse; kept in `frontend/` to avoid scope growth.
- [OPEN] Palette finals depend on the check; hex values in R4 are candidates only. Recorded in `tokens/` once passed.
- [OPEN] ZWJ/lone surrogate behaviour across Python vs JS (SP02): lone surrogates cannot appear in valid JSON text, so not fixtured.
- [DEFERRED] Playwright/visual-regression suite; revisit if layout regressions bite.
- [DEFERRED] Performance beyond ~500 turns.
- [RESOLVED: separate pairs] One fixture per behaviour so a failing test names the cause.

## Acceptance Criteria
- Every pair in R1 exists, passes R3, and `out-of-range` flags exactly its expected claims.
- `unicode` literal-substring assertions fail if slicing is swapped for `String.prototype.slice`.
- `npm run check:palette` (script) exits 0; token contrast/deltaE Vitest passes; thresholds from R4.
- Mock-mode smoke test passes all listed flows with network stubbed and no console errors.
- `docs/contracts/README.md` lists the new pairs and flags `out-of-range`; schemas and `schema_version` unchanged (`git diff` on `*.schema.json` empty).
- `docs/testing/review-ui.md` exists with the checklist and fixture legend.
- `npm ci && typecheck && lint && test && build` all pass.
