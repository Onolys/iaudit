---
status: approved
summary: Nine core tasks for the checker, including the timeframe check moved into core; LLM observes, code decides; one gated optional row.
date: 2026-10-11
---
# Tasks: 05 Check

Source of truth: [PRD.md](PRD.md). For each linked claim, decide verdict, concerns, explanation and `suggested_revision` as 02 `ClaimDraft`s. The verifier LLM only observes; code decides. The timeframe check (bucket 4) is core, so all 8 ADHD variants must pass (07 O-3).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Entry points, stalled and out-of-scope pass-through | 04 | todo |
| 2 | Group A code checks and missing-role skip | 1 | todo |
| 3 | Verifier call: observations and P1 flags, fixed floors | 1 | todo |
| 4 | Polarity, ordinal compare both ways, minimal at-least cues | 3 | todo |
| 5 | Timeframe check (core) | 3 | todo |
| 6 | Certainty, conflicting accounts, causal, context gaps, inference | 3 | todo |
| 7 | Evidence roles, decision table D0-D9, dedup | 4, 5, 6 | todo |
| 8 | Explanation templates and `suggested_revision` | 7 | todo |
| 9 | Failure handling, logging, config, variant-map test | 8 | todo |
| 10 | [OPTIONAL, gated] Optional items | all core in every SP | todo |

## Task 1 — Entry points
What it is / what it means: The checker surface 06 calls (R1).
What changes at a high level: `check_claims`, `check_one`, `stalled_draft`, `passthrough_oos` (copies 03's `oos_reason`, resolved O-12), `decide`.
Done when: stalled and out-of-scope claims produce valid drafts with zero LLM calls.

## Task 2 — Group A checks
What it is / what it means: Code-only reporter and question-as-answer checks (R2, D5, D6).
What changes at a high level: A3 reporter attribution (speaker string or role), A9 question-as-answer for interviewer question turns, the locked missing-role rule (skip, keep `ambiguous_turns`; resolved O-7), zero-call short-circuits.
Done when: acceptance 4 passes, including the call counter.

## Task 3 — Verifier call
What it is / what it means: One mid-tier call per remaining claim (R3, D2, D3, D10).
What changes at a high level: Input is the claim plus the turns 04 showed; output is per-item relation, polarity, amounts, timeframe, certainty, experiencer, and claim-level P1 flags with confidence. Fixed floors 0.5 (P0) and 0.6 (P1), no calibration.
Done when: a stub verifier's output parses and low-confidence flags are dropped and counted (acceptance 6 core).

## Task 4 — Polarity and amounts
What it is / what it means: Buckets 2, 5 and 7 decided in code (R4 items 1-3, D7).
What changes at a high level: Polarity compare; ordinal compare with 03 `step_diff` in both directions ("inflates" / "understates", same concern type); materiality `|d| >= 1` with the adjacent-ambiguous band (O-1 deferred); the minimal at-least cue list (resolved O-2).
Done when: acceptance 3 core passes, including faithful S5 not flagged.

## Task 5 — Timeframe check (core)
What it is / what it means: Bucket 4, moved into core so V5 passes (R4 item 4, D9, row D6).
What changes at a high level: Compare claim timeframe with each item's; demote mismatched items to `qualifying`; emit `timeframe_mismatch` only when no support remains. Implicit-current claims fire only at high confidence.
Done when: V5 ("He currently forgets work assignments weekly") yields `insufficient_evidence` + `timeframe_mismatch` with turn 17 `qualifying`.

## Task 6 — Remaining signals
What it is / what it means: Quick-pass P1 buckets and the inference rule (R4 items 5-9).
What changes at a high level: Certainty (claim unhedged vs strongly hedged item), conflicting accounts via verifier flag 11, causal links, correction/context/element gaps via flags; flag-cited items count as partial support; inference needs every premise to entail.
Done when: acceptance 7 passes and V6, V7, V8 yield their mapped concerns.

## Task 7 — Decision table
What it is / what it means: First-matching-row verdicts (R5, R6, D1, D8, D11).
What changes at a high level: Evidence roles out, rows D0-D9, dedup (one concern per type, specific beats generic, `wrong_attribution` beats `negation_reversal` per resolved O-8).
Done when: acceptance 2 and 5 pass, including the property test.

## Task 8 — Explanations
What it is / what it means: Neutral code templates (R7, D4).
What changes at a high level: Per-verdict and per-concern templates with no transcript text; `suggested_revision` on by default (resolved O-11).
Done when: the banned-word and no-copy tests pass (acceptance 9 core).

## Task 9 — Failure, logging, variant map
What it is / what it means: A failed claim stalls alone, and the variant map proves the checker (R8, acceptance 1, 8).
What changes at a high level: Timeout, bad JSON twice and unjudged items stall only that claim; `check_claims` never raises; counts-only logs; config keys.
Done when: with a stub verifier, the faithful claims and all 8 variants (V5 included) yield the listed verdicts and concerns.

## Task 10 — [OPTIONAL, gated] Optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: Confidence calibration, code rate-ratio check, at-least cue refinements, few-shot leak tests.
Done when: each optional acceptance part passes.
