---
status: draft
summary: Generic protocol-audit engine `engines/paudit/` + versioned protocol-pack format + MITI 4.2.1 pack; models propose codes with quotes, code validates, enforces rules, computes counts/summaries; N runs as array with mean/spread.
date: 2026-11-20
---
# PRD: SP02 paudit engine + protocol pack format + MITI 4.2.1 pack

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP01 (`engines/core/`, `engines/` layout) · Blocks: SP03 (consumes result + pack), SP04 (engine contract for stubs), SP07 (admin tab)
Owns: `engines/paudit/**` (incl. `schemas/{pack,paudit-result}.schema.json`, `cli.py`, tests), `protocols/miti-4.2.1/**`, `eval/datasets/paudit/**`, `docs/decisions/0018-protocol-pack-data-vs-code.md` (+ `docs/contracts/README.md` pointer only)
Not owned: rating validation (`validate_rating`), per-item comparison, tips, report assembly (SP03), and inside the pack SP03 owns `prompts/tips_*`, the content of `report.yaml`, the `evaluation:` block of `pack.yaml` and `fixtures/evaluation/**` (SP02 ships the pack format, loader, schemas and a stub `report.yaml`); HTTP endpoint/jobs (SP04); admin tab (SP07); `engines/core/*` (SP01 — needs listed below).

## TL;DR
`paudit` takes a transcript, a pack reference and params, and returns a typed, versioned result: per-utterance behaviour codes (quoted, offset-located), counts, summary scores vs reference levels, four globals with cited lines, warnings, `run_info`. Same pipeline shape as eaudit: models propose (utterance split + code + quote + rationale; globals + cited quotes), code decides (quote location, rule enforcement, counts, summaries, range/default/5-cap). Everything MITI-specific lives in `protocols/miti-4.2.1/` as data (`pack.yaml`) plus a thin `rules.py`; the engine has zero MITI strings. N runs → `results[]` + `aggregate` (mean/min/max, representative run). ~6 model calls per 25-min run.

## Problem
- Onolys must produce its own MITI rating to compare with the clinician's. No engine does protocol-level rating; eaudit checks claims, not coded behaviour. [verified: `ls eaudit/src/eaudit` → atomize/link/check/assembler only]
- Hard-coding MITI would block "other protocols later" and violate the anti-goal (MITI specifics in engine code).
- Single-model "rate this session" answers are unverifiable (ADR 0005); every count must trace to a quoted line, every global to cited lines.

## Goals / Non-Goals
**Goals**
- Pack format v0.0.1 (loader + schema validation + parity checks) and a second toy pack in tests proving the engine is protocol-agnostic.
- MITI 4.2.1 pack complete: 4 globals, 10 codes, rules, formulas, reference levels, input checks, rating schema, prompts, report layout, fixtures.
- Deterministic offline tests (stub/fixture LLM); eval dataset folder + CLI so quality can be measured.
- Result shape SP03 can diff against the clinician's rating card without engine knowledge of MITI.

**Non-Goals**
- Official MITI coding claims; inter-rater reliability work (eval later, certified coder data from Tejit).
- User-uploaded/edited packs (packs are trusted repo code; `rules.py` is imported).
- Transcription/diarization (SP01), speaker confirmation UI (SP05), HTTP endpoint (SP04), comparison/tips (SP03), admin UI (SP07), non-English prompts.
- Cross-turn utterances (see Risks).

## Requirements
**R1. Pack format (`pack_format: "0.0.1"`; project-wide rule: no back-compat, bump freely).**
```
protocols/<id>-<version>/
  pack.yaml            # data (below)
  rules.py             # optional hooks (below)
  rating.schema.json   # user's rating; keys must equal pack item ids (parity-tested)
  prompts/             # code_system.md, code_fewshot.json, globals_system.md, globals_fewshot.json
  report.yaml          # section order + labels (read by SP03/SP05)
  fixtures/            # synthetic transcripts + expected.yaml
```
`pack.yaml` sections:

| Section | Content (MITI example) |
|---|---|
| `id`, `version`, `source` | `miti`, `4.2.1`, manual citation + URL + permission note |
| `speaker_roles` | `subject: clinician`, `other: client` (only `subject` speech is coded) |
| `items[]` | `{id, kind: global\|count, label, definition, examples?}`; globals add `scale{min,max,default}`, `evidence_min`, `caps[]` |
| `rules[]` | declarative, engine-generic kinds: `one_code_per_utterance`, `max_per_unit{unit: volley, code: any, n:1}`, `exclusive_group{unit: volley, codes:[sr,cr], precedence:[cr,sr]}`, `cap{item, max, when: poor_practice_cited}` |
| `volley` | `breaks_on: other_speaker` (+ `min_other_words` default 0) |
| `summaries[]` | `{id, label, expr, format, reference{fair, good, direction}}`; `expr` is a whitelisted arithmetic expression over item ids (`(cct+sst)/2`, `cr/(sr+cr)`, `(sr+cr)/question`, `seek_collab+affirm+emphasize_autonomy`); div-by-zero → `null` |
| `input_checks[]` | `{id, kind: duration_max\|duration_min\|param_required\|min_subject_turns, value, severity: error\|warn}`; MITI: 25 min error, 10 min warn (globals unreliable), `change_goal` error |
| `compare` | per-item `kind` + thresholds from brainstorm "Difference rule" (read by SP03; SP03 may extend) |
| `evaluation` | Optional, opaque to paudit: `pack.schema.json` allows any object under this top-level key; owned and validated by SP03's `onolys_evaluation` (MITI: reasons-audit suppress list + context note, tone `banned`, tip limits). Covered by `pack_hash` (it is inside `pack.yaml`) [RESOLVED: `evaluation:` block allowed (reconcile pass)] |

MITI item ids (shared with rating schema, result, report): globals `cct, sst, partnership, empathy`; codes `gi, persuade, persuade_permission, question, sr, cr, affirm, seek_collab, emphasize_autonomy, confront`.

`rating.schema.json` (MITI v1) is the in-app **rating card** and the only rating input (no file upload, no paste-to-parse, no parser step): `{change_goal (required to start a run), coded_span{from_s,to_s}, globals{cct,sst,partnership,empathy: {score: int 1-5|null, reason: string ≤1,000 chars, example?: {at_s: int|null, text: string}}}, counts{<10 code ids>: {count: int ≥0|null, note?: string ≤1,000 chars}}, notes: string ≤3,000 chars}`. `notes` is the free-text "Additional notes / evaluation reasoning" box: it is never parsed into the card; SP03 hands it to eaudit as additional claims. Limits are hard at the API (SP04 rejects >1,000 per reason/note and >3,000 notes) and soft in the UI (live counter, warn only). Every item key is optional/nullable (partial ratings valid). `coded_span` uses **`from_s`/`to_s`** (seconds, int|null): the same names as the engine param `coded_span`, SP04's session field and SP05's form (the web form converts mm:ss to seconds). [RESOLVED: `from_s`/`to_s` everywhere (reconcile pass); brainstorm's `from`/`to` superseded] [RESOLVED: nested card shape replaces the flat `globals`/`counts`/`reasons` shape (Tejit 2026-11-20 r6)]

`rules.py` hooks (all optional, pure functions, no I/O): `check_input(input, ctx) -> [Warning]`, `validate_codes(instances, ctx) -> [Adjustment]` (extra rules data cannot express; may only down-count with a reason, never add/relabel), `compute_summary(counts, globals, ctx) -> dict | None` (override of formula data). MITI `rules.py` ships one real hook: warning `reflection_before_client_speech` (a reflection in a volley with no prior other-speaker turn). Everything else is data.

Loader (`engines/paudit/pack.py`): resolves `miti@4.2.1` under `protocols/` (dir configurable) or a path; validates `pack.yaml` against `schemas/pack.schema.json`; checks parity (rating schema keys = item ids; `report.yaml` and `compare` ids exist; prompt files present; formulas parse and reference only known ids; precedence lists subset of group); computes `pack_hash` (sha256 over pack.yaml, rules.py, rating schema, prompts, report.yaml; not fixtures). Errors → typed `PackError` at load, never at run time.

**R2. Pipeline** (`paudit.run(transcript, pack, params, client) -> PauditResult`; engine-interface shape from SP01).
Params: `speaker_map{subject: <speaker id>}` (required), `change_goal`, `coded_span{from_s,to_s}`, `language` (BCP-47 or `auto`), `n_runs` (default 1), `run_temperature` (default 0.0 for N=1, 0.4 for N>1), `tiers{code,globals}` (default `mid`/`strong`; mapped to models by core registry; both resolve to Claude Sonnet by default, r6).
1. **Input checks** (code): pack `input_checks` + `check_input` hook → typed error or warnings. Unknown-speaker turns treated as `other` + warning.
2. **Select** (code): keep turns that overlap `coded_span` (any clinician turn partly inside the span is included whole) (no timestamps + span → warning `span_ignored`); mark subject vs other by `speaker_map`.
3. **Volleys** (code): consecutive subject turns not broken by another speaker's turn (per pack `volley`) = one volley; `v1..vN`. Other-speaker turns kept as read-only context.
4. **Code pass** (model, batched): ≈25 volleys per call, each preceded by its previous other-speaker turn as context, batches in parallel. Model returns per volley `utterances[{quote, code|null, rationale}]` (split + code in one call; `code` enum built from pack at runtime; `null` = uncoded). Prompt = pack `code_system.md` + definitions rendered from `pack.yaml` (never duplicated) + few-shot; cache prefix = system+definitions, second = transcript header (Claude prompt caching, `anthropic_ephemeral`; the shared prefix is reused across batches and N runs, and batches and N runs run in parallel, r6).
5. **Validate/locate** (code): each `quote` located inside its volley's turn text via core `locate` (exact → normalized → guarded fuzzy; code-point offsets, ADR 0002); ordered, non-overlapping, never crossing a turn boundary. Unlocatable/overlapping → utterance dropped + `quote_not_found`/`overlap` warning; >20% of a batch dropped → one retry of that batch; still bad → run fails (no silent partial counts, ADR 0012).
6. **Rules** (code): apply pack `rules[]` then `validate_codes`. Violations never delete: instance stays with `counted:false` + `uncounted_reason` (`duplicate_in_volley`, `superseded_by_cr`, …) so UI/eval can show why. Winner = first in text order, or `precedence` for groups.
7. **Counts + summaries** (code): counts over `counted` instances; summaries by safe-AST evaluation of pack formulas (public `paudit.formula.evaluate(expr, values) -> float|None`, reused by SP03 for the clinician's own summaries [RESOLVED: public evaluator (reconcile pass)]); label vs reference (`below_fair|fair|good|null`).
8. **Globals pass** (model, 1 call, 4 items): whole span with turn ids, change goal; returns per global `{score, reason, evidence[{turn_id, quote}], poor_practice_cited[]}`. Code: quotes located; score outside scale → run error; `< evidence_min` valid quotes and score ≠ default → reset to default with `source:"default"` + `insufficient_evidence`; score 5 with `poor_practice_cited` non-empty → capped (`source:"capped"`, `raw_score` kept). Globals pass does not see code counts (avoids anchoring; see Decisions).
9. **N runs**: steps 4–8 repeated N times concurrently (core semaphore), each with `run_index` in call tags; step 1–3 shared. A failed run is excluded with warning; all failed → error. `aggregate` computed by code.
10. **Language**: pack prompts English. Transcript language passed in prompt; quotes verbatim in original language, rationales/reasons English. Non-`en*` → info warning `language_not_validated`. Quote location is language-agnostic (NFC, case-fold, whitespace collapse; no stemming).

**R3. Result schema** `engines/paudit/schemas/paudit-result.schema.json`, `schema_version "0.0.1"`:
```
{schema_version, request_id?, protocol:{id,version,pack_hash,pack_format}, language, change_goal,
 coded_span, subject_speaker, n_runs,
 results[{run_index,
   instances[{id, volley_id, turn_id, start, end, start_ms?, end_ms?, quote, code|null,
              counted, uncounted_reason?, rationale}],
   counts{item_id:int}, 
   globals{item_id:{score, source:model|default|capped, raw_score, reason,
                    evidence[{turn_id,start,end,quote}]}},
   summaries{id:{value|null, label, reference{fair,good}}}, warnings[]}],
 aggregate{counts{item:{mean,min,max,values[]}}, globals{...}, summaries{...}, representative_run},
 warnings[], run_info}
```
- Offsets = code points into `turn.text`. `representative_run` = run whose count/global vector is closest to the mean (ties → lowest index); SP03 lists instances from it.
- `run_info` (core builder + `engine:"paudit"`, `protocol:{id,version,pack_hash}`, models per tier, per-stage prompt hashes from the pack, per-call counts). Core hash helper must take a file list (eaudit's is hard-wired). No text in `run_info` or logs.
- Warning codes: `short_session`, `quote_not_found`, `overlap`, `insufficient_evidence`, `capped`, `span_ignored`, `unknown_speaker`, `language_not_validated`, `run_failed`, plus pack-defined.

**R4. Cost/latency.** 25 min ≈ 4k words ≈ 6k tokens → ~60–120 volleys → 3–5 code calls + 1 globals call per run (~6). Est. input ≈ 30–40k tokens/run, ≈ $0.10–0.30 on Claude Sonnet routes with prompt caching (unverified estimate; measure at staging). Wall ≈ 20–40 s/run (batches parallel); N runs parallel. Target ≤60 s p95 at N=1 so SP04's 5-min job budget holds at N≤3.

**R5. Testing / eval.**
- Unit: pack loader (good + 6 malformed packs), safe-expr evaluator (no names outside items, no calls), rules (duplicate GI, SR+CR in a volley → CR counted, cap on 5), quote locating, volley builder, aggregate, schema validation of result, parity test (rating schema ↔ pack items), toy-protocol pack (2 codes, 1 global) run end-to-end to prove genericity; grep test: no `miti|cct|reflection` strings under `engines/paudit/src`.
- Stub client (call_tag-keyed callables) for logic tests; one recorded-replay golden (`FixtureClient`) re-recorded when prompts freeze. Fixtures: 3 synthetic role-plays under `protocols/miti-4.2.1/fixtures/` (good practice; poor practice with Persuade/Confront; 8-min short) with `expected.yaml` (per-utterance intended codes, expected counts, global ranges).
- Eval hook: `eval/datasets/paudit/{metadata.json,adapter.py,…}` same adapter style as `eval/datasets/eaudit/synthetic`; metrics minimal: per-code count MAE, global exact / within-1, %CR error; CLI `python -m paudit.cli run --pack miti@4.2.1 --transcript f.json --params p.json`. No admin wiring (SP07). The eval hook is best effort: the eval harness is not a v1 priority and may break.

## Architecture
```
Transcript(+speaker_map,span) → input_checks → select → volleys ─┬→ code pass ×batches → locate → rules → counts/summaries ┐
                                                                  └→ globals pass → locate → range/default/5-cap ──────────────┴→ run result (×N) → aggregate → PauditResult+run_info
pack.yaml ─ items/rules/summaries/checks → drive every box;  rules.py ─ 3 optional hooks;  prompts/ ─ protocol guidance only
```
Engine owns: pipeline, output-format instructions, response models, locate/validate, generic rule kinds, safe-expr evaluator, aggregate, schemas. Pack owns: vocabulary, definitions, rule parameters, formulas, thresholds, guidance text, labels.

**Needed from SP01 `engines/core/` (interface assumptions):** `LLMClient`/`LLMRequest(tier, call_tag, response_model, cache_prefixes, temperature)` + stub/fixture/recording clients; model-route registry; `Transcript/Turn{id, speaker, text, start_ms?, end_ms?}` + `Span`; `locate(text, quote, hint)` promoted from `eaudit/assembler/locate.py` (+ normalize); `run_info` builder accepting extra fields and a prompt-file hash helper; `safe_log`; generic `Engine.run(transcript, pack_ref, params) -> (result, run_info)` protocol; typed errors (`InputError`, `PackError`) (all in SP01 R2: `locate.py`, `errors.py`, `hash_files`).
**For SP03:** reads `PauditResult.aggregate` (+ `results[representative_run].instances`) and `pack.yaml` `items`/`compare`/`report.yaml`. Rating keys = item ids. **For SP04:** stub engine returns a schema-valid `PauditResult`; the public API exposes paudit only through sessions/runs (no `/v1/paudit`). **For SP07:** admin-only `POST /v1/paudit` (body needs `speaker_map` and `change_goal`).

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Data vs code | Everything declarative in `pack.yaml`; `rules.py` = 3 escape hooks, MITI ships 1 | All rules in Python; all in YAML incl. predicates | Keeps engine MITI-free; a YAML predicate language is overkill |
| 2 | Formulas | Whitelisted arithmetic expr over item ids, safe-AST | `eval`; Python-only `compute_summary` | No code injection, diffable, testable |
| 3 | Segmentation | Model splits utterances inside the code call; code builds volleys and validates quotes | Rules-only sentence split; separate seg call | One call/batch; MITI utterances are judgment (complete thoughts); code still verifies |
| 4 | Untiled text | Allowed (= uncoded) | Require full tiling | MITI has uncoded text; fewer false failures |
| 5 | Rule violations | Keep instance, `counted:false` + reason | Delete | Transparency for UI/eval |
| 6 | Globals pass sees no counts | Independent | Feed counts | Avoids anchoring; counts/globals disagreement is signal |
| 7 | One globals call for 4 items | Single call | 4 calls | Cost; halo effect risk noted, eval can flip |
| 8 | 5-rule | Model must list `poor_practice_cited`; code caps 5→4 | Prompt-only | "Code decides" |
| 9 | No evidence → default | Reset to default 3 | Trust score | MITI default-3 spirit |
| 10 | N runs | Array + aggregate; representative run for instances; T=0 for N=1, 0.4 for N>1 | Average instances; always T=0 | Instances cannot be averaged; identical T=0 runs add nothing |
| 11 | Failure | Failed batch → run fails; failed run excluded when N>1 | Partial counts | Wrong counts worse than none (ADR 0012) |
| 12 | Non-English | Best effort + info warning | Block | Params-only swap; unvalidated |
| 13 | Version | `pack_format`/result `0.0.1`, hash in run_info | Semver compat | Project rule |
| 14 | Rating input shape | In-app rating card, nested score/reason/example + count/note + notes; API-enforced char limits | File/paste parsed into a flat schema | Card is the only input (Tejit r6); no parsing risk |

## Manual steps
- Tejit: ≥3 real role-play transcripts + ≥1 certified-coder rating each (eval ground truth); confirm citation/permission wording shown in `source`.
- Implementer: read manual 4.2.1 (PDF) and write item definitions with citation; do not paraphrase loosely.

## Risks / Open Questions
- [DEFERRED: Tejit supplies transcripts and coder ratings] Utterances crossing a turn boundary (diarizer splits one thought). v1 treats as two utterances; may inflate counts. Measure on real transcripts; build and test on synthetic fixtures now.
- [RESOLVED: any other-speaker turn breaks a volley; `min_other_words` knob exists (Tejit 2026-11-20 r6, accepted default)] Does a client "mm-hm" break a volley?
- [RESOLVED: include any clinician turn that overlaps the span (Tejit 2026-11-20)] Span selection uses overlap (`start_ms < to_s*1000 and end_ms > from_s*1000`), not `start_ms` containment; turns without `end_ms` fall back to `start_ms`.
- [DEFERRED: Claude Sonnet quality, measured on Tejit's transcripts] Claude Sonnet coding quality vs expert (published AI-vs-expert globals r≈0.34–0.63); prompts/few-shot tuning needs real data. Build and test on synthetic fixtures now.
- [RESOLVED: admin-only `POST /v1/paudit` on SP07's `admin-backend`; the public API exposes paudit only via sessions/runs (reconcile pass)]
- [DEFERRED: Tejit supplies transcripts and coder ratings] Prompt wording for "prefer fewer parses" and uncoded categories needs certified-coder review; prompts ship as v1 drafts, reviewed later.
- [DEFERRED] Self-consistency voting across N runs per utterance; non-English prompts; user packs; caudit reuse of pack format.
- [RESOLVED: tests need no network — stub client by call_tag + one recorded golden]

## Acceptance Criteria
- Pack loader loads `miti@4.2.1` and a toy pack; 6 malformed packs each raise `PackError`; parity test green.
- Stub-driven run on each fixture yields a schema-valid `PauditResult` with counts/summaries equal to `expected.yaml`; replaying the golden twice is byte-identical.
- Rule tests: 2 GI in a volley → 1 counted; SR+CR → CR counted; global 5 with poor practice → 4; no evidence → 3; summaries match formulas incl. div-by-zero → null.
- Input: >25 min or missing change goal → typed error; <10 min → `short_session` warning.
- `n_runs=3` → 3 results + aggregate with mean/min/max and `representative_run`.
- `run_info` carries pack id/version/hash, models, prompt hashes; no transcript text in logs.
- No MITI-specific strings in `engines/paudit/src` (grep test).
- `python -m paudit.cli run …` works offline with stub; `eval/datasets/paudit/` loads in the eval harness and reports MAE/within-1 (best effort; skipped if the eval harness is broken).
