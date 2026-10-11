# Review UI reference

Lookup facts for the review UI in [../../frontend/](../../frontend/). Request and response shapes: [../contracts/](../contracts/README.md).

**Audience:** users.

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
- The reply is delayed 250 ms. Cancel works during the wait.
- Header shows a "Mock data" chip.

| Pair | Shows |
|---|---|
| `default` | One claim per verdict. |
| `partial` | Partial status, a not-processed section, a second warning. |
| `out-of-range` | One claim span past the section text. |

## The request the app sends

`POST <VITE_AUDIT_URL>`, JSON body = the uploaded request, headers `Content-Type` and `Accept: application/json`, no cookies (`credentials: omit`), timeout 120 s. The service must allow CORS from the app's origin.

## Checks on the reply

In this order. The first failure stops the audit.

1. Body is not empty and is valid JSON.
2. It is a JSON object.
3. `schema_version` is `1.0.0`.
4. It matches the response schema.
5. `request_id` equals the request's, if the request had one.
6. Claim ids are unique.

Then each span is checked against the uploaded text. A bad span flags only its claim or excerpt.

## Error screens

| Cause | Title | Buttons |
|---|---|---|
| Empty or non-JSON file; fails request schema | Invalid request file | Choose another file |
| Mock off, no URL | Audit service not configured | Choose another file |
| No mock pair for `request_id` | No mock audit for this request | Choose another file |
| Fetch failed (down, wrong URL, CORS) | Couldn't reach the audit service. | Retry |
| No reply in 120 s | Request timed out | Retry |
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
| Schema version | `1.0.0` |

Verdict and evidence styles are in `frontend/src/tokens/index.ts`; concern names in `frontend/src/claim-detail/concernLabels.ts` (mission checks 1–12).
