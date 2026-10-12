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

Every `IAUDIT_*` setting, its default and its meaning is in [configuration.md](configuration.md). The few that decide how a request fails are the limits (`IAUDIT_MAX_BODY_BYTES`, `IAUDIT_MAX_TURNS`, `IAUDIT_MAX_SECTIONS`), the deadline (`IAUDIT_AUDIT_DEADLINE_S`, default 60 s) and the mode switches `IAUDIT_PIPELINE` and `IAUDIT_LLM_MODE`.

## Warnings

Every 200 reply carries a `warnings` list, and `status` is `partial` if and only if a `section_not_processed` warning is present. When each code is emitted: [warnings.md](warnings.md).

A claim that stalls on a model failure or the deadline is returned with verdict `insufficient_evidence`, not dropped.
