---
status: draft
summary: 14 tasks for SP02 — pack format/loader and schemas first (pure code, starts before the SP01 gate), then volleys, formulas, MITI pack, code/globals passes, runs, fixtures, live check, ADR, and the live measurement after the gate.
date: 2026-11-20
---
# Tasks: SP02 paudit engine + protocol pack format + MITI 4.2.1 pack
Source of truth: [PRD.md](PRD.md). Lane A. Tests follow SP00 conventions: markers `unit` / `integration` / `live`, default `-m "not live"`; live checks never run in PR CI. CI job: `paudit` (SP00 job: ruff + `uv run --package paudit pytest -m "not live"`, skipped until `engines/paudit/pyproject.toml` exists, so Task 1 activates it). Tests use the core stub/fixture clients (no network). SP03 owns `prompts/tips_*`, the `evaluation:` block, the `report.yaml` content and `fixtures/evaluation/**`; SP02 ships only a stub `report.yaml` and leaves the `evaluation:` key open.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | `engines/paudit` skeleton, pack schema, loader, `pack_hash`, grep test | SP01 T1 | done |
| 2 | `rating.schema.json` (rating card) + parity test | 1 | done |
| 3 | Result models and `paudit-result.schema.json` | 1 | done |
| 4 | Safe formula evaluator `paudit.formula.evaluate` | 1 | done |
| 5 | Select, volley builder, input checks, hook interface | 1, 3 | done |
| 6 | MITI 4.2.1 pack data, `rules.py` hook, prompt drafts | 2, 4, 5 | done |
| 7 | Rules, counts, summaries (code side) | 3, 4, 6 | done |
| 8 | Code pass: batching, warm-first, halving, locate/validate | 5, 6, 7, SP01 T3, T5, T6 | in-progress |
| 9 | Globals pass: evidence, default, caps | 3, 6, SP01 T3, T5 | todo |
| 10 | `paudit.run`: N runs, aggregate, `run_info` | 8, 9, SP01 T10 | todo |
| 11 | Synthetic fixtures, `expected.yaml`, thresholds, offline CLI `run`, golden | 10 | todo |
| 12 | Live `paudit.cli check` | 11 | todo |
| 13 | ADR 0018, contracts pointer, CI finish | 10 | todo |
| 14 | Live measurement after the SP01 gate; tune pack `params` | 12, SP01 T13 | todo |

Parallel lanes: all of Lane A, but split among people. Tasks 1 to 7 are pure code and need only SP01 Task 1 (workspace + types) plus, where noted, SP01 Task 3 helpers (`hash_files`, `locate`, stub/fixture clients), which land before the gate; they start before SP01 Task 13. Tasks 8 to 13 use the core client and routes (SP01 Tasks 3, 5, 6, 10) but run on stub clients only. Only Task 14 (live) needs the gate. After Task 1: Tasks 2, 3, 4 run concurrently; after Task 6, Tasks 8 and 9 run concurrently; Task 13 can run beside 11 to 12. Cross-lane sync points: Task 2 (`rating.schema.json`: SP05 builds the rating card, SP03 `validate_rating`) and Task 3 (result schema: SP03, SP04 stub engine) — push each as soon as green. Task 4 (`paudit.formula.evaluate`) is reused by SP03.

## Task 1 — `engines/paudit` skeleton, pack schema, loader, `pack_hash`, grep test
What it is / what it means: the engine package and the pack format, so everything else has a contract. Traces to R1, Decisions 1, 13, 20 (loader, schema and grep test stay in v1).
What changes at a high level: new workspace member `engines/paudit` with `pyproject.toml` (depends on `onolys_core`), `schemas/pack.schema.json` (`pack_format: "0.0.1"`, all `pack.yaml` sections; the `evaluation:` key is any object), `pack.py` loader resolving `miti@4.2.1` under a configurable `protocols/` dir or a path, parity checks (report/compare ids, prompt files, precedence subset, formulas reference known ids), `pack_hash` via the core file-list helper (pack.yaml, rules.py, rating schema, prompts, report.yaml; not fixtures), typed `PackError` at load only. Tests use a minimal in-test pack until Task 6.
Done when: unit tests cover schema acceptance/rejection, each parity check, hash stability and change on edit, `evaluation:` accepted; a grep test fails if `miti|cct|reflection` or any model id appears under `engines/paudit/src`. CI job `paudit` runs green (no longer skipped).

## Task 2 — `rating.schema.json` (rating card) + parity test
What it is / what it means: the in-app rating card, the only rating input; a sync point for SP05 and SP03. Traces to R1 (rating schema), Decision 14, `from_s`/`to_s` resolution.
What changes at a high level: `protocols/miti-4.2.1/rating.schema.json` with the nested shape: `change_goal`, `coded_span{from_s,to_s}`, `globals{cct,sst,partnership,empathy: {score 1-5|null, reason, example?{at_s, text}}}`, `counts{10 code ids: {count, note?}}`, `notes`; every item key optional/nullable; `maxLength` 1,000 on reason, note, example text and 3,000 on notes. Parity test ties schema keys to pack item ids once the pack lands (Task 6).
Done when: unit tests accept partial and full cards, reject out-of-range scores, negative counts and over-length strings (1,000 incl. `example.text`, 3,000 notes); the parity test (schema keys equal pack item ids) is wired and passes after Task 6; job `paudit` green. SP03 and SP05 are told the file is stable.

## Task 3 — Result models and `paudit-result.schema.json`
What it is / what it means: the typed, versioned output SP03 diffs and SP04 stubs. Traces to R3, Decisions 5, 10, 13.
What changes at a high level: pydantic models plus `schemas/paudit-result.schema.json` (`schema_version "0.0.1"`): protocol block, `results[]` with instances (`counted`, `uncounted_reason`, offsets as code points, optional ms), counts, globals (`source` model|default|capped, `raw_score`, evidence), summaries with reference and label, warnings, `aggregate` with `representative_run`, and `run_info` as the core `RunInfo`. Warning codes enumerated, pack-defined codes allowed.
Done when: unit tests validate sample results against both the models and the JSON schema, reject missing fields and bad enums, and round-trip; job `paudit` green. SP04 can build its stub engine on this.

## Task 4 — Safe formula evaluator `paudit.formula.evaluate`
What it is / what it means: summary scores as data, no `eval`. Traces to R2 step 7, Decision 2.
What changes at a high level: `formula.py` with a whitelisted AST evaluator (numbers, item ids, `+ - * /`, parentheses) exposing `evaluate(expr, values) -> float|None` plus a parse-time check used by the loader; division by zero gives `None`; label vs reference (`below_fair|fair|good|null`) helper.
Done when: unit tests cover the four MITI formulas, div-by-zero to null, unknown names, calls, attributes and other node types rejected, label boundaries; the loader uses the parse check; job `paudit` green. Public signature is stable for SP03.

## Task 5 — Select, volley builder, input checks, hook interface
What it is / what it means: the pure code before any model call. Traces to R2 steps 1 to 3, R1 hooks, Risks (overlap span, volley break) and Decision 19.
What changes at a high level: input checks from pack `input_checks` (`duration_max/min`, `param_required`, `min_subject_turns`, `min_other_turns`) plus the optional `check_input` hook, producing typed `InputError` or warnings (`short_session`, `unknown_speaker` treated as other, `span_ignored` without timestamps); span selection by overlap (turns without `end_ms` fall back to `start_ms`); volley builder per pack `volley` (any other-speaker turn breaks; `min_other_words` knob), ids `v1..vN`; loader support for the three optional `rules.py` hooks.
Done when: unit tests cover over-length, missing `change_goal`, fewer than 5 subject or 3 other turns (errors), under-10-min warning, partial-overlap turn included whole, "mm-hm" breaking a volley and the `min_other_words` knob; job `paudit` green.

## Task 6 — MITI 4.2.1 pack data, `rules.py` hook, prompt drafts
What it is / what it means: all MITI content as data. Traces to R1, Decisions 1, 8, 9, 19, 20, Manual steps (implementer reads the manual).
What changes at a high level: `protocols/miti-4.2.1/pack.yaml` (source with citation, URL and permission-note placeholder for Tejit; speaker roles; 4 globals with scale/default 3/`evidence_min`, 10 codes with definitions from the manual; `caps[]` only where the manual states one, each citing a page; `rules[]`; `volley`; four `summaries[]` with reference levels; `input_checks`; `compare` from the brainstorm "Difference rule"; empty `evaluation` left to SP03; optional `params`), `rules.py` with the single `reflection_before_client_speech` warning hook, stub `report.yaml`, `prompts/` v1 drafts (`code_system.md`, `globals_system.md`, few-shot JSON).
Done when: unit tests load `miti@4.2.1` cleanly, run the Task 2 parity test, assert every cap cites a manual page and that formulas parse, and cover the hook; job `paudit` green. Prompt wording stays a draft pending coder review (deferred).

## Task 7 — Rules, counts, summaries (code side)
What it is / what it means: "code decides" after the model proposes. Traces to R2 steps 6 to 7, Decisions 4, 5.
What changes at a high level: apply pack `rules[]` kinds (`one_code_per_utterance`, `max_per_unit`, `exclusive_group` with precedence), then the `validate_codes` hook (down-count only); violations stay as `counted:false` with `uncounted_reason`; counts over counted instances; summaries via Task 4; label vs reference.
Done when: unit tests show 2 GI in a volley gives 1 counted, SR+CR gives CR counted and SR `superseded_by_cr`, hook cannot add or relabel, counts and summaries match formulas including div-by-zero null; job `paudit` green.

## Task 8 — Code pass: batching, warm-first, halving, locate/validate
What it is / what it means: the model-proposes step for utterances and codes. Traces to R2 steps 4 to 5, Decisions 3, 11, 15, 16, 17.
What changes at a high level: response model with code enum built from the pack; prompt assembled from `code_system.md`, definitions rendered from `pack.yaml` and few-shot, with `cache_prefixes`; `volleys_per_call` batches sent via core `warm_then_fanout` (first alone) on route `paudit_code`; token params default from the engine, overridable in pack `params`, clamped to the route; `LLMBadOutput` halves the batch and retries each half once; quotes located inside the volley turn via core `locate`; unlocatable or overlapping dropped with `quote_not_found`/`overlap`; over 20% dropped retries the batch once, then the run fails.
Done when: stub-client tests prove route name and no sampling parameter in the request, batch size honoured, second batch not started before the first returns, halving then failure, drop and retry thresholds, clamp; job `paudit` green.

## Task 9 — Globals pass: evidence, default, caps
What it is / what it means: four global ratings with cited lines. Traces to R2 step 8, Decisions 6, 7, 8, 9.
What changes at a high level: one call on route `paudit_globals` with the span, turn ids and change goal (no counts); returns score, reason, evidence quotes, `poor_practice_cited`; code locates quotes, errors on out-of-scale scores, resets to the default with `insufficient_evidence` below `evidence_min`, applies a cap only where the pack item has `caps[]` (`source:"capped"`, `raw_score` kept); truncation retried once, then the run fails.
Done when: stub-client tests cover no evidence gives 3, capped only for an item with a `caps[]` entry and not for one without, out-of-range error, truncation retry, and route name; job `paudit` green.

## Task 10 — `paudit.run`: N runs, aggregate, `run_info`
What it is / what it means: the assembled engine implementing the core `Engine` protocol. Traces to R2 step 9 and the params list, R3 (aggregate, `run_info`), R4, Decision 10, Decision 11.
What changes at a high level: `run(transcript, pack, params, client) -> PauditResult` wiring Tasks 5, 7, 8, 9 (globals started alongside the code fan-out); `n_runs` default 1 repeated bounded by the route semaphore, a failed run excluded with `run_failed`, all failed is an error; `aggregate` (mean/min/max/values, `representative_run` closest to mean, ties lowest); `run_info` with engine, `code_version`, preset, both routes, pack id/version/hash, `prompt_hashes` including engine-owned templates, usage; no text in logs.
Done when: tests show N=1 aggregate equals the single run with `representative_run` 0, a doctored pack prompt and an engine template each change `prompt_hashes`, a log capture has no transcript text, `paudit_code` and `paudit_globals` requested; an N=2 logic test with one failed run; results validate against the Task 3 schema; job `paudit` green.

## Task 11 — Synthetic fixtures, `expected.yaml`, thresholds, offline CLI `run`, golden
What it is / what it means: the offline proof and the data the live check uses. Traces to R5, Acceptance Criteria, Risks (build on synthetic data now).
What changes at a high level: three synthetic role-plays in `protocols/miti-4.2.1/fixtures/` (good practice; poor practice with Persuade and Confront; 8-minute short) each with intended per-utterance codes, expected counts and global ranges in `expected.yaml`, plus `thresholds.yaml`; `python -m paudit.cli run --pack miti@4.2.1 --transcript f.json --params p.json` offline with the stub client; one recorded `FixtureClient` golden.
Done when: stub-driven runs on each fixture give a schema-valid result whose counts and summaries equal `expected.yaml`, the golden replayed twice yields identical output, the short fixture yields `short_session`, and the CLI `run` test passes offline; job `paudit` green.

## Task 12 — Live `paudit.cli check`
What it is / what it means: quality and latency proof without the `eval/` harness. Traces to R5 live check, Decision 18, Decision 16, R4.
What changes at a high level: `python -m paudit.cli check --pack miti@4.2.1 --preset <name>` runs the 3 fixtures on the real client, compares with `expected.yaml`, prints per-code count MAE, globals within-1, bad-output/retry rate, p95 latency and tokens, and exits non-zero past `thresholds.yaml`; no admin wiring.
Done when: offline unit tests of the pass/fail logic against a fixture client, including a doctored thresholds file making it fail, run in job `paudit`; a `live`-marked wrapper test is skipped in PR CI.

## Task 13 — ADR 0018, contracts pointer, CI finish
What it is / what it means: record the data-versus-code decision and confirm CI. Traces to Owns list, Decision 1, Decision 20.
What changes at a high level: `docs/decisions/0018-protocol-pack-data-vs-code.md` (pack as data, three hooks, safe-expr formulas, `pack_format` 0.0.1, scope cuts) with an empty measurements section; pointer line in `docs/contracts/README.md`; confirm `ci.yml` job `paudit` and the nightly entry for the live check.
Done when: a relative-link grep finds no broken links in the touched docs; job `paudit` green alongside `core`, `eaudit` and `frontend`.

## Task 14 — Live measurement after the SP01 gate; tune pack `params`
What it is / what it means: settle the "[OPEN until measured]" item as a measure-and-record step, not a design question. Traces to R4, Risks (token defaults and the 90 s target), Decision 16.
What changes at a high level: with live credentials and the SP01 gate passed, run `paudit.cli check` per offered preset; record token use, truncation/retry rate, p95 latency (target at most 90 s at N=1) and cost in ADR 0018; if `code_max_tokens` (8000) or `globals_max_tokens` (3000) truncate, or p95 misses, tune pack `params` (batch size and token limits) and re-run.
Done when: the live check exits 0 and the ADR records the outputs, the final `params` and any fallback applied; any preset is offered to users only after this passes. Not run in PR CI (live marker; nightly or manual).

## Owner steps (not agent work)
- Tejit: supply at least 3 real role-play transcripts with at least 1 certified-coder rating each (tuning and eval ground truth; not a launch blocker); confirm the citation and permission wording in `pack.yaml › source`; certified-coder review of the coding prompts (deferred).
- Tejit: supply `ANTHROPIC_API_KEY` for the live check (also needed for the SP01 gate).
- Implementer: read MITI 4.2.1 manual (PDF) and write item definitions with citation; do not paraphrase loosely.
