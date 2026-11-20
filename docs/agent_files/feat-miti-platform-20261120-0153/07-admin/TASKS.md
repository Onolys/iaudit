---
status: draft
summary: SP07 tasks (AFTER LAUNCH, r7): shared auth package, admin-backend gateway + admin-only paudit route, Dockerfile, frontend flags/auth gate/paudit tab, Hosting headers, SP06 flip, deploy-admin.yml, staging verification, docs, prod + acceptance.
date: 2026-11-20
---
# Tasks: SP07 admin.onolys.com — gated review UI + paudit tab
Source of truth: 07-admin/PRD.md. **AFTER LAUNCH (r7): none of this is v1 work; start only once SP01, SP02 and SP06 (staging and prod) are live.** Until then results are inspected with `python -m paudit.cli` and the GCS run artifacts. Tasks 1-4 are backend (`admin/`), 5-8 are frontend, 9-10 are infra and CI, 11-13 verify, document and release. The eval server/Eval tab is not deployed (R6, R7, D1) and no task touches `eval/`. CI jobs referenced are the existing SP00 `frontend` and `eaudit` jobs, plus `admin/` tests added to PR CI in task 10. No Playwright (SP00 r8). Owner steps first: 9 (allowlist emails), 12 (DNS), 13 (prod approval).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | `admin/auth` ASGI verifier package + workspace wiring | SP01 T1 (workspace) | todo |
| 2 | `admin/backend` gateway: auth + CORS + mounted eaudit app | 1 | todo |
| 3 | `POST /v1/paudit` and `GET /v1/paudit/fixtures` | 2, SP02 T10 | todo |
| 4 | `admin/backend/Dockerfile` image | 3 | todo |
| 5 | Frontend registry, product-to-view mapping, `VITE_EVAL_ENABLED` | SP01 | todo |
| 6 | Login gate and bearer transport (`auth/`, `transport/`) | 5 | todo |
| 7 | paudit tab (`paudit/`), types and schema vitest, mock mode | 5, 6, 3 (contract) | todo |
| 8 | Hosting config: SPA fallback and security headers | 5 | todo |
| 9 | Flip `admin_enabled`, secrets, staging admin resources | 4, SP06 T2, SP06 T4 (owner step: allowlist emails) | todo |
| 10 | `deploy-admin.yml` and PR CI for `admin/` | 4, 8, 9 | todo |
| 11 | Staging verification (auth, timeout, audit, paudit) | 7, 10 | todo |
| 12 | Docs: `backend-api.md` admin section and ADR 0023 | 11 | todo |
| 13 | Prod flip, domain, deploy, acceptance sweep | 11, 12 (owner steps: DNS, approval) | todo |

Parallel lanes: backend 1-4 and frontend 5-8 are independent until task 7 needs the paudit route contract from task 3 (the frontend builds on the SP02 schema and mock mode first, so 7 can start after 5 and 6 and finish once 3 lands). 6 and 8 both touch `frontend/` but different files, so they can run in parallel after 5; keep 5 first because it changes `App.tsx` and `products.ts`. Task 9 can run alongside 5-8 once 4 exists. Sync points: SP01 owns the root `pyproject.toml` (additive `admin/*` members only here); SP02 owns the paudit result schema and `paudit.run`; SP06 owns the admin Terraform resources behind `admin_enabled`, `_deploy-cloudrun.yml`, DNS values and WIF `deployer-{env}`; SP05 header conventions are reused for Hosting. Lane C web tasks (SP05) share nothing with `frontend/` files here.

## Task 1 — `admin/auth` verifier package
What it is / what it means: the one tested place that decides who may call `admin-backend`; reusable later by the eval server (PRD R3, D3, D4, D5).
What changes at a high level: new uv workspace member `admin/auth` (package `onolys_admin_auth`, root `pyproject.toml` glob `admin/*`, additive) with ASGI middleware that verifies an Identity Platform ID token (signature, audience = project, issuer, expiry via google-auth), requires `email_verified` and `email` in `ADMIN_ALLOWED_EMAILS` (comma list, case-insensitive, no MFA claim required), handles preflight `OPTIONS` before auth, returns `{error:{code,message}}` 401/403, and logs no token or email. Startup fails when auth is on and the allowlist is empty; `ADMIN_AUTH=off` is refused unless `ENV=local|test`.
Done when: unit tests cover missing token, malformed token, expired, wrong audience, wrong issuer, unverified email, non-listed email, mixed-case allowlisted email (allowed), empty allowlist startup failure, `off` refused outside `local|test`, preflight bypass, and a log-capture test showing no token or email; existing `eaudit` and `frontend` CI jobs still pass with the workspace change.

## Task 2 — `admin/backend` gateway with auth, CORS, eaudit mount
What it is / what it means: the single Cloud Run app, with eaudit's behaviour untouched (PRD R4, R5, D2, D3).
What changes at a high level: new workspace member `admin/backend` with a FastAPI parent app: auth middleware from task 1 plus CORS (exact origins from `ADMIN_CORS_ORIGINS`, headers `authorization,content-type`), and the unmodified eaudit app mounted for `/v1/audit` and its health route. No change to eaudit's contract or code.
Done when: tests show every route (audit, health, unknown paths) returns 401/403 without a valid allowlisted token and succeeds with one; a CORS test shows allowed and disallowed origins and a preflight that passes without a token; with `ADMIN_AUTH` off and `ENV=local`, the existing `/v1/audit` contract tests pass through the gateway unchanged; the `eaudit` CI job still passes.

## Task 3 — `POST /v1/paudit` and fixtures route
What it is / what it means: admin-only way to run SP02's paudit on a pasted or fixture transcript (PRD R4, R5, D7; resolved: admin-only route).
What changes at a high level: `POST /v1/paudit` accepting `{transcript, pack:"miti@4.2.1", params:{speaker_map:{subject}, change_goal, coded_span?, language?, n_runs?}}`, calling `paudit.run` in-process, returning the SP02 `PauditResult` plus `run_info`; synchronous with deadline `ADMIN_PAUDIT_DEADLINE_S` (default 100), the same size limit as eaudit, and contract-style 4xx/504 bodies. `GET /v1/paudit/fixtures` lists and serves only the pack's synthetic fixtures, each with ready-to-run `params`. Nothing is stored; no transcript text is logged.
Done when: tests on a fake LLM adapter return a result that validates against the SP02 result JSON schema; missing `speaker_map` or `change_goal` gives a 4xx; oversize body gives the size error; a forced slow run gives the 504 body at the deadline; fixtures route returns only synthetic fixtures; log-capture shows no transcript text; auth tests from task 2 cover both new routes; one live run on the MITI synthetic fixture is recorded (marker `live`, not in CI).

## Task 4 — `admin/backend` Dockerfile
What it is / what it means: the deployable image (PRD R9, architecture).
What changes at a high level: `admin/backend/Dockerfile` building the gateway with engines, `protocols/` pack and the workspace packages needed; no real data, datasets or eval code baked in; `ENV` and `ADMIN_AUTH` default to safe values (auth on).
Done when: the image builds in CI or locally; a container smoke test starts it with auth on and a test allowlist and returns 401 for an anonymous health call to a protected route; starting it with an empty allowlist exits non-zero; an image listing check shows no `eval/datasets` or transcript data inside.

## Task 5 — Frontend registry, view mapping, eval flag
What it is / what it means: groundwork so a second product can exist and the deployed build never shows Eval (PRD R1, R8, D1).
What changes at a high level: `PRODUCTS` in `products.ts` gains `{id:"paudit", label:"paudit"}`; `App.tsx` maps product id to a view component (replacing the eaudit-only branch); `config.ts` gains `VITE_EVAL_ENABLED` (default unchanged for local dev, `false` in the deployed build) which hides the Eval tab and prevents eval calls. A placeholder paudit view is acceptable until task 7.
Done when: vitest covers product-to-view mapping, the Eval tab hidden and zero eval requests when the flag is false, and Eval visible by default locally; existing `frontend` CI job (lint, typecheck, vitest) passes; mock mode still works.

## Task 6 — Login gate and bearer transport
What it is / what it means: the browser side of the gate (PRD R2, D4, D5).
What changes at a high level: `frontend/src/auth/` using `firebase/auth` only: email/password and Google sign-in, sign-out, no sign-up screen, no MFA screens; the gate renders only when `VITE_AUTH_REQUIRED=true` (local dev and `VITE_MOCK` skip it); `authDomain = admin.onolys.com`. `transport/` attaches `Authorization: Bearer <ID token>` through one injected provider; 401 triggers one forced token refresh then the login screen; 403 shows a "not on the admin list" screen.
Done when: vitest with a fake auth provider covers gate on/off, token attach, 401 then one refresh then login, 403 screen, no sign-up route, no MFA UI, and that dev/mock skip the gate; the `frontend` CI job passes.

## Task 7 — paudit tab
What it is / what it means: the UI for running paudit and reading the result (PRD R8, D7, risks).
What changes at a high level: `frontend/src/paudit/`: transcript paste or JSON upload, "Load fixture" (prefills params), pack field default `miti@4.2.1`, clinician speaker dropdown from the transcript's speakers, required change goal, optional coded span, `n_runs`, Run; result view with utterance table (code, quote, rationale), counts, summary scores against reference levels, four globals with cited lines, warnings and `run_info`. Includes a "do not paste real PHI until BAA" note. Hand-written TS types; mock mode ships one sample result. State in memory only: no transcript text in URLs, logs or storage.
Done when: a vitest checks the TS types against `engines/paudit/schemas/paudit-result.schema.json` (pattern of `eval-schema.test.ts`); component tests render the sample result with codes, counts, summaries, globals and warnings; required-field validation blocks Run; a test asserts no transcript text reaches URL, `localStorage` or console; the `frontend` CI job passes.

## Task 8 — Hosting config: SPA fallback and headers
What it is / what it means: static serving rules for both sites (PRD R1, R5).
What changes at a high level: `frontend/firebase.json` for targets `admin` and `admin-staging`: SPA fallback only, no `/v1` or `/eval-api` rewrite; headers like SP05 (CSP with `connect-src` limited to the `admin-backend` Cloud Run URL and Identity Platform, `no-referrer`, `nosniff`, `frame-ancestors 'none'`, no-cache on HTML). `.firebaserc` admin targets already come from SP06 task 2.
Done when: a config test (script or vitest) parses `firebase.json` and asserts no `/v1` rewrite, the required headers and the SPA fallback; a built `frontend/dist` served by the Firebase emulator returns the headers; the `frontend` CI job passes.

## Task 9 — Flip `admin_enabled`, secrets, staging admin resources
What it is / what it means: create the admin infra that SP06 prepared behind a flag (PRD R5, R9, D8; SP06 tasks 2, 4, 12). Owner step: Tejit provides the allowlist emails.
What changes at a high level: set `admin_enabled=true` for staging, apply; seed `admin-allowed-emails-{env}` with the owner-provided list via SP06's seed script; confirm `onolys-admin-backend-staging` has the `allUsers` invoker, `ADMIN_CORS_ORIGINS`, secret refs, 130 s request timeout, and the `admin-backend-staging` SA; Identity Platform authorised domains include the staging admin host.
Done when: plan before apply shows only admin resources; second plan empty; anonymous request to the service reaches the app and gets 401 from the in-app gate (not an IAM 403 from Cloud Run); the secret contains the supplied list (checked by name and count, value not printed); the staging service reports timeout 130 s; `infra` CI job green.

## Task 10 — `deploy-admin.yml` and PR CI for `admin/`
What it is / what it means: automated deploys and tests (PRD R9, D8).
What changes at a high level: `deploy-admin.yml` calling SP06's `_deploy-cloudrun.yml` (inputs `env`, `service`, `image`; WIF `deployer-{env}`) for `onolys-admin-backend-{env}` with the image built from task 4, building `frontend` with `VITE_AUTH_REQUIRED=true`, `VITE_EVAL_ENABLED=false`, `VITE_AUDIT_URL` and Firebase vars, then `firebase deploy --only hosting:admin-staging` or `hosting:admin`. Staging on push to `main` touching `admin/ frontend/ engines/ protocols/`; prod by manual dispatch with approval. PR CI gains an `admin/` test job; blocking eval jobs stay skipped.
Done when: actionlint passes; a real staging run deploys service and site and its smoke (anonymous call returns 401, not 5xx) passes; the revision carries `GIT_SHA`; a PR touching `admin/` runs the new test job; the existing `frontend` and `eaudit` jobs stay green; no JSON keys used.

## Task 11 — Staging verification
What it is / what it means: prove the acceptance behaviour on real staging, including the settled timeout question (PRD R5, AC1-6; resolved: confirm on staging).
What changes at a high level: run the checks and record results: allowlisted login with no MFA step, non-listed account sees the 403 screen, unverified-email token refused; an audit of a 60-100 s fixture completes through the direct Cloud Run URL; record the Hosting-to-Cloud-Run timeout and header pass-through measurement (informational; direct URL stays the design); paudit on the MITI synthetic fixture returns a schema-valid result and renders in the tab; the deployed bundle has no Eval tab and makes no eval calls; repo and image contain no real data.
Done when: each check has a recorded result (in the ADR draft or PR notes); the measured timeout is written down; fixing any failure ends with the failing test re-run green; `frontend` and `eaudit` CI jobs green.

## Task 12 — Docs: `backend-api.md` and ADR 0023
What it is / what it means: the written record (PRD R10, AC7).
What changes at a high level: add an "Admin deployment" section to `docs/reference/backend-api.md` (auth, bearer header, CORS headers, the paudit and fixtures routes, env vars, deadline); write `docs/decisions/0023-admin-deployment-and-auth.md` with D1-D9 headlines and the task 11 measurements. `eval-api.md` is not edited.
Done when: every env var, route and header in the doc was checked against the code or a staging run; the repo docs check, if any, passes; no edits to `eval-api.md`.

## Task 13 — Prod flip, domain, deploy, acceptance sweep
What it is / what it means: go live on `admin.onolys.com` and tick the acceptance criteria (PRD R1, R9, AC1-7). Owner steps: DNS records, prod allowlist emails, approve the prod dispatch.
What changes at a high level: apply `admin_enabled=true` for prod (admin domain, service, SA, secret); seed `admin-allowed-emails-prod`; Tejit adds the DNS records SP06 prints; run `deploy-admin.yml` for prod via dispatch with approval; walk AC1-7 and record evidence.
Done when: domain verified and certificate active; `https://admin.onolys.com` loads the login gate and an allowlisted login reaches the review UI and paudit tab; a non-listed account gets the 403 screen; prod anonymous API call gets 401; second `terraform plan` empty; AC1-7 each have a recorded result.

## Owner steps
Owner-only (Tejit), from the PRD Manual steps:
1. Provide the admin allowlist emails for staging and prod (value of secret `admin-allowed-emails-{env}`) (tasks 9, 13).
2. Add DNS records for `admin.onolys.com` from SP06's output after the Hosting custom domain exists (task 13). The authorised domains are set by SP06 Terraform. No MFA setup.
3. Approve the prod `deploy-admin.yml` dispatch in the `production` GitHub environment (task 13).
4. Supply paudit coder ratings when available; real data stays out of the repo and images (not a blocker).
