# Backend API

What the backend accepts, returns, and reads from the environment. Facts are taken from `backend/src/iaudit_backend/`.

**Audience:** users.

The request and response bodies are defined by the [contract](../contracts/README.md). This page covers only what the contract leaves out: the HTTP path, status codes, limits, settings, and when each warning is emitted. There is no authentication in this release.

## Endpoints

| Method and path | Purpose |
|---|---|
| `POST /v1/audit` | Audit one assessment against one interview. Body: an `AuditRequest`. Reply: an `AuditResponse`. |
| `GET /healthz` | Liveness. Returns `{"status": "ok"}`. |

One call is synchronous. The audit has a hard time cap (`IAUDIT_AUDIT_DEADLINE_S`, default 60 s); the review UI waits up to 120 s.

## How a request is checked

`POST /v1/audit` checks in this order and stops at the first failure.

1. Body size, from `Content-Length` and again while the body is read (reading stops as soon as the cap is passed).
2. The body parses as a JSON object.
3. `schema_version` equals `1.0.0` (checked before the schema, so an old client gets `unsupported_version`).
4. Turn count and section count.
5. The body matches the request schema.
6. Turn ids and section ids are unique.
7. The pipeline runs, then the reply is validated against the response schema.

## Errors

Every non-2xx reply has the contract error body (`error.code`, `error.message`, and `request_id` when known). Messages never contain request text.

| HTTP | `error.code` | When |
|---|---|---|
| 400 | `invalid_request` | Not JSON, not an object, fails the request schema, or has duplicate ids. |
| 400 | `unsupported_version` | `schema_version` is present and is not `1.0.0`. |
| 413 | `payload_too_large` | Body over `IAUDIT_MAX_BODY_BYTES`, turns over `IAUDIT_MAX_TURNS`, or sections over `IAUDIT_MAX_SECTIONS`. |
| 422 | `invalid_request` | Framework fallback for malformed request parameters. |
| 404, 405 | `other` | Unknown path or wrong method. |
| 500 | `internal_error` | Unexpected failure, or the reply failed the response schema. |
| 503 | `unavailable` | Nothing usable finished because the model provider was unavailable. |
| 504 | `unavailable` | Nothing usable finished before the deadline. |

A run where some sections or claims finish is **not** an error: it returns 200 with warnings (and `status: "partial"` when a section was not processed). The 503 and 504 replies apply only when no section was audited, or when every in-scope claim stalled, so an empty result cannot be mistaken for "nothing wrong".

## CORS

Only the origins in `IAUDIT_CORS_ORIGINS` (default `http://localhost:5173`) may call the API from a browser. Methods are `POST`, `GET`, and `OPTIONS`; the only allowed header is `content-type`; credentials are off. A rejected preflight returns an error body with code `other`.

## Settings

Set as `IAUDIT_<NAME>` environment variables. `Settings` in `config.py` also reads a `.env` file in the directory the server starts in (normally `backend/`). Defaults come from `Settings`.

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_PIPELINE` | `full` | `full` runs the audit; `stub` returns a valid empty audit. |
| `IAUDIT_LLM_MODE` | `live` | `live` calls providers; `fixture` replays recorded calls from `IAUDIT_FIXTURE_DIR`; `stub` makes every model call fail as unavailable. |
| `IAUDIT_FIXTURE_DIR` | `tests/fixtures/llm` | Recorded calls for `fixture` mode. |
| `IAUDIT_MODEL_CHEAP`, `_MID`, `_STRONG` | Haiku 4.5, Sonnet 5.5, Opus 5.5 | LiteLLM model ids for the three tiers. |
| `IAUDIT_AUDIT_DEADLINE_S` | `60` | Hard cap for one audit. A startup warning is logged above 100. |
| `IAUDIT_LLM_TIMEOUT_S`, `IAUDIT_LLM_MAX_RETRIES`, `IAUDIT_LLM_MAX_CONCURRENCY` | `30`, `1`, `20` | Per-call timeout, retries, and parallel calls. |
| `IAUDIT_MAX_BODY_BYTES`, `IAUDIT_MAX_TURNS`, `IAUDIT_MAX_SECTIONS` | `2000000`, `2000`, `50` | Request limits. |
| `IAUDIT_PREP_LLM` | `false` | When `true`, a cheap-tier model tags the few transcript turns the rules could not decide (question, correction, hypothetical). A failed or invalid chunk keeps the rule result. `IAUDIT_PREP_CHUNK_TURNS` (30) and `IAUDIT_PREP_CONTEXT_TURNS` (3) size the calls. If prep runs past `IAUDIT_PREP_SOFT_TIMEOUT_S` (10), the rules-only result is used. |
| `IAUDIT_PIPELINE_MAX_CLAIMS` | `80` | Claims audited per request. More are dropped and `input_truncated` is emitted. |
| `IAUDIT_SERVER_TIMING` | `false` | When `true`, a 200 reply carries a `Server-Timing` header with durations only: `total`, then `prep`, `atomize`, `link`, `check`, `assemble` in milliseconds. |
| `IAUDIT_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins. |
| `IAUDIT_CONTRACTS_DIR` | `docs/contracts` of the repo | Where the schemas are read. Environment only: not a `Settings` field, so `.env` does not set it. |
| `IAUDIT_LOG_LEVEL` | `INFO` | Logging level. Logs carry counts and ids only, never text. |

Stage tuning knobs (`IAUDIT_ATOMIZE_*`, `IAUDIT_LINK_*`, `IAUDIT_CHECK_*`, per-stage `*_CALL_TIMEOUT_S`, `IAUDIT_ASSEMBLE_RESERVE_S`, `IAUDIT_MIN_CALL_S`, and similar) are listed in `Settings` and are not needed to run the service.

**Provider keys.** The service reads the standard provider variables LiteLLM uses, for example `ANTHROPIC_API_KEY`. They are not `IAUDIT_*` settings and are never logged. With `IAUDIT_LLM_MODE=live` and no key present, the service starts, logs a warning, and audits fail with 503.

## Warnings

`warnings` appears on every 200 reply. `status` is `partial` if and only if at least one `section_not_processed` warning is present.

| Code | Emitted when |
|---|---|
| `section_not_processed` | A section produced no claims because the audit ran out of time, an internal error occurred, or no claim could be located in it. Carries `section_index`. |
| `ambiguous_speaker` | A claim relies on a turn with no `role`. No speaker is assumed. Carries `claim_id`. |
| `input_truncated` | More claims were found than `IAUDIT_PIPELINE_MAX_CLAIMS`; the extra claims were not audited. |
| `span_out_of_range` | A claim or evidence span did not fit the input and was omitted. A safety net; not expected in normal runs. |
| `other` | A claim was adjusted or omitted: its verdict changed because cited evidence could not be verified or conflicts with it; wording was changed to avoid reproducing transcript text (a quoted span of four or more words, a timestamp, or eight or more consecutive words from the transcript that the assessment does not itself contain; the last is `IAUDIT_COPY_NGRAM`, default `8`, `0` turns it off); the claim was not audited in time; it failed final validation; it overlapped another claim and was omitted, or was trimmed to remove the overlap (`IAUDIT_OVERLAP_TRIM`, default `true`); or it could not be located in the text. |

A claim that stalls on a model failure or the deadline is returned with verdict `insufficient_evidence`, not dropped.
