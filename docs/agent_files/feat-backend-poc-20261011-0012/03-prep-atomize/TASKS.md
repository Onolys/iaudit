---
status: approved
summary: Eight core tasks for rules-only prep, Q-A pairing, scales, the claim model, the atomizer prompt and call, span validation with retry, and logging; one gated optional row.
date: 2026-10-11
---
# Tasks: 03 Prep + Atomize

Source of truth: [PRD.md](PRD.md). Rules-only dialogue acts and question-answer pairing over turns, plus one mid-tier atomizer call per section that splits the assessment into checkable claims with slots.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Turn index and rules-only dialogue acts | 01 | done |
| 2 | Question-answer pairing by speaker | 1 | done |
| 3 | `scales.py` ordinal scales | 01 | done |
| 4 | `AtomicClaim` model, fixed `oos_reason`, config | 01 | done |
| 5 | Atomizer prompt and "Jordan" few-shot | 4 | done |
| 6 | `atomize_section` / `atomize_sections` call | 3, 5, 02/T2 | done |
| 7 | Span resolution, validation, one retry, section failures | 6 | done |
| 8 | Counts-only logging and sentinel test | 7 | done |
| 9 | [OPTIONAL, gated] Optional items | all core in every SP | todo |

## Task 1 — Turn index and dialogue acts
What it is / what it means: Deterministic per-turn acts with no LLM (R1, R2, D3, D5).
What changes at a high level: `IndexedTurn` (role copied, never inferred; `act_source=rule`) and the R2 rule table for question, backchannel, correction, hypothetical and answer. Every unsure case resolves to no act. Polar tokens after another speaker's question are `answer`; pure continuers stay `backchannel`.
Done when: tests cover each rule row, ADHD turn 13 "Hm." as backchannel, and turn 5 "actually" as emphasis.

## Task 2 — Question-answer pairing
What it is / what it means: Links answers to questions by speaker string only (R4, D4).
What changes at a high level: `QAPair(question_index, response_indices)` and `responds_to`, ending at the questioner's next turn or another speaker's question. Works with missing roles.
Done when: pairing tests pass with and without roles.

## Task 3 — Ordinal scales
What it is / what it means: Shared frequency and severity buckets used by 05 (R8, D10).
What changes at a high level: `FrequencyBucket` 0-5 and `SeverityBucket` 0-4, `bucket_from_rate()`, `lexicon_bucket()`, and `step_diff()` signed in both directions. Numeric text normalizes to `rate_per_week` and wins over the LLM's bucket.
Done when: "three or four times a week" is 3.5/wk `often`, "twice a month" is 0.46/wk, and `step_diff` signs are tested both ways.

## Task 4 — Claim model and config
What it is / what it means: The claim shape 04, 05 and 02 consume (R6, R11, D6, D8, D9, D13).
What changes at a high level: `AtomicClaim` with segments, `span_hint`, proposition, scope and `oos_category`, fixed `oos_reason` sentence per category (resolved 05 O-12), subject, `reported_by` list, polarity, quantities, timeframe, hedged, causal links. Assessor observations map to `unobservable` (resolved O-3). Config keys `ATOMIZE_MAX_CLAIMS`, `ATOMIZE_MAX_TOKENS`, `ATOMIZE_RETRY`.
Done when: model validation tests pass and `oos_reason` is set iff out of scope.

## Task 5 — Atomizer prompt and few-shot
What it is / what it means: The prompt that enforces the granularity rules (R7, R10, D11).
What changes at a high level: System prompt with scope rules, taxonomy, strict output schema, verbatim-segment and roster rules; `prompts/atomize_fewshot.json` with 4 fictional "Jordan" examples marked `split: "prompt"`. Checked by hand for no overlap with eval fixtures (the CI leak test is optional).
Done when: the prompt renders from tier names only and the few-shot file loads.

## Task 6 — Atomizer call
What it is / what it means: One mid-tier call per section, run concurrently (R5, D1).
What changes at a high level: `atomize_section` and `atomize_sections` send section text plus a speaker roster (no transcript text), with `cache_prefix` = system + taxonomy + few-shot and `timeout_s` bounded by the deadline.
Done when: a fixture-replayed ADHD section returns parsed claims.

## Task 7 — Validation, retry, failure
What it is / what it means: Claims are located and checked before leaving 03 (R7, R9, D7, D12).
What changes at a high level: Resolve segments via 02 `locate()` and compute `span_hint`; check ids, links, scope/category, roster speakers, overlap, cap and coverage gaps; one terse retry (ids and error kinds only) when budget allows; drop still-invalid claims; mark section failures with the R9.5 reasons. Never raises per section. Dropped claims and gaps go to logs only (resolved O-4).
Done when: tests cover each failure reason, the retry path, and a skipped retry under low budget.

## Task 8 — Logging
What it is / what it means: Counts-only observability (R12).
What changes at a high level: Log turns, claims per section, drops, gaps, retries and failures through 01's allowlist.
Done when: a sentinel test shows no turn, section, segment or proposition text in logs.

## Task 9 — [OPTIONAL, gated] Optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: Cheap-LLM act tagging for unsure turns, the 8-word leak CI test, the soft-timeout path.
Done when: each optional acceptance part passes.
