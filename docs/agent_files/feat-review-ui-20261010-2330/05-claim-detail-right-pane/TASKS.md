---
status: draft
summary: Three tasks: ClaimDetail header, suggestion and concerns; excerpt rendering with chunks and role styling; expansion controls and special states.
date: 2026-10-10
---
# Tasks: 05 Claim detail (right pane)

Source of truth: docs/agent_files/feat-review-ui-20261010-2330/05-claim-detail-right-pane/PRD.md. One `ClaimDetail` component in `frontend/src/claim-detail/`, built on 02's position helpers (`orderEvidence`, `walkSpan`, `buildChunks`, `sliceCodePoints`) and 01's tokens. Buildable in parallel with 04.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | ClaimDetail header, suggestion and concerns | none | todo |
| 2 | Excerpt rendering | 1 | todo |
| 3 | Expansion controls and special states | 2 | todo |

## Task 1 — ClaimDetail header, suggestion and concerns
What it is / what it means: The component shell and everything above the excerpts (PRD R1-R4; Decisions 1, 2, 7, 8, 10).
What changes at a high level: Add `ClaimDetail({claim, request, check})` with local `activeConcern` state, verdict badge from `VERDICT_STYLE`, plain-text explanation, the insufficient-evidence line, and the out-of-range warning strip. Add the "Suggestion — not applied" box (only for non-null text, no buttons). Add `concernLabels.ts` (12 mission names in `CONCERN_TYPES` order, raw-value fallback) and the concern list; a concern is an `aria-pressed` toggle only when it cites a placed evidence id.
Done when: tests cover section order for `c-contradicted`, badge icon + label, suggestion absent for null and without button otherwise, empty/dangling concern is not a button; no `dangerouslySetInnerHTML`.

## Task 2 — Excerpt rendering
What it is / what it means: Transcript-order excerpts shown from exact slices (PRD R5 rendering, R7; Decisions 3, 4, 6, 9).
What changes at a high level: Call `orderEvidence`, `walkSpan` and `buildChunks` (memoised) and render chunks as `TurnRow`s: speaker, optional role, timestamp verbatim or `#<0-based index>`, highlighted slice via `sliceCodePoints` with the rest dimmed, role-coloured left border, role chip on the first highlighted row, "Audit note (paraphrase, not a quote):" note, "(empty turn)", neutral highlight for shared turns. Wire concern activation to `emphasised`/`dimmed` classes. Out-of-range evidence becomes one-line notices, never sliced.
Done when: tests pass for transcript order with reversed evidence, `c-partial` turns 2-3 as one excerpt with the split at char 45, timestamp/index, note prefix, concern emphasis and clearing, shared-turn overlap without duplicate turn, out-of-range notice without throwing.

## Task 3 — Expansion controls and special states
What it is / what it means: GitHub-style +3 expansion and the empty-state table (PRD R5 expansion, R6, R8; Decision 5).
What changes at a high level: Add `expansion` state per evidence id and `ExpandControl` rows at chunk edges and gaps ("Show 3 more turns above/below (N hidden)", removed at 0, +3 via `buildChunks`). Add context-only row styling. Implement the R6 states: `out_of_scope` reason block with no concerns or excerpts; "No excerpt in the supplied interview."; "No excerpts to show.". Add remaining tests including key change resetting concern and expansion.
Done when: one "above" click adds exactly 3 turns (fewer at index 0), neighbours merge without repeating a turn, controls hide at bounds; `c-insufficient`, `c-oos`, and `out-of-range` states render; `npm test`, lint, typecheck pass; `docs/contracts/` unchanged.
