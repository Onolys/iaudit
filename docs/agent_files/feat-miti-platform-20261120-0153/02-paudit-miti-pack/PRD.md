---
status: draft
summary: Generic protocol-audit engine `engines/paudit/` + versioned protocol-pack format + MITI 4.2.1 pack; models propose codes with quotes, code validates, enforces rules, computes counts/summaries; `n_runs` param (default 1); live `paudit.cli check` against fixtures.
date: 2026-11-20
---
# PRD: SP02 paudit engine + protocol pack format + MITI 4.2.1 pack

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP01 (`engines/core/`, `engines/` layout; SP01's live STT/LLM gate has passed) · Blocks: SP03 (consumes result + pack), SP04 (engine contract for stubs), SP07 (admin tab)
Owns: `engines/paudit/**` (incl. `schemas/{pack,paudit-result}.schema.json`, `cli.py`, tests), `protocols/miti-4.2.1/**`, `docs/decisions/0018-protocol-pack-data-vs-code.md` (+ `docs/contracts/README.md` pointer only)
Not owned: rating validation (`validate_rating`), per-item comparison, tips, report assembly (SP03), and inside the pack SP03 owns `prompts/tips_*`, the content of `report.yaml`, the `evaluation:` block of `pack.yaml` and `fixtures/evaluation/**` (SP02 ships the pack format, loader, schemas and a stub `report.yaml`); HTTP endpoint/jobs (SP04); admin tab (SP07); `engines/core/*` (SP01 — needs listed below).

## TL;DR
`paudit` takes a transcript, a pack reference and params, and returns a typed, versioned result: per-utterance behaviour codes (quoted, offset-located), counts, summary scores vs reference levels, four globals with cited lines, warnings, `run_info`. Same pipeline shape as eaudit: models propose (utterance split + code + quote + rationale; globals + cited quotes), code decides (quote location, rule enforcement, counts, summaries, range/default/pack caps). Everything MITI-specific lives in `protocols/miti-4.2.1/` as data (`pack.yaml`) plus a thin `rules.py`; the engine has zero MITI strings and zero model facts (it asks core for routes `paudit_code` / `paudit_globals`). `n_runs` (default 1) → `results[]` + `aggregate`. ~6 model calls per 25-min run. `python -m paudit.cli check` runs the fixtures live and fails past set thresholds.

## Problem
- Onolys must produce its own MITI rating to compare with the clinician's. No engine does protocol-level rating; eaudit checks claims, not coded behaviour. [verified: `ls eaudit/src/eaudit` → atomize/link/check/assembler only]
- Hard-coding MITI would block "other protocols later" and violate the anti-goal (MITI specifics in engine code).
- Single-model "rate this session" answers are unverifiable (ADR 0005); every count must trace to a quoted line, every global to cited lines.

## Goals / Non-Goals
**Goals**
- Pack format v0.0.1 (loader + schema validation + parity checks); a grep test keeps the engine protocol-agnostic.
- MITI 4.2.1 pack complete: 4 globals, 10 codes, rules, formulas, reference levels, input checks, rating schema, prompts, report layout, fixtures.
- Offline logic tests (stub/fixture LLM) plus a live `paudit.cli check` so quality and latency are measured on the real model without the `eval/` harness.
- No model ids, token limits, timeouts or provider branches in the engine: swapping the LLM is a routes-file edit (SP01 R3).
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
  fixtures/            # synthetic transcripts + expected.yaml + thresholds.yaml (for `paudit.cli check`)
```
`pack.yaml` sections:

| Section | Content (MITI example) |
|---|---|
| `id`, `version`, `source` | `miti`, `4.2.1`, manual citation + URL + permission note |
| `speaker_roles` | `subject: clinician`, `other: client` (only `subject` speech is coded) |
| `items[]` | `{id, kind: global\|count, label, definition, examples?}`; globals add `scale{min,max,default}`, `evidence_min`, and optional per-item `caps[{max, when: poor_practice_cited, source: <manual page>}]`. A cap is set only on an item where the manual states it, with the page cited; the engine has no cap of its own |
| `params` | Optional defaults for engine params: `volleys_per_call`, `code_max_tokens`, `globals_max_tokens` (R2) |
| `rules[]` | declarative, engine-generic kinds: `one_code_per_utterance`, `max_per_unit{unit: volley, code: any, n:1}`, `exclusive_group{unit: volley, codes:[sr,cr], precedence:[cr,sr]}` |
| `volley` | `breaks_on: other_speaker` (+ `min_other_words` default 0) |
| `summaries[]` | `{id, label, expr, format, reference{fair, good, direction}}`; `expr` is a whitelisted arithmetic expression over item ids (`(cct+sst)/2`, `cr/(sr+cr)`, `(sr+cr)/question`, `seek_collab+affirm+emphasize_autonomy`); div-by-zero → `null` |
| `input_checks[]` | `{id, kind: duration_max\|duration_min\|param_required\|min_subject_turns\|min_other_turns, value, severity: error\|warn}`; MITI: 25 min error, 10 min warn (globals unreliable), `change_goal` error, `min_subject_turns: 5` error, `min_other_turns: 3` error |
| `compare` | per-item `kind` + thresholds from brainstorm "Difference rule" (read by SP03; SP03 may extend) |
| `evaluation` | Optional, opaque to paudit: `pack.schema.json` allows any object under this top-level key; owned and validated by SP03's `onolys_evaluation` (MITI: reasons-audit suppress list + context note, tone `banned`, tip limits). Covered by `pack_hash` (it is inside `pack.yaml`) [RESOLVED: `evaluation:` block allowed (reconcile pass)] |

MITI item ids (shared with rating schema, result, report): globals `cct, sst, partnership, empathy`; codes `gi, persuade, persuade_permission, question, sr, cr, affirm, seek_collab, emphasize_autonomy, confront`.

`rating.schema.json` (MITI v1) is the in-app **rating card** and the only rating input (no file upload, no paste-to-parse, no parser step): `{change_goal (required to start a run), coded_span{from_s,to_s}, globals{cct,sst,partnership,empathy: {score: int 1-5|null, reason: string ≤1,000 chars, example?: {at_s: int|null, text: string ≤1,000 chars}}}, counts{<10 code ids>: {count: int ≥0|null, note?: string ≤1,000 chars}}, notes: string ≤3,000 chars}`. `notes` is the free-text "Additional notes / evaluation reasoning" box: it is never parsed into the card; SP03 hands it to eaudit as additional claims. Limits are written into `rating.schema.json` (`maxLength`, incl. `example.text` ≤1,000) and hard at the API (SP04 rejects >1,000 per reason/note/example text and >3,000 notes) and soft in the UI (live counter, warn only). Every item key is optional/nullable (partial ratings valid). `coded_span` uses **`from_s`/`to_s`** (seconds, int|null): the same names as the engine param `coded_span`, SP04's session field and SP05's form (the web form converts mm:ss to seconds). [RESOLVED: `from_s`/`to_s` everywhere (reconcile pass); brainstorm's `from`/`to` superseded] [RESOLVED: nested card shape replaces the flat `globals`/`counts`/`reasons` shape (Tejit 2026-11-20 r6)]

`rules.py` hooks (all optional, pure functions, no I/O): `check_input(input, ctx) -> [Warning]`, `validate_codes(instances, ctx) -> [Adjustment]` (extra rules data cannot express; may only down-count with a reason, never add/relabel), `compute_summary(counts, globals, ctx) -> dict | None` (override of formula data). MITI `rules.py` ships one real hook: warning `reflection_before_client_speech` (a reflection in a volley with no prior other-speaker turn). Everything else is data.

Loader (`engines/paudit/pack.py`): resolves `miti@4.2.1` under `protocols/` (dir configurable) or a path; validates `pack.yaml` against `schemas/pack.schema.json`; checks parity (rating schema keys = item ids; `report.yaml` and `compare` ids exist; prompt files present; formulas parse and reference only known ids; precedence lists subset of group); computes `pack_hash` (sha256 over pack.yaml, rules.py, rating schema, prompts, report.yaml; not fixtures). Errors → typed `PackError` at load, never at run time.

**R2. Pipeline** (`paudit.run(transcript, pack, params, client) -> PauditResult`; engine-interface shape from SP01).
Params: `speaker_map{subject: <speaker id>}` (required), `change_goal`, `coded_span{from_s,to_s}`, `language` (BCP-47 or `auto`), `n_runs` (default 1), `volleys_per_call` (default 25), `code_max_tokens` (default 8000), `globals_max_tokens` (default 3000). The last three take their defaults from the engine, may be overridden in `pack.yaml › params`, and the token values are clamped to the route's `max_output_tokens`. The engine asks core for the task routes `paudit_code` (code pass) and `paudit_globals` (globals pass); model id, timeout, retries, concurrency and structured-output mode come from the route (SP01 R3; both alias `mid` = Claude Sonnet by default). The engine sets no sampling parameter and never branches on provider.
1. **Input checks** (code): pack `input_checks` + `check_input` hook → typed error or warnings. Unknown-speaker turns treated as `other` + warning.
2. **Select** (code): keep turns that overlap `coded_span` (any clinician turn partly inside the span is included whole) (no timestamps + span → warning `span_ignored`); mark subject vs other by `speaker_map`.
3. **Volleys** (code): consecutive subject turns not broken by another speaker's turn (per pack `volley`) = one volley; `v1..vN`. Other-speaker turns kept as read-only context.
4. **Code pass** (model, batched, route `paudit_code`): `volleys_per_call` volleys per call, each preceded by its previous other-speaker turn as context. Model returns per volley `utterances[{quote, code|null, rationale}]` (split + code in one call; `code` enum built from pack at runtime; `null` = uncoded). Prompt = pack `code_system.md` + definitions rendered from `pack.yaml` (never duplicated) + few-shot; cache prefixes = system+definitions, then transcript header, passed as `cache_prefixes` (always prompt content; whether they are cached is the route's `caching_mode`, not the engine's concern). **Warm first:** the first batch is sent alone; the remaining batches fan out in parallel only after it returns (core `warm_then_fanout`), because parallel calls cannot read a cache entry that is still being written. A truncated or otherwise invalid response is `LLMBadOutput`: the batch is halved and each half retried once; still bad → run fails.
5. **Validate/locate** (code): each `quote` located inside its volley's turn text via core `locate` (exact → normalized → guarded fuzzy; code-point offsets, ADR 0002); ordered, non-overlapping, never crossing a turn boundary. Unlocatable/overlapping → utterance dropped + `quote_not_found`/`overlap` warning; >20% of a batch dropped → one retry of that batch; still bad → run fails (no silent partial counts, ADR 0012).
6. **Rules** (code): apply pack `rules[]` then `validate_codes`. Violations never delete: instance stays with `counted:false` + `uncounted_reason` (`duplicate_in_volley`, `superseded_by_cr`, …) so UI/eval can show why. Winner = first in text order, or `precedence` for groups.
7. **Counts + summaries** (code): counts over `counted` instances; summaries by safe-AST evaluation of pack formulas (public `paudit.formula.evaluate(expr, values) -> float|None`, reused by SP03 for the clinician's own summaries [RESOLVED: public evaluator (reconcile pass)]); label vs reference (`below_fair|fair|good|null`).
8. **Globals pass** (model, 1 call, 4 items, route `paudit_globals`, started alongside the code-pass fan-out): whole span with turn ids, change goal; returns per global `{score, reason, evidence[{turn_id, quote}], poor_practice_cited[]}`. Code: quotes located; score outside scale → run error; `< evidence_min` valid quotes and score ≠ default → reset to default with `source:"default"` + `insufficient_evidence`; for an item that has a pack `caps[]` entry, a score above its `max` with `poor_practice_cited` non-empty → capped to `max` (`source:"capped"`, `raw_score` kept); items without a `caps[]` entry are never capped. Globals pass does not see code counts (avoids anchoring; see Decisions). A truncated response (`LLMBadOutput`) is retried once; still bad → run fails.
9. **N runs** (`n_runs`, default 1): steps 4–8 repeated N times (bounded by the route's semaphore; runs after the first start once the first run's warm call has returned), each with `run_index` in call tags; step 1–3 shared. N>1 relies on the model's natural variance; determinism is not promised. A failed run is excluded with warning; all failed → error. `aggregate` computed by code (at N=1 it equals the single run). v1 ships and tests N=1; N=3 fixtures and mean/range presentation are After launch.
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
- `run_info` = core `RunInfo` (SP01 R10): `engine:"paudit"`, `code_version`, `preset`, `routes{paudit_code, paudit_globals: {litellm_id, provider, structured_output_mode, temperature_effective, params_hash}}`, `pack{id, version, hash}`, `prompt_hashes`, `n_runs`, `usage`. `prompt_hashes` covers the pack's prompt files AND the engine-owned prompt templates (output-format instructions, definition renderer), so a template change is visible even when the pack is unchanged. Core hash helper takes a file list. No text in `run_info` or logs.
- Warning codes: `short_session`, `quote_not_found`, `overlap`, `insufficient_evidence`, `capped`, `span_ignored`, `unknown_speaker`, `language_not_validated`, `run_failed`, plus pack-defined.

**R4. Cost/latency.** 25 min ≈ 4k words ≈ 6k tokens → ~60–120 volleys → 3–5 code calls + 1 globals call per run (~6). Est. input ≈ 30–40k tokens/run, ≈ $0.10–0.30 on Claude Sonnet routes (unverified estimate; the first code call writes the cache, later batches read it; `paudit.cli check` prints tokens). Wall = warm call + slowest remaining call, i.e. about two call durations instead of one: est. 40–90 s/run (unverified; `paudit.cli check` prints p95). Target ≤90 s p95 at N=1, inside SP04's target of ≤5 min from run start to report.

**R5. Testing / eval.**
- Unit: pack loader + schema on the MITI pack, safe-expr evaluator (no names outside items, no calls), rules (duplicate GI, SR+CR in a volley → CR counted), per-item cap (capped only where the pack has a `caps[]` entry), input checks (`min_subject_turns`, `min_other_turns`), quote locating, volley builder, batch halving on `LLMBadOutput`, token params clamped to the route, aggregate, schema validation of result, parity test (rating schema ↔ pack items; `example.text` `maxLength` 1,000); grep test: no `miti|cct|reflection` strings and no model id under `engines/paudit/src`.
- Stub client (call_tag-keyed callables) for logic tests; one recorded-replay golden (`FixtureClient`) re-recorded when prompts freeze. Fixtures: 3 synthetic role-plays under `protocols/miti-4.2.1/fixtures/` (good practice; poor practice with Persuade/Confront; 8-min short) with `expected.yaml` (per-utterance intended codes, expected counts, global ranges).
- CLI: `python -m paudit.cli run --pack miti@4.2.1 --transcript f.json --params p.json` (works offline with the stub client).
- **Live check (r7; does not depend on `eval/`):** `python -m paudit.cli check --pack miti@4.2.1 --preset <name>` runs the 3 fixtures against the real model and compares with `expected.yaml`; prints per-code count MAE, globals within-1, bad-output/retry rate, p95 latency, tokens; exits non-zero when a value is past `fixtures/thresholds.yaml`. Run once per preset before that preset is offered to users, and again after a prompt or route change. No admin wiring (SP07).

## Architecture
```
Transcript(+speaker_map,span) → input_checks → select → volleys ─┬→ code pass ×batches → locate → rules → counts/summaries ┐
                                                                  └→ globals pass → locate → range/default/caps ───────────────┴→ run result (×N) → aggregate → PauditResult+run_info
pack.yaml ─ items/rules/summaries/checks → drive every box;  rules.py ─ 3 optional hooks;  prompts/ ─ protocol guidance only
```
Engine owns: pipeline, output-format instructions, response models, locate/validate, generic rule kinds, safe-expr evaluator, aggregate, schemas. Pack owns: vocabulary, definitions, rule parameters, formulas, thresholds, guidance text, labels.

**Needed from SP01 `engines/core/` (interface assumptions):** `LLMClient.complete_json` / `LLMRequest(tier=<route name>, call_tag, response_model, cache_prefixes, max_tokens)` + stub/fixture/recording clients; route registry with task routes `paudit_code`, `paudit_globals` (limits, timeouts, retries, per-route semaphore, `LLMRateLimited` backoff all inside core); `warm_then_fanout`; `LLMBadOutput` on truncated output; `Transcript/Turn{id, speaker, text, start_ms?, end_ms?}` + `Span`; `locate(text, quote, hint)` promoted from `eaudit/assembler/locate.py` (+ normalize); `RunInfo` (SP01 R10) and a file-list hash helper; `safe_log`; generic `Engine.run(transcript, pack_ref, params) -> (result, run_info)` protocol; typed errors (`InputError`, `PackError`) (all in SP01 R2: `locate.py`, `errors.py`, `hash_files`).
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
| 8 | Score caps | Per-item `caps[]` in the pack with the manual page cited, set only where the manual states it; model lists `poor_practice_cited`; code applies the cap | Engine rule capping all four globals at 4; prompt-only | "Code decides", and the engine holds no MITI rule. r7 audit (2026-11-20) |
| 9 | No evidence → default | Reset to default 3 | Trust score | MITI default-3 spirit |
| 10 | N runs | Array + aggregate; representative run for instances; `n_runs` default 1 | Average instances | Instances cannot be averaged. r7 audit (2026-11-20): N>1 untested in v1 |
| 11 | Failure | Failed batch → run fails; failed run excluded when N>1 | Partial counts | Wrong counts worse than none (ADR 0012) |
| 12 | Non-English | Best effort + info warning | Block | Params-only swap; unvalidated |
| 13 | Version | `pack_format`/result `0.0.1`, hash in run_info | Semver compat | Project rule |
| 14 | Rating input shape | In-app rating card, nested score/reason/example + count/note + notes; API-enforced char limits | File/paste parsed into a flat schema | Card is the only input (Tejit r6); no parsing risk |
| 15 | Model choice | Task routes `paudit_code` / `paudit_globals` from core; engine holds no model id, limit, timeout or sampling setting | Engine-level tier params and a run sampling param | LLM swap is a routes-file edit; the default model rejects non-default sampling values (SP01 R3). r7 audit (2026-11-20) |
| 16 | Batch size and output limits | `volleys_per_call` 25, `code_max_tokens` 8000, `globals_max_tokens` 3000, clamped to the route; truncated → halve + retry once | Fixed numbers in code; fail on truncation | Models differ in output limits; a smaller batch usually fits. r7 audit (2026-11-20) |
| 17 | Cache with parallel batches | First batch alone, then fan out | All batches at once | A cache entry being written cannot be read; costs about one extra call duration. r7 audit (2026-11-20) |
| 18 | Quality proof | Live `paudit.cli check` with thresholds file | `eval/datasets/paudit` hook | `eval/` harness is not a v1 priority; the check needs only the pack fixtures. r7 audit (2026-11-20) |
| 19 | Minimum input | `min_subject_turns: 5`, `min_other_turns: 3` as pack errors | Warn only | Too little speech gives meaningless counts and globals. r7 audit (2026-11-20) |
| 20 | Scope cuts | Toy second pack, malformed-pack test set, N=3 fixtures and mean/range presentation moved to After launch | Keep in v1 | Owner accepted the cuts; loader, schema and grep test stay. r7 audit (2026-11-20) |

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
- [DEFERRED: After launch, cut from v1 (r7 audit 2026-11-20)] Toy second protocol pack; the malformed-pack test set; the `eval/datasets/paudit` hook; N=3 fixtures and multi-run mean/range presentation (engine keeps `n_runs`, default 1).
- [DEFERRED] Optional per-provider prompt override: `prompts/<provider>/…` falling back to `prompts/…`.
- [OPEN until measured] Token defaults (`code_max_tokens` 8000, `globals_max_tokens` 3000) and the ≤90 s target are estimates; the default model's thinking shares the output budget (SP01 R3). `paudit.cli check` reports truncation/retry rate and p95; tune the pack `params` from that.
- [RESOLVED: tests need no network — stub client by call_tag + one recorded golden]

## Acceptance Criteria
- Pack loader loads `miti@4.2.1`; a pack that breaks the schema or parity raises `PackError` at load; parity test green (incl. `example.text` `maxLength` 1,000 in `rating.schema.json`).
- Stub-driven run on each fixture yields a schema-valid `PauditResult` with counts/summaries equal to `expected.yaml`; replaying the golden twice gives the same result.
- Rule tests: 2 GI in a volley → 1 counted; SR+CR → CR counted; a global with a pack `caps[]` entry scored above its `max` with poor practice cited → capped; a global without a `caps[]` entry is not capped; every MITI `caps[]` entry cites a manual page; no evidence → 3; summaries match formulas incl. div-by-zero → null.
- Input: >25 min, missing change goal, fewer than 5 subject turns or fewer than 3 other-speaker turns → typed error; <10 min → `short_session` warning.
- Routes: prompt capture shows the code pass requests route `paudit_code` and the globals pass `paudit_globals`; the engine sends no sampling parameter; token params above the route's `max_output_tokens` are clamped; no model id in `engines/paudit/src` (grep).
- Batching: `volleys_per_call` is honoured; a batch answering with `LLMBadOutput` is halved and retried once, then the run fails; with a stub client the second batch does not start before the first has returned.
- `n_runs=1` → 1 result + `aggregate` equal to it and `representative_run = 0`.
- `run_info` carries `code_version`, `preset`, both routes, pack id/version/hash, and `prompt_hashes` that change when either a pack prompt or an engine-owned template changes; no transcript text in logs.
- No MITI-specific strings in `engines/paudit/src` (grep test).
- `python -m paudit.cli run …` works offline with stub.
- Live: `python -m paudit.cli check --pack miti@4.2.1 --preset default` runs the 3 fixtures on the real model, prints per-code count MAE, globals within-1, bad-output/retry rate, p95 latency and tokens, and exits non-zero when a value is past `fixtures/thresholds.yaml` (test: a doctored thresholds file makes it fail).
