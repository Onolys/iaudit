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
| 5 | paudit on the MITI synthetic fixture, schema-valid | Met on the redeploy (admin at 9069a08; first run 500, fixed in 4abf760). `POST /v1/paudit` on `good_practice`: 200 in 43.8 s, 14,345 bytes, valid against `engines/paudit/schemas/paudit-result.schema.json`. The live result also renders in the paudit tab (utterance table with codes, quotes and rationales) |
| 6 | Deployed bundle: no Eval tab, no eval calls | Met in the DOM and network: `VITE_EVAL_ENABLED` is inlined as `false`; tabs shown are `eaudit` and `paudit` only; no request to `/eval-api` during sign-in, tab switch, fixture load and run. The bundle still contains the eval client code and schema strings (dead code, gated at runtime) |
| 7 | No real data in repo or image | Met for clinical data: no audio files tracked; the image copies only engines, admin packages, `protocols/` (MITI synthetic fixtures; `**/tests`, `docs`, `eval`, datasets are excluded by `.dockerignore`), `config/` and the JSON schemas. Findings outside the image: `docs/reference/infra.md` lists the 3 real allowlist emails, `infra/variables.tf` has a default that is a real email, and `docs/reference/staging-e2e.md` names the real audio sample file. Owner decision needed |

### Defect found: deployed site renders blank (CSP vs Ajv) - resolved

The deployed CSP (`script-src 'self' https://apis.google.com`) blocked Ajv's `new Function`, so the site rendered blank. Resolved in 4a2b33a by precompiling the validators, keeping the strict CSP. Re-check at 9069a08, no CSP bypass: login screen renders; 0 `securitypolicyviolation` events in both sessions; allowlisted user signs in, review UI shows tabs `eaudit` and `paudit`; paudit tab loads the fixture, runs (21 s) and renders the result; the non-listed verified user sees the "Not allowed / This account is not on the admin list" screen (one 403, no console errors besides that).

### Cleanup

Allowlist restored (new secret version equal to the original, temporary version disabled), service rolled to a revision that reads it, test users confirmed 403 then deleted (sign-in now fails). The service's template annotation used for rolling was removed; timeout, env and image unchanged.

### Re-check after fixes

Run 2026-11-20, same method (two synthetic users, temporary allowlist version, rolled revision), then restored: new secret version equal to the original (3 entries), temporary version disabled, service rolled so it reads the original list, the previously listed test user got 403, both users deleted (sign-in fails). Rolling annotation removed. Checks 5 and the blank-site defect are resolved as recorded above; checks 1-4, 6 and 7 are unchanged.
