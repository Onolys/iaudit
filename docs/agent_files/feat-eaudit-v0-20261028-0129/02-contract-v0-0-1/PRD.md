---
status: approved
summary: Reset every schema to 0.0.1 with no back-compat; 17 concern types plus required concern group (derived from type); optional turn speaker; error body redesigned to {status, message, details[{code,message}]} with a fixed detail-code table.
date: 2026-10-28
---
# PRD: SP02 Contract v0.0.1

Repo/branch: iaudit / `feat/eaudit-v0` · Depends on: SP01 (rename `backend/`→`eaudit/`, package `eaudit`, `codepoints.ts`→`frontend/src/utils/`) · Blocks: SP03 (needs the 4 new enum values + `group`), SP04 (docs prose)
Owns: `docs/contracts/{audit-request,audit-response,error-response}.schema.json`, `docs/contracts/README.md` (normative tables only), `docs/contracts/examples/*`, `eval/schemas/*.schema.json`, `docs/decisions/0016-*.md` (+ edits to 0011/0014/0015), `docs/examples/{mock,real}/*`, `eaudit/src/eaudit/{app.py,api/errors.py,contract.py,models/audit.py,models/concern_groups.py (new),assembler/*,prep/{models,rules,pairing}.py,check/group_a.py}` + tests/fixtures, `frontend/src/{contract/*,transport/{errorBody,errors,client,ErrorScreen}.*,claim-detail/{concernLabels,ConcernList,ChunkView}.*,eval/{evalTypes.ts,fixtures/*}}` + tests.
Not owned: detection of the 4 new types, prompt/verifier/template/dedup work (SP03); explanatory docs prose and diagrams (SP04).

## TL;DR
One coordinated contract change, no migration. (1) All schemas (`docs/contracts/*` and `eval/schemas/*`) go to `schema_version` `"0.0.1"`; all legacy/back-compat code and version-history text is deleted. (2) Concern `type` enum grows 13→17. (3) New required `concerns[].group` (4 values) derived from type by one mapping; schema enforces consistency. (4) `transcript[].speaker` optional; missing = unknown, speaker-dependent checks skipped, `ambiguous_speaker` warning. (5) Error body becomes `{schema_version, request_id?, status, message, details[]}` with custom detail codes. SP03 can then build detection against a frozen contract.

## Problem
- Contract carries 1.0.0/1.1.0/1.2.0 history, version-bump prose, and rejection paths (`unsupported_version`) for a project that is not deployed. Pure drag. [verified: README "Version history", `app.py` `SUPPORTED_VERSION`, `errors.py` `SCHEMA_VERSION`, `models/audit.py:79,137`, `assembler/__init__.py:92`, frontend `validate.ts:46`]
- Taxonomy is moving to 17 types; the flat list is too long for a reviewer. A 4-way group gives the UI a stable summary axis that survives future type additions.
- Real transcripts often lack speaker labels; `speaker` is required today, so such input is rejected rather than audited. [verified: request schema `Turn.required`]
- Error body has a broad `error.code` enum (`invalid_request`, `unsupported_version`, `other`...) that duplicates HTTP status and is too coarse to say what failed. [verified: `error-response.schema.json`, `api/errors.py`]

**Contract-versioning rule (whole initiative): all schemas are `"0.0.1"`; the project is not deployed; no legacy/back-compat code, version history or migration; a non-conforming file just shows a validation error and the owner deletes it.**

## Goals / Non-Goals
**Goals**
- Versioning rule (below) applied everywhere in one change; grep for `1\.[012]\.0` returns zero hits outside git history and `docs/agent_files/`.
- Contract, backend models, frontend types/validator agree on 17 types, `group`, optional speaker, new error body.
- Every example/fixture regenerated so all validators pass at 0.0.1.
- Contract README normative tables match the schemas (concern types, group, speaker, error body, detail codes).

**Non-Goals**
- Detecting the new 4 types or changing prompts/templates/verifier/dedup (SP03). SP02 only adds them to enum, types, labels, group map.
- Narrative docs, diagrams, concepts pages (SP04). SP02 touches `docs/contracts/README.md` normative tables and the minimum wording that would otherwise be false.
- Any back-compat, migration tool, or dual-version acceptance.
- New roles, inferring a speaker, guessing roles (ADR 0011 holds).

## Requirements
**R1. Versioning rule (stated verbatim in ADR 0016 and README).** All schemas reset to `schema_version` `"0.0.1"`: the three contract schemas and `eval/schemas/{metrics,item_rows,compare}.schema.json`. The project is not deployed; there is no legacy. Delete: back-compat code, version history text, rejection paths for 1.0.0/1.1.0 (`unsupported_version` code, `wrong_version` kind in frontend `validate.ts`/`errors.ts`/`ErrorScreen`), ADR wording about version bumps where misleading. A file or body that does not match the current schema shows a validation error; the user deletes it. No migration. Version is a literal in one place per component (schema `const`; backend constant read from schema or one module constant; frontend one constant) and may later be bumped normally.

**R2. Concern types (17).** Enum order and the group map below must match SP03 Requirements 2 (group map) and 5 (check numbering 14-17) exactly; SP03 is the single source. Order = existing 13 then `opinion_as_fact`, `calculation_error`, `meaning_shift`, `unsupported_inference`. Updated in: response schema enum, backend `ConcernType`, frontend `CONCERN_TYPES`. The README "Concern types" table loses the "Mission check N" numbering assumption for new rows (mission.md is SP03); add a Group column.

**R3. Group.** `concerns[].group` required. Map copied from SP03 Requirement 2 (single source). Enum values and UI labels:

| `group` value | UI label | Types |
|---|---|---|
| `not_in_interview` | Not in interview | unsupported_claim, unsupported_causal_link, question_as_answer, unsupported_inference |
| `opposite_of_interview` | Opposite of interview | contradictory_evidence, negation_reversal |
| `changed_detail` | Changed detail | wrong_attribution, timeframe_mismatch, quantity_mismatch, frequency_severity_inflation, certainty_inflation, opinion_as_fact, calculation_error, meaning_shift |
| `missing_context` | Missing context | context_stripping, correction_ignored, conflicting_accounts_flattened |

Enforced three ways: backend emits from the map; response schema `Concern.allOf` has 4 `if type in [...] then group const` clauses; frontend validator (Ajv, same schema) rejects mismatch. Unit test per language asserts the map equals the schema (parity test reads the schema; a single drift test is the guard, no cross-language codegen).

**R4. Optional speaker.** `Turn.required` = `[id, text]`; `speaker` optional (minLength 1 when present). Missing = unknown. Never invent, never default to "" or "unknown" in data.
- Backend: `models.Turn.speaker: str | None`; `prep.models.IndexedTurn.speaker: str | None`.
- `prep/pairing.py` and `prep/rules.py:114,140`: a turn with `speaker is None` never equals any speaker (`None != x` and `None != None` both treated as "different/unknown"), so it cannot terminate a questioner's run by identity and is not paired as respondent by speaker comparison. Rule: a question turn with unknown speaker gets no pair; unknown-speaker turns are not added to `resp` lists; they do not break a questioner's run. Same guard in `link/validate.py:65`, `link/shortlist.py` speaker floor/self-correction (skip None).
- `check/group_a.py`: attribution check (`t.speaker == e.speaker`), question-as-answer, and conflicting-accounts (speaker-set based) skipped for unknown-speaker turns; counted like `role_skipped`; turns reported via `ambiguous` so the assembler warns.
- Warning: existing `ambiguous_speaker` fires when a claim cites a turn lacking `speaker` OR `role` (role-missing behaviour unchanged, ADR 0011); message text becomes "Speaker or role was missing for turn(s) {turns}; none was assumed."
- Verifier prompt rendering (`check/verifier.py:64`) prints `speaker="unknown"` for None (prompt text only, not data).
- Frontend: `Turn.speaker?: string`; `ChunkView` shows "Unknown speaker" label when absent.

**R5. Error body.** Non-2xx body, every status:
```json
{
  "schema_version": "0.0.1",
  "request_id": "example-001",
  "status": 400,
  "message": "The request does not match the audit contract.",
  "details": [
    { "code": "schema_violation", "message": "transcript: must contain at least 1 item" }
  ]
}
```
Required: `schema_version`, `status` (integer 400-599, equals HTTP status), `message` (non-empty plain text), `details` (array, min 1). `request_id` optional. No top-level code; old `error` object and enum removed. Detail `message` carries schema paths and fixed text only, never values (existing policy in `errors.py`). Several details allowed (e.g. up to 5 schema issues).

Detail codes (schema enum; table is normative, copied into contract README; SP04 writes prose around it):

| Code | HTTP | Raised by | Meaning | UI message (frontend, from `message`; fallback text if body invalid) | Reviewer action |
|---|---|---|---|---|---|
| `invalid_json` | 400 | app.py step 2 | Body is not JSON or not a JSON object | Request rejected: the file is not valid JSON. | Fix the JSON file. |
| `unsupported_media_type` | 415 | step 0 | Content-Type is not application/json | Request rejected: wrong content type. | Send JSON. |
| `schema_violation` | 400 | step 5 | Body fails request schema (incl. wrong `schema_version`, missing field, bad enum) | Request rejected + each detail line (path: reason) | Fix the listed fields or delete the file. |
| `empty_transcript` | 400 | step 5 | `transcript` is `[]` | Request rejected: the transcript has no turns. | Add turns. |
| `empty_assessment` | 400 | step 5 | `assessment` is `[]` | Request rejected: the assessment has no sections. | Add sections. |
| `duplicate_ids` | 400 | step 6 | Duplicate turn or section ids (counts only) | Request rejected: duplicate ids. | Make ids unique. |
| `invalid_parameters` | 422 | validation handler | Non-body parameter error (paths only) | Request rejected: invalid parameters. | Retry with a standard client. |
| `body_too_large` | 413 | steps 1 | Body over `max_body_bytes` | Request too large. | Split or shorten the input. |
| `too_many_turns` | 413 | step 4 | Over `max_turns` | Transcript has too many turns. | Shorten transcript. |
| `too_many_sections` | 413 | step 4 | Over `max_sections` | Assessment has too many sections. | Shorten assessment. |
| `rate_limited` | 429 | reserved, not raised today (kept in enum) | Too many requests | Too many requests. | Wait and retry. |
| `not_found` | 404 | http handler | Unknown path | Service endpoint not found. | Check the configured URL. |
| `method_not_allowed` | 405 | http handler | Wrong HTTP method | Method not allowed. | Use POST /v1/audit. |
| `cors_rejected` | 400/403 (as the preflight status) | CORS middleware | Preflight origin/method/header refused | Cross-origin request blocked. | Add origin to backend CORS settings. |
| `request_rejected` | other 4xx | http handler fallback | Any other framework HTTP error | Request could not be served. | Retry; report if repeated. |
| `upstream_unavailable` | 503 | `LLMUnavailable` | Model provider unreachable or failing after retries | Audit service temporarily unavailable. | Retry later (retryable). |
| `deadline_exceeded` | 504 | `DeadlineExceeded`/`TimeoutError` | Audit deadline passed with no usable result | The audit ran out of time. | Retry or use a shorter input (retryable). |
| `internal_error` | 500 | catch-all; response self-validation failure | Backend bug | Internal server error. | Report; retry once (retryable). |

`unsupported_version`, `other`, `unavailable`, `payload_too_large`, `invalid_request` are deleted. Wrong `schema_version` is just a `schema_violation` on `/schema_version`.
Top-level `message` per code is fixed backend text (one string per status class); UI shows `message`, then each `details[].message` as a list.

**R6. Backend errors.** `ApiError(status, message, details, request_id)`; `error_body(status, message, details, request_id)`; delete `SUPPORTED_VERSION` check at step 3 of `app.py` (schema `const` covers it). Step 5 chooses `empty_transcript`/`empty_assessment` when those arrays are `[]`, else `schema_violation` per issue (cap 5, existing `_MAX_ISSUES`). Outcome log field uses first detail code instead of `exc.code`. `ContractCORSMiddleware` preflight reject uses `cors_rejected`.

**R7. Frontend errors.** `readErrorMessage` → `readErrorBody(text): {status, message, details} | undefined`, only when the body validates; `LoadError.http_4xx/http_5xx` carry `message` + `details`; `ErrorScreen` shows title from status (existing), `message`, then details list; invalid/non-JSON body → generic text for the HTTP status (consumer rule kept). `isRetryable` unchanged (status-based only; detail codes are display/diagnostics, never drive retry). Automatic audit-POST retry is limited to 429 (SP01). Delete `wrong_version` LoadError reason and its screen text; wrong version surfaces as `schema`.

**R8. Frontend UI.** `ConcernType` 17, `ConcernGroup` type, `CONCERN_GROUP: Record<ConcernType, ConcernGroup>` and `CONCERN_GROUP_LABELS` in new `frontend/src/contract/concernGroups.ts`; `CONCERN_LABELS` gains: "Opinion stated as fact", "Calculation error", "Meaning shift", "Unsupported inference". `ConcernList` groups a claim's concerns under group headings (fixed order: Not in interview, Opposite of interview, Changed detail, Missing context; empty groups omitted); inside a group, concern order kept. Validator: after Ajv, no extra group check needed (schema enforces); `concerns` tests updated. Tokens: concern types have no color tokens today (`tokens/index.ts` is verdict/evidence-role only), so no token change; a group is a heading only. [verified: grep]

**R9. Examples/fixtures regenerated.** Script once (kept out of repo or in `scripts/` only if SP01 has a home): set `schema_version` `"0.0.1"`, add `group` to every concern from the map, convert error example. Covers: `docs/contracts/examples/*` (add one `no-speaker.request/response` pair and a multi-error example), `docs/examples/mock/*/{request,response}.json`, `docs/examples/real/*/request.json`, `docs/examples/curl.md`, `eaudit/eval/data/adhd/requests/*.json`, `frontend/src/{fixtures,transport/mock}` and `frontend/src/eval/fixtures/*.json` + `evalTypes.ts`, eval tests that hardcode `1.0.0`. Recorded LLM replay fixtures (`eaudit/tests/fixtures/llm/*`, ADR 0013) hold model outputs, not response bodies: grep found no `schema_version` in them, so they should be unchanged. [verified: grep for schema_version limited to requests/tests; confirm in task by running replay tests]. `eaudit/eval/data/adhd` gold files: if they list concerns, add no `group` (gold is by type).

**R10. Eval schemas.** `metrics`, `item_rows`, `compare` `const` → `"0.0.1"`, and the eval dataset-metadata schema/model includes the new `product` field (`"eaudit"`; added by SP01, coordinated: SP02 owns the version reset, SP01 owns the field); `eval/src/iaudit_eval/metrics/report.py` literal; stored run files on disk with `1.0.0` simply fail validation (no migration). Eval bucket list derives from the enum (`gold.py`); the 4 new buckets appear automatically and are empty until SP03. Confirm the ADHD oracle report test (`eval/tests/test_oracle.py`) still lists only its gold buckets.

**R11. Docs touched (normative only).** `docs/contracts/README.md`: delete Versioning section and "Version history"; replace with "Version: `0.0.1`; no compatibility promise"; update Request table (speaker optional), add Concern table (type, group, label), Concern types table (17, group column), Warnings (`ambiguous_speaker` wording), Rules (consumer: invalid body → error), Error response section + detail-code table (R5). `docs/reference/{backend-api,warnings}.md`: only lines that would be false (error codes, speaker). Everything else → SP04.

**R12. ADRs.** New `0016-contract-reset-0-0-1-groups-optional-speaker-error-details.md` (versioning rule, group, optional speaker, error redesign, detail codes). Edit 0011 (add "same for speaker"), 0014 (drop "A 1.0.0 client gets a version error", "Each later bump repeats…"; keep run_info decision), 0015 (drop version-bump wording, keep taxonomy decision). Mark 0014/0015 as amended by 0016 in a one-line note.

## Architecture
Single source of truth: schemas in `docs/contracts/` (backend reads in place; frontend imports via `@contracts`). Type→group map exists once per language:
- Python: `eaudit/src/eaudit/models/concern_groups.py` (`GROUP_OF: dict[ConcernType, ConcernGroup]`); assembler sets `group` when building each concern; no other code writes it.
- TS: `frontend/src/contract/concernGroups.ts` (`CONCERN_GROUP`).
- Schema: 4 `allOf` if/then clauses.
- Drift tests: Python and TS each load the response schema and compare enum + clause membership to their map.

Concern object (response):
```json
{ "type": "quantity_mismatch", "group": "changed_detail",
  "explanation": "...", "evidence_ids": ["e1"] }
```
Error flow: raise `ApiError(status, message, details)` anywhere → one handler → `error_body` → validated against error schema in tests. Unknown-speaker flow: request validates → prep marks None → pairing/Group A skip → `ambiguous` list → assembler warning → UI "Unknown speaker".

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Version | `0.0.1` everywhere, no compat | Keep 1.x bump to 2.0.0; accept both | Not deployed; zero migration cost |
| 2 | Group values | snake_case `not_in_interview`, `opposite_of_interview`, `changed_detail`, `missing_context`; labels in UI only | Label strings in the data | Stable keys, label wording editable without a contract change |
| 3 | Group authority | Backend emits, schema enforces via allOf, frontend validates via same schema | Frontend derives only; backend-only | Needed in response for consumers other than our UI; cheap to enforce |
| 4 | Map location | One module per language + drift test | Generated from schema; shared JSON read by both | No codegen toolchain; test is enough |
| 5 | Speaker absent | Property omitted = unknown; `""` invalid (minLength 1) | Allow `null`; default "unknown" | Never invent; one representation |
| 6 | Ambiguity warning | Reuse `ambiguous_speaker` for missing speaker or role | New code | Same meaning; avoids warning-enum change |
| 7 | Error `status` field | Required, equals HTTP status | Omit; derive from HTTP | Body usable when logged/saved without headers |
| 8 | Error detail codes | Flat custom code per cause, 18 values | Top-level category + sub-codes; free text | Matches what backend raises; UI/reviewer action table 1:1 |
| 9 | Wrong schema_version | `schema_violation` | Dedicated `unsupported_version` | No version story to tell; deleted per rule |
| 10 | Group in UI | Heading grouping inside claim detail | Group chips/filter in the left pane | Smallest change; reviewer reads concerns together |
| 11 | ADR | One new ADR 0016 + small edits | Three new ADRs | One coordinated reset |

## Manual steps
- User deletes any saved request/response/eval run files at old versions (they will show validation errors).
- Mission wording for the 4 new types is SP03; nothing here.
- Owner re-run of live evals is not part of SP02 (TofuEval runs are [DEFERRED] to the owner outside this initiative).

## Risks / Open Questions
- [RESOLVED: group values snake_case, labels per R3] naming.
- [RESOLVED: recorded LLM replay fixtures hold model I/O, not response bodies; verify by running replay tests] fixture scope.
- [RESOLVED: eval schemas also reset] per initiative rule.
- [RESOLVED: `details` minItems 1; every error body always carries at least one detail (bare framework 404 gets `not_found`)] details.
- [RESOLVED: keep `rate_limited` as a reserved code] rate_limited.
- [RESOLVED: frontend retry decisions on HTTP status only (429 for audit POST, per SP01); detail codes are display/diagnostics] retry basis.
- [RESOLVED: single `ambiguous_speaker` warning covers missing role and missing speaker] warnings.
- [RESOLVED: unknown-speaker turns are skipped in Q/A pairing] pairing.
- [RESOLVED: missing speaker rendered as "unknown" in prompts (prompt text only)] prompt rendering.
- [DEFERRED] Prose docs, diagrams, mission.md (SP04/SP03). New-type detection (SP03).
- Risk: request schema `Turn` loosening makes `speaker`-roster logic in `atomize/validate.py:83` receive None; guard with `if s.speaker`.

## Acceptance Criteria
1. `grep -rE '"?(1\.0\.0|1\.1\.0|1\.2\.0)"?'` over code, schemas, fixtures, docs (excluding `docs/agent_files/`) returns nothing; `unsupported_version`, `wrong_version`, "Version history" gone.
2. All six schemas have `schema_version` const `0.0.1`; backend, frontend, eval tests green; request/response/error examples validate with both Python (`jsonschema`) and Ajv.
3. Response schema rejects: a concern missing `group`; a concern whose group disagrees with its type (one negative test per group); a type outside the 17.
4. Eval dataset metadata schema carries `product` at `0.0.1`. Request without any `speaker` validates; audit returns 200, with `ambiguous_speaker` on claims citing those turns; Q/A pairing and attribution/question-as-answer/conflicting-accounts do not use missing speakers (unit tests in `prep`, `check/group_a`); UI renders "Unknown speaker".
5. Every non-2xx path in `app.py`/`errors.py` emits a body valid against the new error schema, `status` equals HTTP status, with the detail code from the table (test per code; `rate_limited` schema-only).
6. Frontend: valid error body shows message + details; HTML/empty/old-shape body shows generic status text; `ConcernList` groups under the four labels in fixed order; drift tests pass in Python and TS.
7. Contract README tables (concern types+group, speaker, error body, detail codes) match the schemas; ADR 0016 present, 0011/0014/0015 edited.
8. Replay-mode CI (ADR 0013) passes without regenerating LLM fixtures.
