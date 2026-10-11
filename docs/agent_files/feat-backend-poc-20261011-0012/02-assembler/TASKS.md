---
status: approved
summary: Nine core tasks for the assembler: drafts, locate(), evidence and claim resolution, repairs, rule 9, warnings, final validation, example reproduction; one gated optional row.
date: 2026-10-11
---
# Tasks: 02 Assembler + contract enforcement

Source of truth: [PRD.md](PRD.md). Turns internal drafts from 03-05 into a contract-valid response in `backend/src/iaudit_backend/assembler/`. `locate()` here is the only offset matcher.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Draft models, `assemble()` entry point, counts-only report | 01 | done |
| 2 | `locate()`: exact, normalized, guarded fuzzy, ellipsis, hint | 1 | done |
| 3 | Evidence resolution and `eN` ids | 2 | done |
| 4 | Claim resolution and overlap policy | 2 | todo |
| 5 | Repair table | 3, 4 | todo |
| 6 | Rule 9 core copy check | 5 | todo |
| 7 | Warnings and status | 5 | todo |
| 8 | Final validation: `check_rules` and schema, quarantine once | 6, 7 | todo |
| 9 | Reproduce `examples/response.json` spans | 8 | todo |
| 10 | [OPTIONAL, gated] Optional items | all core in every SP | todo |

## Task 1 — Draft models and entry point
What it is / what it means: The internal input model 03-06 produce (Inputs table, D-11).
What changes at a high level: `ExcerptSegment`, `EvidenceDraft`, `ConcernDraft`, `ClaimDraft` (`segments` + `span_hint`), `InternalAudit`; `assemble(request, internal, cfg)` returning a response and an `AssembleReport` that holds counts only; `AssemblyError`.
Done when: models round-trip in tests and the report holds no text fields.

## Task 2 — `locate()`
What it is / what it means: The single offset-resolution function (R1, D-2, D-4).
What changes at a high level: Exact match, then normalized match with an index map back to original code points, then guarded fuzzy (min length 12, threshold 90, window ratio, digit/number-word/negator multiset guard, word-boundary snap). Ellipsis fragments and nearest-to-hint for repeats. Offsets are on strings exactly as received.
Done when: tests cover each tier, the guard rejecting "twice" vs "once" and "did not" vs "did", ellipsis hull rejection, and `\r\n` counted as two code points.

## Task 3 — Evidence resolution
What it is / what it means: Evidence spans only from the cited turn (R2, D-3, D-5).
What changes at a high level: Locate each segment in its turn; drop unmatched segments and fully unmatched evidence (and its concern keys); merge consecutive cross-turn segments only when they meet the edge rule (slack 0), else split; assign `e1..eN`; collapse identical span+role duplicates.
Done when: tests cover single, merged cross-turn, split, and dropped evidence with concern-key cleanup.

## Task 4 — Claim resolution and overlap policy
What it is / what it means: Claim spans inside one section with no overlap (R3, D-8 core).
What changes at a high level: Verify `span_hint`, else locate per segment in order; drop unlocatable claims with an `other` warning; a non-blank section with zero located claims becomes `section_not_processed` (`no_claims_located`, per resolved O-7). Overlap: nested drops the outer, identical keeps the more severe, partial drops the less severe; each drop adds an `other` warning.
Done when: tests cover each overlap case and the `no_claims_located` path.

## Task 5 — Repair table
What it is / what it means: Enforce contract rules 1-12 per claim after drops (R4, D-6, D-7).
What changes at a high level: Apply the R4 rows in order: drop empty concerns, `supported` without support, contradicting under `supported`, `contradicted` without contradiction, empty `partially_supported`, contradiction under `insufficient_evidence`, `out_of_scope` stripping, stalled claims, rule-7 key filtering. Verdict changes swap in a fixed explanation and add an `other` warning. Never upgrades to `supported`.
Done when: one test per R4 row.

## Task 6 — Rule 9 core copy check
What it is / what it means: Explanations never copy transcript text (R5 core, D-9 core).
What changes at a high level: Flag quoted spans of 4+ words found in the transcript and timestamp patterns; drop `note` fields that are exact substrings of a turn; null `suggested_revision` on violation; strip offending sentences or fall back to fixed text with an `other` warning.
Done when: tests show each violation kind repaired and fallback text used when nothing is left.

## Task 7 — Warnings and status
What it is / what it means: Warning order and the `partial` rule (R6).
What changes at a high level: Emit `section_not_processed`, defensive `span_out_of_range`, `ambiguous_speaker` (turn indexes only), `input_truncated`, and `other` in the R6 order; `status` is `partial` iff any section is not processed; `request_id` copied when present.
Done when: tests cover each warning and both status values.

## Task 8 — Final validation
What it is / what it means: Never ship an invalid audit (R7, D-10).
What changes at a high level: Independent `check_rules()` for rules 1, 7, 8, 10, then schema validation via 01's loader; quarantine offending claims once and re-validate; a second failure or a non-claim error raises `AssemblyError`.
Done when: injected bad claims are quarantined, and a broken top-level field raises.

## Task 9 — Example reproduction
What it is / what it means: Proves the assembler against the contract example (acceptance 1).
What changes at a high level: Build drafts matching `docs/contracts/examples/response.json` and assemble them against `request.json`.
Done when: output spans and verdicts equal the example file.

## Task 10 — [OPTIONAL, gated] Optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: 8-gram copy check and the partial-overlap trim.
Done when: each optional acceptance part passes.
