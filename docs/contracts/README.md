# Audit contract 1.0.0

Source of truth for the evidence-audit request and response. The frontend owns this contract. The backend implements it.

This is the JSON **body** of one synchronous call. HTTP path, method, and auth are out of scope. There is no streaming and no background job: one request, one response.

| File | What it is |
|---|---|
| [audit-request.schema.json](audit-request.schema.json) | Input. Machine-checked structure. |
| [audit-response.schema.json](audit-response.schema.json) | Output. Machine-checked structure. |
| [error-response.schema.json](error-response.schema.json) | Body of any non-2xx reply. See [Error response](#error-response). |
| [examples/request.json](examples/request.json), [examples/response.json](examples/response.json) | One fictional worked example (pair `default`). |
| [examples/partial.request.json](examples/partial.request.json), [examples/partial.response.json](examples/partial.response.json) | Fictional `partial` audit: one section not processed, plus a second warning. |
| [examples/out-of-range.request.json](examples/out-of-range.request.json), [examples/out-of-range.response.json](examples/out-of-range.response.json) | Fictional audit where exactly one claim span runs past the section text. It intentionally breaks rule 1 so consumers can be tested against it; no other example does. |
| This file | Conventions, field meanings, allowed values, and rules a schema cannot express. |

If this file and a schema disagree about **structure**, the schema wins. If they disagree about a **rule the schema cannot express**, this file wins. Change them in the same commit.

The verdict list and the concern-type list mirror [../mission.md](../mission.md). When the mission changes, update both schemas and this file, then bump `schema_version`.

## Versioning

`schema_version` is `MAJOR.MINOR.PATCH`.

- Removing or renaming a field, or removing an allowed value, bumps **major**.
- Adding an optional field or an allowed value bumps **minor**.
- Wording-only changes stay on the same version.

A producer must send `"schema_version": "1.0.0"`. A consumer must reject any other value and must not render a partial audit from an invalid body.

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
| `schema_version` | yes | Always `"1.0.0"`. |
| `request_id` | no | Caller-chosen id. Echoed on the response. Not a content hash. |
| `transcript` | yes | Non-empty array of turns, in order. |
| `transcript[].id` | yes | Log id. Not an evidence anchor. |
| `transcript[].speaker` | yes | Free-text speaker name. |
| `transcript[].role` | no | `interviewer`, `respondent`, `informant`, or `other`. Fixed list so checks 3 and 9 can rely on it. Omit rather than guess. |
| `transcript[].text` | yes | Turn text. May be empty. |
| `transcript[].timestamp` | no | Display exactly as supplied. Never inferred. |
| `assessment` | yes | Non-empty array of reasoning sections. One section is fine. |
| `assessment[].id` | yes | Log id. Not a claim anchor. |
| `assessment[].label` | no | Domain or sub-domain name. Display only. |
| `assessment[].score` | no | Number or string. Display only. Never audited. |
| `assessment[].text` | yes | The clinician's reasoning for this section. |

Ids must be unique among turns, and unique among sections.

## Response

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Always `"1.0.0"`. |
| `request_id` | when sent | Exact echo of the request id. |
| `status` | yes | `complete` or `partial`. |
| `warnings` | yes | May be empty. |
| `claims` | yes | May be empty only when the reasoning has no classifiable span. |

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

### Concern types

A claim may have several. Explain the discrepancy once; do not repeat the same finding. Order matches mission checks 1–12.

| Value | Mission check |
|---|---|
| `unsupported_claim` | 1. Claim support |
| `contradictory_evidence` | 2. Contradictory evidence |
| `wrong_attribution` | 3. Wrong person or source attribution |
| `timeframe_mismatch` | 4. Timeframe mismatch |
| `negation_reversal` | 5. Negation reversal |
| `certainty_inflation` | 6. Certainty inflation |
| `frequency_severity_inflation` | 7. Frequency or severity inflation |
| `context_stripping` | 8. Context stripping |
| `question_as_answer` | 9. Question mistaken for an answer |
| `correction_ignored` | 10. Correction ignored |
| `conflicting_accounts_flattened` | 11. Conflicting accounts flattened |
| `unsupported_causal_link` | 12. Unsupported causal links |

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
| `ambiguous_speaker` | Speaker identity is unclear and was not guessed. | — |
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

- If the body fails the schema or `schema_version` is not `1.0.0`, show an error. Do not render half an audit.
- If one span is out of range, still render that claim, with a warning badge. Do not shift the other highlights.
- Colour and layout are not part of this contract. Verdict drives the left pane. Evidence `role` drives the right pane.
- The right pane can expand past an excerpt. Expansion uses the same transcript array; it is not a new field.
- Do not treat `label` or `score` as an audit result.

## Error response

Any non-2xx reply carries this body instead of an audit. Example: [examples/error.json](examples/error.json). It is an additive new file, so the request/response contract stays at `1.0.0`. HTTP path and CORS stay out of scope.

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Always `"1.0.0"`. |
| `request_id` | no | Echo of the request id, when known. |
| `error.code` | yes | One value from the table below. |
| `error.message` | yes | Human-readable plain text, shown to the reviewer as-is. |

| Code | Typical HTTP status | Meaning |
|---|---|---|
| `invalid_request` | 400, 422 | The request body is malformed or fails the request schema. |
| `unsupported_version` | 400 | `schema_version` is not supported. |
| `payload_too_large` | 413 | The request is too large to process. |
| `rate_limited` | 429 | Too many requests. Retry later. |
| `internal_error` | 500 | The backend failed. |
| `unavailable` | 502, 503, 504 | The backend is down or overloaded. |
| `other` | any | Anything else, explained in `message`. |

Consumer rule: if the body validates against the schema, show `error.message`. If not (empty, HTML, other JSON), fall back to generic text for the HTTP status. Never render an audit from an error body.

## Non-goals

- No diagnosis, no score audit, no protocol or consent review.
- No check that the interview is true in the world. Fidelity is to the supplied interview only.
- No audio, files, or speech-to-text. The caller sends turns and sections already.
- No write-back to the assessment.
- No quote text, no timestamps, and no content hash in the response.
- No streaming and no job id.

## Worked example

[examples/request.json](examples/request.json) is fictional. [examples/response.json](examples/response.json) is the matching audit. Apply each span to the request; the response deliberately does not repeat the words.
