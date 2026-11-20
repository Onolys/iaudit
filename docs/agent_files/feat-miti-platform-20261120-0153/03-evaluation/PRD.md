---
status: draft
summary: New `engines/evaluation/` library turns transcript + clinician rating + PauditResult into one versioned report JSON: rating parser, eaudit "reasons audit" via an optional audit profile, per-item compare with templated "Onolys disagrees, here's why" text, 3-5 quote-validated tips, pack-driven report assembly.
date: 2026-11-20
---
# PRD: SP03 evaluation — rating parser, reasons audit, compare, tips, report

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP01 (core), SP02 (PauditResult, pack, rating schema) · Blocks: SP04 (worker calls it), SP05 (renders report JSON)
Owns: `engines/evaluation/**` (package `onolys_evaluation`, incl. `schemas/{report,parsed-rating}.schema.json`, tests); small additive edits in `engines/eaudit/**` (`models/audit.py`, `contract.py`, `check/checker.py`, `atomize/prompt.py`, tests) + `docs/contracts/{audit-request,audit-response}.schema.json` + `docs/contracts/examples/profile.*`; in the pack: `protocols/miti-4.2.1/prompts/{rating_parse,tips}_*`, `report.yaml` content, the `evaluation:` block of `pack.yaml`, `fixtures/evaluation/**`; `docs/decisions/0019-*`.
Not owned: confirm UIs (SP05), storage/jobs/endpoints (SP04), paudit pipeline, pack loader core (SP02), `EauditEngine` wrapper shell (SP01).

## TL;DR
Everything between "transcript + confirmed speaker map + raw rating + PauditResult" and "report JSON". Five pure-ish parts in one new package: (1) `parse_rating` (text/file → pack rating schema, flagged, user confirms), (2) reasons audit = today's eaudit run on the clinician's reasons, with an optional **audit profile** that suppresses concern types the pack lists, (3) deterministic `compare` with template-written explanations, (4) tips (model proposes, code validates quotes, tips derived only from Onolys's rating), (5) `build_report` laid out by pack `report.yaml`. eaudit runs in parallel with paudit and tips, so wall time ≈ paudit + tips, well inside the 5-min job target.

## Problem
- eaudit audits a free-text assessment; the clinician's rating is structured (item id, score/count, reason) and arrives as arbitrary pasted/uploaded text. [verified: `AuditRequest.assessment[Section{id,label,score display-only,text}]`]
- Nothing compares clinician vs Onolys, explains differences with evidence, or writes tips.
- eaudit's 17 checks assume a clinician's write-up of a patient interview; several are noise or misleading on a self-rating of MI behaviour. [verified: `docs/mission.md` 17 checks]
- The web app needs one stable, self-contained JSON to render; every number and quote in it must trace to the transcript.

## Goals / Non-Goals
**Goals:** rating in, report out, fully offline-testable with fixture LLM clients; MITI specifics only in the pack; tone rules enforced in code; no invented quotes; `POST /v1/audit` unchanged for existing callers.
**Non-goals:** upload/confirm UI, storage, jobs, HTTP (SP04/05); OCR; changing paudit scoring; official MITI claims; chart/dashboard rendering; PDF export; clinician-vs-clinician comparison; timestamp-aware evidence retrieval (see Risks).

## Requirements

**R1. Library + public API** (`engines/evaluation/`, dist `onolys-evaluation`, import `onolys_evaluation`; depends on `onolys_core`, `eaudit`, `paudit` public types; core never imports it):
```python
extract_text(data: bytes, filename: str, media_type: str|None) -> Extracted   # status ok|unreadable|unsupported|too_large; text; hint
parse_rating(ctx, pack, text: str, hints: dict) -> ParsedRating               # R2
validate_rating(pack, obj) -> list[Issue]                                      # SP04 re-validates what the user confirmed
run_evaluation(ctx, pack, transcript, speaker_map, params, rating|None, paudit_result|None) -> Report
build_report(...)  # pure assembly from already-computed parts (used by tests, admin)
```
`run_evaluation` starts the reasons audit (R3) at t0 concurrently with paudit (unless a `paudit_result` is passed in), runs tips (R5) when paudit finishes, joins, then compare + assemble in code. Worker (SP04) may call parts separately; `parse_rating` is its own job step before run.

**R2. Rating parser.**
- `extract_text`: txt as-is; docx (`python-docx`, paragraphs + tables), pdf (`pypdf`, text layer only), xlsx (`openpyxl`, `data_only`, sheets serialised as labelled TSV). No OCR: empty/near-empty text (image-only pdf, scans) → `unreadable` + hint "paste the text instead". Caps: 10 MB file (matches the SP04/SP05 upload limit), 40k chars text, zip-expansion cap (docx/xlsx), macros/formulas never executed. File content is untrusted data in the prompt (delimited; instruction-like text ignored by prompt + schema-constrained output).
- `parse_rating`: one model call on a cheap/mid route (`parse` route) with the pack's `rating.schema.json` + `prompts/rating_parse_system.md` (guidance: where pack item labels/synonyms live; tallies vs ticks; "n/a" → null). Output validated by code: jsonschema, keys ⊆ pack item ids, globals int within `scale`, counts int ≥ 0, `coded_span` clock strings (`mm:ss`, `h:mm:ss`) normalised to the schema's `coded_span.from_s`/`to_s` seconds fields. Partial ratings valid (missing item = null, never defaulted).
- Anti-invention: every `reason` must be located in the source text (core `locate`: exact → normalised); not found → reason dropped + flag `reason_not_in_source`. A score/count whose digits/number-word do not occur in the source → kept but flagged `value_unverified`. Flags are paths (`/globals/empathy`), never text.
- Output `ParsedRating{status ok|partial|unreadable|invalid, rating, field_flags[{path, code}], source_sha256, warnings, run_info}`. User confirms/edits (SP05); `validate_rating` re-checks the confirmed object. Text is never logged.

**R3. eaudit adaptation (reasons audit).**
- Mapping (code, pack-driven): one eaudit `Section` per rated item **with a reason**: `id=item id`, `label=pack label`, `score=clinician value` (display-only, as today), `text=reason`. Items with a value but no reason produce no section (nothing to audit). Transcript turns → eaudit `Turn` via core helper; roles from speaker map: clinician → `interviewer`, client → `respondent`.
- No new claim type is needed: reasons that are evaluative ("this was a complex reflection") are `out_of_scope` in atomize today; the *judgement* is covered by compare vs Onolys. The reasons audit therefore checks the **factual premises** ("she said she wanted to cut down", "I asked three open questions").
- **Contract change (optional `profile` on the request):** `profile{suppress_concerns: [ConcernType], context_note: str}` (extra=forbid, both optional). `schema_version` moves `0.0.1 → 0.0.2`; server accepts both, `profile` only valid with `0.0.2`, response echoes the request's version. Requests without `profile` take the exact current code path (golden test: byte-identical response on `docs/contracts/examples`).
- Suppression is applied **before the decision table**: `check/checker.py` drops verifier flags (and derived concerns) of suppressed types, so verdicts are recomputed from what remains, not left dangling. No concern is ever hidden after the fact. Prompts unchanged except an appended `context_note` block when present (cache prefix of profile-less runs untouched).
- MITI pack config (`pack.yaml › evaluation.reasons_audit`), engine stays generic:

| Concern type | MITI self-rating | Why |
|---|---|---|
| unsupported_claim, contradictory_evidence, wrong_attribution, negation_reversal, question_as_answer, frequency_severity_inflation, meaning_shift, context_stripping, correction_ignored, certainty_inflation | **keep** | These test whether the cited behaviour/client statement happened as described |
| timeframe_mismatch | suppress | One short session; no past/present drift to catch |
| quantity_mismatch, calculation_error | suppress | Tallies are compared per item by compare; double-reporting |
| opinion_as_fact, unsupported_causal_link, unsupported_inference | suppress | A rating rationale is interpretive by nature |
| conflicting_accounts_flattened | suppress | One client, no competing sources |

`context_note` (pack text): "This is the interviewer's own rating of their conduct. First person refers to the interviewer (speaker role interviewer); item names are protocol codes."
- Report shows eaudit's templated explanations and verdicts; `suggested_revision` is dropped by default (`show_suggested_revision: false`) for tone. Partial/timeout eaudit result → `reasons_audit.status: partial` with a warning; the report still ships.

**R4. Compare** (code only; thresholds from `pack.yaml › compare`, MITI values = brainstorm "Difference rule").
| Kind | Clinician side | Onolys side | Diff / flag |
|---|---|---|---|
| global | int or null | `aggregate.mean` (+min/max/values when N>1) | `signed = onolys − clinician`; `differs = abs ≥ 1`; `within_one = abs ≤ 1` |
| count | int or null | aggregate mean, instances from `representative_run` | `signed` always shown; `flagged = abs ≥ 2 or abs/max(clin, onolys) ≥ 0.25` [RESOLVED: denominator max(c, o), so 0 vs 1 flags, 4 vs 5 does not] |
| summary | computed by code from the clinician's own counts/globals via the pack formula (paudit's safe evaluator, reused); null if any input missing | `aggregate.summaries` | value vs `reference{fair,good}` both sides; always labelled "reference level, not pass mark" |
Statuses: `agree | differs | flagged | not_rated | no_onolys_value`. No rating → every clinician field null, no diff, aggregates null.
**Explanation (template, no model):** for `differs/flagged` items: headline from `report.yaml` (default "Onolys disagrees, here's why"), then (a) "Onolys scored X (mean of N runs, range a–b); you scored Y", (b) Onolys's own reason (paudit `reason`, tone-linted, R6), (c) **lines behind Onolys's score**: globals = paudit `evidence[]`; counts = counted instances of that code from the representative run (all in data, UI shows first `max_instances_shown`), (d) **lines supporting the clinician** where present: reasons-audit claims of that item with `supported/partially_supported` + their `supporting` evidence. Counts note: self-rating has tallies only, so we list Onolys's instances, not which of the clinician's differ. Agreeing items get "Onolys agrees" + same lines, collapsed.

**R5. Tips** (3–5, ranked, one pack item each).
- Input: **only Onolys's representative run** (counted instances with quotes, globals + reasons, summaries vs reference) and clinician turns with the preceding client turn as context. The clinician rating and the diffs are never in the prompt (structural guarantee that tips derive from Onolys's rating, not from disagreement).
- Model (`tips` route, pack `prompts/tips_system.md` + generic output-format instructions) proposes ≤7 `{item_id, observation, quote{turn_id,text}, alternative, why_it_matters}`, ordered by expected impact.
- Code validates: `item_id` ∈ pack items; quote located inside the named **clinician** turn (core `locate`, no fuzzy beyond normalisation) and **replaced by the actual transcript substring** with offsets, so shown text can only be real; `alternative` non-empty, ≤2 sentences, ≠ quote; ≤2 tips per item, one tip per (item, turn); tone lint; keep first 5 valid. <3 valid → one retry with violations listed; still <3 → ship fewer + warning `fewer_tips` (never fabricate to reach 3). Zero valid → empty `tips` + warning.

**R6. Tone enforced in code.** `tone.py` lints every model-authored string that reaches the report (paudit reasons/rationales, tip text) against `pack.yaml › evaluation.tone.banned` (phrases/regex: "you are wrong", "incorrect", "mistake", "failed to", "you should have", "bad", …; second-person verdicts). Fail → tips: counted as invalid (retry loop); paudit reason: prose omitted, evidence lines kept, warning `reason_withheld_tone`. All static template strings come from `report.yaml` and a unit test lints them with the same list. Wording rule: "Onolys reads this as…", never "you got it wrong"; no per-person verdicts.

**R7. Report JSON** (`schemas/report.schema.json`, `schema_version "0.0.1"`, self-contained: quotes copied with `{turn_id,start,end}`; transcript still fetched separately by id for context):
```
{schema_version, request_id?, created_at,
 header{change_goal, protocol{id,version,pack_hash,label}, language, coded_span, subject_speaker,
        n_runs, models{route:litellm_id}, params, has_clinician_rating, rating_coverage{rated,total}},
 layout[{section, title, items?}],                 # from report.yaml
 scorecard[{item_id, kind, label, clinician{value|null}, onolys{value, mean, min, max, values[]},
            diff{signed, abs, direction, status, within_one?}}],
 globals[{item_id, onolys{score, source, reason?, evidence[]}, clinician{value, reason?}, diff, explanation{headline, body[], onolys_lines[], clinician_support_lines[]}}],
 behaviours[{item_id, clinician_count, onolys_count{mean,min,max,values[]}, instances[{id,turn_id,start,end,quote,rationale}], instances_total, diff, explanation}],
 summaries[{id, label, clinician{value,label}|null, onolys{value,label}, reference{fair,good}, note}],
 reasons_audit{status: ran|partial|skipped|failed, items[{item_id, reason, claims[{span, verdict, explanation, concerns[], evidence[{role,turn_id,start,end,quote}]}]}]},
 tips[{rank, item_id, observation, quote{turn_id,start,end,text}, alternative, why_it_matters}],
 method{statement, limits[], not_official_miti_coding: true, citation},
 aggregates{globals_compared, avg_abs_global_difference|null, within_one_share|null, counts_flagged|null},
 warnings[{code, item_id?}], run_info{evaluation, paudit, eaudit, parser?}}
```
- Layout, section order, titles, static texts, `max_instances_shown`, section on/off all come from `report.yaml`; builder emits data for every section it knows and `layout` tells the UI order. No-rating run: scorecard has Onolys values only, `reasons_audit.status: skipped`, aggregates null, tips + method still present.
- Dashboard fields (`avg_abs_global_difference`, `within_one_share` over globals with both values) are computed here once; SP04 copies them onto the Report doc for tiles. Latest-version rule is SP04's.
- No transcript or rating text in logs or `run_info`; per-stage hashes of evaluation prompts included.
- Consumers: SP04 stores this document verbatim (`schema_version` → its `report_schema_version`), validates against `report.schema.json` and copies `aggregates`; SP05 generates its TS types from the same schema file. Claim `verdict` is eaudit's `supported|partially_supported|contradicted|insufficient_evidence|out_of_scope`; evidence `role` is `supporting|contradicting|qualifying`.

**R8. Latency/cost.** Reasons audit ≤14 sections (4 globals + 10 codes), short reasons → ≈15–30 claims, ~2–3 model calls per claim (link/check) + prep; all parallel, bounded by eaudit's deadline (`IAUDIT_AUDIT_DEADLINE_S`, worker passes ≤120 s). Critical path: `max(paudit ≈ 60 s, eaudit ≈ 40–90 s)` → tips ≈ 15–25 s → assembly < 1 s ⇒ ≈ 1.5–2.5 min at N=1; parse step ≈ 5–10 s, outside the run. Estimated extra cost ≈ $0.10–0.35 per session on Flash/Pro-class routes [unverified; measure]. Levers: skip sections without a reason, tips on one call, eaudit unaffected by N.

**R9. Tests** (offline, `FixtureClient`/stub from core; synthetic fixtures from `protocols/miti-4.2.1/fixtures/` + new `fixtures/evaluation/`): see Acceptance Criteria.

## Architecture
```
file/text ─extract─> parse_rating ─(user confirms: SP05)─> rating ─┐
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
| 4 | Versioning | `0.0.2`, accept `0.0.1` and `0.0.2`, `profile` only in `0.0.2` | Silent additive field on `0.0.1`; hard reset | Existing `POST /v1/audit` callers untouched; explicit signal |
| 5 | Parallelism | eaudit starts with paudit; tips after paudit | Sequential; eaudit after paudit | eaudit does not need Onolys's rating; saves ~1 min |
| 6 | Explanations | Code templates + validated Onolys reason + evidence lines | Model-written "why" per item | Tone and quote guarantees (ADR 0005); no extra calls |
| 7 | Tips input | Onolys's representative run only | Include clinician diffs | Brief: tips come from Onolys's rating, not differences |
| 8 | Tip quotes | Located, then replaced with transcript substring | Trust model quote | Never invent quotes |
| 9 | Fewer than 3 tips | Ship fewer + warning | Pad or fail | No fabrication; partial value beats error |
| 10 | Clinician summaries | Computed by code from their counts/globals with pack formulas | Skip summaries vs reference | Gives a like-for-like %CR/R:Q comparison for free |
| 11 | Parser verification | Reasons must exist in source; numbers flagged if absent | Trust model; strict reject | User confirms anyway; flags focus their check |
| 12 | Report layout | Fixed data keys + `layout[]` from `report.yaml` | Fully dynamic sections | Stable TS types for SP05, pack still controls order/labels/text |
| 13 | `suggested_revision` | Not shown | Show | Reads as correction of the person; tone rule |

## Manual steps
- Tejit: 3 real self-ratings in the formats users actually use (docx/pdf/xlsx/pasted) for parser fixtures; wording sign-off of `evaluation.tone.banned`, headline and method/limits text.
- Cross-SP (additive asks, not blockers; all accepted (reconcile pass): SP01 R6 `profile` passthrough, SP02 R1 `evaluation:` block + `from_s`/`to_s` + public `paudit.formula.evaluate`, SP04 `validate_rating` + `aggregates`): SP02 pack schema must allow an `evaluation:` top-level block and leave `report.yaml`/`prompts/{rating_parse,tips}_*` content to SP03; SP02 rating schema names for `coded_span` seconds fields (`from_s/to_s`) must match the parser; SP01 `EauditEngine` accepts `profile`; SP02 exposes the safe formula evaluator publicly; SP04 uses `validate_rating` and copies `aggregates`.

## Risks / Open Questions
- [OPEN] Verify where the verifier flags enter the decision table in `check/checker.py`/`group_a.py` so one filter point covers all 12 flag types plus `unsupported_claim` derivation.
- [OPEN] Confirm assessment span `Pointer.index` is the section index so claims map back to items (examples in `docs/contracts/examples`); else carry a section-id map.
- [OPEN] eaudit's link step is BM25 on claim text; clinicians often cite timestamps ("at 3:10") which it ignores. Measure retrieval recall on fixtures; DEFERRED fix: timestamp-hinted shortlist.
- [OPEN] Gemini vs Claude quality for atomize/check with first-person self-ratings (eaudit tuned on Claude); eval run once real self-ratings exist.
- [OPEN] Real cost of reasons audit on a verbose rating; cap reason length (default 1,000 chars/item, truncate + warning)?
- [OPEN] Does one tips call reliably give ≥3 valid quotes on Gemini? Retry once is built in; tune on real transcripts.
- [OPEN] Parser accuracy on messy xlsx layouts; fallback is paste.
- [RESOLVED: count-flag denominator = max(clinician, Onolys)]
- [DEFERRED] OCR for image-only files; tips about strengths; localised report text; multi-run per-instance voting display.

## Acceptance Criteria
1. `extract_text`: txt/docx/pdf/xlsx fixtures → expected text; image-only pdf and empty file → `unreadable` with paste hint; oversize/zip-bomb → `too_large`; no OCR dependency.
2. `parse_rating` (stub client): full, partial (only 2 globals) and noisy fixtures → schema-valid `ParsedRating`; hallucinated reason → dropped + `reason_not_in_source`; out-of-range score or unknown key → rejected/flagged; clock span → seconds; no text in logs.
3. eaudit: request without `profile` yields a byte-identical response on every `docs/contracts/examples` fixture; with `profile.suppress_concerns=[timeframe_mismatch,…]` a fixture claim that previously returned `timeframe_mismatch` returns no such concern and a verdict consistent with remaining flags; `0.0.1` + `profile` → validation error; both versions accepted.
4. Reasons-audit mapping: rating with reasons on 3 items → 3 sections with ids = item ids and score display-only; roles mapped from speaker map; item without reason → no section; MITI suppress list in the pack matches the table in R3 (test reads `pack.yaml`).
5. Compare: table-driven tests for global (0, 1, 2 diff; N=3 mean), count (4v5 unflagged, 0v1 flagged, 2 abs flagged), summary (clinician %CR from their counts, div-by-zero → null), partial rating (`not_rated`), no rating (all diffs absent, aggregates null).
6. Explanations contain only template text + pack/paudit text + quoted transcript; every quote in a differing item exists in the transcript at the stated offsets; a planted banned phrase in a paudit reason → prose withheld + `reason_withheld_tone`; all `report.yaml` strings pass the tone lint.
7. Tips: 3–5 items, each `item_id` in pack, each quote equals the transcript substring in a clinician turn; invented-quote / non-clinician-turn / banned-tone proposals dropped; <3 valid → retry then `fewer_tips`; prompt capture proves the clinician rating is absent from the tips call.
8. Report: output validates `report.schema.json` for fixtures with rating, partial rating, and no rating (Onolys + tips + method only); layout order follows `report.yaml`; `aggregates.avg_abs_global_difference` / `within_one_share` match hand computation; method block states "not official MITI coding".
9. `run_evaluation` with stub clients: eaudit and paudit start concurrently (test asserts overlap), eaudit timeout → report with `reasons_audit.status: partial` + warning, N=3 paudit result → mean/spread in scorecard.
10. Grep test: no MITI strings in engine source; `onolys_evaluation` imports no `api`; fixtures replay with zero network; `uv run --package onolys-evaluation pytest` and `cd engines/eaudit && uv run pytest` green.
