---
status: draft
summary: Pure, deterministic gold/project functions that turn iAudit claim verdicts into TofuEval sentence and summary labels, plus frozen mapping.json v1.0.0, TofuEval metric registrations and slices, paper reference rows, per-item UI rows, and integrity reporting.
date: 2026-10-20
---
# PRD: C2 TofuEval projection & metrics

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: C1 `01-data-and-items` (items, requests), B3 `03-metrics-scoring` (registry, slicing, bootstrap, policies), B1 (contract 1.1.0 response shape) · Owns: `eval/datasets/tofueval/{projection.py, labels.py, metrics.py, item_rows.py, integrity.py, mapping.json, references.json}`, `eval/datasets/tofueval/mapping_history/` (created on first bump), `eval/tests/tofueval/` (projection, metrics, mapping, references tests + fictional fixtures). Shared edits: the `gold`/`project`/`item_row`/`pairs`/`mapping_version`/`report_extra` bodies in C1's `adapter.py` (thin delegation only), and the `levels`, `slices`, `metrics`, `references`, `mapping`, `gold_kind`, `pool_all` keys in C1's `metadata.json`.

## TL;DR
Given a saved `AuditResponse` and a C1 item, C2 produces a native TofuEval-style prediction: each summary sentence is labelled consistent / inconsistent / unresolved from the claims whose spans overlap it; the summary label aggregates sentences. C2 registers the TofuEval metrics (balanced accuracy, inconsistent-class P/R/F1, recall for 7 error types, concern agreement for 5, diagnostics, R4 dual-policy and R10 base-rate), the slice grid, paper reference rows, per-item rows for the UI, and the integrity block (mapping version, test-run count). Everything is pure Python over saved runs: no network, no LLM, no TofuEval text.

## Problem
- TofuEval gold is sentence-level binary plus post-hoc multi-label error types; iAudit emits atomic claims with five verdicts and 12 concerns. Without a frozen, deterministic projection, results are researcher-degrees-of-freedom (brief decisions 13-20, 23).
- Rules that decide results (boundary-crossing, meta sentences, unresolved handling, concern mapping) must be frozen and versioned before the first test run, and later projects (A adds `quantity_mismatch`) must not silently change old numbers.
- D2 needs per-item gold vs ours vs match to show without re-deriving anything in the frontend.

## Goals / Non-Goals
**Goals**
- `gold(item)` and `project(response, item)` implementing brief §5.5 exactly; hand-computed fixture tests.
- `mapping.json` v1.0.0 (brief §5.7) with a loader that is strict about its own contents and tolerant of new concern types.
- All metrics and slices in the locked list; `references.json` with all 10 Table 3 rows.
- Per-item rows (summary-level plus per-sentence detail) with no TofuEval text.
- Integrity block per report; frozen-file test.

**Non-Goals**
- Item construction, transcripts, requests, download (C1); registry, bootstrap, compare, run store (B2/B3); any UI (D); taxonomy changes (A).
- Four-way verdict claims, atomization quality, evidence-offset scoring, cross-sentence errors, attribution on MeetingBank.
- Any hard block on test runs (decision 13: informational only).

## Requirements
**Inputs (reconciled with C1/B2/B3)**
- C1 `Item` (B2 shape): `id`, `doc_id`, `split`; `meta` = `dataset, topic, topic_category, model_name, model_group ("original_five"|"model_extra")`; `payload.sentences` = `[{sent_idx, text, label: "yes"|"no" (raw; C2 normalises to consistent/inconsistent), types: [str], exp, contamination_identifier, start, end}]` (sorted by `sent_idx`, code-point offsets into section 0 of the assessment). Text and `exp` are in memory only.
- B3: C2 implements the adapter hook `pairs(item, gold, prediction, failure)` (B3 R1) emitting pairs at levels `sentence` and `summary` (plus boolean concern levels); `unresolved` units get `pred=None, failure="unresolved"`. B3's `policy.py` applies primary/secondary before any metric runs, so dataset metrics never see `pred=None`. B3 owns CI, one-way slicing by `pair.meta`, report assembly and `references.json` pass-through.

**R1 Gold.** `gold(item)` returns per-sentence `{sent_idx, text, label, types, exp, start, end}` (label normalised from raw `yes`/`no`; `text` and `exp` read from C1's local data, in memory only: never written to run files, `item_rows.json` or metrics) and `summary = inconsistent iff any sentence inconsistent` (paper §3.4 aggregation). `gold_kind` in metadata is `tofueval_summary_sentences`; B4 passes it through and D2's GoldPanel switches on it.

**R2 Claim-to-sentence mapping** (frozen v1.0.0). Spans are half-open `[start.char, end.char)` in section 0; the join space belongs to no sentence.
- Claim with `span.start.index != 0`, empty span, or zero overlap with every sentence: **unmapped** (counted in `unmapped_claim_rate`, affects no sentence).
- Otherwise the claim is assigned to **every sentence it overlaps by at least 1 code point** (brief §5.5 row 2 applied literally; "maximal overlap" is the single-sentence special case, so the two brief rows agree). A claim assigned to 2+ sentences is **boundary-crossing** (reported).

**R3 Sentence label** (first match wins).
1. `inconsistent`: any mapped claim verdict in {contradicted, partially_supported, insufficient_evidence}.
2. `unresolved`: no mapped claim.
3. `consistent`: otherwise (all mapped are supported, or supported plus out_of_scope).
4. `consistent` with `meta=true`: only out_of_scope claims mapped; counted consistent, tallied as `meta_consistent_n`.

**R4 Summary label.** inconsistent if any sentence inconsistent; else unresolved if any sentence unresolved; else consistent. A failed item (`pred is None`) is all-unresolved at both levels. `status: partial` needs no special case (single section: no claims, so unresolved).

**R5 Unresolved scoring.** Primary: counted wrong, defined as the opposite class to gold (gold-inconsistent becomes FN, gold-consistent becomes FP), so every metric stays hand-computable. Secondary: unit excluded; the entry carries B3's `policy: secondary`. Applies at sentence and summary level independently.

**R6 Metrics** (registry names, `impl: "dataset:tofueval"`; empty class in a slice gives `value: null`, `n` still reported):

| Metric | Level | Definition |
|---|---|---|
| `bacc_sentence`, `bacc_summary` | sentence, summary | mean of recall(inconsistent) and recall(consistent) |
| `prec_inconsistent`, `rec_inconsistent`, `f1_inconsistent` | both | inconsistent = positive |
| `recall_by_type` x 7 | sentence | among gold-inconsistent sentences carrying type T, share predicted inconsistent; multi-label rows count in every type they carry; metric name `rec_type_<T>` (type is in the name, not a slice), n shown |
| `concern_match_rate` x 5 | sentence | among gold sentences with scored type T (dataset-applicable per mapping), share where the union of concerns over all mapped claims intersects the allowed set; unresolved counts as no match (primary) |
| `concern_match_base_rate` x 5 (R10) | sentence | same test applied to gold-**consistent** sentences: chance level for any-in-set |
| `unresolved_rate`, `meta_consistent_n` | both / sentence | coverage and policy tallies |
| `claims_per_sentence`, `unmapped_claim_rate`, `boundary_crossing_rate` | diagnostic | adapter health (R5 of C brief) |
| `concern_not_in_mapping` | diagnostic | per concern type outside every allowed set: count on mapped claims (feeds project A) |
| R4 diagnostic: `bacc_sentence_meta_unresolved`, `bacc_summary_meta_unresolved` (extra levels emitted by `pairs()`) | both | meta sentences re-labelled unresolved (wrong in primary); headline policy stays `meta_as_consistent` |

**R6a Mapping onto B3.** `bacc_*`, `prec/rec/f1_inconsistent` and `unresolved_rate` are metadata aliases of B3 built-ins (`balanced_accuracy`; `precision`/`recall`/`f1` with `positive: "inconsistent"`; `failure_rate` with `reason: unresolved`) and need no code; the seven type metrics are aliases of `recall_by_type` with a `tag` param. `concern_match_rate`/`concern_match_base_rate` are boolean levels `concern:<T>` emitted by `pairs()` (B3 R1). The diagnostics read scalar counts carried in `pair.meta` and are the only code in `metrics.py` (`pairwise` metrics). Exact level names are fixed at task time.

**R7 Slices.** B3 slices one-way over `pair.meta`, so the crossed grid is expressed as derived meta keys declared in `slices`: `model_group`, `dataset`, `topic_category`, `model_name`, plus `group_dataset` (`original_five|mediasum`, ...), `group_topic`, `group_model`. Metadata sets `pool_all: false` so no entry pools original-five with Model-Extra; the `model_group` slice is the "all datasets" row within a group. Type metrics use `group_dataset` only. `contamination` is the run-level tag `run.json` `tags.contamination` (B2; default unset), shown in `metrics.json` `run.tags`, not a partition.

**R8 Mapping loader.** Validate: `mapping_version` semver; each `allowed` concern is in the current response-schema concern enum (fail loudly if a mapped concern disappears: mapping drift needs a version bump); `datasets` / `dataset_overrides` keys are known datasets; `recall_only` types have `allowed: null`. Predicted concerns not in any allowed set are ignored for matching (never an error, never added to an allowed set) and counted by `concern_not_in_mapping`.

**R9 Per-item row** (`item_row`, no text, no `exp`): see Architecture.

**R10 Integrity** (`integrity.py`; returned by the adapter hook `report_extra`, stored by B3 in `metrics.json` `dataset_extra`): `mapping_version`, `mapping_sha256`, `test_run_count` and this run's ordinal for (tofueval, mapping_version) over local runs with `split in {test, all}` (any state), dev-run count, `label_noise_note` (kappa 0.34 / 0.42), `secondary_excludes_failures` note, `primary_policy`. Informational only. `adapter.mapping_version()` returns the version and B2 records it in `run.json` at run start; B3 R9 `compare` already warns when it differs.

**R11 References.** `references.json` with all 10 Table 3 rows x 8 cells, as B3 `references` entries, `note: "paper-reported, different model & date"`, test split stated in `label`, greyed in the UI, no CI, never ranked. File shape `{rows, caveats}` (B3 R8). Top-level `caveats` (B3 `reference_caveats`): LLM rows = mean of 3 runs (gpt-4-0613 for GPT-4); original five models only; per-document with source supplied, no atomization; label noise.

## Architecture
```
adapter.gold(item)            -> labels.gold(item) -> Gold
adapter.project(resp, item)   -> projection.project(resp, item, mapping) -> Projection
adapter.item_row(pair)        -> item_rows.build(...)
metrics.py                    registers names into B3 registry (dataset override by name)
integrity.py                  scans eval/runs/*/run.json (read-only)
```
```python
Gold        = {"sentences": [{"sent_idx", "label", "types", "start", "end"}], "summary": str}
Projection  = {"sentences": [{"sent_idx", "label", "meta": bool, "claim_ids": [..],
                              "verdicts": [..], "concerns": [..], "boundary": bool}],
               "summary": str, "claims_total": int, "claims_unmapped": int}
```
**Item row** (the `adapter.item_row` hook; B3 R8 calls it at scoring and writes `item_rows.json` beside `metrics.json`; B4 serves it to D2). The common fields are B3's `ItemRow`; everything TofuEval-specific sits in `detail`:
```json
{"item_id": "", "label": "<doc_id> / <topic> / <model_name>", "status": "ok|failed|unmapped",
 "gold": "inconsistent (2 of 6 sentences)", "pred": "inconsistent (1 of 6; 1 unresolved)",
 "match": true, "outcome": "tp|tn|fp|fn|unresolved",
 "detail": {"doc_id": "", "dataset": "", "topic_category": "", "model_name": "", "model_group": "",
  "gold": {"summary": "consistent|inconsistent", "n_sentences": 0, "n_inconsistent": 0, "types": ["..."]},
  "pred": {"summary": "consistent|inconsistent|unresolved", "n_inconsistent": 0, "n_unresolved": 0, "n_meta": 0},
  "sentences": [{"sent_idx": 0, "start": 0, "end": 0, "gold_label": "", "gold_types": [],
                 "pred_label": "", "meta": false, "claim_ids": [], "verdicts": [], "concerns": [],
                 "outcome": "tp|tn|fp|fn|unresolved", "concern_match": {"<type>": true}}]}}
```
`outcome` is on the **primary** policy (unresolved shown as `unresolved`, scored wrong); `match` is true for tp/tn, false for fp/fn, null for unresolved/failed. Text and `exp` are not persisted (license rule 7); D2 gets sentence text and `exp` from `ItemDetail.gold` (B4 computes `adapter.gold(item)` on demand from the local data).

**`mapping.json` v1.0.0** = brief §5.7 byte-for-byte (including `dataset_overrides` and `datasets`). `mapping_version` covers mapping **and** projection rules (R2-R5): any change to either bumps it. Old versions are kept in `mapping_history/<ver>.json`; a test pins the sha256 of the v1.0.0 content.

**Table 3** [verified: `pdftotext -layout -f 7 -l 7 p.pdf`, PDF p.7 = ACL p.4460; header "Sentence-Level: MediaSum Main, Marginal, MeetingBank Main, Marginal; Summary-Level: same"; caption "on the test set"]. Values as BAcc %, in that column order (stored as fractions):

| Evaluator | S-MS-main | S-MS-marg | S-MB-main | S-MB-marg | U-MS-main | U-MS-marg | U-MB-main | U-MB-marg |
|---|---|---|---|---|---|---|---|---|
| Baseline | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| SummaC-ZS | 66.1 | 73.9 | 63.9 | 80.6 | 62.7 | 64.1 | 58.1 | 72.4 |
| SummaC-CV | 67.6 | 73.0 | 62.6 | 77.3 | 61.2 | 66.5 | 52.4 | 72.9 |
| QAFactEval | 53.9 | 74.0 | 58.0 | 75.8 | 61.4 | 74.2 | 55.1 | 68.2 |
| AlignScore | 69.2 | 76.2 | 61.2 | 78.6 | 65.5 | 72.1 | 63.4 | 71.8 |
| Vicuna-13B | 54.0 | 54.8 | 49.6 | 61.9 | 55.6 | 59.1 | 51.2 | 59.2 |
| Vicuna-33B | 51.0 | 51.1 | 53.6 | 48.4 | 52.5 | 53.4 | 53.2 | 51.0 |
| WizardLM-13B | 59.8 | 53.5 | 58.8 | 56.6 | 57.0 | 54.5 | 54.6 | 58.0 |
| WizardLM-30B* | 54.5 | 53.9 | 53.5 | 53.4 | 53.3 | 54.4 | 53.0 | 53.2 |
| GPT-3.5-Turbo | 61.6 | 68.9 | 56.0 | 65.0 | 59.6 | 65.8 | 63.2 | 65.7 |
| GPT-4 | 64.9 | 80.2 | 67.5 | 90.3 | 63.7 | 78.9 | 74.7 | 83.1 |

\*Printed "30B" in Table 3 but "33B" in Table 4; keep the Table 3 label.

**Worked fixture** (fictional, 1 item, 6 sentences; gold-inconsistent s1 EI, s4 TAM): predictions s1 inconsistent, s2 consistent, s3 inconsistent, s4 unresolved, s5 meta, s6 consistent. Primary: TP=1, FN=1 (s4 unresolved), FP=1 (s3), TN=3 (s2,s5,s6) so `rec_inconsistent`=0.5, `prec_inconsistent`=0.5, `bacc_sentence`=(0.5+0.75)/2=0.625. Secondary (s4 excluded): bacc=(1+0.75)/2=0.875. R4 alt (s5 unresolved becomes FP): TN=2, bacc=(0.5+0.5)/2=0.5. `meta_consistent_n`=1; `concern_match_rate[EI]`=1/1 if s1's claim carries `unsupported_claim`, `[TAM]`=0/1 primary. The test file derives these numbers by hand in comments, not by calling the code under test.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Boundary rule reading | Assign to all sentences overlapped by >=1 code point | Max overlap with tie-break; minimum-overlap threshold | Brief §5.5 row 2, frozen. Risk: off-by-few offsets flag a neighbour; measured by `boundary_crossing_rate` (R5), fixed only by a version bump |
| 2 | Version scope | One `mapping_version` for mapping + projection rules; history dir; sha-pin test | Separate projection_version | Brief §7.1 versions them together; one number to record |
| 3 | Unknown/new concerns | Ignored for matching, counted in `concern_not_in_mapping`; mapped concerns must exist in current enum | Auto-include new types; error on unknown predicted types | A's `quantity_mismatch` must not change v1.0.0 numbers. A1 keeps mapping v1.0.0 untouched for a clean before/after (A1 Decision 11); any later mapping change is a separate versioned decision (new `mapping_version`, old file kept in `mapping_history/`), never mixed |
| 4 | Unresolved as wrong | Opposite-to-gold class in primary | Separate "abstain" cell | Keeps all metrics standard and hand-computable; B3 policy |
| 5 | Empty class | `value: null` + n | 0 or NaN | Avoids fake zeros; D renders n/a |
| 6 | Headline grid | model_group x dataset (incl. "all"), never pool groups | Fully crossed grid; all-pooled | n stays visible; original-five comparable to paper. "all" datasets within a group allowed, MeetingBank caveat in caveats |
| 7 | R10 base rate | Sentence-level on gold-consistent sentences, per type | Concern-level share of all predicted concerns (brief wording) | Directly comparable to `concern_match_rate`; same test, different population |
| 8 | Per-item row text | No text/`exp` persisted; fetched on demand | Embed text | License rule 7 |
| 9 | Reference values | Fractions in 0..1; test split only | Percent as printed | Same scale as live `bacc_*` |
| 10 | Test-run counting | Scan local run folders, split in {test, all}, any state | Central ledger/DB | No new store; runs are local and gitignored anyway |
| 11 | Contamination | Run-level tag stamped on entries | Per-item slice | It is a property of the audited model, not the item |
| 12 | Integrity enforcement | Report block + warnings | Hard block | Decision 13 (informational) |

## Manual steps
- Operator sets `tags.contamination` per run (release/cutoff vs 2024-03) through the start-run request body (B4); there is no UI field in v1.
- Optional: one human glance at PDF p.7 to confirm the text-layer reading (low risk; header and caption verified by text).
- On any future mapping bump (a separate decision, not project A1): maintainer copies the old file to `mapping_history/`, bumps version, adds a new sha pin.

## Risks / Open Questions
- [RESOLVED: pdftotext layout, PDF p.7; header order and caption "test set" confirmed; 5 brief rows match] R7 Table 3 column assignment.
- [RESOLVED: B3 R1/R8/R9 (see `03-metrics-scoring/PRD.md`)] `pred=None` is handled by B3's policy before dataset metrics; per-item hook is `adapter.item_row`; compare warns on differing `mapping_version`.
- [RESOLVED: `run.json` `tags`, set only via the optional `tags` field of the B4 start-run request; default unset; no D1 UI field in v1] Where the contamination tag is set.
- [OPEN] Add `concern_match_given_detected` (match among gold sentences predicted inconsistent)? Separates concern agreement from recall; not in locked list, so not built unless approved.
- [RESOLVED: a claim overlapping two summary sentences flags BOTH, accepted as designed; owner decision 2026-10-20] Rule 1 (any 1-code-point overlap) over-flag. Stays observable on dev via `boundary_crossing_rate`; not tuned on test.
- [OPEN] Persisting `exp` for the GoldPanel: assumed on-demand only (D2 decision).
- [DEFERRED] `concern_not_in_mapping` evidence may inform a future, separately versioned mapping decision (not A1; A1 leaves v1.0.0 untouched).
- [DEFERRED] Per-type CIs are wide (CO 30, TAM 39, OF 42): n always shown, types never ranked.

## Acceptance Criteria
- Fixture tests (fictional only): each boundary case (inside one sentence, spans two, in join space, wrong section index, empty span), each sentence/summary label rule, failed item, meta mix, multi-label type, MeetingBank overrides (Mis-Referencing excluded, Opinion-as-Fact without `wrong_attribution`) pass against hand-computed values; the worked example above reproduces 0.625 / 0.875 / 0.5.
- `mapping.json` equals brief §5.7; sha pin test passes; loader rejects an allowed concern missing from the current enum and ignores an unknown predicted concern.
- All listed metrics appear with `{metric,value,n,ci,slice,impl}`; no headline entry lacks `model_group`.
- `references.json` has 10 rows x 8 values equal to the table above, each labelled "paper-reported, different model & date".
- Item rows validate against the shape above, contain no text/`exp`, and `outcome` is consistent with the sentence counts.
- Report header carries mapping_version, mapping_sha256, test_run_count and ordinal; two runs with different mapping versions trigger the compare warning.
- Metric and projection modules import no network/LLM client and no `iaudit_backend`.
