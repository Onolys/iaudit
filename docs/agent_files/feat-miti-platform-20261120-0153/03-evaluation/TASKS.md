---
status: draft
summary: 10 tasks for SP03 — report schema + fixtures first (SP04/SP05 sync point), rating validation, eaudit `profile`, reasons-audit mapping, tone, compare, tips, assembly, `run_evaluation`, live check + ADR 0019.
date: 2026-11-20
---
# Tasks: SP03 evaluation — rating validation, reasons audit, compare, tips, report
Source of truth: [PRD.md](PRD.md). Tests follow SP00 conventions: pytest markers `unit` / `integration` / `live`, default `-m "not live"`; the live check never runs in PR CI. All tests use `FixtureClient`/stub LLMs and fixture `PauditResult`s, no network. CI jobs: `evaluation` (SP00 per-package job: ruff + pytest `-m "not live"`, skipped until `engines/evaluation/pyproject.toml` exists, so Task 1 turns it on) and `eaudit` (Task 3).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Package skeleton, report types, `report.schema.json` and fixtures | SP01 T1; SP02 T2, SP02 T3 (`rating.schema.json`, `PauditResult` shape) | todo |
| 2 | `validate_rating` (draft vs final) | 1 | todo |
| 3 | eaudit: optional `profile`, suppress filter, contract `0.0.2` | SP01 T3 (core extraction) | todo |
| 4 | Reasons-audit mapping, evidence mapping, pack `evaluation:` block | 1, 3, SP01 T10 | todo |
| 5 | Tone lint and `report.yaml` static strings | 1 | todo |
| 6 | Compare and template explanations | 1, 5, SP02 T4 (`paudit.formula.evaluate`) | todo |
| 7 | Tips: prompt, quote validation, retry | 1, 5, SP01 T4 (route `tips`) | todo |
| 8 | `build_report` assembly | 4, 6, 7 | todo |
| 9 | `run_evaluation` orchestration, progress, partial failure | 8, SP02 T10 (paudit entry point) | todo |
| 10 | Live check, measurements, ADR 0019, boundary tests | 9, SP02 working paudit | todo |

Parallel lanes: all of Lane A after SP02. Task 1 goes first and is a sync point: push it as soon as green, because SP05 generates its TS types from `report.schema.json` and SP04 stores/validates the report verbatim against it. Tasks 1, 2, 5, 6, 7 need only SP02's published types and schemas plus fixture paudit results, so they can start before paudit works end to end. Task 3 (eaudit, different package) runs in parallel with 1 and 2. After 1: 4 (needs 3), 6 and 7 (both need 5) can run side by side. Task 8 joins 4, 6, 7; Tasks 9 and 10 are serial and need a working paudit.

## Task 1 — Package skeleton, report types, `report.schema.json` and fixtures
What it is / what it means: the stable contract everyone else reads, shipped early. Traces to R1 (API shapes), R7, D1, D12.
What changes at a high level: new workspace member `engines/evaluation/` (`onolys-evaluation`, import `onolys_evaluation`; depends on core, eaudit, paudit public types; core never imports it). Typed `Report`, `EvaluationOutput`, `Issue`, `Warning`, public function signatures as stubs, and `schemas/report.schema.json` at `schema_version "0.0.1"` with the R7 shape. Three report fixtures (full rating, partial rating, no rating) plus a fixture transcript, speaker map and `PauditResult` under `protocols/miti-4.2.1/fixtures/evaluation/`.
Done when: unit tests validate the three fixture reports against the schema and reject a malformed one; a test loads the types from the schema keys; job `evaluation` now runs and is green; schema path and fixture names are announced for SP04/SP05.

## Task 2 — `validate_rating` (draft vs final)
What it is / what it means: the rating card is checked by code only; no parser anywhere. Traces to R2, D11, D16, AC1.
What changes at a high level: `validate_rating(pack, obj, final)` returning `Issue{path, code}` with no text: jsonschema against the pack's `rating.schema.json`, keys within pack item ids, integer scores within `scale`, counts integer at least 0, `coded_span` ordered and non-negative, hard limits (reason/note/example text 1,000, notes 3,000); `final=true` adds non-empty `change_goal`. Missing item stays null. A final card with no values and no notes is classified as a "no rating" run.
Done when: unit tests (job `evaluation`) cover full, partial (two globals), all-null, over-limit (1,001/1,001/3,001), out-of-range score, unknown key, bad span, draft with empty `change_goal` passing while final fails; a log-capture test shows no text logged; a dependency test shows no office/pdf/extractor packages.

## Task 3 — eaudit: optional `profile`, suppress filter, contract `0.0.2`
What it is / what it means: the only eaudit change for MITI: a request-level list of concern types to drop, plus a context note. Traces to R3 (contract, suppression, MI scope), D3, D4, D17, AC3.
What changes at a high level: `profile{suppress_concerns, context_note}` (extra=forbid, both optional) in `models/audit.py`, `contract.py` and `docs/contracts/{audit-request,audit-response}.schema.json` with `profile.*` examples; `schema_version` bumped to `0.0.2` with examples moved. The implementer reads `check/checker.py` and `group_a.py` and picks one filter point before the decision table covering every verifier flag type plus `unsupported_claim` derivation, so verdicts are recomputed. `context_note` appended to prompts only when present (`atomize/prompt.py`).
Done when: the existing `/v1/audit` tests pass on `0.0.2` examples without `profile`; new tests show a suppressed `timeframe_mismatch` disappears, a claim whose only flag was suppressed gets the no-flag verdict, a claim with one suppressed and one kept flag keeps the kept flag's verdict, and profile-less prompts are byte-identical (cache prefix). Job `eaudit` green. The chosen filter point is noted for ADR 0019 (Task 10).

## Task 4 — Reasons-audit mapping, evidence mapping, pack `evaluation:` block
What it is / what it means: turns the rating card into an eaudit request and maps results back to report lines. Traces to R3 (mapping, evidence mapping, MITI config table), D2, D18, AC2, AC4.
What changes at a high level: code builds one `Section` per rated item with a reason, example or note (example appended as `Example at mm:ss: …`), plus a `notes` section; items without text produce none. Transcript turns map to eaudit `Turn`s with clinician to `interviewer`, client to `respondent`. Result mapping: `turn_id = sent_turn_ids[index]`, single-turn spans one line, multi-turn spans split per turn, `quote` always the real transcript substring; claim spans resolve to item id or `notes` via section order. The MITI `pack.yaml › evaluation.reasons_audit` suppress list and `context_note` are added to the pack.
Done when: tests (job `evaluation`, eaudit stubbed) cover three reasons giving three sections with display-only scores, the example line, the `notes` section, no section without a reason, role mapping, the 1-turn and 3-turn evidence cases with quote equality, and a test reading `pack.yaml` that the suppress list matches the R3 table.

## Task 5 — Tone lint and `report.yaml` static strings
What it is / what it means: tone rules enforced by code, not by prompt. Traces to R6, D6, AC6.
What changes at a high level: `tone.py` lints any model-authored string against `pack.yaml › evaluation.tone.banned` (phrases/regex, second-person verdicts). The pack gets `report.yaml` content (layout, section order, titles, headline "Onolys disagrees, here's why", method statement and limits, `max_instances_shown`) and the `evaluation.tone` block. Wording-sign-off by Tejit is an owner step, not a blocker.
Done when: unit tests (job `evaluation`) show each banned phrase flagged, a clean string passing, and a test that lints every static string in `report.yaml` with the same list; layout loads from YAML with a clear error for a malformed file.

## Task 6 — Compare and template explanations
What it is / what it means: deterministic per-item diff and the "why" text, with no model call. Traces to R4, D6, D10, D19, AC5, AC6.
What changes at a high level: `compare` for globals (signed, `differs`, `within_one`), counts (`agree`/`differs`/`flagged` with abs ≥ 2 or ratio ≥ 0.25 over max(c, o)), and summaries (clinician value computed from their own inputs through the public `paudit.formula.evaluate`, null on missing input or divide by zero), thresholds read from `pack.yaml › compare`. Statuses `not_rated` and `no_onolys_value`; no rating gives null diffs. Explanation builder: headline, "Onolys scored X; you scored Y", Onolys reason (tone-linted, withheld with `reason_withheld_tone`), Onolys lines (global evidence or representative-run instances), clinician-support lines from supported reasons-audit claims; agreeing items collapsed.
Done when: table-driven tests (job `evaluation`) cover diffs 0/1/2 for globals, counts 5v5, 4v5, 0v1, abs 2, clinician %CR and div-by-zero, partial rating, no rating; every quoted line exists in the transcript at stated offsets; a planted banned phrase withholds prose and emits the warning.

## Task 7 — Tips: prompt, quote validation, retry
What it is / what it means: model proposes, code validates; tips come only from Onolys's own rating. Traces to R5, D7, D8, D9, AC7.
What changes at a high level: pack `prompts/tips_system.md` plus engine output-format instructions; one call on route `tips` with only the representative run (instances, globals and reasons, summaries vs reference) and clinician turns with the preceding client turn. Validator: `item_id` in pack, quote located in the named clinician turn via core `locate` and replaced by the real substring with offsets, non-empty `alternative` of at most two sentences and different from the quote, at most two tips per item and one per (item, turn), tone lint, keep first five. Fewer than three valid triggers one retry listing violations; still fewer ships fewer with `fewer_tips`; call failure yields `tips_failed`.
Done when: tests with a stub client (job `evaluation`) cover valid 3-5 tips, invented quote, non-clinician turn, banned tone, retry then `fewer_tips`, zero valid, call error, and a prompt-capture test proving no clinician rating or diff text reaches the call.

## Task 8 — `build_report` assembly
What it is / what it means: the pure step that joins every part into one self-contained report. Traces to R7, D12, D13, AC8.
What changes at a high level: `build_report(...)` assembles header (`stt` from `transcript.stt_run`, `preset`, `code_version`, `rating_coverage`), `layout` from `report.yaml`, scorecard, globals, behaviours, summaries, `reasons_audit` (templated explanations only; `suggested_revision` dropped), tips, method (states "not official MITI coding"), aggregates (`avg_abs_global_difference`, `within_one_share`, `counts_flagged`), warnings and `run_info`. No-rating run: Onolys values only, `reasons_audit.status: skipped`, null aggregates, tips and method kept. Never truncates; no text in `run_info`.
Done when: output validates `report.schema.json` for full, partial and no-rating fixtures (job `evaluation`); layout order follows `report.yaml`; aggregates match hand-computed values; header fields and the method statement are asserted; a test confirms prompt hashes cover pack tips prompts and engine templates.

## Task 9 — `run_evaluation` orchestration, progress, partial failure
What it is / what it means: the single entry point SP09's worker adapter calls once. Traces to R1 (orchestration, progress, partial failure), D5, D14, D15, AC9.
What changes at a high level: asyncio flow: reasons audit starts at t0 alongside paudit (skipped when a `paudit_result` is passed in or no rating), tips start when paudit finishes and run alongside eaudit, then compare and assemble. `progress_cb(stage, status)` for `paudit|eaudit|tips|compare|assemble`, always `started` then one of `done|failed`, non-applicable stages report `done` at once, a raising callback is logged and ignored. paudit error raises; eaudit timeout gives `partial` + `reasons_audit_partial`, eaudit error gives `failed` + `reasons_audit_failed`; tips error gives `tips_failed`. `EvaluationOutput.artifacts` carries paudit, eaudit and tips results.
Done when: stub-client tests (job `evaluation`) assert eaudit/paudit overlap, full progress sequences, a raising callback, each partial-failure case above, paudit failure raising with no report built, and no-rating and supplied-paudit paths.

## Task 10 — Live check, measurements, ADR 0019, boundary tests
What it is / what it means: proof on the real model plus the build-time numbers. Traces to R8, R9, D17, D20, AC10, AC11.
What changes at a high level: `python -m onolys_evaluation.check [--preset]` runs one fixture (transcript + final card) end to end and passes with at least 3 valid tips and `reasons_audit.status: ran`; prints tips quote-valid rate, per-stage latency and tokens. A `live`-marked wrapper test. Boundary tests: grep for no `miti|cct|reflection` in `engines/evaluation/src` or the eaudit filter code, no `api` import, fixtures replay with zero network. ADR `0019-*` records the design, the chosen eaudit filter point, and measured latency and per-session cost (the R8 estimate is [unverified] until measured).
Done when: offline unit tests of the check's pass/fail logic and the grep/boundary tests pass in job `evaluation`; `uv run --package onolys-evaluation pytest` and `cd engines/eaudit && uv run pytest` are green (jobs `evaluation`, `eaudit`); the live run exits 0 and its output, latency and cost figures are recorded in ADR 0019. Quality on real self-ratings stays deferred; not run in PR CI.

## Owner steps (not agent work)
- Tejit supplies 3 real self-ratings (to sanity-check card fields and caps) when available; not a launch blocker.
- Tejit signs off the wording of `evaluation.tone.banned`, the report headline and the method/limits text.
- Live check needs `ANTHROPIC_API_KEY` locally (SP01 owner step).
- Cross-SP additive asks (already accepted, not blockers): SP01 `EauditEngine` accepts `profile`; SP02 allows the `evaluation:` pack block, uses `from_s/to_s`, and exposes `paudit.formula.evaluate`; SP04 calls `validate_rating`.
