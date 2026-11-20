# 0023 Admin deployment and auth

Status: draft. Task 12 writes the decisions; only the staging verification record is here.

## Staging verification (Task 11)

Run 2026-11-20 against `onolys-admin-backend-staging` (Cloud Run, revision built from commit 698d622) and the `onolys-admin-staging` Hosting site, with two synthetic Identity Platform users (deleted afterwards). No real emails or secrets are recorded here; the allowlist is described by count only.

### Task 9/10 leftovers (read-only, Cloud Run Admin API)

| Item | Result |
|---|---|
| Request timeout | 130 s: met |
| Invoker | `allUsers` (`roles/run.invoker`): met |
| Service account | `admin-backend-staging`: met |
| `GIT_SHA` env and `commit-sha` label | 698d622...: met |
| Secret `admin-allowed-emails-staging` | 3 entries: met |

The service reads the allowlist through a secret env ref on version `latest`, resolved when an instance starts, so a changed list needs a new revision (rolled with an annotation-only update).

### Task 11 checks

| # | Check | Result |
|---|---|---|
| 1 | Allowlisted, verified account, no MFA step | Met. Password sign-in, token claims show `email_verified` true and no second factor; `GET /v1/paudit/fixtures` 200 (3 fixtures). CORS preflight from the staging site origin 200 |
| 2 | Verified account not on the list | Met. API 403 `forbidden`; browser shows the "Not allowed / not on the admin list" screen after the first backend call (the gate learns of the 403 lazily) |
| 3 | Unverified email, even if listed | Met. 403 `forbidden`; the same account returned 200 once verified. Anonymous call: 401 |
| 4 | Audit of a 60-100 s synthetic fixture via the direct URL | Met. Synthetic request built from the MITI `poor_practice` fixture turns plus 40 synthetic sections: 200 in 71.7 s (second run 55.2 s), status `partial` (LLM could not locate claims in some filler sections; not an infra fault). Smaller requests: 4 sections 23.6 s, 14 sections 35.2 s. Wall times are far below the 100 s deadline and the 130 s service timeout |
| 4b | Hosting-to-Cloud-Run timeout and header pass-through | Not measured. The deployed Hosting config has no `/v1` rewrite (SPA fallback only, by design D2), so there is no path to measure without a temporary Hosting change. Design stays: browser calls Cloud Run directly. The documented Hosting rewrite limit is 60 s |
| 5 | paudit on the MITI synthetic fixture, schema-valid | Not met on the deployed image: `POST /v1/paudit` returns 500. Cause: image has no `config/`, while infra sets `ROUTES_FILE=config/staging/routes.yaml` (relative to `/app`); `ConfigError` is raised when the live LLM client is built. Fixed in `admin/backend/Dockerfile` (`COPY config /app/config`) with a test; needs a redeploy, then re-run this check (schema validation and tab rendering of a live result still pending) |
| 6 | Deployed bundle: no Eval tab, no eval calls | Met in the DOM and network: `VITE_EVAL_ENABLED` is inlined as `false`; tabs shown are `eaudit` and `paudit` only; no request to `/eval-api` during sign-in, tab switch, fixture load and run. The bundle still contains the eval client code and schema strings (dead code, gated at runtime) |
| 7 | No real data in repo or image | Met for clinical data: no audio files tracked; the image copies only engines, admin packages, `protocols/` (MITI synthetic fixtures; `**/tests`, `docs`, `eval`, datasets are excluded by `.dockerignore`), `config/` and the JSON schemas. Findings outside the image: `docs/reference/infra.md` lists the 3 real allowlist emails, `infra/variables.tf` has a default that is a real email, and `docs/reference/staging-e2e.md` names the real audio sample file. Owner decision needed |

### Defect found: deployed site renders blank (CSP vs Ajv)

The deployed `frontend/firebase.json` CSP has `script-src 'self' https://apis.google.com`. The frontend compiles JSON schemas at import time with Ajv, which uses `new Function`, so the browser blocks it ("Evaluating a string as JavaScript violates ... 'unsafe-eval'") and the page stays blank, with no login screen. The checks above that need the UI were run with CSP bypassed in the browser; the API checks are unaffected. Proposed fix (owner/security call): either add `'unsafe-eval'` to `script-src` (one line, weakens CSP on an allowlisted internal site) or precompile the schemas at build time (Ajv standalone code), which keeps the strict CSP. Not changed in this task.

### Cleanup

Allowlist restored (new secret version equal to the original, temporary version disabled), service rolled to a revision that reads it, test users confirmed 403 then deleted (sign-in now fails). The service's template annotation used for rolling was removed; timeout, env and image unchanged.
