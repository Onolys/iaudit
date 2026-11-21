---
status: draft
summary: New `engines/evaluation/` library turns transcript + clinician rating card + PauditResult into one versioned report JSON: rating-card validation (no parsing), eaudit "reasons audit" (reasons, examples and the additional-notes box) via an optional audit profile, per-item compare with templated "Onolys disagrees, here's why" text, 3-5 quote-validated tips, pack-driven report assembly.
date: 2026-11-20
---
# PRD: SP03 evaluation — rating validation, reasons audit, compare, tips, report

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP01 (core), SP02 (PauditResult, pack, rating schema) · Blocks: SP09 (the worker's real `Evaluation` adapter calls it; SP04 builds on a fake), SP05 (renders report JSON)
Owns: `engines/evaluation/**` (package `onolys_evaluation`, incl. `schemas/report.schema.json`, tests); small additive edits in `engines/eaudit/**` (`models/audit.py`, `contract.py`, `check/checker.py`, `atomize/prompt.py`, tests) + `docs/contracts/{audit-request,audit-response}.schema.json` + `docs/contracts/examples/profile.*`; in the pack: `protocols/miti-4.2.1/prompts/tips_*`, `report.yaml` content, the `evaluation:` block of `pack.yaml`, `fixtures/evaluation/**`; `docs/decisions/0019-*`.
Not owned: rating card UI (SP05), storage/jobs/endpoints (SP04), paudit pipeline, pack loader core (SP02), `EauditEngine` wrapper shell (SP01).

## TL;DR
Everything between "transcript + confirmed speaker map + rating card + PauditResult" and "report JSON". Four pure-ish parts in one new package: (1) `validate_rating` (the in-app rating card, validated by code; there is no parser, no file/paste input and no model step), (2) reasons audit = today's eaudit run on the clinician's reasons, examples and the additional-notes box, with an optional **audit profile** that suppresses concern types the pack lists, (3) deterministic `compare` with template-written explanations, (4) tips (model proposes, code validates quotes, tips derived only from Onolys's rating), plus (5) `build_report` laid out by pack `report.yaml`. One entry point, `run_evaluation(..., progress_cb)`, runs it all in-process (asyncio): eaudit in parallel with paudit; tips start when paudit finishes and run alongside eaudit; then compare and assemble. Wall time ≈ max(paudit + tips, eaudit), inside SP04's target of ≤5 min from run start to report. A paudit failure fails the run; an eaudit or tips failure still yields a report.

## Problem
- eaudit audits a free-text assessment; the clinician's rating is structured (item id, score/count, reason, optional example) and arrives from the in-app rating card plus one free-text notes box. [verified: `AuditRequest.assessment[Section{id,label,score display-only,text}]`]
- Nothing compares clinician vs Onolys, explains differences with evidence, or writes tips.
- eaudit's 17 checks assume a clinician's write-up of a patient interview; several are noise or misleading on a self-rating of MI behaviour. [verified: `docs/mission.md` 17 checks]
- The web app needs one stable, self-contained JSON to render; every number and quote in it must trace to the transcript.

## Goals / Non-Goals
**Goals:** rating in, report out, fully offline-testable with fixture LLM clients; MITI specifics only in the pack; tone rules enforced in code; no invented quotes; existing `POST /v1/audit` tests still pass; a live `onolys_evaluation.check` proves the chain on the real model.
**Non-goals:** upload/confirm UI, storage, jobs, HTTP (SP04/05); OCR; changing paudit scoring; official MITI claims; chart/dashboard rendering; PDF export; clinician-vs-clinician comparison; file/paste rating parsing (rating card only).

## Requirements

**R1. Library + public API** (`engines/evaluation/`, dist `onolys-evaluation`, import `onolys_evaluation`; depends on `onolys_core`, `eaudit`, `paudit` public types; core never imports it):
```python
validate_rating(pack, obj, final: bool) -> list[Issue]                         # R2; SP04 calls it on every `PUT …/rating` (limits: reason/note/example text ≤1,000, notes ≤3,000)
run_evaluation(ctx, pack, transcript, speaker_map, params, rating|None, paudit_result|None,
               progress_cb: Callable[[stage, status], None] | None = None) -> EvaluationOutput   # rating = validated final card
build_report(...)  # pure assembly from already-computed parts (used by tests, admin)
```
- **Inputs/outputs (the SP04 `Evaluation` adapter contract).** `ctx` = core `RunContext` (LLM client built from the run's preset, deadline, `request_id`). `params` = `{change_goal, coded_span{from_s,to_s}, language, n_runs, preset, code_version}`; the header's `stt` is read from `transcript.stt_run`. `EvaluationOutput{report: Report, artifacts{paudit: PauditResult, eaudit: <eaudit response> | None, tips: <validated tips + raw proposals> | None}}`; `run_info` is `report.run_info`. SP04 stores the report and writes the artifacts to GCS.
- **Orchestration (r7).** `run_evaluation` is the whole `running` phase: SP04 calls it once, in-process, from ONE Cloud Task. asyncio does the parallelism: the reasons audit (R3) starts at t0 concurrently with paudit (unless a `paudit_result` is passed in), tips (R5) start when paudit finishes, then compare and assemble in code. There are no per-stage tasks and the worker does not call the parts separately; a retry re-runs the whole run.
- **Progress.** `progress_cb(stage, status)` is called with stage ∈ `paudit | eaudit | tips | compare | assemble` and status ∈ `started | done | failed`. Stages are progress labels only. Every stage reports `started` and then exactly one of `done | failed`; a stage that does not apply (eaudit on a no-rating run) reports `done` at once. The callback must not raise into the run (errors in it are logged and ignored).
- **Partial failure.** paudit failing (or all N scoring runs failing) raises: the run is `failed`. eaudit failing or timing out does not: the report is assembled with `reasons_audit.status = failed|partial` and warning `reasons_audit_failed|reasons_audit_partial`. Tips failing does not: `tips = []` and warning `tips_failed`. In both cases the session ends in `report_ready`.
- There is no parse step: the run starts once transcript + speaker confirm + a final card (`final=true`) or `no_rating` are in (SP04 R4). The run uses the rating revision SP04 snapshotted (`rating_id`) at start.

**R2. Rating card (no parsing).** [RESOLVED: in-app rating card only; no `extract_text`, `parse_rating`, spreadsheet/docx/pdf parsing or parser model step (Tejit 2026-11-20 r6)]
- Input is the pack's `rating.schema.json` object (SP02 R1): `change_goal`, `coded_span{from_s,to_s}`, per global `{score 1-5, reason ≤1,000 chars, example?{at_s, text ≤1,000 chars}}` [RESOLVED: 1,000 chars (Tejit r6)], per behaviour code `{count, note ≤1,000 chars}`, and `notes` (≤3,000 chars, "Additional notes / evaluation reasoning"). `notes` is free text and is **not** parsed into the card.
- `validate_rating(pack, obj, final)` (code only). **Draft (`final=false`, the web app's autosave):** jsonschema; keys ⊆ pack item ids; scores int within `scale`; counts int ≥ 0; `coded_span` ordered, ≥ 0; length limits above (hard limits: SP04 rejects over-limit input; the UI only warns). A draft may be incomplete in any way and never gates a run. **Final (`final=true`):** everything a draft checks, plus `change_goal` non-empty. Only a final card (or `no_rating`) lets the run start. Partial ratings are valid in both (missing item = null, never defaulted). Returns `Issue{path, code}` (paths, never text). A final card with no scores/counts and no notes is treated as a "no rating" run.
- Text is never logged; no flags such as `reason_not_in_source` exist any more (the user typed the card).

**R3. eaudit adaptation (reasons audit).**
- Mapping (code, pack-driven): one eaudit `Section` per rated item **with a reason or example**: `id=item id`, `label=pack label`, `score=clinician value` (display-only, as today), `text=reason` (+ the example as a final line `Example at mm:ss: <text>` when present; plain text only, no retrieval hint in v1). Behaviour-code `note`s map the same way. Items with a value but no reason/example/note produce no section (nothing to audit). The **additional notes** box maps to one extra section `id=notes`, `label="Additional notes / evaluation reasoning"`, `text=notes`, so its claims are audited against the transcript like any other (no suppression exception). Transcript turns → eaudit `Turn` via core helper; roles from speaker map: clinician → `interviewer`, client → `respondent`.
- No new claim type is needed: reasons that are evaluative ("this was a complex reflection") are `out_of_scope` in atomize today; the *judgement* is covered by compare vs Onolys. The reasons audit therefore checks the **factual premises** ("she said she wanted to cut down", "I asked three open questions").
- **Contract change (optional `profile` on the request):** `profile{suppress_concerns: [ConcernType], context_note: str}` (extra=forbid, both optional). `schema_version` is simply bumped `0.0.1 → 0.0.2` (r7: the server does not accept both versions; examples and tests move to `0.0.2`). Other contract details (e.g. `Pointer.index` semantics, a section-id map for pointers) may be changed freely when needed: bump `schema_version` and update `docs/contracts/`. [RESOLVED: change the contract if needed, bump schema_version (Tejit 2026-11-20 r6)] Requests without `profile` take the current code path; the existing `/v1/audit` tests still pass on the updated examples (responses may show the new version and model ids).
- Suppression is applied **before the decision table**: the implementer picks the exact filter point after reading `check/checker.py`/`group_a.py` (one point that covers all verifier flag types plus `unsupported_claim` derivation) and drops flags (and derived concerns) of suppressed types, so verdicts are recomputed from what remains, not left dangling. No concern is ever hidden after the fact. [RESOLVED: build decides the filter point (Tejit 2026-11-20 r6)]
- **eaudit MI work in v1 = the suppress list + `context_note`, nothing else (r7).** The table below is the list (tunable in the pack). No new MI-specific checks are added in v1 (Deferred). eaudit searches the whole transcript as today; timestamp-hinted retrieval is Deferred. Prompts are unchanged except an appended `context_note` block when present (cache prefix of profile-less runs untouched).
- **Evidence mapping (eaudit → report).** eaudit evidence spans are `Span{start: Pointer{index, char}, end: Pointer{index, char}}` (`eaudit/models/audit.py`): `index` is the 0-based position in the request's `transcript` array, `char` a code-point offset, and a span may cross turns [verified: `docs/contracts/README.md`]. The report needs `{turn_id, start, end, quote}` per line, so code maps them: evaluation keeps the list of core turn ids in the order it sent them and `turn_id = sent_turn_ids[index]`. A single-turn span (`start.index == end.index`) → one evidence line `[start.char, end.char)`. A multi-turn span is split into one evidence line per turn: first turn `[start.char, len)`, every turn in between in full, last turn `[0, end.char)`; all lines keep the evidence item's `role`. `quote` is always the substring of the core turn text at those offsets, never model text. Claim spans point into `assessment[index].text`: `index` → section → `item_id` (or `notes`) by the order the sections were sent.
- MITI pack config (`pack.yaml › evaluation.reasons_audit`), engine stays generic:

| Concern type | MITI self-rating | Why |
|---|---|---|
| unsupported_claim, contradictory_evidence, wrong_attribution, negation_reversal, question_as_answer, frequency_severity_inflation, meaning_shift, context_stripping, correction_ignored, certainty_inflation | **keep** | These test whether the cited behaviour/client statement happened as described |
| timeframe_mismatch | suppress | One short session; no past/present drift to catch |
| quantity_mismatch, calculation_error | suppress | Tallies are compared per item by compare; double-reporting |
| opinion_as_fact, unsupported_causal_link, unsupported_inference | suppress | A rating rationale is interpretive by nature |
| conflicting_accounts_flattened | suppress | One client, no competing sources |

`context_note` (pack text): "This is the interviewer's own rating of their conduct. First person refers to the interviewer (speaker role interviewer); item names are protocol codes."
- Report shows eaudit's templated explanations and verdicts; `suggested_revision` is dropped by default (`show_suggested_revision: false`) for tone. Partial/timeout eaudit result → `reasons_audit.status: partial`; eaudit error → `failed` with empty `items`; each with its warning (R1); the report still ships.

**R4. Compare** (code only; thresholds from `pack.yaml › compare`, MITI values = brainstorm "Difference rule"). Clinician values are read from the card: `globals[id].score`, `counts[id].count`.
| Kind | Clinician side | Onolys side | Diff / flag |
|---|---|---|---|
| global | int or null | `aggregate.mean` (the single run's score at the default N=1) | `signed = onolys − clinician`; `differs = abs ≥ 1`; `within_one = abs ≤ 1` |
| count | int or null | aggregate mean, instances from `representative_run` | `signed` always shown; `flagged = abs ≥ 2 or abs/max(clin, onolys) ≥ 0.25` [RESOLVED: denominator max(c, o), so 0 vs 1 flags, 4 vs 5 does not]. Status: `agree` if signed difference = 0; `differs` if ≠ 0 and not flagged; `flagged` otherwise |
| summary | computed by code from the clinician's own counts/globals via the pack formula (paudit's safe evaluator, reused); null if any input missing | `aggregate.summaries` | value vs `reference{fair,good}` both sides; always labelled "reference level, not pass mark" |
Statuses: `agree | differs | flagged | not_rated | no_onolys_value`. No rating → every clinician field null, no diff, aggregates null.
**Explanation (template, no model):** for `differs/flagged` items: headline from `report.yaml` (default "Onolys disagrees, here's why"), then (a) "Onolys scored X; you scored Y" (mean/range wording for N>1 is After launch), (b) Onolys's own reason (paudit `reason`, tone-linted, R6), (c) **lines behind Onolys's score**: globals = paudit `evidence[]`; counts = counted instances of that code from the representative run (all in data, UI shows first `max_instances_shown`), (d) **lines supporting the clinician** where present: reasons-audit claims of that item with `supported/partially_supported` + their `supporting` evidence. Counts note: self-rating has tallies only, so we list Onolys's instances, not which of the clinician's differ. Agreeing items get "Onolys agrees" + same lines, collapsed.

**R5. Tips** (3–5, ranked, one pack item each).
- Input: **only Onolys's representative run** (counted instances with quotes, globals + reasons, summaries vs reference) and clinician turns with the preceding client turn as context. The clinician rating and the diffs are never in the prompt (structural guarantee that tips derive from Onolys's rating, not from disagreement).
- Model (one call on core route `tips`, which aliases `mid` = Claude Sonnet by default; model id, limits and timeout come from the route, SP01 R3; it is a single call, so no cache reuse is assumed; pack `prompts/tips_system.md` + generic output-format instructions) proposes ≤7 `{item_id, observation, quote{turn_id,text}, alternative, why_it_matters}`, ordered by expected impact.
- Code validates: `item_id` ∈ pack items; quote located inside the named **clinician** turn (core `locate`, no fuzzy beyond normalisation) and **replaced by the actual transcript substring** with offsets, so shown text can only be real; `alternative` non-empty, ≤2 sentences, ≠ quote; ≤2 tips per item, one tip per (item, turn); tone lint; keep first 5 valid. <3 valid → one retry with violations listed (retry once, Claude); still <3 → ship fewer + warning `fewer_tips` (never fabricate to reach 3). Zero valid → empty `tips` + warning. The tips call itself failing (error, timeout, bad output after the retry) → `tips = []` + warning `tips_failed`; the report still ships (R1).

**R6. Tone enforced in code.** `tone.py` lints every model-authored string that reaches the report (paudit reasons/rationales, tip text) against `pack.yaml › evaluation.tone.banned` (phrases/regex: "you are wrong", "incorrect", "mistake", "failed to", "you should have", "bad", …; second-person verdicts). Fail → tips: counted as invalid (retry loop); paudit reason: prose omitted, evidence lines kept, warning `reason_withheld_tone`. All static template strings come from `report.yaml` and a unit test lints them with the same list. Wording rule: "Onolys reads this as…", never "you got it wrong"; no per-person verdicts.

**R7. Report JSON** (`schemas/report.schema.json`, `schema_version "0.0.1"`, self-contained: quotes copied with `{turn_id,start,end}`; transcript still fetched separately by id for context):
```
{schema_version, request_id?, created_at,
 header{change_goal, protocol{id,version,pack_hash,label}, language, coded_span, subject_speaker,
        n_runs, models{route:litellm_id}, stt{provider, model, location, language_requested, language_detected, adapter_version},
        preset, code_version, params, has_clinician_rating, rating_coverage{rated,total}},
 layout[{section, title, items?}],                 # from report.yaml
 scorecard[{item_id, kind, label, clinician{value|null}, onolys{value, mean, min, max, values[]},
            diff{signed, abs, direction, status, within_one?}}],
 globals[{item_id, onolys{score, source, reason?, evidence[]}, clinician{value, reason?, example?{at_s?, text}}, diff, explanation{headline, body[], onolys_lines[], clinician_support_lines[]}}],
 behaviours[{item_id, clinician_count, clinician_note?, onolys_count{mean,min,max,values[]}, instances[{id,turn_id,start,end,quote,rationale}], instances_total, diff, explanation}],
 summaries[{id, label, clinician{value,label}|null, onolys{value,label}, reference{fair,good}, note}],
 reasons_audit{status: ran|partial|skipped|failed, items[{item_id (pack item id or `notes` for the additional-notes box), reason, claims[{span, verdict, explanation, concerns[], evidence[{role,turn_id,start,end,quote}]}]}]},
 tips[{rank, item_id, observation, quote{turn_id,start,end,text}, alternative, why_it_matters}],
 method{statement, limits[], not_official_miti_coding: true, citation},
 aggregates{globals_compared, avg_abs_global_difference|null, within_one_share|null, counts_flagged|null},
 warnings[{code, item_id?}], run_info{evaluation, paudit, eaudit}}
```
- Layout, section order, titles, static texts, `max_instances_shown`, section on/off all come from `report.yaml`; builder emits data for every section it knows and `layout` tells the UI order. No-rating run: scorecard has Onolys values only, `reasons_audit.status: skipped`, aggregates null, tips + method still present.
- Dashboard fields (`avg_abs_global_difference`, `within_one_share` over globals with both values) are computed here once and stay in the report JSON (copying them onto the Report doc for dashboard tiles is After launch, SP04 D19). Latest-version rule is SP04's.
- Header (r7): `stt` is the transcript's typed `SttRun`, `preset` the preset name the run used, `code_version` the `GIT_SHA` of the build. Each `run_info` entry is a core `RunInfo` (SP01 R10).
- No transcript or rating text in logs or `run_info`; `prompt_hashes` cover the pack's tips prompts and the engine-owned templates.
- Size: a report JSON larger than 500 KB is stored in GCS with a pointer on the Firestore doc (storage is SP04's; noted here so the builder never assumes a size limit and never truncates).
- Consumers: SP04 stores this document verbatim (`schema_version` → its `report_schema_version`), and validates against `report.schema.json`; SP05 generates its TS types from the same schema file. Claim `verdict` is eaudit's `supported|partially_supported|contradicted|insufficient_evidence|out_of_scope`; evidence `role` is `supporting|contradicting|qualifying`.

**R8. Latency/cost.** Reasons audit ≤15 sections (4 globals + 10 codes + notes), reasons ≤1,000 chars each and notes ≤3,000 → ≈15–40 claims, ~2–3 model calls per claim (link/check) + prep; all parallel, bounded by eaudit's deadline (`IAUDIT_AUDIT_DEADLINE_S`, worker passes ≤120 s). Critical path: `max(paudit ≤ 90 s + tips ≈ 15–25 s, eaudit ≈ 40–90 s)` → assembly < 1 s ⇒ ≈ 1.5–2.5 min at N=1 (the run only starts once the final card is in, and transcription already ran while the user filled it). Caching (r7): parallel calls cannot read a cache entry that is still being written, so paudit sends one warm call before fanning out (already counted in its ≤ 90 s, SP02 R4) and eaudit uses its existing `pipeline/warmup.py`; no estimate here assumes cache reuse across simultaneous calls or between paudit, eaudit and tips. Estimated extra cost ≈ $0.15–0.50 per session on Claude Sonnet routes [unverified; `onolys_evaluation.check` prints tokens; measure at staging]. Levers: skip sections without a reason, tips on one call, eaudit unaffected by N.

**R9. Tests** (offline, `FixtureClient`/stub from core; synthetic fixtures from `protocols/miti-4.2.1/fixtures/` + new `fixtures/evaluation/`): see Acceptance Criteria. **Live check (r7; does not depend on `eval/`):** `python -m onolys_evaluation.check [--preset <name>]` runs one fixture (transcript + final card) end to end on the real model and passes when there are ≥3 valid tips and eaudit completes (`reasons_audit.status: ran`); it prints the tips quote-valid rate, per-stage latency and tokens.

## Architecture
```
rating card (SP05 form → SP04 `validate_rating`) ─> rating ───────┐
transcript + speaker_map ───────────────────────┬──────────────────┼─> reasons audit: eaudit(profile) ─┐
                                                └─> paudit (SP02) ─┴─> PauditResult ─> tips ───────────┤
pack.yaml(compare, evaluation) + report.yaml ───────────────────────────────> compare ─> build_report ─┴─> Report JSON ─> SP04 stores / SP05 renders
```
Engine owns: mechanics (mapping, filter hook, validation, locate, compare arithmetic, tone lint, assembly). Pack owns: item ids/labels, suppress list, context note, thresholds, banned phrases, tip guidance, layout, method text. Grep test: no `miti|cct|reflection` strings in `engines/evaluation/src` or in the eaudit filter code.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Library location | `engines/evaluation/`, import `onolys_evaluation` | `engines/eval` / top-level `eval/` (clashes with admin eval harness `iaudit_eval`); inside `api/` | Distinct from `eval/`; unit-testable without HTTP; admin can reuse |
| 2 | Reasons → eaudit | One section per item with a reason, existing contract | New claim/ item-rating input type in eaudit | Contract already fits; evaluative reasons fall to `out_of_scope` by design |
| 3 | Concern suppression | Optional request `profile`, filtered before decision table; list lives in pack | Hard-code in eaudit; post-filter concerns | Engine stays generic; verdict stays consistent with remaining concerns |
| 4 | Versioning | Bump to `0.0.2` only | Accept `0.0.1` and `0.0.2` side by side with identical goldens; silent additive field on `0.0.1` | Project rule: no back-compat, bump freely; owner accepted the cut. r7 audit (2026-11-20) |
| 5 | Parallelism | eaudit starts with paudit; tips after paudit, alongside eaudit | Sequential; eaudit after paudit; tips fully parallel to paudit | eaudit does not need Onolys's rating; saves ~1 min; tips need paudit's instances (see Risks) |
| 6 | Explanations | Code templates + validated Onolys reason + evidence lines | Model-written "why" per item | Tone and quote guarantees (ADR 0005); no extra calls |
| 7 | Tips input | Onolys's representative run only | Include clinician diffs | Brief: tips come from Onolys's rating, not differences |
| 8 | Tip quotes | Located, then replaced with transcript substring | Trust model quote | Never invent quotes |
| 9 | Fewer than 3 tips | Ship fewer + warning | Pad or fail | No fabrication; partial value beats error |
| 10 | Clinician summaries | Computed by code from their counts/globals with pack formulas | Skip summaries vs reference | Gives a like-for-like %CR/R:Q comparison for free |
| 11 | Rating input | In-app card only; deterministic `validate_rating`; notes box audited as claims | File/paste parsed by a model with user confirm | No parser step, no confirm gate, faster (Tejit r6) |
| 12 | Report layout | Fixed data keys + `layout[]` from `report.yaml` | Fully dynamic sections | Stable TS types for SP05, pack still controls order/labels/text |
| 13 | `suggested_revision` | Not shown | Show | Reads as correction of the person; tone rule |
| 14 | Orchestration | One `run_evaluation` call in one Cloud Task; asyncio inside; `progress_cb(stage, status)` for labels | Worker calls parts as separate tasks with a fan-out threshold | One retry unit, no cross-task state; simpler to get running. r7 audit (2026-11-20) |
| 15 | Partial failure | paudit failure fails the run; eaudit or tips failure still ships a report with status + warning | Fail the run on any stage error | Onolys's rating is the core value; the rest degrades gracefully. r7 audit (2026-11-20) |
| 16 | Draft vs final card | `validate_rating(…, final)`: drafts check shape/limits only; final adds `change_goal`; only final or `no_rating` gates the run | One validation for every save | Autosave must not be rejected or start a run. r7 audit (2026-11-20) |
| 17 | eaudit MI scope | Suppress list + `context_note` only | New MI-specific checks; timestamp-hinted retrieval | Smallest change that removes noise; owner accepted the cut. r7 audit (2026-11-20) |
| 18 | Evidence mapping | Index → `turn_id` by sent order; multi-turn span split into one line per turn | Change the eaudit contract to turn ids | No contract change; report lines stay single-turn like paudit's. r7 audit (2026-11-20) |
| 19 | Count status | `agree` = 0, `differs` ≠ 0 and not flagged, `flagged` otherwise | Two states (agree/flagged) | A difference of 1 on a large count is shown but not flagged. r7 audit (2026-11-20) |
| 20 | Live proof | `python -m onolys_evaluation.check` | Rely on the `eval/` harness | `eval/` is not a v1 priority. r7 audit (2026-11-20) |

## Manual steps
- Tejit: 3 real self-ratings (to sanity-check card fields and caps) when available; wording sign-off of `evaluation.tone.banned`, headline and method/limits text.
- Cross-SP (additive asks, not blockers; all accepted (reconcile pass): SP01 R6 `profile` passthrough, SP02 R1 `evaluation:` block + `from_s`/`to_s` + public `paudit.formula.evaluate`, SP04 `validate_rating`): SP02 pack schema must allow an `evaluation:` top-level block and leave `report.yaml`/`prompts/tips_*` content to SP03; SP02 rating schema names for `coded_span` seconds fields (`from_s/to_s`) and the nested card shape must match `validate_rating`; SP01 `EauditEngine` accepts `profile`; SP02 exposes the safe formula evaluator publicly; SP04 uses `validate_rating`.

## Risks / Open Questions
- [RESOLVED: build decides the filter point after reading `check/checker.py`/`group_a.py`; v1 = suppress list + `context_note` only (r7 audit 2026-11-20, supersedes r6)]
- [RESOLVED: contract details such as `Pointer.index` may be changed freely; bump `schema_version` (Tejit 2026-11-20 r6)] v1 keeps index-based pointers and maps them in evaluation (R3).
- [DEFERRED: After launch (r7 audit 2026-11-20, supersedes r6)] Timestamp-hinted retrieval: eaudit's link step is BM25 on claim text and ignores timestamps clinicians cite ("at 3:10"); v1 searches the whole transcript.
- [DEFERRED: After launch (r7 audit 2026-11-20)] New MI-specific eaudit checks; accepting contract `0.0.1` and `0.0.2` side by side with identical goldens; multi-run mean/range wording.
- [DEFERRED: Claude Sonnet quality, measured on Tejit's transcripts] Quality of atomize/check on first-person self-ratings; run once real self-ratings exist. Build and test on synthetic fixtures now.
- [RESOLVED: card caps: reason/note ≤1,000 chars per item, additional notes ≤3,000; API rejects over-limit input, UI only warns (Tejit 2026-11-20 r6)] Cost of the reasons audit on a verbose rating is bounded by these caps; measure at staging.
- [RESOLVED: tips retry once, on Claude (Tejit 2026-11-20 r6)] Tune on real transcripts.
- [RESOLVED: tips start when paudit finishes and run alongside eaudit (Tejit 2026-11-20 r6)] Tips need paudit's counted instances (D7), so they cannot run fully parallel to paudit.
- [RESOLVED: no parsing, so no xlsx/docx/pdf parser risk (Tejit 2026-11-20 r6)]
- [RESOLVED: count-flag denominator = max(clinician, Onolys)]
- [DEFERRED] Tips about strengths; localised report text; multi-run per-instance voting display.

## Acceptance Criteria
1. `validate_rating`: full, partial (only 2 globals), no-rating (all null) and over-limit cards (reason 1,001 chars, example text 1,001, notes 3,001) → expected `Issue` lists; out-of-range score or unknown key rejected; `coded_span` ordering checked; a draft (`final=false`) with empty `change_goal` passes and the same card with `final=true` returns an issue on `change_goal`; no text in logs; no extractor/parser or office/pdf dependency in the package.
2. Evidence mapping: an eaudit evidence span inside one turn → one report evidence line whose `turn_id` is the id of the turn sent at that index; a span crossing 3 turns → 3 lines (first from `start.char` to the end, middle in full, last up to `end.char`), each `quote` equal to the transcript substring at its offsets.
3. eaudit: the existing `/v1/audit` tests pass on the examples moved to `0.0.2`, without `profile`; with `profile.suppress_concerns=[timeframe_mismatch,…]` a fixture claim that previously returned `timeframe_mismatch` returns no such concern; **verdicts are recomputed after the suppress filter**: a claim whose only flag was of a suppressed type gets the verdict it would have had with no flag, and a claim with one suppressed and one kept flag keeps the verdict the kept flag gives (test asserts both).
4. Reasons-audit mapping: rating with reasons on 3 items → 3 sections with ids = item ids and score display-only; an example line is appended to its item's text; a non-empty additional-notes box → one extra section `id=notes`; roles mapped from speaker map; item without reason → no section; MITI suppress list in the pack matches the table in R3 (test reads `pack.yaml`).
5. Compare: table-driven tests for global (0, 1, 2 diff), count (5v5 → `agree`, 4v5 → `differs`, 0v1 → `flagged`, abs 2 → `flagged`), summary (clinician %CR from their counts, div-by-zero → null), partial rating (`not_rated`), no rating (all diffs absent, aggregates null).
6. Explanations contain only template text + pack/paudit text + quoted transcript; every quote in a differing item exists in the transcript at the stated offsets; a planted banned phrase in a paudit reason → prose withheld + `reason_withheld_tone`; all `report.yaml` strings pass the tone lint.
7. Tips: 3–5 items, each `item_id` in pack, each quote equals the transcript substring in a clinician turn; invented-quote / non-clinician-turn / banned-tone proposals dropped; <3 valid → retry then `fewer_tips`; prompt capture proves the clinician rating is absent from the tips call.
8. Report: output validates `report.schema.json` for fixtures with rating, partial rating, and no rating (Onolys + tips + method only); header carries `stt`, `preset`, `code_version`; layout order follows `report.yaml`; `aggregates.avg_abs_global_difference` / `within_one_share` match hand computation; method block states "not official MITI coding".
9. `run_evaluation` with stub clients: eaudit and paudit start concurrently (test asserts overlap); `progress_cb` receives `started`/`done` for `paudit`, `eaudit`, `tips`, `compare`, `assemble` and a raising callback does not break the run; eaudit timeout → report with `reasons_audit.status: partial` + `reasons_audit_partial`; eaudit error → `status: failed` + `reasons_audit_failed`; tips error → `tips: []` + `tips_failed`; paudit error → `run_evaluation` raises and no report is built.
10. Grep test: no MITI strings in engine source; `onolys_evaluation` imports no `api`; fixtures replay with zero network; `uv run --package onolys-evaluation pytest` and `cd engines/eaudit && uv run pytest` green.
11. Live: `python -m onolys_evaluation.check` on the real model exits 0 with ≥3 valid tips and `reasons_audit.status: ran`, and prints the tips quote-valid rate, per-stage latency and tokens.
