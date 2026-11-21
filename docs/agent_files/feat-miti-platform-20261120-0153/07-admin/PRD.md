---
status: draft
summary: AFTER LAUNCH (r7), not part of v1. Deploy today's eaudit review UI plus a new paudit tab as admin.onolys.com behind Identity Platform sign-in limited to an email allowlist (no MFA), with one Cloud Run service (`admin-backend`) and an admin-only POST /v1/paudit; the eval server/Eval tab is not deployed in v1.
date: 2026-11-20
---
# PRD: SP07 admin.onolys.com — gated review UI + paudit tab

> **After launch (r7).** This whole sub-project is cut from v1 (Tejit, audit round 7, 2026-11-20) and is built after launch; no `dev-tasks` for it until then. Until it exists, results are inspected with `python -m paudit.cli` locally and the run artifacts in GCS (`{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json`, SP04 R7). The text below is the design to pick up later.

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP01 (`engines/` paths, `onolys_core`), SP02 (paudit API + result schema), SP06 (project, SAs, buckets, deploy workflows, DNS) · Owns: `admin/**` (new: `auth/` shared verifier, `backend/` gateway + Dockerfile), `frontend/src/{products.ts,App.tsx,config.ts,auth/**,paudit/**,transport/**}` + `frontend/firebase.json`, `.github/workflows/deploy-admin.yml`, root `pyproject.toml` (workspace members `admin/*`, additive), `docs/reference/backend-api.md` (auth/deploy section), `docs/decisions/0023-admin-deployment-and-auth.md`

## TL;DR
Admin = static React app on Firebase Hosting site `onolys-admin` (target `admin`) plus **one** Cloud Run service, `admin-backend` (eaudit + new admin-only `POST /v1/paudit`; full name `onolys-admin-backend-{env}` per SP06 R12). `admin.onolys.com` = today's eaudit review UI + the new paudit tab only. Access = Identity Platform sign-in restricted to an email allowlist Tejit provides (verified email + allowlist, enforced server-side by a shared ASGI auth layer); **no two-factor/MFA** [RESOLVED: Tejit 2026-11-20 r6]. Local dev is unchanged (auth off unless an env var turns it on). The eval server/Eval tab, `admin-eval` service, GCS FUSE volume and admin data bucket are **not deployed in v1** [DEFERRED: eval is not a priority and may break (Tejit r6)]. The browser calls audit/paudit **directly** on the Cloud Run URL (Hosting rewrites cap at 60 s; audits run up to 100 s; async API elsewhere keeps requests short).

## Problem
- The review UI only runs on localhost. (The eval server stays local-only, has no auth by design and refuses non-loopback hosts; it is not deployed in v1. [verified: `docs/reference/eval-api.md`, `server/guards.py`])
- Platform work (paudit, MITI fixtures, Tejit's real transcripts) needs a shared, internal place to run and judge engines without exposing clinical text.
- The registry has only `eaudit`; no way to try paudit. [verified: `frontend/src/products.ts`]

## Goals / Non-Goals
**Goals:** internal-only, login-gated admin at `admin.onolys.com` (+ staging); every non-public route authenticated server-side; paudit runnable from the UI on a pasted/fixture transcript; deploys via SP06 workflows; local dev untouched.
**Non-goals:** deploying the eval server/Eval tab (deferred); MFA; IAP/load balancer; tenant separation; user management UI; paudit eval runs (see D7); changing eaudit's contract, `/v1/audit` behaviour or the eval API shape; public access; moving admin to its own repo (kept possible).

## Requirements
**R1 Hosting.** Firebase Hosting sites `onolys-admin` (target `admin`, custom domain `admin.onolys.com`) and `onolys-admin-staging` (target `admin-staging`, default `*.web.app` only), created by SP06, serve `frontend/dist`. SPA fallback only: no `/v1` and no `/eval-api` rewrite (R5). The deployed build hides the Eval tab and makes no eval calls (build flag `VITE_EVAL_ENABLED`, set to `false` in the deployed build; default unchanged for local dev). Headers like SP05 (CSP with `connect-src` for the `admin-backend` Cloud Run URL + Identity Platform, `no-referrer`, `nosniff`, `frame-ancestors 'none'`, no-cache on HTML).
**R2 Login gate (frontend).** `frontend/src/auth/` (`firebase/auth` only): email/password sign-in and Google sign-in (both subject to the server-side allowlist), no sign-up screen, no MFA enrollment or challenge, sign-out. Gate renders only when `VITE_AUTH_REQUIRED=true`; local dev and `VITE_MOCK` skip it. `transport/` attaches `Authorization: Bearer <ID token>` through one injected provider; 401 → one forced refresh, then login; 403 → "not on the admin list" screen. `authDomain = admin.onolys.com`.
**R3 Server auth (`admin/auth`, package `onolys_admin_auth`).** ASGI middleware used by `admin-backend` (kept as a package so the eval server can reuse it later). Accepts an Identity Platform ID token: signature/`aud`=project/`iss`/expiry via google-auth, `email_verified`, `email` ∈ `ADMIN_ALLOWED_EMAILS` (Secret Manager `admin-allowed-emails-{env}` via secret ref, comma list, case-insensitive, supplied by Tejit). No second-factor claim is required. Preflight `OPTIONS` handled before auth (CORS: exact origins from `ADMIN_CORS_ORIGINS`, headers `authorization,content-type`). Failures: 401 / 403 with a small `{error:{code,message}}` body; no token or email in logs; allowlist empty ⇒ deny all and fail startup when `ADMIN_AUTH=on`. Off (`ADMIN_AUTH=off`) is refused unless `ENV=local|test`.
**R4 Gateway (`admin/backend`).** FastAPI parent app: auth middleware + CORS; routes `POST /v1/paudit`, `GET /v1/paudit/fixtures`; mounts the unmodified eaudit app for `/v1/audit` and its health. `POST /v1/paudit` body `{transcript, pack:"miti@4.2.1", params:{speaker_map:{subject}, change_goal, coded_span?{from_s,to_s}, language?, n_runs?}}` (the SP02 R2 params; `speaker_map` and `change_goal` are required there) → SP02 `PauditResult` (+ `run_info`); sync, deadline `ADMIN_PAUDIT_DEADLINE_S` (default 100), size limit like eaudit, contract-style 4xx/504 bodies. `GET …/fixtures` lists/serves the pack's synthetic fixtures only, each with ready-to-run `params`. [RESOLVED: admin-only `POST /v1/paudit`; the public API exposes paudit only via sessions/runs (reconcile pass)] `admin/auth` and `admin/backend` are uv workspace members (root `pyproject.toml` globs `admin/*`, SP01 R8).
**R5 Timeouts.** [RESOLVED: Hosting→Cloud Run header pass-through/timeout: confirm on staging; the async API keeps requests short (Tejit 2026-11-20 r6)] Hosting→Cloud Run rewrites have a 60 s request limit (Firebase docs; re-verify on staging) while audit/paudit deadlines are 100 s. So the UI calls `admin-backend` directly (`VITE_AUDIT_URL`, already supported by `config.ts`) with CORS + bearer token; Cloud Run request timeout 130 s (> deadline + grace); SP06 R12 provisions it with the `allUsers` invoker and `ADMIN_CORS_ORIGINS` [RESOLVED: SP06 lists CORS + public invoker for admin-backend, auth enforced in-app (reconcile pass)].
**R6 Eval server deploy.** [DEFERRED: eval server/Eval tab not deployed in v1; the harness is not a priority and may break (Tejit 2026-11-20 r6)] No `eval/Dockerfile`, no `admin-eval` service, no `IAUDIT_EVAL_BASE_PATH`/`IAUDIT_EVAL_ALLOWED_HOSTS`/`IAUDIT_BACKEND_AUTH`/`IAUDIT_EVAL_DATASETS_DIR` changes; `eval/` code is untouched by this SP.
**R7 Eval storage.** [DEFERRED: no GCS FUSE volume and no `onolys-admin-data-{env}` bucket in v1; the GCS FUSE items and the eval-probe-timeout item are moot (Tejit 2026-11-20 r6)] Real data (Tejit's transcripts, licensed sets) must still never be committed or baked into an image; SP02's paudit data follows the same rule.
**R8 paudit tab.** `PRODUCTS` gains `{id:"paudit", label:"paudit"}`; `App.tsx` maps product id → view component (replaces the eaudit-only branch). `frontend/src/paudit/`: transcript paste/upload (JSON `Transcript`) or "Load fixture" (prefills params); pack field (default `miti@4.2.1`); clinician speaker (`speaker_map.subject`, dropdown of the transcript's speakers) and change goal (both required by paudit); optional coded span (`from_s`/`to_s`); n_runs; Run → table of utterances with code + quote + rationale, counts, summary scores vs reference levels, four globals with cited lines, warnings, `run_info`. Mock mode ships one sample result. TS types hand-written and checked against `engines/paudit/schemas/paudit-result.schema.json` by a vitest (pattern of `eval-schema.test.ts`). No transcript text in URLs, logs or storage (state in memory only).
**R9 CI/CD.** `deploy-admin.yml` calls SP06's reusable `_deploy-cloudrun.yml` (inputs `env`, `service`, `image`; WIF `deployer-{env}`) for `onolys-admin-backend-{env}` (image built here from `admin/backend/Dockerfile`), builds `frontend` with `VITE_*` and runs `firebase deploy --only hosting:admin-staging` / `hosting:admin`. Staging on push to `main` touching `admin/ frontend/ engines/ protocols/`; prod by manual dispatch with approval. PR CI additionally runs `admin/` tests. Eval-related CI jobs that block may be disabled/skipped (eval is not a priority; SP01).
**R10 Docs.** `backend-api.md`: add "Admin deployment" (auth, CORS headers, paudit route). ADR 0023 records the decisions below. `eval-api.md` is not edited (eval not deployed).

## Architecture
```
Browser admin.onolys.com ── Firebase Hosting `admin` (static dist, SPA fallback)
  ├─ Identity Platform (sign-in; allowlist enforced server-side, no MFA)
  └─ direct HTTPS + Bearer ───► Cloud Run admin-backend [auth mw + CORS]
                                     ├─ /v1/audit  (eaudit app, unchanged)
                                     └─ /v1/paudit (paudit.run, in-process; Claude Sonnet via ANTHROPIC_API_KEY)
Secret `admin-allowed-emails-{env}` → `ADMIN_ALLOWED_EMAILS`. SA (SP06 R9): `admin-backend-{env}` (secret accessor). Eval server: not deployed in v1.
```

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Service split | One service `admin-backend`; eval server deferred | Two services (`admin-eval` too); one combined service | Eval is not a v1 priority and may break (Tejit r6); it stays standalone locally |
| D2 | Audit/paudit routing | Browser direct to Cloud Run + CORS | Hosting `/v1` rewrite; cut deadline to <60 s | Rewrite cap 60 s < 100 s deadline; changing deadlines alters eaudit behaviour |
| D3 | Auth placement | Shared ASGI middleware in `admin/auth`, eaudit and eval code untouched | Auth inside eaudit/eval behind env flag | Keeps engines clean; local dev identical; one tested verifier. Reconciles eval "no auth by design" (auth is the deployment's, not the server's) |
| D4 | Allowlist, no MFA | Email allowlist in Secret Manager + `email_verified`; same Identity Platform project/users as app | Separate tenant for admin; IAP; TOTP MFA | Locked brief (no IAP/LB); Tejit r6: no MFA anywhere. App has open sign-up, so allowlist + verified email are both required; tenant split deferred |
| D5 | Sign-in providers | Email/password and Google, both gated by the allowlist | MFA of any kind | No MFA (Tejit r6), so Google sign-in needs no special handling |
| D6 | Eval storage | [DEFERRED] not deployed in v1 | GCS FUSE volume; GCS adapter | Eval server deferred (Tejit r6) |
| D7 | paudit eval | Defer; tab is single-run only. `eval/datasets/paudit/` (SP02) stays adapter-only | Generalise eval client to per-product endpoint | Eval client is hard-wired to `POST /v1/audit` + audit contract validation [verified: `client.py:125`]; needs a product-aware engine, beyond minimal scope |
| D8 | Environments | Staging + prod services/buckets/sites, one project | Prod only | Matches brief |
| D9 | Timing | Whole sub-project After launch; until then `python -m paudit.cli` locally + run artifacts in GCS | Build the admin site for v1 | Owner-approved cut: not needed by the first early-access users. r7 audit (2026-11-20) |

## Manual steps (Tejit)
- DNS records for `admin.onolys.com` (SP06 supplies exact values) after the Hosting custom domain is added.
- Provide the admin allowlist emails (value of secret `admin-allowed-emails-{env}`); the authorized domains (`admin.onolys.com`, staging `*.web.app`) are set by SP06's Terraform (R4). No MFA setup.
- Supply paudit coder ratings when available (real data stays out of the repo).

## Risks
| Risk | Mitigation |
|---|---|
| Open sign-up in app lets anyone create a user in the same project | Allowlist is server-side and mandatory; email verified; admin UI has no sign-up |
| Real clinical transcripts pasted into the paudit tab | Admin-only, in-memory, no logging of text; admin-backend only, nothing stored; tab shows a "do not paste real PHI until BAA" note [RESOLVED: not a blocker; admin is internal-only (staff allowlist), separate from what users see; legal/BAA is Tejit's; keep engineering defaults (Tejit 2026-11-20)] |

## Open Questions
- [RESOLVED: no MFA anywhere; admin = Identity Platform sign-in + email allowlist Tejit provides (Tejit 2026-11-20 r6)] The MFA-for-Google-sign-in question is moot.
- [RESOLVED: moot, eval server not deployed in v1 (Tejit 2026-11-20 r6)] Eval start/resume probes <60 s through the Hosting rewrite; GCS FUSE spike result.
- [RESOLVED: confirm on staging; async API keeps requests short (Tejit 2026-11-20 r6)] Exact Hosting→Cloud Run timeout and header pass-through.
- [RESOLVED: aligned to SP06 R9/R11/R12/R13 names ((reconcile pass))] Hosting sites `onolys-admin`/`onolys-admin-staging`, service `onolys-admin-backend-{env}`, SA `admin-backend-{env}`, reusable `_deploy-cloudrun.yml` (the eval service and admin data bucket are deferred).
- [DEFERRED: Tejit r6] Eval server/Eval tab deployment (`admin-eval`, GCS FUSE, admin data bucket).
- [DEFERRED] paudit eval runs; separate Identity Platform tenant; moving `admin/`+`frontend/`+`eval/` to their own repo.
- [RESOLVED: yes] paudit exposed over HTTP only as an admin route (answers SP02 [OPEN]; reconcile pass).

## Acceptance Criteria
1. Unauthenticated, non-allowlisted or unverified-email tokens get 401/403 on every `admin-backend` route (tests per case, incl. expired and wrong-audience); an allowlisted, verified token succeeds (no MFA claim needed).
2. With `ADMIN_AUTH` unset locally, `scripts/dev.sh` flows, `/v1/audit`, the local eval server and UI behave exactly as before; existing frontend and eaudit suites pass (eval suite best-effort).
3. `ADMIN_AUTH=off` refuses to start unless `ENV=local|test`; empty allowlist refuses to start with auth on.
4. Staging: allowlisted login works without any MFA step; non-listed account sees the 403 screen; an audit of a 60–100 s fixture completes via the direct URL.
5. `POST /v1/paudit` on the MITI synthetic fixture returns a schema-valid result; the paudit tab renders codes, counts, summaries, globals, warnings in mock and live modes.
6. The deployed build shows no Eval tab and makes no eval calls; no dataset/transcript content from real data is present in the repo or image.
7. `deploy-admin.yml` deploys staging on merge and prod on approved dispatch; `backend-api.md` and ADR 0023 are updated.
