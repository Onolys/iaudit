# Review UI reference

Lookup facts for the review UI in [../../frontend/](../../frontend/). Request and response shapes: [../contracts/](../contracts/README.md).

**Audience:** users.

The top-level **eaudit | Eval** switch opens either this upload/review flow or the
[Eval UI](eval-ui.md). eaudit is selected initially. Switching away discards the loaded
audit and selection and cancels any in-flight audit request; returning starts fresh.
Eval runs continue on the server when leaving its tab and reattach on return.

## Environment

Set in `frontend/.env.local` (git-ignored; start from `.env.example`). Values are fixed at build time.

| Variable | Meaning |
|---|---|
| `VITE_AUDIT_URL` | Audit endpoint URL. Empty or missing = no URL. |
| `VITE_MOCK` | Mock mode is on only if exactly `true`. |

If mock is off and there is no URL, the app shows "Audit service not configured".

## Mock mode

- No network call. The reply comes from `docs/contracts/examples/`, then goes through normal reply checks.
- A pair is `<name>.request.json` + `<name>.response.json`. Plain `request.json`/`response.json` is `default`. Other files (such as `error.json`) are ignored.
- The upload is matched by exact `request_id`. No id or no match gives "No mock audit for this request". There is no fallback.
- The reply is delayed (see [Fixed values](#fixed-values)). Cancel works during the wait.
- The header shows a "Mock data" chip only once a mock audit has loaded, not while loading or on an error screen.

| Pair | Shows |
|---|---|
| `default` | One claim per verdict. |
| `partial` | Partial status, a not-processed section, a second warning. |
| `out-of-range` | One claim span past the section text. |

## The request the app sends

`POST <VITE_AUDIT_URL>`, JSON body = the uploaded request, headers `Content-Type` and `Accept: application/json`, no cookies (`credentials: omit`), with a timeout (see [Fixed values](#fixed-values)). The service must allow CORS from the app's origin.

## Checks on the reply

In this order. The first failure stops the audit.

1. Body is not empty and is valid JSON.
2. It is a JSON object.
3. `schema_version` is `1.2.0`.
4. It matches the response schema.
5. `request_id` equals the request's, if the request had one.
6. Claim ids are unique.

The optional `run_info` block is accepted when it matches the schema and is not displayed. A reply renders the same with or without it.

Then each span is checked against the uploaded text. A bad span flags only its claim or excerpt.

## Error screens

| Cause | Title | Buttons |
|---|---|---|
| Empty or non-JSON file; fails request schema | Invalid request file | Choose another file |
| Mock off, no URL | Audit service not configured | Choose another file |
| No mock pair for `request_id` | No mock audit for this request | Choose another file |
| Fetch failed (down, wrong URL, CORS) | Couldn't reach the audit service. | Retry |
| A bundled mock file fails to load | Couldn't reach the audit service. (address shown: "bundled mock fixtures") | Retry |
| No reply before the timeout | Request timed out | Retry |
| Cancel pressed | Cancelled. | Retry |
| HTTP 5xx | Audit service error (status). | Retry |
| HTTP 408, 429 | Request rejected (status) | Retry, Choose another file |
| Other HTTP 4xx | Request rejected (status) | Choose another file |
| Steps 1–4 and 6 above fail | Invalid audit response | Choose another file |
| Step 5 fails | Response doesn't match this request. | Choose another file |

For HTTP errors the service's `error.message` is shown only if the body matches the [error schema](../contracts/error-response.schema.json). Schema problems list at most 50 paths.

## Fixed values

| Value | Setting |
|---|---|
| Request timeout | 120 s |
| Mock delay | 250 ms |
| Context step | 3 turns per click |
| Schema version | `1.2.0` |

Verdict and evidence styles are in `frontend/src/tokens/index.ts`; concern names in `frontend/src/claim-detail/concernLabels.ts` (mission checks 1–13).
