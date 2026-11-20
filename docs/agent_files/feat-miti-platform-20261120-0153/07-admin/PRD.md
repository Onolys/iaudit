---
status: draft
summary: Deploy today's review UI + eval server as admin.onolys.com behind Identity Platform (email allowlist + TOTP MFA) with two Cloud Run services, GCS-mounted eval storage, an admin-only POST /v1/paudit, and a minimal paudit tab.
date: 2026-11-20
---
# PRD: SP07 admin.onolys.com — gated review UI, eval server, paudit tab

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP01 (`engines/` paths, `onolys_core`), SP02 (paudit API + result schema), SP06 (project, SAs, buckets, deploy workflows, DNS) · Owns: `admin/**` (new: `auth/` shared verifier, `backend/` gateway + Dockerfile), `eval/Dockerfile`, small additive edits in `eval/src/iaudit_eval/{client,paths,server/guards,server/app}.py`, `frontend/src/{products.ts,App.tsx,config.ts,auth/**,paudit/**,transport/**}` + `frontend/firebase.json`, `.github/workflows/deploy-admin.yml`, root `pyproject.toml` (workspace members `admin/*`, additive), `docs/reference/{eval-api,backend-api}.md` (auth/deploy sections), `docs/decisions/0023-admin-deployment-and-auth.md`

## TL;DR
Admin = static React app on Firebase Hosting site `onolys-admin` (target `admin`) plus **two** Cloud Run services: `admin-backend` (eaudit + new admin-only `POST /v1/paudit`) and `admin-eval` (eval server); full names `onolys-admin-backend-{env}` / `onolys-admin-eval-{env}` per SP06 R12. Both sit behind one shared ASGI auth layer: Identity Platform ID token, `email_verified`, email in allowlist, MFA claim present. Local dev is unchanged (auth off unless an env var turns it on). Eval run data goes to a private GCS bucket via one Cloud Run GCS volume at `/data`; real datasets never enter the repo. The browser calls audit/paudit **directly** on the Cloud Run URL (Hosting rewrites cap at 60 s; audits run up to 100 s).

## Problem
- The review UI and eval server only run on localhost; eval server has no auth by design and refuses non-loopback hosts. [verified: `docs/reference/eval-api.md` "no CORS middleware or authentication", `server/guards.py` Host/peer checks]
- Platform work (paudit, MITI fixtures, Tejit's real transcripts) needs a shared, internal place to run and judge engines without exposing clinical text.
- Cloud Run disk is ephemeral; eval keeps runs/reports/data on the local filesystem. [verified: `paths.py` `runs_dir/data_dir/datasets_dir`]
- The registry has only `eaudit`; no way to try paudit. [verified: `frontend/src/products.ts`]

## Goals / Non-Goals
**Goals:** internal-only, login-gated admin at `admin.onolys.com` (+ staging); every non-public route authenticated server-side; eval history survives restarts; paudit runnable from the UI on a pasted/fixture transcript; deploys via SP06 workflows; local dev untouched.
**Non-goals:** IAP/load balancer; tenant separation; user management UI; paudit eval runs (see D7); changing eaudit's contract, `/v1/audit` behaviour or the eval API shape; public access; moving admin to its own repo (kept possible).

## Requirements
**R1 Hosting.** Firebase Hosting sites `onolys-admin` (target `admin`, custom domain `admin.onolys.com`) and `onolys-admin-staging` (target `admin-staging`, default `*.web.app` only), created by SP06, serve `frontend/dist`. Rewrite `/eval-api/**` → Cloud Run `onolys-admin-eval-{env}`; SPA fallback last. No `/v1` rewrite (R5). Headers like SP05 (CSP with `connect-src` for the two Cloud Run URLs + Identity Platform, `no-referrer`, `nosniff`, `frame-ancestors 'none'`, no-cache on HTML).
**R2 Login gate (frontend).** `frontend/src/auth/` (`firebase/auth` only): email/password sign-in (+ Google if D5 spike passes), no sign-up screen, TOTP enrollment screen on first login, TOTP challenge on later logins, sign-out. Gate renders only when `VITE_AUTH_REQUIRED=true`; local dev and `VITE_MOCK` skip it. `transport/` and `eval/evalApi` attach `Authorization: Bearer <ID token>` through one injected provider; 401 → one forced refresh, then login; 403 → "not on the admin list" screen. `authDomain = admin.onolys.com`.
**R3 Server auth (`admin/auth`, package `onolys_admin_auth`).** ASGI middleware, used by both services. Accepts, in order: (a) Identity Platform ID token — signature/`aud`=project/`iss`/expiry via google-auth, `email_verified`, `email` ∈ `ADMIN_ALLOWED_EMAILS` (Secret Manager `admin-allowed-emails-{env}` via secret ref, comma list, case-insensitive), `firebase.sign_in_second_factor` present; (b) on `admin-backend` only: Google OIDC token from the `admin-eval-{env}` SA (audience = backend URL, exact SA email in `ADMIN_SERVICE_ACCOUNTS`, a plain env var set by SP06 Terraform). Preflight `OPTIONS` handled before auth (CORS: exact origins from `ADMIN_CORS_ORIGINS`, headers `authorization,content-type`). Failures: 401 / 403 with a small `{error:{code,message}}` body; no token or email in logs; allowlist empty ⇒ deny all and fail startup when `ADMIN_AUTH=on`. Off (`ADMIN_AUTH=off`) is refused unless `ENV=local|test`.
**R4 Gateway (`admin/backend`).** FastAPI parent app: auth middleware + CORS; routes `POST /v1/paudit`, `GET /v1/paudit/fixtures`; mounts the unmodified eaudit app for `/v1/audit` and its health. `POST /v1/paudit` body `{transcript, pack:"miti@4.2.1", params:{speaker_map:{subject}, change_goal, coded_span?{from_s,to_s}, language?, n_runs?}}` (the SP02 R2 params; `speaker_map` and `change_goal` are required there) → SP02 `PauditResult` (+ `run_info`); sync, deadline `ADMIN_PAUDIT_DEADLINE_S` (default 100), size limit like eaudit, contract-style 4xx/504 bodies. `GET …/fixtures` lists/serves the pack's synthetic fixtures only, each with ready-to-run `params`. [RESOLVED: admin-only `POST /v1/paudit`; the public API exposes paudit only via sessions/runs (reconcile pass)] `admin/auth` and `admin/backend` are uv workspace members (root `pyproject.toml` globs `admin/*`, SP01 R8).
**R5 Timeouts.** Hosting→Cloud Run rewrites have a 60 s request limit (Firebase docs; re-verify on staging) while audit/paudit deadlines are 100 s. So the UI calls `admin-backend` directly (`VITE_AUDIT_URL`, already supported by `config.ts`) with CORS + bearer token; Cloud Run request timeout 130 s (> deadline + grace); SP06 R12 provisions it with the `allUsers` invoker and `ADMIN_CORS_ORIGINS` [RESOLVED: SP06 lists CORS + public invoker for admin-backend, auth enforced in-app (reconcile pass)]. Eval API calls are short and use the Hosting rewrite (`VITE_EVAL_API_BASE=/eval-api`, existing default); fallback is the direct URL, one env change.
**R6 Eval server deploy.** `eval/Dockerfile` (own `uv.lock`, no engines). `onolys-admin-eval-{env}` (SP06 R12): `max=1` instance, `min=1` in prod and 0 in staging, CPU always allocated (runs are background tasks), concurrency 20. Additive env-driven code changes only: `IAUDIT_EVAL_BASE_PATH=/eval-api` (routes served under a prefix because Hosting cannot strip it), `IAUDIT_EVAL_ALLOWED_HOSTS` (extra exact Host values; Host/Origin guards stay), `IAUDIT_BACKEND_AUTH=google-oidc` (client attaches an OIDC token for `IAUDIT_BACKEND_URL`), `IAUDIT_EVAL_DATASETS_DIR` (optional override of `paths.datasets_dir()`, default unchanged; set to `/app/eval/datasets` so in-image adapters survive `IAUDIT_EVAL_HOME=/data/eval`). Defaults and local behaviour unchanged; `test_no_backend_import_in_eval` still passes.
**R7 Eval storage.** Private bucket `onolys-admin-data-{env}` (SP06 R6/R12: uniform access, no public ACL, soft-delete 0, versioning off, only the `admin-eval-{env}` SA), mounted as one Cloud Run GCS volume at `/data` with `IAUDIT_EVAL_HOME=/data/eval` (runs in `/data/eval/runs`, real data in `/data/eval/data`); `datasets/` adapters + synthetic sets stay in the image via `IAUDIT_EVAL_DATASETS_DIR=/app/eval/datasets` [verified: `paths.py` derives runs/data/datasets from `IAUDIT_EVAL_HOME`]. Real data (Tejit's transcripts, licensed sets) is uploaded to `data/` by hand/script, never committed; SP02's paudit data follows the same rule. [RESOLVED: aligned to SP06's `/data` mount and `onolys-admin-data-{env}` (reconcile pass)]
**R8 paudit tab.** `PRODUCTS` gains `{id:"paudit", label:"paudit"}`; `App.tsx` maps product id → view component (replaces the eaudit-only branch). `frontend/src/paudit/`: transcript paste/upload (JSON `Transcript`) or "Load fixture" (prefills params); pack field (default `miti@4.2.1`); clinician speaker (`speaker_map.subject`, dropdown of the transcript's speakers) and change goal (both required by paudit); optional coded span (`from_s`/`to_s`); n_runs; Run → table of utterances with code + quote + rationale, counts, summary scores vs reference levels, four globals with cited lines, warnings, `run_info`. Mock mode ships one sample result. TS types hand-written and checked against `engines/paudit/schemas/paudit-result.schema.json` by a vitest (pattern of `eval-schema.test.ts`). No transcript text in URLs, logs or storage (state in memory only).
**R9 CI/CD.** `deploy-admin.yml` calls SP06's reusable `_deploy-cloudrun.yml` (inputs `env`, `service`, `image`; WIF `deployer-{env}`) for `onolys-admin-backend-{env}` and `onolys-admin-eval-{env}` (images built here from `admin/backend/Dockerfile` and `eval/Dockerfile`), builds `frontend` with `VITE_*` and runs `firebase deploy --only hosting:admin-staging` / `hosting:admin`. Staging on push to `main` touching `admin/ eval/ frontend/ engines/`; prod by manual dispatch with approval. PR CI additionally runs `admin/` tests.
**R10 Docs.** `eval-api.md`: replace "no authentication" with "the server itself stays auth-free and loopback-only locally; when deployed it is reachable only through the admin auth layer"; add the three env vars. `backend-api.md`: add "Admin deployment" (auth, CORS headers, paudit route). ADR 0023 records D1–D7.

## Architecture
```
Browser admin.onolys.com ── Firebase Hosting `admin` (static dist, /eval-api/** rewrite)
  ├─ Identity Platform (sign-in + TOTP)
  ├─ /eval-api/** ─► Cloud Run admin-eval  [auth mw] ► eval server ─► GCS volumes (runs/, data/)
  │                                              └─ OIDC (eval SA) ─┐
  └─ direct HTTPS + Bearer ───► Cloud Run admin-backend [auth mw + CORS] ◄┘
                                     ├─ /v1/audit  (eaudit app, unchanged)
                                     └─ /v1/paudit (paudit.run, in-process)
Secret `admin-allowed-emails-{env}` → `ADMIN_ALLOWED_EMAILS`; `ADMIN_SERVICE_ACCOUNTS` is a plain env var. SAs (SP06 R9): `admin-backend-{env}` (Vertex, secret accessor), `admin-eval-{env}` (bucket objectAdmin; no invoker role needed: app-level auth).
```

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Service split | Two services: `admin-backend`, `admin-eval` | One combined service (mount eval in gateway) | Eval is standalone with its own lock and an import-boundary test; different resource profile (CPU-always, 1 instance vs scale-to-zero); combined needs a messy dependency graph |
| D2 | Audit/paudit routing | Browser direct to Cloud Run + CORS | Hosting `/v1` rewrite; cut deadline to <60 s | Rewrite cap 60 s < 100 s deadline; changing deadlines alters eaudit behaviour |
| D3 | Auth placement | Shared ASGI middleware in `admin/auth`, eaudit and eval code untouched | Auth inside eaudit/eval behind env flag | Keeps engines clean; local dev identical; one tested verifier. Reconciles eval "no auth by design" (auth is the deployment's, not the server's) |
| D4 | Allowlist + MFA | Email allowlist in Secret Manager + `email_verified` + second-factor claim; same Identity Platform project/users as app | Separate tenant for admin; IAP | Locked brief (no IAP/LB). App has open sign-up, so allowlist + verified email + MFA claim are all required; tenant split deferred |
| D5 | MFA type / providers | TOTP; email/password first, Google only if its token carries the second-factor claim | SMS MFA; Google-only | TOTP needs no SMS billing; federated Google may skip MFA, so it cannot count unless proven |
| D6 | Eval storage | GCS FUSE volume mounts for `runs/` and `data/` | New GCS adapter in `store.py`; local-only/ephemeral admin eval | Zero path/code change; durable; local-only loses run history. Spike first (R7 [OPEN]) |
| D7 | paudit eval | Defer; tab is single-run only. `eval/datasets/paudit/` (SP02) stays adapter-only | Generalise eval client to per-product endpoint | Eval client is hard-wired to `POST /v1/audit` + audit contract validation [verified: `client.py:125`]; needs a product-aware engine, beyond minimal scope |
| D8 | Environments | Staging + prod services/buckets/sites, one project | Prod only | Matches brief; staging gets `min-instances=0` for eval to save cost |

## Manual steps (Tejit)
- DNS records for `admin.onolys.com` (SP06 supplies exact values) after the Hosting custom domain is added.
- Provide the allowlist emails (value of secret `admin-allowed-emails-{env}`); TOTP MFA and the authorized domains (`admin.onolys.com`, staging `*.web.app`) are set by SP06's Terraform (R4).
- Upload real transcripts/datasets to `onolys-admin-data-{env}` under `eval/data/`; supply paudit coder ratings when available.

## Risks
| Risk | Mitigation |
|---|---|
| Open sign-up in app lets anyone create a user in the same project | Allowlist is server-side and mandatory; email verified; MFA claim; admin UI has no sign-up |
| GCS FUSE lacks semantics eval relies on (atomic rename, `chmod`, partial writes) | Day-1 spike running a synthetic eval run on the mount; fallback: local disk + copy to bucket on run completion and restore at boot |
| `min=1` CPU-always eval instance costs a fixed amount per month | Prod only; staging scale-to-zero; revisit if unused |
| Hosting strips/changes `Authorization` or caches `/eval-api` | Verify on staging (same check as SP05); fallback direct URL + CORS |
| Real clinical transcripts pasted into the paudit tab | Admin-only, in-memory, no logging of text; bucket private; tab shows a "do not paste real PHI until BAA" note [RESOLVED: not a blocker; admin is internal-only (staff allowlist), separate from what users see; legal/BAA is Tejit's; keep engineering defaults (Tejit 2026-11-20)] |

## Open Questions
- [OPEN] Does Identity Platform MFA apply to Google sign-in? Default: email/password + TOTP only until a token with `sign_in_second_factor` is observed.
- [OPEN] Do eval start/resume probes finish in <60 s through the Hosting rewrite? Default: rewrite for `/eval-api`, direct URL if not.
- [OPEN] GCS FUSE spike result (R7/D6).
- [OPEN] Exact Hosting→Cloud Run timeout and header pass-through; confirm on staging.
- [RESOLVED: aligned to SP06 R9/R11/R12/R13 names ((reconcile pass))] Hosting sites `onolys-admin`/`onolys-admin-staging`, services `onolys-admin-{backend,eval}-{env}`, SAs `admin-{backend,eval}-{env}`, bucket `onolys-admin-data-{env}`, reusable `_deploy-cloudrun.yml`.
- [DEFERRED] paudit eval runs; separate Identity Platform tenant; moving `admin/`+`frontend/`+`eval/` to their own repo.
- [RESOLVED: yes] paudit exposed over HTTP only as an admin route (answers SP02 [OPEN]; reconcile pass).

## Acceptance Criteria
1. Unauthenticated, non-allowlisted, unverified-email, or no-MFA tokens get 401/403 on every `admin-backend` and `admin-eval` route (tests per case, incl. expired and wrong-audience); allowlisted + MFA token succeeds.
2. With `ADMIN_AUTH` unset locally, `scripts/dev.sh` flows, `/v1/audit`, eval server and UI behave exactly as before; existing frontend, eval and eaudit suites pass.
3. `ADMIN_AUTH=off` refuses to start unless `ENV=local|test`; empty allowlist refuses to start with auth on.
4. Staging: login with TOTP enrolls and challenges; non-listed account sees the 403 screen; an audit of a 60–100 s fixture completes via the direct URL.
5. `POST /v1/paudit` on the MITI synthetic fixture returns a schema-valid result; the paudit tab renders codes, counts, summaries, globals, warnings in mock and live modes.
6. An eval run survives an `admin-eval` restart (history and reports intact); no dataset/transcript content from real data is present in the repo or image.
7. `deploy-admin.yml` deploys staging on merge and prod on approved dispatch; `eval-api.md`, `backend-api.md` and ADR 0023 are updated.
