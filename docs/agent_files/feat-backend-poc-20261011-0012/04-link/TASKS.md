---
status: approved
summary: Six core tasks for BM25 shortlisting, whole vs shortlist mode, the linker call, deterministic validation, retry/stall, and LinkResult wiring; one gated optional row.
date: 2026-10-11
---
# Tasks: 04 Link

Source of truth: [PRD.md](PRD.md). For each in-scope claim, find the transcript turns that bear on it: shortlist with BM25 (or whole transcript when small), one mid-tier linker call, then deterministic validation.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Stemmer, BM25 top-k, Q/A and clarification neighbors | 03 | todo |
| 2 | `auto` choice between whole transcript and shortlist | 1 | todo |
| 3 | Linker prompt and call with one `cache_prefix` | 2 | todo |
| 4 | Validation: shortlist membership, `locate()` dry run, snapping, answer status, `ambiguous_turns` | 3, 02 | todo |
| 5 | Retry and per-claim `stalled` | 4 | todo |
| 6 | `LinkResult`, entry points, logging, config, fixture test through `assemble` | 5 | todo |
| 7 | [OPTIONAL, gated] Optional items | all core in every SP | todo |

## Task 1 — Shortlist
What it is / what it means: Cheap retrieval so the linker sees only likely turns (R1 core, D1 BM25 only, D2, D10).
What changes at a high level: Built-in stemmer and tokenizer, BM25Okapi index over turns with paired-question tokens, top-k query from the claim, then neighbors: the question before a responding hit, replies after a question hit, and the clarification window. Defaults k=8, window 4, cap 30 ship as stated (O-3 deferred).
Done when: shortlist tests on the ADHD fixture return the gold turns for the variant claims.

## Task 2 — Mode choice
What it is / what it means: Send the whole transcript when it is small (R2, D4).
What changes at a high level: `LINK_MODE=auto|whole|shortlist`; `auto` uses `ceil(chars/4)` against `LINK_WHOLE_MAX_TOKENS` 8,000 (O-2 deferred). Tests force `shortlist` on ADHD.
Done when: tests cover each mode and the threshold boundary.

## Task 3 — Linker call
What it is / what it means: One mid-tier call per in-scope claim (R3, R6, D5, D11).
What changes at a high level: Prompt and strict output (evidence items with turn, role, segments, inference shape); single `cache_prefix` (system + transcript in whole mode, system + stage block in shortlist mode); `build_link_context` and `link_one` per 06 R8.
Done when: a fixture-replayed call parses for the ADHD claims.

## Task 4 — Validation
What it is / what it means: Code checks every cited turn (R4, D6, D7).
What changes at a high level: Drop cites outside the shortlist; dry-run `locate()` on each segment; snap to the full question turn (kept per resolved O-8); compute `answer_status` from 03 acts and demote `supporting` to `qualifying` for question-only or non-answer turns; inference checks; dedup and caps; fill `ambiguous_turns` for evidence turns with missing role (resolved O-1f).
Done when: tests cover each drop and demotion, and V6 turn 23 accepts either `contradicting` or `qualifying` (resolved O-9).

## Task 5 — Retry and stall
What it is / what it means: A failed claim stalls alone (R5, D8).
What changes at a high level: One retry on invalid output when budget allows, then mark the claim `stalled`; client errors map to `stalled` per claim.
Done when: tests show one stalled claim while others link.

## Task 6 — Wiring
What it is / what it means: The output 05 and 02 consume (R7, R8).
What changes at a high level: `LinkResult` (items, shortlist, mode, status), `link_claims`, `to_evidence_drafts`, counts-only logging, config keys. 07 reads `LinkResult.shortlist` from a stub-linker run for recall.
Done when: a fixture test runs link output through 02 `assemble` to a schema-valid response.

## Task 7 — [OPTIONAL, gated] Optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: Per-speaker floor, later-correction pull, RRF fusion with rapidfuzz, `shortlist_only()` recall hook, cache tuning, leak test.
Done when: each optional acceptance part passes.
