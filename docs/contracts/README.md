# Audit contract 0.0.1

Source of truth for the evidence-audit request and response. The frontend owns this contract. The backend implements it.

This is the JSON **body** of one synchronous call. HTTP path, method, and auth are out of scope. The backend's HTTP path, status codes and CORS are in [../reference/backend-api.md](../reference/backend-api.md). There is no streaming and no background job: one request, one response.

| File | What it is |
|---|---|
| [audit-request.schema.json](audit-request.schema.json) | Input. Machine-checked structure. |
| [audit-response.schema.json](audit-response.schema.json) | Output. Machine-checked structure. |
| [error-response.schema.json](error-response.schema.json) | Body of any non-2xx reply. See [Error response](#error-response). |
| [examples/request.json](examples/request.json), [examples/response.json](examples/response.json) | One fictional worked example (pair `default`). |
| [examples/partial.request.json](examples/partial.request.json), [examples/partial.response.json](examples/partial.response.json) | Fictional `partial` audit: one section not processed, plus a second warning. |
| [examples/out-of-range.request.json](examples/out-of-range.request.json), [examples/out-of-range.response.json](examples/out-of-range.response.json) | Fictional audit where exactly one claim span runs past the section text. It intentionally breaks rule 1 so consumers can be tested against it; no other example does. |
| [examples/no-speaker.request.json](examples/no-speaker.request.json), [examples/no-speaker.response.json](examples/no-speaker.response.json) | Fictional audit with omitted speaker identities and an ambiguity warning. |
| [examples/error.json](examples/error.json), [examples/multi-error.json](examples/multi-error.json) | Single-detail and multiple-detail error bodies. |
| This file | Conventions, field meanings, allowed values, and rules a schema cannot express. |

If this file and a schema disagree about **structure**, the schema wins. If they disagree about a **rule the schema cannot express**, this file wins. Change them in the same commit.

The verdict list and the concern-type list mirror [../mission.md](../mission.md). When the mission changes, update both schemas and this file.

Version: `0.0.1`; no compatibility promise.

**Contract-versioning rule (whole initiative): all schemas are `"0.0.1"`; the project is not deployed; no legacy/back-compat code, version history or migration; a non-conforming file just shows a validation error and the owner deletes it.**

A consumer must not render a partial audit from an invalid body.

## Conventions

- Indexes and character offsets start at 0.
- `end` is **exclusive**, like Python slicing and `Array.prototype.slice`.
- Character offsets count **Unicode code points**, not bytes and not UTF-16 units. Python `str` already counts this way. In JavaScript, slice with `Array.from(text)`, not `text.slice`, so an emoji cannot shift later highlights.

```javascript
Array.from(text).slice(start, end).join("")
```

`"hi👍"` is three code points (`h`, `i`, `👍`) and four UTF-16 units. The thumbs-up is offset 2, and the exclusive end after it is 3.

- A claim stays inside one assessment section, so `span.start.index` equals `span.end.index`.
- An evidence excerpt may cross turns, for example a question followed by "yes". Turns strictly between `start.index` and `end.index` are included in full.
- Do not end a cross-turn span at `{index: N, char: 0}`. That turn would contribute nothing. End on the last included turn, at its length or at a mid-turn offset.
- Speakers are free text (`clinician1`, `patient1`, `caretaker1`, or any custom name). Each distinct string is a separate speaker. There is no cap.
- `label` and `score` name a section for display. The backend must not audit them.
- Turn `id` and section `id` are for logs only. Nothing in the response points at them. Positions use the array index.
- The response contains no quote text and no timestamp. Both sides hold the same input, so a position is enough.

## How to read a span

Compare pointers in order: smaller `index` first, then smaller `char`. `start` must be strictly before `end`.

For evidence, walk the transcript:

1. On the start turn, take code points `[start.char, end of turn)`.
2. Take every turn strictly between the two indexes, in full.
3. On the end turn, take code points `[0, end.char)`. If both pointers share an index, take `[start.char, end.char)` of that turn only.

A claim uses the same walk inside one section, so only step 3 applies, against `assessment[index].text`.

`char` may equal the item's code-point length only on an **end** pointer (the exclusive end of the item). A start pointer must be inside the item.

## Request

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Always `"0.0.1"`. |
| `request_id` | no | Caller-chosen id. Echoed on the response. Not a content hash. |
| `transcript` | yes | Non-empty array of turns, in order. |
| `transcript[].id` | yes | Log id. Not an evidence anchor. |
| `transcript[].speaker` | no | Non-empty free-text speaker name when supplied. Omitted means unknown; never infer it or insert an empty string, `null`, or a placeholder. |
| `transcript[].role` | no | `interviewer`, `respondent`, `informant`, or `other`. Fixed list so checks 3 and 9 can rely on it. Omit rather than guess. |
| `transcript[].text` | yes | Turn text. May be empty. |
| `transcript[].timestamp` | no | Display exactly as supplied. Never inferred. |
| `assessment` | yes | Non-empty array of reasoning sections. One section is fine. |
| `assessment[].id` | yes | Log id. Not a claim anchor. |
| `assessment[].label` | no | Domain or sub-domain name. Display only. |
| `assessment[].score` | no | Number or string. Display only. Never audited. |
| `assessment[].text` | yes | The clinician's reasoning for this section. |

Ids must be unique among turns, and unique among sections.

A turn without `speaker` stays unknown. Speaker-dependent checks and question/answer pairing skip it. A claim citing a turn without `speaker` or `role` receives `ambiguous_speaker`; neither identity nor role is assumed. The UI displays "Unknown speaker" for an omitted speaker.

## Response

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Always `"0.0.1"`. |
| `request_id` | when sent | Exact echo of the request id. |
| `status` | yes | `complete` or `partial`. |
| `warnings` | yes | May be empty. |
| `claims` | yes | May be empty only when the reasoning has no classifiable span. |
| `run_info` | no | Provenance of the run (see below). Omitted by producers that did not run the full pipeline. |

### run_info

Optional. Ids, hashes and counts only; no other keys are allowed (no transcript text).

| Field | Required | Meaning |
|---|---|---|
| `models.cheap`, `models.mid`, `models.strong` | yes | Model id used for each tier. |
| `prompt_hashes.atomize`, `.link`, `.check`, `.prep` | yes | 16 lowercase hex chars (sha256 prefix of the prompt file bytes). |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` | no | Integers, 0 or more. |
| `cost_usd` | no | Number, 0 or more. |

Example: [examples/response.json](examples/response.json). [examples/partial.response.json](examples/partial.response.json) omits it.

### Claim

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique in the response. |
| `span` | yes | Where the claim sits in `assessment`. Index is the section. |
| `verdict` | yes | One of the five values below. |
| `explanation` | yes | Why. Not a quote. |
| `out_of_scope_reason` | when `out_of_scope` | Why it cannot be checked. Omit on every other verdict. |
| `suggested_revision` | no | A proposed rewording, or `null`. A proposal only. Never applied. |
| `concerns` | yes | May be empty. |
| `evidence` | yes | May be empty. |

The backend splits the reasoning into claims. The frontend only renders them.

Include an `out_of_scope` claim for a statement the audit will not check, such as a diagnostic conclusion, so the left pane has no unexplained gap. Spacing between claims need not be covered.

### Verdicts

These are the mission's results, plus outside-of-scope. The left pane distinguishes claims by verdict.

| Value | Mission meaning | How to read it |
|---|---|---|
| `supported` | The interview substantiates the claim without a material change in meaning. | Verified. |
| `partially_supported` | Some of the claim is supported; some is exaggerated, altered, or unsubstantiated. | Problem. |
| `contradicted` | Explicit supplied evidence conflicts with the claim. | Problem. |
| `insufficient_evidence` | The material does not establish the claim, or is too ambiguous. | Not verified. **Not** the same as wrong. |
| `out_of_scope` | External criteria or unavailable observations. Not a factual verdict. | Not checkable. |

### Concern

| Field | Required | Meaning |
|---|---|---|
| `type` | yes | One of the 17 concern types below. |
| `group` | yes | The group assigned to `type` in the table below. A different group is invalid. |
| `explanation` | yes | Non-empty explanation of the potential discrepancy. Not a quote. |
| `evidence_ids` | yes | Array of evidence ids on this claim. May be empty. |

Group labels are display text, not fields in the concern object. The backend emits `group` from the type-to-group map; the response schema enforces the mapping and the frontend validates against that schema.

| `group` value | UI label |
|---|---|
| `not_in_interview` | Not in interview |
| `opposite_of_interview` | Opposite of interview |
| `changed_detail` | Changed detail |
| `missing_context` | Missing context |

The UI groups a claim's concerns in the order above, omits empty groups, and preserves concern order within each group.

### Concern types

A claim may have several. Explain the discrepancy once; do not repeat the same finding. Rows follow contract enum order.

| Value | Label | Group |
|---|---|---|
| `unsupported_claim` | Claim support | `not_in_interview` |
| `contradictory_evidence` | Contradictory evidence | `opposite_of_interview` |
| `wrong_attribution` | Wrong person, source, or entity attribution | `changed_detail` |
| `timeframe_mismatch` | Timeframe mismatch | `changed_detail` |
| `negation_reversal` | Negation reversal | `opposite_of_interview` |
| `certainty_inflation` | Certainty inflation | `changed_detail` |
| `frequency_severity_inflation` | Frequency or severity inflation | `changed_detail` |
| `context_stripping` | Context stripping | `missing_context` |
| `question_as_answer` | Question mistaken for an answer | `not_in_interview` |
| `correction_ignored` | Correction ignored | `missing_context` |
| `conflicting_accounts_flattened` | Conflicting accounts flattened | `missing_context` |
| `unsupported_causal_link` | Unsupported causal links | `not_in_interview` |
| `quantity_mismatch` | Quantity mismatch | `changed_detail` |
| `opinion_as_fact` | Opinion stated as fact | `changed_detail` |
| `calculation_error` | Calculation error | `changed_detail` |
| `meaning_shift` | Meaning shift | `changed_detail` |
| `unsupported_inference` | Unsupported inference | `not_in_interview` |

Omitting a type means the audit did not find that concern. It is not a way to say the check was skipped. This version has no coverage field.

### Evidence

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique within the claim. `concerns[].evidence_ids` point here. |
| `role` | yes | `supporting`, `contradicting`, or `qualifying`. The right pane distinguishes excerpts by this. |
| `span` | yes | Position in `transcript`. Index is the turn. |
| `note` | no | Short paraphrase. Not a quote. |

### Warnings

| Code | When | Also required |
|---|---|---|
| `section_not_processed` | That assessment section was skipped. | `section_index` |
| `span_out_of_range` | A returned span does not fit the input. | `claim_id` |
| `ambiguous_speaker` | A claim cites a turn without `speaker` or `role`; neither was assumed. Message: "Speaker or role was missing for turn(s) {turns}; none was assumed." | — |
| `input_truncated` | The input could not be processed in full, beyond one section. | — |
| `other` | Anything else, explained in `message`. | — |

## Rules the schema cannot express

1. Every span lies inside the input. `start` is strictly before `end`. A claim has `start.index == end.index`. A cross-turn evidence span does not use `char: 0` on the end turn.
2. A `supported` claim has at least one `supporting` excerpt and no `contradicting` excerpt.
3. A `contradicted` claim has at least one `contradicting` excerpt.
4. A `partially_supported` claim has at least one concern.
5. An `insufficient_evidence` claim may have no evidence. It must not include a `contradicting` excerpt; that verdict would be `contradicted`.
6. An `out_of_scope` claim has `out_of_scope_reason` and no concerns.
7. `concerns[].evidence_ids` refer only to evidence on the same claim. Evidence ids are unique within the claim. Claim ids are unique in the response.
8. Claim spans do not overlap, and one claim does not nest inside another.
9. The response contains no transcript text and no timestamp. `explanation`, `note`, and `suggested_revision` are written, not copied.
10. If the request has `request_id`, the response echoes it unchanged. There is no content hash in this version. The consumer still rejects a span that falls outside the input it holds.
11. `status: "partial"` requires at least one `section_not_processed` warning.
12. Wording stays a potential concern for a person to review. "Not substantiated by the supplied interview" is not an allegation of fabrication or misconduct. `suggested_revision` is never applied by either side.

Rules 2–6 and 11 are also enforced by the response schema.

## Consumer rules

- If the body fails the current schema, show a validation error. Do not render a partial audit from an invalid body.
- If one span is out of range, still render that claim, with a warning badge. Do not shift the other highlights.
- Colour and layout are not part of this contract. Verdict drives the left pane. Evidence `role` drives the right pane.
- The right pane can expand past an excerpt. Expansion uses the same transcript array; it is not a new field.
- Do not treat `label` or `score` as an audit result.

## Error response

Every non-2xx reply carries this body instead of an audit. Examples: [examples/error.json](examples/error.json), [examples/multi-error.json](examples/multi-error.json). Request, response and error bodies share `schema_version: "0.0.1"`.

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Always `"0.0.1"`. |
| `request_id` | no | Echo of the request id, when known. |
| `status` | yes | Integer from 400 through 599; equals the HTTP response status. |
| `message` | yes | Non-empty plain text shown to the reviewer as-is. Fixed backend text for the error class. |
| `details` | yes | Array containing at least one detail. Several details may describe the failure; request schema validation reports at most five issues. |
| `details[].code` | yes | One of the 18 detail codes below. |
| `details[].message` | yes | Non-empty plain text containing schema paths and fixed text only, never input values. |

The body has no top-level code or nested `error` object. A wrong `schema_version` is a `schema_violation` at the schema-version path, just like any other invalid field.

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

Consumer rule: if the body validates against the error schema and its `status` equals the HTTP response status, show `message`, followed by each `details[].message` as a list. Otherwise (including empty, HTML, or other JSON), use generic text for the HTTP status. Never render an audit from an error body. Retry decisions use HTTP status only; detail codes are for display and diagnostics. Automatic audit POST retry is limited to 429.

## Non-goals

- No diagnosis, no score audit, no protocol or consent review.
- No check that the interview is true in the world. Fidelity is to the supplied interview only.
- No audio, files, or speech-to-text. The caller sends turns and sections already.
- No write-back to the assessment.
- No quote text, no timestamps, and no content hash in the response.
- No streaming and no job id.

## Worked example

[examples/request.json](examples/request.json) is fictional. [examples/response.json](examples/response.json) is the matching audit. Apply each span to the request; the response deliberately does not repeat the words.
