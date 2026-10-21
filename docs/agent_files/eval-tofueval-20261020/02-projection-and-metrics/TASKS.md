---
status: draft
summary: Nine tasks for the TofuEval gold/projection rules, frozen mapping, pairs and metric registrations, slices, item rows, integrity block and paper reference rows; all offline and fixture-tested.
date: 2026-10-20
---
# Tasks: C2 TofuEval projection & metrics

Source of truth: [PRD.md](PRD.md). Pure, deterministic Python over saved runs that turns iAudit claim verdicts into TofuEval sentence and summary labels and registers the TofuEval metrics, slices, references, item rows and integrity block. Agents make no live LLM calls and download no real data; tests use fictional fixtures only.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Frozen mapping.json, loader and sha pin | none | todo |
| 2 | Gold labels | none | todo |
| 3 | Claim-to-sentence projection | 1 | todo |
| 4 | Pairs emission and unresolved policy inputs | 2, 3 | todo |
| 5 | Metric registrations, slices and metadata | 4 | todo |
| 6 | Per-item rows | 4 | todo |
| 7 | Integrity block and adapter wiring | 1, 5, 6 | todo |
| 8 | Paper reference rows | none | todo |
| 9 | Worked-example end-to-end test and import hygiene | 7, 8 | todo |

## Task 1 — Frozen mapping, loader, sha pin
What it is / what it means: The concern-to-error-type mapping is a versioned, frozen input (R8, D2, D3).
What changes at a high level: Add `mapping.json` v1.0.0 exactly as brief §5.7 (including `datasets` and `dataset_overrides`). Add a strict loader: semver version, every allowed concern in the current response-schema enum (fail loudly if one disappears), known dataset keys, `recall_only` types with `allowed: null`. Unknown predicted concerns are ignored for matching, never an error. Define the `mapping_history/` convention (created only on first bump) and pin the v1.0.0 sha256 in a test.
Done when: mapping equals brief §5.7, sha pin passes, loader rejects a missing enum concern and tolerates an unknown predicted one.

## Task 2 — Gold labels
What it is / what it means: Native TofuEval gold per item (R1).
What changes at a high level: `gold(item)` normalises raw `yes`/`no` to consistent/inconsistent per sentence, carries types, offsets, and in-memory-only text and `exp`, and derives summary = inconsistent iff any sentence is. Set `gold_kind` to `tofueval_summary_sentences` in metadata. Text and `exp` are never written to run files, item rows or metrics.
Done when: fictional-fixture tests cover label normalisation, multi-label types and summary aggregation.

## Task 3 — Claim-to-sentence projection
What it is / what it means: The frozen projection rules R2-R4 (D1, D2).
What changes at a high level: Map claims using half-open section-0 spans: wrong section index, empty span or zero overlap is unmapped; otherwise assign to every sentence overlapped by at least 1 code point, flagging boundary-crossing. Apply sentence-label rules in first-match order (inconsistent, unresolved, consistent, meta consistent), summary aggregation, and the failed-item all-unresolved case. Output the `Projection` shape with claim totals and unmapped counts.
Done when: hand-computed tests pass for inside one sentence, spanning two, join space, wrong section, empty span, each label rule, meta mix and failed item.

## Task 4 — Pairs emission and unresolved handling inputs
What it is / what it means: The adapter `pairs()` hook feeding B3 (R5, R6a, D4, D7).
What changes at a high level: Emit sentence and summary pairs, with `pred=None, failure="unresolved"` for unresolved units so B3's primary/secondary policy applies. Also emit boolean levels `concern:<T>` (gold-inconsistent and gold-consistent base-rate populations, union of concerns over all mapped claims against the mapping-allowed set, dataset overrides honoured), `concern_detected:<T>` (only gold-inconsistent sentences predicted inconsistent), the meta-as-unresolved extra levels, and `pair.meta` scalar counts plus derived slice keys.
Done when: tests show correct pair populations, overrides (Mis-Referencing excluded, Opinion-as-Fact without `wrong_attribution`) and no `pred=None` leaks outside the unresolved convention.

## Task 5 — Metric registrations, slices, metadata
What it is / what it means: The locked TofuEval metric list on B3's registry (R6, R6a, R7, D5, D6, D11).
What changes at a high level: Declare in `metadata.json` the metric aliases of B3 built-ins (bacc, inconsistent-class P/R/F1, unresolved rate, seven `rec_type_<T>`, concern match, given-detected and base-rate rates) with `impl: "dataset:tofueval"`. Implement only the pairwise diagnostics in `metrics.py`: claims per sentence, unmapped and boundary-crossing rates, `concern_not_in_mapping`, `meta_consistent_n`. Declare the slice grid (`model_group`, `dataset`, `topic_category`, `model_name`, `group_dataset`, `group_topic`, `group_model`), `pool_all: false`, type metrics on `group_dataset` only, and null-with-n on empty classes.
Done when: every listed metric appears as `{metric,value,n,ci,slice,impl}` with no headline entry lacking `model_group`.

## Task 6 — Per-item rows
What it is / what it means: D2's per-item gold vs ours vs match, without frontend re-derivation (R9, D8).
What changes at a high level: Implement `item_row` building B3's `ItemRow` with TofuEval `detail` (gold/pred summaries, counts, per-sentence offsets, labels, types, claim ids, verdicts, concerns, outcome, concern_match). `outcome` follows the primary policy; `match` is true for tp/tn, false for fp/fn, null for unresolved/failed. No sentence text or `exp`.
Done when: tests validate the row shape, outcome consistency with sentence counts, and absence of text/`exp`.

## Task 7 — Integrity block and adapter wiring
What it is / what it means: Informational reporting of mapping version and test-run count (R10, D10, D12).
What changes at a high level: `integrity.py` reads `eval/runs/*/run.json` read-only and returns mapping version and sha256, test-run count and this run's ordinal for (tofueval, version) over split in {test, all} any state, dev-run count, label-noise note (kappa 0.34/0.42), secondary-excludes-failures note and primary policy. Wire `report_extra` and `mapping_version` in C1's `adapter.py`, along with thin delegation for `gold`, `project`, `item_row`, `pairs`. No hard block.
Done when: tests over fictional run folders give correct counts and ordinal, and two runs with differing mapping versions trigger B3's compare warning.

## Task 8 — Paper reference rows
What it is / what it means: Greyed paper context beside live results (R11, D9).
What changes at a high level: Add `references.json` with `{rows, caveats}`: all 10 Table 3 evaluators by 8 BAcc cells as fractions, each labelled "paper-reported, different model & date" with test split in the label, no CI, WizardLM-30B* label kept. Top-level caveats cover LLM rows as mean of 3 runs (gpt-4-0613), original five models only, per-document with source supplied and no atomization, and label noise. Wire into metadata `references`.
Done when: a test compares all 80 values to the PRD table and checks labels and caveats.

## Task 9 — Worked-example end-to-end test and import hygiene
What it is / what it means: The PRD's acceptance gate (Acceptance Criteria).
What changes at a high level: Add the fictional 6-sentence item and its saved response, with hand-derived numbers in comments. Assert primary 0.625, secondary 0.875, meta-as-unresolved 0.5, `meta_consistent_n`=1, `concern_match_rate` EI=1/1 and TAM=0/1, `concern_match_given_detected` EI=1/1 and TAM null with n=0. Add an import test that metric and projection modules load no network/LLM client and no `iaudit_backend`.
Done when: the full suite passes offline.

## Owner manual checks
- Run live dev/test audits and evals; agents run none.
- Set `tags.contamination` per run via the B4 start-run body (no UI field in v1).
- Optional: glance at PDF p.7 to confirm the Table 3 reading.
- On any future mapping bump: copy the old file to `mapping_history/`, bump version, add a new sha pin.
