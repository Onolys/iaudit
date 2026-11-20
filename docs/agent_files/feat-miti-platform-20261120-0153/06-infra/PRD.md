---
status: draft
summary: Terraform-managed GCP project `onolys` (staging + prod in us-central1): Identity Platform, two Firestore DBs, private GCS, Cloud Tasks, Cloud Run api/worker/admin, Firebase Hosting with same-origin /v1 rewrite, WIF-based GitHub Actions deploys, budget alert and DNS list for Tejit.
date: 2026-11-20
---
# PRD: SP06 infra — GCP resources, hosting/domains, CI/CD, config

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: none (Phase 1); satisfies SP04 "SP06 interface", SP05 manual steps, SP07 admin host needs · Owns: `infra/**` (Terraform + scripts), `.github/workflows/{deploy-staging,deploy-prod,infra-plan,web-preview,_deploy-cloudrun}.yml` (`_deploy-cloudrun.yml` is a reusable `workflow_call`, also used by SP07's `deploy-admin.yml`), root `.firebaserc`, root `firebase.json` + `firestore.rules` (Firestore only; web hosting config is SP05's `web/firebase.json`), `docs/reference/infra.md` (runbook, env var table, DNS list), `docs/decisions/0022-infra-*`

## TL;DR
One GCP project (`onolys`), one region (`us-central1`), two environments (`staging`, `prod`) provisioned by Terraform (state in a GCS bucket; no gcloud needed, runs on this machine with ADC). CI (GitHub Actions, Workload Identity Federation, no JSON keys) builds one image, deploys staging on merge to `main`, prod on a gated manual run that promotes the same image digest. `app.onolys.com` = Firebase Hosting site with `/v1/**` rewritten to Cloud Run `api` (resolves SP04 [OPEN]). Tejit's tasks: DNS records, budget amount, Google sign-in toggle, email templates, billing/Owner access.

## Problem
Nothing exists for the platform: SP04/05/07 each list resources they need, but nobody owns creating them, wiring IAM, deploying, or the DNS records. Landing already uses project `onolys` (Hosting sites `onolys`, `onolys-redirect`) [verified: `firebase hosting:sites:list --project onolys`], so new things must not disturb it. This machine has `firebase` CLI logged in, user ADC with quota project `juno-medical-clarity`, no `gcloud`/`terraform`/`docker` [verified: `which`]. Reference app simplify-med deploys with bash+gcloud in one workflow and a long-lived `GCP_SA_KEY` secret, and has no IaC [verified: `.github/workflows/deploy.yml`, no `infra/`]; we copy its api/worker one-image split and `SERVICE_MODE`, not its key handling.

## Goals / Non-Goals
**Goals:** all resources reproducible from code; staging and prod isolated by data and IAM; no long-lived deploy keys; PHI-ready controls (private buckets, no soft-delete retention, audit logs, single US residency); cost bounded by config; SP04/05/07 interfaces met exactly; idempotent re-runs.
**Non-goals:** app code, Dockerfile, Firestore index contents (SP04), web config/CSP (SP05), eval-server code (SP07), landing deploy (stays as-is), DNS edits (Tejit), HIPAA BAA/legal, load balancer/Cloud Armor, multi-region, monitoring dashboards, Cloud Scheduler jobs.

## Requirements
**R1 Provisioning.** Terraform (`google` + `google-beta` providers, version pinned; `infra/.terraform-version`). Layout: `infra/bootstrap.sh` (curl+ADC: creates versioned private state bucket `onolys-tfstate`), `infra/main.tf` (project-level: APIs, Identity Platform, Hosting sites, AR, WIF, audit config, budget), `infra/modules/environment/` (called for `staging` and `prod`: bucket, queue, SAs, Cloud Run, secrets shells, Firestore DB), `infra/scripts/{install-tools.sh,seed-secrets.py}`. Provider uses `user_project_override=true`, `billing_project="onolys"` so ADC quota project need not be switched (no gcloud). `install-tools.sh` downloads the pinned terraform binary to `~/.local/bin`. Cloud Run images are CI-owned (`lifecycle.ignore_changes` on image); initial apply uses a public placeholder image.
**R2 APIs enabled:** serviceusage, cloudresourcemanager, iam, iamcredentials, sts, run, artifactregistry, firestore, storage, cloudtasks, secretmanager, identitytoolkit, firebase, firebasehosting, firebaserules, speech, aiplatform, cloudbilling, billingbudgets, logging, monitoring.
**R3 Region.** Cloud Run, Artifact Registry, Cloud Tasks, GCS, Firestore, Vertex Gemini: `us-central1`. STT v2 Chirp 3 is only documented for multi-regions `us`/`eu`, not `us-central1` [verified: docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model, fetched 2026-11-20], so STT uses location `us` via endpoint `us-speech.googleapis.com`. This is US-resident but not one region; accepted deviation, recorded in the ADR.
**R4 Identity Platform** (Terraform `google_identity_platform_config`): email+password (min length 8, verification required by SP04 at API), open sign-up, email-enumeration protection on, TOTP MFA enabled (optional for app users; enforced for admin by SP07 via the `firebase.sign_in_second_factor` claim), authorized domains `app.onolys.com`, `admin.onolys.com`, `onolys-app.web.app`, `onolys-app-staging.web.app`, `onolys-admin.web.app`, `onolys-admin-staging.web.app`, `localhost` (site ids per R11; follow any fallback ids). Google sign-in and email templates are console steps (OAuth client cannot be created by API). One user pool for both envs; data isolation is by Firestore DB/bucket, not by user. A Firebase web app is registered per host; its public config is exported as Terraform outputs and written to GitHub vars `VITE_FIREBASE_*`; the browser API key is restricted to HTTP referrers (app hosts, localhost) and the identitytoolkit/securetoken APIs.
**R5 Firestore** (Native, `us-central1`, location is permanent): database `(default)` = prod, `staging` = staging (one project, so the DB is the env boundary). Rules: deny-all (`root firestore.rules`); indexes from `api/firestore.indexes.json` deployed to both DBs by CI via firebase-tools (`firebase.json` lists both databases). **PITR off, no scheduled backups, delete-protection on for prod** so "delete removes everything" holds; TTL policies are not used (auto-expiry deferred in SP04). Prod DB cannot be recovered after an erroneous delete: accepted v1 risk.
**R6 GCS** one private bucket per env, `onolys-audio-{env}` (prefixes for audio, rating, transcript objects are SP04's; no separate buckets for transcripts/ratings/exports, since PDF export is cut): uniform bucket-level access, public access prevention enforced, no versioning, **soft-delete retention 0** (default 7 days would defeat hard delete), Google-managed encryption, lifecycle: delete objects under `uploads/` older than 1 day, optional `expiry` hook off. CORS (PUT/HEAD, headers `Content-Type`, `x-goog-content-length-range`, max-age 3600): prod `https://app.onolys.com`; staging `https://onolys-app-staging.web.app` + `http://localhost:5173`. Hosting preview-channel hosts vary per PR, so previews run mock mode (cannot upload). Separate private buckets `onolys-admin-data-{env}` for SP07 (R12): uniform access, public access prevention, soft-delete 0, no CORS, no lifecycle, **versioning off** (real transcripts may land there and hard delete must hold) [RESOLVED: versioning off; SP07 had asked for on (reconcile pass)]. Data-access audit logs (DATA_READ, DATA_WRITE) on `storage.googleapis.com` and `firestore.googleapis.com` via `google_project_iam_audit_config`; they log resource names (uid/session ids), never content.
**R7 Cloud Tasks** queue `steps-{env}` (`us-central1`): `max_attempts=2` (one retry, per SP04 D3), min backoff 5 s, max backoff 30 s, `max_concurrent_dispatches` prod 5 / staging 2, `max_dispatches_per_second` 5. The 10-min dispatch deadline is set per task by SP04 (queue config cannot hold it).
**R8 Cloud Run** (one image, `SERVICE_MODE` env; Dockerfile is SP04's and must include ffmpeg; the same image serves api, worker; admin services use SP07's own images `admin/backend/Dockerfile` and `eval/Dockerfile`). Services per env: `onolys-api-{env}`, `onolys-worker-{env}`, and the two admin services `onolys-admin-backend-{env}`, `onolys-admin-eval-{env}` (R12).
| Service | CPU/mem | Timeout | Concurrency | Min/Max inst | Invoker |
|---|---|---|---|---|---|
| api | 1 / 1 GiB | 60 s | 80 | 0 / 10 prod, 3 staging | `allUsers` (app-level auth; needed for Hosting rewrite) |
| worker | 2 / 2 GiB | 900 s | 4 | 0 / 10 prod, 3 staging | tasks-invoker SA only |
| admin-backend | 1 / 1 GiB | 130 s | 20 | 0 / 3 | `allUsers` (app-level auth + CORS, R12) |
| admin-eval | 1 / 2 GiB, CPU always allocated | 900 s | 20 | prod 1 / 1, staging 0 / 1 | `allUsers` (app-level auth, R12) |
Request-based billing, min 0 (cold start accepted for v1). If an org policy blocks `allUsers`, fallback is a separate `api.onolys.com` domain mapping (also needs public) [OPEN].
**R9 Service accounts** (per env unless noted; least privilege, roles bound at resource level where possible):
| SA | Roles |
|---|---|
| `api-{env}` | `datastore.user` (its DB, conditioned on database name), `storage.objectAdmin` on bucket, `iam.serviceAccountTokenCreator` on itself (V4 signing), `cloudtasks.enqueuer` on queue, `iam.serviceAccountUser` on tasks-invoker, `secretmanager.secretAccessor` on its secrets |
| `worker-{env}` | `datastore.user`, `storage.objectAdmin` on bucket, `aiplatform.user`, `speech.client`, `cloudtasks.enqueuer` + `serviceAccountUser` on tasks-invoker, `secretAccessor` |
| `tasks-invoker-{env}` | `run.invoker` on worker only |
| `admin-backend-{env}` | `aiplatform.user`, `secretAccessor` on admin secrets |
| `admin-eval-{env}` | `objectAdmin` on `onolys-admin-data-{env}`; no invoker role needed (app-level auth); its identity token is the OIDC credential for calls to admin-backend (R12) |
| `deployer-staging`, `deployer-prod` | `run.developer` on its services, `iam.serviceAccountUser` on runtime SAs, `artifactregistry.writer` (staging) / `reader` (prod), Firebase Hosting admin on its sites, `firebaserules.admin` + `datastore.indexAdmin` on its DB. Prod deployer trusts only the `production` GitHub environment |
| `tf-plan` | read-only viewer, state bucket read |
`enqueuer`, `serviceAccountUser` on tasks-invoker and Storage-service-agent access are additions to SP04's list (SP04 omitted them). Staging SAs get no access to prod resources and vice versa.
**R10 Secret Manager.** Shells created by Terraform, values seeded by `infra/scripts/seed-secrets.py` (keeps values out of state): `uid-hmac-key-{env}` (random, for `uid_hash` log field), `admin-allowed-emails-{env}` (comma list of admin emails; value from Tejit; SP07 `ADMIN_ALLOWED_EMAILS`), `anthropic-api-key` (optional, empty until an alternate Claude route is used). No model keys are needed for Vertex/STT (ADC via SA). Mounted as env vars via Cloud Run secret refs.
**R11 Hosting/domains.** Firebase Hosting sites (new, alongside landing): `onolys-app` (prod; `app.onolys.com`), `onolys-app-staging` (default `*.web.app` URL only, no custom domain), `onolys-admin` (`admin.onolys.com`), `onolys-admin-staging` (default URL only). Site ids are global; fallbacks `onolys-miti-app*` if taken [OPEN]. Root `.firebaserc` targets `app`, `app-staging`, `admin`, `admin-staging`. `web/firebase.json` (SP05) has one hosting entry per target; `/v1/**` rewrites to `onolys-api-prod` (prod) and `onolys-api-staging` (staging), `us-central1`, before the SPA fallback. Custom domains created by `google_firebase_hosting_custom_domain`; Terraform output `required_dns_updates` gives exact values after apply. **Preview channels:** FirebaseExtended hosting-deploy action on SP05 PRs against the `app-staging` site (7-day expiry); PRs from forks get no secrets (repo is public).
**R12 Admin hosting (SP07 interface).** Two Cloud Run services per env, images built by SP07 (`admin/backend/Dockerfile`, `eval/Dockerfile`) and deployed by SP07's `deploy-admin.yml` through the reusable `_deploy-cloudrun.yml` (R13): `onolys-admin-backend-{env}` (eaudit app + admin-only `POST /v1/paudit`; request timeout 130 s so the 100 s audit/paudit deadline fits) and `onolys-admin-eval-{env}` (eval server; `max-instances=1`, CPU always allocated, concurrency 20; min 1 in prod, 0 in staging). Both are `allUsers`-invokable: auth is enforced in the app (Identity Platform ID token + `ADMIN_ALLOWED_EMAILS` + TOTP claim; `admin-backend` also accepts a Google OIDC token from the `admin-eval-{env}` SA, listed in `ADMIN_SERVICE_ACCOUNTS`). **CORS:** the browser calls `admin-backend` directly (Hosting rewrites cap at ~60 s, audits run up to 100 s), so Terraform sets `ADMIN_CORS_ORIGINS` (`https://admin.onolys.com` prod; `https://onolys-admin-staging.web.app` + `http://localhost:5173` staging) and the app answers preflight (Cloud Run has no CORS config); `admin-eval` is reached through the Hosting rewrite `/eval-api/**` and needs no CORS [RESOLVED: CORS + public invoker for admin-backend, auth in-app (reconcile pass)]. Hosting sites `onolys-admin` (prod, `admin.onolys.com`) and `onolys-admin-staging` (default URL only) serve `frontend/dist`; the `**`/`/eval-api/**` rewrites live in SP07's `frontend/firebase.json`. Env vars set by Terraform: `ENV`, `ADMIN_AUTH=on`, `AUTH_PROJECT`, `ADMIN_CORS_ORIGINS`, `ADMIN_SERVICE_ACCOUNTS` (admin-eval SA email), `ADMIN_ALLOWED_EMAILS` (secret ref); on admin-eval `IAUDIT_BACKEND_URL` (admin-backend URL) and `IAUDIT_BACKEND_AUTH=google-oidc`; on admin-backend `ROUTES_FILE`/`STT_PROVIDERS_FILE`/`DEFAULT_PRESET`/`VERTEX_LOCATION`. **Eval storage:** the eval server writes to the local filesystem (`IAUDIT_EVAL_HOME`, `IAUDIT_CONTRACTS_DIR`; dirs created mode 0700 [verified: `eval/src/iaudit_eval/paths.py`]). Infra mounts bucket `onolys-admin-data-{env}` as a Cloud Run GCS volume at `/data` on `admin-eval` and sets `IAUDIT_EVAL_HOME=/data/eval` (runs in `/data/eval/runs`, real data in `/data/eval/data`). [verified: `paths.py` also derives `datasets_dir()` from `IAUDIT_EVAL_HOME`, which would hide the in-image adapters/synthetic sets; SP07 adds an additive `IAUDIT_EVAL_DATASETS_DIR=/app/eval/datasets` override.] GCS FUSE has weak chmod/rename-atomicity semantics, so SP07 must either verify it works (day-1 spike) or add a storage-backed mode; persistent disk is unavailable on Cloud Run. Datasets with real session data must stay out of the repo and out of the image.
**R13 CI/CD** (Onolys/onolys; Workload Identity Federation pool+provider `github`, attribute condition `repository=='Onolys/onolys'`; deployer SAs impersonated, no JSON keys):
| Workflow | Trigger | Does |
|---|---|---|
| `infra-plan.yml` | PR touching `infra/**` | `terraform fmt/validate/plan` as `tf-plan`; apply is local/manual only in v1 |
| `deploy-staging.yml` | push `main` (after CI green) | build image once (`docker/build-push-action`), tag `sha`, push to AR; deploy api+worker to staging by digest (admin services are deployed by SP07's `deploy-admin.yml`); deploy Firestore rules/indexes to `staging` DB; build+deploy `web/` to `app-staging`; smoke `GET /v1/healthz` |
| `deploy-prod.yml` | `workflow_dispatch` (input: image sha, default latest staging-deployed) or tag `v*` | GitHub environment `production` with required reviewer (Tejit); **promotes the same digest** (no rebuild) to prod; Firestore rules/indexes to `(default)`; web to `app`; smoke test |
| `web-preview.yml` | PR touching `web/**` | preview channel on `app-staging` |
| `_deploy-cloudrun.yml` | `workflow_call` | reusable: inputs `env`, `service`, `image` (digest), `region`; impersonates `deployer-{env}` via WIF and deploys one Cloud Run service by digest; used by deploy-staging/prod and by SP07's `deploy-admin.yml` |
Concurrency group per environment, `cancel-in-progress: false`. Landing repo keeps its own `FIREBASE_SERVICE_ACCOUNT` workflow, untouched [verified: `onolys-landing/.github/workflows/ci.yml`]. Artifact Registry repo `onolys` with cleanup policy (keep 20 recent, delete untagged >14 d).
**R14 Env vars / config.** Per service, set by Terraform (non-secret) and documented in `docs/reference/infra.md`; names follow SP04's `api/.env.example`:
| Var | api | worker | Notes |
|---|---|---|---|
| `ENV` (`staging`/`prod`), `SERVICE_MODE` (`api`/`worker`), `GCP_PROJECT`, `REGION` | yes | yes | |
| `FIRESTORE_DATABASE` (`staging` or `(default)`) | yes | yes | SP04 reads it for every Firestore client [RESOLVED: accepted in SP04 (reconcile pass)] |
| `AUTH_PROJECT`, `AUDIO_BUCKET`, `CORS_ORIGINS`, `DAILY_RUN_CAP`, `ADAPTERS=real` | yes | yes | CORS: api only |
| `TASKS_QUEUE`, `TASKS_SA`, `WORKER_URL` | yes | yes | worker URL = Cloud Run URL (Terraform output), also OIDC audience |
| `STT_LOCATION=us`, `STT_ENDPOINT=us-speech.googleapis.com`, `VERTEX_LOCATION=us-central1` | | yes | |
| `ROUTES_FILE`, `STT_PROVIDERS_FILE`, `DEFAULT_PRESET` | yes | yes | point to `config/{env}/…` baked into the image; read by SP01 R3/R4 (alias `IAUDIT_LLM_ROUTES_FILE`); `DEFAULT_PRESET` picks the default of the routes file's `presets:` (SP04's allowlist) [RESOLVED: SP01 reads them (reconcile pass)] |
| `ADMIN_AUTH`, `ADMIN_CORS_ORIGINS`, `ADMIN_SERVICE_ACCOUNTS`, `ADMIN_ALLOWED_EMAILS` (secret) | admin services only | | see R12 (SP07 names) |
Model/STT params are config files in the repo (`config/staging/routes.yaml`, `config/prod/…`, SP01 route + provider format), selected by env vars. Changing a model = PR + deploy; urgent override = redeploy service with a different `ROUTES_FILE`/`DEFAULT_PRESET`. Secrets arrive via secret refs, never in files. SP01/SP04 own file contents; SP06 owns that the env vars exist and point at them.
**R15 Cost guardrails.** Budget `google_billing_budget` on the billing account: amount from `var.monthly_budget_usd` (Tejit; placeholder 50), alerts at 50/90/100% actual and 100% forecast, to a Monitoring email channel (Tejit's address). Budgets alert, they do not stop spend. Caps in infra: Cloud Run max-instances and Tasks `max_concurrent_dispatches` (R7/R8); per-user daily run cap is app-side (SP04 `DAILY_RUN_CAP`, default 20). Audit-log volume is checked after one week (Data Access logs bill by ingestion).

## Architecture
```
Browser ─ app.onolys.com ─ Firebase Hosting (site onolys-app: dist/) ─ /v1/** rewrite ─► Cloud Run onolys-api-prod ─► Firestore (default)
   │                                                                                     ├► GCS onolys-audio-prod (signed URLs)
   └─ PUT signed URL (CORS: app origin) ───────────────────────────────────────────────►┘└► Cloud Tasks steps-prod ─OIDC► onolys-worker-prod ─► STT (us) · Vertex (us-central1)
staging: same shape (site onolys-app-staging, db `staging`, *-staging services) · admin.onolys.com: site onolys-admin ─► Cloud Run onolys-admin ─► GCS FUSE onolys-admin-data
CI: GitHub OIDC ─WIF─► deployer-{env} SA ─► AR push, Cloud Run deploy, firebase deploy
```

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Provisioning | Terraform, state in GCS, run locally via ADC | gcloud/bash scripts (simplify-med style); Pulumi | Declarative drift/plan, covers Identity Platform/Hosting/IAM/budget; single binary, no gcloud needed; scripts are not idempotent for IAM |
| D2 | Env separation | One project; Firestore named DB `staging` + `(default)` prod; per-env buckets/SAs/queues | Collection prefixes; two projects | Brief fixes one project; DBs give a hard data boundary without changing SP04 collection names |
| D3 | Region | us-central1 everywhere except STT `us` multi-region | `nam5` multi-region Firestore; all `us` | Chirp 3 is not listed for us-central1; single-region for everything else matches the brief; Firestore location is irreversible so pick the simple one |
| D4 | Web/API origin | Hosting site + `/v1/**` rewrite to Cloud Run (same origin) | `api.onolys.com` + CORS; global LB | No CORS/preflight, same stack as landing, free CDN, no LB cost. Rewrite limit 60 s fits (<1 s calls, uploads direct to GCS) |
| D5 | Deploy auth | WIF per-env deployer SAs; prod gated by GitHub environment | SA JSON key secret (simplify-med) | No long-lived key in a public repo; prod SA only impersonable from `production` environment |
| D6 | Prod promotion | Same image digest, manual approval | Rebuild on tag | What ran in staging is what ships |
| D7 | Backups | PITR off, no backups, GCS soft-delete 0 | PITR 7 d; default soft delete | Required for hard-delete claim (SP04 R7); Tejit owns legal |
| D8 | Admin auth/host | Hosting `admin.` → Cloud Run, app-level Identity Platform allowlist + MFA | IAP + HTTPS LB | Brief: no IAP/LB in v1; LB costs ~$18/mo |
| D9 | Secrets seeding | Script, not Terraform | `random_password` in state | Keeps values out of state |
| D10 | Staging domain | `*.web.app` only | `staging.app.onolys.com` | Fewer DNS records for Tejit; all functionality testable |

## Manual steps
Tejit (all owner-only):
1. Confirm his Google account is Owner on `onolys` and has Billing Account Administrator on the linked billing account (needed for budget, API enablement, Identity Platform upgrade); confirm billing is linked.
2. Choose `monthly_budget_usd` and alert email.
3. Add DNS records after `terraform apply` prints them. Expected shape (final values only after site creation; use output `required_dns_updates` or Firebase console > Hosting > custom domain):
   | Host | Type | Value |
   |---|---|---|
   | `app.onolys.com` | TXT | `hosting-site=onolys-app` (ownership) |
   | `app.onolys.com` | A | `199.36.158.100` (typical Hosting IP; confirm in output) |
   | `admin.onolys.com` | TXT | `hosting-site=onolys-admin` |
   | `admin.onolys.com` | A | `199.36.158.100` |
   Also remove/loosen any conflicting AAAA/CAA for these hosts; certificate issuance follows verification (minutes to hours).
4. Firebase console > Authentication > Sign-in method: enable Google (auto-creates OAuth client); add redirect `https://app.onolys.com/__/auth/handler` (and staging host) to that client.
5. Customize verification/reset email templates (sender name, subject, link domain) in console.
6. Create GitHub environment `production` with himself as required reviewer; set repo variables from Terraform outputs (WIF provider, deployer SA emails, `VITE_FIREBASE_*`).
7. If using Claude as alternate route: supply Anthropic key for `seed-secrets.py`.
8. Supply the admin allowlist emails (value of secret `admin-allowed-emails-{env}`); upload real transcripts/datasets by hand to `onolys-admin-data-{env}` under `eval/data/`.
Agents: install terraform, run `bootstrap.sh`, `terraform apply`, seed secrets, run first deploys.

## Risks / Open Questions
- [RESOLVED: Hosting rewrite, same origin] SP04/SP05 `/v1` question; fallback `api.onolys.com` + CORS if staging shows Hosting drops `Authorization`/`ETag` or caches `/v1` (SP05 verifies).
- [RESOLVED: PITR off] Firestore backups vs deletion (D7), prod DB delete-protection on.
- [OPEN] Is Chirp 3 diarization usable from `us` with batch vs sync recognize, and does the STT service agent need `objectViewer` on the audio bucket? Verify in SP01 spike; Terraform grants it if needed.
- [OPEN] Gemini model availability in `us-central1` vs `global`/`us` endpoint; if only `global`, data residency claim weakens. Verify at SP01/SP02 model pinning.
- [RESOLVED: SP04 stages uploads under top-level `uploads/{uid}/{sid}/…` and moves them on `validate` ((reconcile pass))] The lifecycle rule matches the `uploads/` prefix.
- [OPEN] Org policy might block `allUsers` invoker; check at first apply.
- [OPEN] Hosting site ids `onolys-app`, `onolys-app-staging`, `onolys-admin`, `onolys-admin-staging` may be taken (global namespace).
- [OPEN] GCS FUSE semantics for the eval server (R12); decision belongs to SP07.
- [OPEN] Terraform support for every Identity Platform setting (MFA/TOTP, password policy) in the pinned provider; fallback is REST patch in a script.
- Risk: budget alert is not a cap; mitigated by max-instances, dispatch caps, daily user cap.
- Risk: shared user pool means a staging bug could touch prod accounts' tokens only for auth, never data.
- [DEFERRED] Monitoring dashboards, uptime checks, WAF/Cloud Armor, min-instances warm start, CI-driven terraform apply, separate Identity Platform tenants per env.

## Acceptance Criteria
1. `infra/scripts/install-tools.sh` then `bootstrap.sh` then `terraform init/validate/plan` succeed from this machine using ADC with no gcloud and no change to the ADC quota project; a second `plan` after `apply` shows no changes.
2. After apply, per env: bucket private (public access prevention enforced, soft-delete 0, CORS and `uploads/` lifecycle present), queue `steps-{env}` with max_attempts 2, Cloud Run api/worker exist with limits in R8, Firestore DBs `(default)` and `staging` exist with PITR disabled, listed APIs enabled, Identity Platform config active with TOTP enabled and open sign-up.
3. IAM check: staging SAs cannot read prod bucket or DB; worker not invokable without the tasks SA OIDC token (401/403 for anonymous); api invokable anonymously.
4. Data-access audit logs appear for a Storage read and a Firestore write.
5. Staging deploy via merge to `main` runs end to end with WIF (no JSON key in repo secrets), `GET https://<staging-site>.web.app/v1/healthz` returns 200 through the rewrite, and a signed PUT from the staging origin passes CORS.
6. Prod deploy runs only after environment approval, reuses the staging digest, and prod deployer SA cannot be impersonated from other workflows or forks.
7. Budget exists with thresholds and the notification channel; Cloud Run max-instances and queue concurrency match R7/R8.
8. `docs/reference/infra.md` lists resource names, env var table, outputs, and the exact DNS records for `app.` and `admin.` taken from Terraform output.
