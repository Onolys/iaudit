# 0016. Reset the contract; group concerns; allow missing speakers; detail errors

**Audience:** contributors.

**Status:** accepted.

**Context.** The project is not deployed. The contract needs 17 concern types, a stable summary grouping, transcripts without speaker identities, and errors that identify each failed check without exposing input values.

**Decision.**

**Contract-versioning rule (whole initiative): all schemas are `"0.0.1"`; the project is not deployed; no legacy/back-compat code, version history or migration; a non-conforming file just shows a validation error and the owner deletes it.**

All three contract schemas and the eval metrics, item-row and comparison schemas use `schema_version: "0.0.1"`. Schema constants, backend and frontend constants, validators, models and examples move together. A body that does not match the current schema produces a validation error. There is no migration or parallel schema acceptance; a later contract change may bump the version normally.

The concern enum has the existing 13 entries followed by `opinion_as_fact`, `calculation_error`, `meaning_shift`, and `unsupported_inference`. Every concern requires `group`, assigned by `type`:

| Group | UI label | Types |
|---|---|---|
| `not_in_interview` | Not in interview | `unsupported_claim`, `unsupported_causal_link`, `question_as_answer`, `unsupported_inference` |
| `opposite_of_interview` | Opposite of interview | `contradictory_evidence`, `negation_reversal` |
| `changed_detail` | Changed detail | `wrong_attribution`, `timeframe_mismatch`, `quantity_mismatch`, `frequency_severity_inflation`, `certainty_inflation`, `opinion_as_fact`, `calculation_error`, `meaning_shift` |
| `missing_context` | Missing context | `context_stripping`, `correction_ignored`, `conflicting_accounts_flattened` |

The backend emits the group from its map. The response schema enforces all four mappings with conditional clauses, and the frontend validates with that same schema. Each language has one map with a schema parity test. UI group headings follow the table order, omit empty groups, and retain concern order within a group.

A turn requires only `id` and `text`. `speaker` is optional and must be a non-empty string when present. Omission means unknown; never insert an empty string, `null`, or an invented identity. This extends [ADR 0011](0011-role-optional-never-guessed.md): speaker-dependent checks and question/answer pairing skip unknown speakers, and cited turns missing either speaker or role produce `ambiguous_speaker`. Its fixed message is "Speaker or role was missing for turn(s) {turns}; none was assumed." The UI displays "Unknown speaker" for an absent identity; prompt text alone may render it as `speaker="unknown"`.

Every non-2xx body contains required `schema_version`, `status`, `message`, and `details`; `request_id` is optional. `status` is an integer from 400 through 599 and equals the HTTP status. `message` is non-empty plain text. `details` contains at least one `{code, message}` item; detail messages contain paths and fixed text only, never input values. Request schema failures return at most five issues. There is no top-level code or nested `error` object. An incorrect schema-version value is a `schema_violation`.

The 18 detail codes and their prescribed meanings are:

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

A consumer shows a valid body's `message` and each detail message. An invalid body, or a body whose status differs from the HTTP status, uses generic status text. Retry remains status-based; detail codes never decide retry, and automatic audit POST retries are limited to 429. `rate_limited` is reserved in the enum and is not raised today.

This ADR amends [0014](0014-run-info-optional-one-shared-version.md) only for the contract reset; optional `run_info`, shared versions and provenance restrictions remain. It amends [0015](0015-add-quantity-mismatch-widen-attribution-and-context-stripping.md) for the expanded enum and reset; its quantity, attribution, context and frozen evaluation-mapping decisions remain.

**Alternatives.** Retain schema compatibility handling; derive groups only in the UI; require or infer speaker identities; use one broad error category per HTTP class. These add machinery or lose information needed by consumers and reviewers.

**Consequences.** Saved bodies that fail the current schema are deleted by their owner. Concerns have one enforced group across consumers. Missing speaker identity remains unknown and narrows the checks. Errors can identify several failed fields without returning their values. Detection of the four additional concern types is separate from this contract change.
