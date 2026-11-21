# Backend API

What the backend accepts, returns, and reads from the environment. Facts are taken from `engines/eaudit/src/eaudit/`.

**Audience:** users.

The request and response bodies are defined by the [contract](../contracts/README.md). This page covers only what the contract leaves out: the HTTP path, status codes, limits, settings, and when each warning is emitted. The eaudit backend described above has no authentication. The admin deployment adds some; see [Admin deployment](#admin-deployment).

## Endpoints

| Method and path | Purpose |
|---|---|
| `POST /v1/audit` | Audit one assessment against one interview. Body: an `AuditRequest`. Reply: an `AuditResponse`. |
| `GET /healthz` | Liveness. Returns `{"status": "ok"}`. |

One call is synchronous. The audit has a hard time cap (`IAUDIT_AUDIT_DEADLINE_S`, default 100 s); the review UI waits up to 120 s.

## Run info

With the `full` pipeline, a successful reply carries `run_info` (contract: [run_info](../contracts/README.md#run_info)): the model id used for each tier (`models.cheap`, `.mid`, `.strong`) and a hash per prompt group (`prompt_hashes.atomize`, `.link`, `.check`, `.prep`; first 16 hex chars of the sha256 of the prompt file bytes, the same as the eval manifest). The `stub` pipeline omits `run_info`, because it would name models and prompts that were not used.

`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` and `cost_usd` are optional in the contract. The backend does not do token accounting or pricing, so it never sets them, and never sends zeros in their place. `run_info` holds ids, hashes and counts only, never transcript or assessment text.

## How a request is checked

`POST /v1/audit` checks in this order and stops at the first failure.

0. `Content-Type`, when supplied, is `application/json`.
1. Body size, from `Content-Length` and again while the body is read (reading stops as soon as the cap is passed).
2. The body parses as a JSON object.
4. Turn count and section count.
5. The body matches the request schema.
6. Turn ids and section ids are unique.
7. The pipeline runs, then the reply is validated against the response schema.

## Errors

Every non-2xx reply has the contract error body: `schema_version`, `status` (equal to the HTTP status), `message`, a non-empty `details` list of `{code, message}`, and `request_id` when known. Messages contain paths and fixed text, never request values. The full detail-code and reviewer-action table is in the [contract](../contracts/README.md#error-response).

| HTTP | `details[].code` | When |
|---|---|---|
| 400 | `invalid_json` | Not JSON or not a JSON object. |
| 400 | `schema_violation`, `empty_transcript`, `empty_assessment` | Request schema violation (including a wrong schema version), or an empty required array. |
| 400 | `duplicate_ids` | Turn ids or section ids are duplicated; only counts are reported. |
| 413 | `body_too_large`, `too_many_turns`, `too_many_sections` | Body over `IAUDIT_MAX_BODY_BYTES`, turns over `IAUDIT_MAX_TURNS`, or sections over `IAUDIT_MAX_SECTIONS`. |
| 415 | `unsupported_media_type` | `Content-Type` is present and is not `application/json`. |
| 422 | `invalid_parameters` | Framework fallback for non-body request parameters. |
| 404 | `not_found` | Unknown path. |
| 405 | `method_not_allowed` | Wrong HTTP method. |
| 400, 403 | `cors_rejected` | Rejected preflight; the body status matches the preflight status. |
| 429 | `rate_limited` | Reserved; not raised today. |
| other 4xx | `request_rejected` | Other framework HTTP error. |
| 500 | `internal_error` | Unexpected failure, or the reply failed the response schema. |
| 503 | `upstream_unavailable` | Nothing usable finished because the model provider was unavailable. |
| 504 | `deadline_exceeded` | Nothing usable finished: the deadline passed, or every unit failed (for example, unusable model output). |

A run where some sections or claims finish is **not** an error: it returns 200 with warnings (and `status: "partial"` when a section was not processed). The 503 and 504 replies apply only when no section was audited, or when every in-scope claim stalled, so an empty result cannot be mistaken for "nothing wrong".

## CORS

Only the origins in `IAUDIT_CORS_ORIGINS` (default `http://localhost:5173`) may call the API from a browser. Methods are `POST`, `GET`, and `OPTIONS`; the only allowed header is `content-type`; credentials are off. A rejected preflight returns an error body with detail code `cors_rejected`.

## Settings

Every `IAUDIT_*` setting, its default and its meaning is in [configuration.md](configuration.md). The few that decide how a request fails are the limits (`IAUDIT_MAX_BODY_BYTES`, `IAUDIT_MAX_TURNS`, `IAUDIT_MAX_SECTIONS`), the deadline (`IAUDIT_AUDIT_DEADLINE_S`, default 100 s) and the mode switches `IAUDIT_PIPELINE` and `IAUDIT_LLM_MODE`.

## Warnings

Every 200 reply carries a `warnings` list, and `status` is `partial` if and only if a `section_not_processed` warning is present. When each code is emitted: [warnings.md](warnings.md).

A claim that stalls on a model failure or the deadline is returned with verdict `insufficient_evidence`, not dropped.

## Admin deployment

The internal admin site (`admin.onolys.com`, also `onolys-admin-staging.web.app`) is a single environment, staging (owner decision 2026-11-21; no prod admin), and runs one Cloud Run service, `onolys-admin-backend-staging`. It uses only synthetic MITI fixtures, no user data; its CORS allows `https://admin.onolys.com` and `https://onolys-admin-staging.web.app`. It serves the unchanged eaudit app (`POST /v1/audit`) plus admin-only paudit routes, behind a login check. Everything above applies to `/v1/audit` there. Code: `admin/backend/src/onolys_admin_backend/app.py`, `admin/auth/src/onolys_admin_auth/`. Why it is built this way: [ADR 0023](../decisions/0023-admin-deployment-and-auth.md).

### Auth

Every request except a CORS preflight (`OPTIONS`) must carry `Authorization: Bearer <Identity Platform ID token>` (`middleware.py`). The token is checked for an RS256 signature, `aud` equal to the project (`ADMIN_AUTH_PROJECT`), `iss` equal to `https://securetoken.google.com/<project>`, and expiry (`verifier.py`). Then `email_verified` must be true and the email must be in `ADMIN_ALLOWED_EMAILS` (case-insensitive). No second factor is required. Token and email are never logged.

| HTTP | `error.code` | When |
|---|---|---|
| 401 | `unauthenticated` | No bearer header, or the token is invalid or expired. Reply carries `WWW-Authenticate: Bearer`. |
| 403 | `forbidden` | Valid token, but the email is unverified or not on the list. |
| 503 | `upstream_unavailable` | The token signing keys could not be fetched. |

These three replies use a small body `{"error": {"code", "message"}}`, not the contract error body of the routes below.

### Routes

| Method and path | Purpose |
|---|---|
| `POST /v1/audit` | eaudit, unchanged. |
| `POST /v1/paudit` | Run a paudit pass. Body: `{transcript, pack: "miti@4.2.1", params}`; optional `request_id`. `params` needs `speaker_map.subject` and `change_goal`; optional `coded_span {from_s, to_s}`, `language`, `n_runs` (integer 1 to 5). Reply: a `PauditResult` (schema: `engines/paudit/schemas/paudit-result.schema.json`). Synchronous; nothing is stored. |
| `GET /v1/paudit/fixtures` | List the synthetic MITI fixtures with ready-to-run `params`. |
| `GET /v1/paudit/fixtures/{name}` | One fixture: `{name, description, pack, transcript, params}`. Synthetic fixtures only. |

paudit errors use the contract error body (same shape as [Errors](#errors)), from `paudit_routes.py`:

| HTTP | `details[].code` | When |
|---|---|---|
| 400 | `invalid_json` | Body not JSON or not an object. |
| 400 | `unknown_pack`, `missing_parameter`, `invalid_parameters`, `schema_violation`, `empty_transcript`, `input_rejected` | Bad `pack`, `params` or transcript. |
| 404 | `not_found` | Unknown fixture name. |
| 413 | `body_too_large` | Body over the eaudit body limit (default 2,000,000 bytes). |
| 415 | `unsupported_media_type` | `Content-Type` present and not `application/json`. |
| 500 | `internal_error` | Unexpected failure. |
| 502 | `run_failed` | Every run failed. |
| 503 | `upstream_unavailable` | Model provider unavailable. |
| 504 | `deadline_exceeded` | `ADMIN_PAUDIT_DEADLINE_S` passed. |

### CORS

Handled before auth, so preflights need no token and 401/403 replies also carry CORS headers (`app.py`). Only the exact origins in `ADMIN_CORS_ORIGINS` are allowed (a wildcard or `null` stops startup). Methods: `GET`, `POST`, `OPTIONS`. Allowed headers: `authorization`, `content-type`. Credentials are off. The browser calls the Cloud Run URL directly, so the site's CSP `connect-src` lists that origin (`frontend/firebase.json`, filled in by `scripts/ci/set_admin_origin.sh`).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ENV` | none (image sets `prod`) | `local` or `test` allows auth off. Any other value or unset counts as non-local. |
| `ADMIN_AUTH` | `on` (`off` when `ENV` is `local`/`test`) | `on` or `off`. `off` with a non-local `ENV` stops startup. |
| `ADMIN_AUTH_PROJECT` | `GCP_PROJECT` | Project whose ID tokens are accepted. Required with auth on. |
| `ADMIN_ALLOWED_EMAILS` | none | Comma list. Empty stops startup with auth on. Cloud Run reads it from Secret Manager `admin-allowed-emails-{env}` (version `latest`, read when an instance starts, so a change needs a new revision). |
| `ADMIN_CORS_ORIGINS` | empty (no origin allowed) | Comma list of exact origins. |
| `ADMIN_PAUDIT_DEADLINE_S` | `100` | Hard time cap for `POST /v1/paudit`. |
| `PORT` | `8080` | Listen port (image). |

Cloud Run request timeout is 130 s, above both deadlines (`IAUDIT_AUDIT_DEADLINE_S` for audit, `ADMIN_PAUDIT_DEADLINE_S` for paudit). The service is public at Cloud Run (`allUsers` invoker); access is enforced only by the app. Terraform: `infra/modules/environment/services.tf`. Deploy: `.github/workflows/deploy-admin.yml`.

### Deadline and hosting

The Firebase Hosting rewrite limit (60 s) is below the 100 s deadlines, so the site has no `/v1` rewrite. The frontend is built with `VITE_AUTH_REQUIRED=true`, `VITE_AUDIT_URL` (the Cloud Run URL plus `/v1/audit`) and the `VITE_FIREBASE_*` values; `VITE_EVAL_ENABLED` is `false` in the deployed build, so there is no Eval tab and no eval call.
