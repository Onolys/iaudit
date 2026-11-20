# Infrastructure runbook

**Audience:** the owner and agents who operate, deploy and debug Onolys on GCP.

Everything here was checked on 2026-11-20 against `terraform output`, `terraform show` (state), the Cloud Run API and Cloud Logging (`entries:list`). Terraform is the source of truth: if this page and `infra/` disagree, `infra/` wins, then fix this page. Why the choices were made: [ADR 0022](../decisions/0022-infra-gcp-terraform-two-environments.md).

## Overview

One GCP project (`onolys`, number `1054076260967`), region `us-central1`, two environments (`staging`, `prod`) in one Terraform root (`infra/`, state in `gs://onolys-tfstate`, prefix `infra`, Terraform `1.9.8`). Staging and prod are isolated by Firestore database, bucket, queue, service accounts and secrets. One Identity Platform user pool serves both.

```
Browser -> Hosting site (onolys-app) -> /v1/** rewrite -> Cloud Run onolys-api-prod -> Firestore (default), GCS, Cloud Tasks
Cloud Tasks steps-prod -(OIDC)-> onolys-worker-prod -> STT (location us) + Anthropic API
staging: same shape, site onolys-app-staging, Firestore DB `staging`, *-staging services
```

## Resource names

| Resource | staging | prod |
|---|---|---|
| Cloud Run api | `onolys-api-staging` | `onolys-api-prod` |
| Cloud Run worker | `onolys-worker-staging` | `onolys-worker-prod` |
| Cloud Run admin backend | `onolys-admin-backend-staging` (`admin_enabled.staging=true`) | not created (`admin_enabled.prod=false`) |
| Firestore database (Native, `us-central1`) | `staging` | `(default)` (delete-protection on) |
| GCS bucket (private) | `onolys-audio-staging` | `onolys-audio-prod` |
| Cloud Tasks queue | `steps-staging` | `steps-prod` |
| Service accounts (`@onolys.iam.gserviceaccount.com`) | `api-staging`, `worker-staging`, `tasks-invoker-staging`, `deployer-staging` | `api-prod`, `worker-prod`, `tasks-invoker-prod`, `deployer-prod` |
| Secret `uid-hmac-key-{env}` | `uid-hmac-key-staging` | `uid-hmac-key-prod` |
| Secret `<base>-{env}` per `llm_secrets` / `stt_secrets` entry (default base `anthropic-api-key`) | `anthropic-api-key-staging` | `anthropic-api-key-prod` |
| Log-based metric (5xx) | `onolys-api-5xx-staging` | `onolys-api-5xx-prod` |
| Alert policies | none while `staging_alerts=false` | `Onolys failed step/run (prod)`, `Onolys api 5xx rate (prod)` |
| Hosting site | `onolys-app-staging` (`https://onolys-app-staging.web.app`) | `onolys-app` (`https://onolys-app.web.app`, custom domain `app.onolys.com`) |

Shared (project level): Artifact Registry repo `onolys` (`us-central1-docker.pkg.dev/onolys/onolys`, no cleanup policy, so any earlier sha stays deployable), budget `onolys monthly`, Monitoring channel `Onolys owner email`, Workload Identity pool `github` with provider `github` (condition `assertion.repository=='Onolys/onolys'`), Speech-to-Text service agent `service-1054076260967@gcp-sa-speech.iam.gserviceaccount.com` (`objectViewer` on both buckets), Identity Platform config (email+password, min length 8, open sign-up, no MFA).

Admin (SP07) resources (`onolys-admin`, `onolys-admin-staging` sites, `admin.onolys.com`, `onolys-admin-backend-{env}`, `admin-allowed-emails-{env}`) exist only per env while `admin_enabled` (a map, default `{ staging = true, prod = false }`) is true for that env: staging owns `onolys-admin-staging`, its web app, `onolys-admin-backend-staging`, `admin-allowed-emails-staging` and the `onolys-admin-staging.web.app` authorised domain; prod ones (`onolys-admin`, `admin.onolys.com`, `onolys-admin-backend-prod`) stay off until launch. `onolys-admin-backend-staging` is public at Cloud Run (`allUsers` invoker) on purpose; access is enforced in the app (Firebase ID token + allowlist), timeout 130 s, runs as `admin-backend-staging`.

Sizing (checked on the live services):

| Service | CPU / mem | Timeout | Concurrency | Max instances (staging / prod) |
|---|---|---|---|---|
| api | 1 / 1 GiB | 60 s | 80 | 3 / 10 |
| worker | 2 / 2 GiB | 900 s | 2 | 3 / 3 |

Queue `steps-{env}`: `max_attempts=2`, backoff 5 s to 30 s, `max_dispatches_per_second=5`, `max_concurrent_dispatches = worker_concurrency x worker_max_instances` (6 in both envs). Rule: never let dispatches exceed worker capacity, or Cloud Run answers 429 and burns a task's two attempts. To raise capacity, raise `worker_max_instances` (tfvar); the dispatch cap follows.

Bucket: uniform access, public access prevention enforced, no versioning, soft-delete 0, lifecycle deletes `uploads/` objects older than 1 day, CORS (PUT/HEAD) for the env's app origin (staging also `http://localhost:5173`).

Region note: STT v2 Chirp 3 is not offered in `us-central1`, so STT uses location `us` / endpoint `us-speech.googleapis.com`. That is a provider option in `config/{env}/stt_providers.yaml`, not infra.

## Environment variables (Cloud Run)

Set by Terraform (`infra/modules/environment/services.tf`). Values below are the live ones, checked with the Cloud Run API on 2026-11-20.

| Var | api | worker | Value |
|---|---|---|---|
| `SERVICE_MODE` | yes | yes | `api` or `worker` |
| `ENV` | yes | yes | `staging` / `prod` |
| `GCP_PROJECT`, `AUTH_PROJECT` | yes | yes | `onolys` |
| `ADMIN_AUTH_PROJECT` | no | no | `onolys`; admin-backend only (admin auth does not read `AUTH_PROJECT`) |
| `REGION` | yes | yes | `us-central1` |
| `FIRESTORE_DATABASE` | yes | yes | `staging` / `(default)` |
| `AUDIO_BUCKET` | yes | yes | `onolys-audio-{env}` |
| `TASKS_QUEUE` | yes | yes | `steps-{env}` |
| `TASKS_SA` | yes | yes | `tasks-invoker-{env}@onolys.iam.gserviceaccount.com` |
| `WORKER_URL` | yes | yes | `https://onolys-worker-{env}-1054076260967.us-central1.run.app` (also the OIDC audience) |
| `ADAPTERS` | yes | yes | `real` |
| `BLOB_SIGNER_EMAIL` | yes | no | `api-{env}@onolys.iam.gserviceaccount.com` (signs V4 upload/read URLs through IAM `signBlob`) |
| `DAILY_RUN_CAP` | yes | yes | `20` (per user, app-side) |
| `ROUTES_FILE` | yes | yes | `config/{env}/routes.yaml` (baked into the image; `stt_providers.yaml` sits next to it) |
| `DEFAULT_PRESET` | yes | yes | `default` |
| `CORS_ORIGINS` | yes | no | staging `https://onolys-app-staging.web.app,http://localhost:5173`; prod `https://app.onolys.com` |
| `UID_HMAC_KEY` | yes | yes | secret ref `uid-hmac-key-{env}` (keys the `uid_hash` log field) |
| `ANTHROPIC_API_KEY` | no | yes | secret ref `anthropic-api-key-{env}` (one ref per `llm_secrets` / `stt_secrets` entry, always the env's own secret; staging and prod use separate provider keys) |
| `GIT_SHA` | yes | yes | set by CI at deploy. `unset` until the first CI deploy (the services still run the placeholder image `us-docker.pkg.dev/cloudrun/container/hello`) |

There are no STT env vars. No model id appears in infra.

## Terraform outputs

Run `cd infra && terraform output` (needs ADC; see Operating Terraform).

| Output | Use |
|---|---|
| `wif_provider` | GitHub var `WIF_PROVIDER`. Now: `projects/1054076260967/locations/global/workloadIdentityPools/github/providers/github` |
| `deployer_staging_email` | GitHub var `DEPLOYER_STAGING_SA`. Now: `deployer-staging@onolys.iam.gserviceaccount.com` |
| `deployer_prod_email` | GitHub var `DEPLOYER_PROD_SA`. Now: `deployer-prod@onolys.iam.gserviceaccount.com` |
| `web_env_staging` | map with `VITE_FIREBASE_API_KEY`, `_AUTH_DOMAIN`, `_APP_ID`, `_STORAGE_BUCKET`, `_MESSAGING_SENDER_ID`, `_PROJECT_ID`, and `VITE_FIRESTORE_DATABASE` (= `staging`). Sensitive: read with `terraform output -json web_env_staging` |
| `web_env_prod` | same keys; `VITE_FIRESTORE_DATABASE` = `(default)` |
| `web_env_admin_staging`, `web_env_admin_prod` | `null` until `admin_enabled` is true for that env |
| `required_dns_updates` | DNS records the owner adds (next section) |
| `custom_domain_status` | Hosting verification state per custom domain |

`VITE_FIRESTORE_DATABASE` is a per-build value: the web app passes it to `getFirestore`. The deploy workflows set it themselves (`staging` in `deploy-staging.yml`, `(default)` in `deploy-prod.yml`), so it is not a GitHub variable; it appears in `web_env_*` for local builds.

The browser API key is public by design (a Firebase web key); it is not restricted yet (After launch).

## DNS records (owner)

Copied verbatim from `terraform output required_dns_updates` on 2026-11-20 (domain `app.onolys.com`, action `ADD` for both):

| Type | Host | Value |
|---|---|---|
| `CNAME` | `app.onolys.com` | `onolys-app.web.app` |
| `TXT` | `_acme-challenge.app.onolys.com` | `oN6Ib3nIZxSzD2DNyT0R_WP254oUKl4wi-cNxyAVPdg` |

Status then (`terraform output custom_domain_status`): `ownership OWNERSHIP_MISSING`, `host HOST_UNHOSTED`, `cert CERT_VALIDATING`. After the records exist, expect `OWNERSHIP_ACTIVE`, `HOST_ACTIVE`, `CERT_ACTIVE` (minutes to hours).

Re-run the output before adding records: the values change if Hosting changes its desired state, and the TXT value is per-certificate. Remove any conflicting `A`/`AAAA` record on `app.onolys.com` (a `CNAME` cannot coexist with other records on the same host).

`admin.onolys.com` has no record yet: it exists only with `admin_enabled=true`; the output then adds its records. Staging has no custom domain (`onolys-app-staging.web.app` only).

## GitHub settings the owner must set

Repo `Onolys/onolys` > Settings > Secrets and variables > Actions > Variables (repository level), and Settings > Environments.

Environments: create `production` with Tejit as required reviewer (all prod jobs use it; the prod deployer trusts only that environment). `staging` is created on first use by `_deploy-cloudrun.yml`; no reviewer needed.

| Variable | Used by | Value (Terraform output) |
|---|---|---|
| `WIF_PROVIDER` | deploy-staging, deploy-prod, deploy-admin, `_deploy-cloudrun` | `wif_provider` |
| `DEPLOYER_STAGING_SA` | same (and the read-only `resolve` step of deploy-prod) | `deployer_staging_email` |
| `DEPLOYER_PROD_SA` | deploy-prod, deploy-admin, `_deploy-cloudrun` | `deployer_prod_email` |
| `GCP_PROJECT`, `GCP_REGION` | optional; default `onolys`, `us-central1` | leave unset |
| `STAGING_VITE_FIREBASE_API_KEY`, `_AUTH_DOMAIN`, `_APP_ID`, `_STORAGE_BUCKET`, `_MESSAGING_SENDER_ID` | deploy-staging (web build) | `web_env_staging` keys `VITE_FIREBASE_*` (same names without the `STAGING_` prefix) |
| `PROD_VITE_FIREBASE_API_KEY`, `_AUTH_DOMAIN`, `_APP_ID`, `_STORAGE_BUCKET`, `_MESSAGING_SENDER_ID` | deploy-prod (web build) | `web_env_prod` keys |
| `STAGING_VITE_CONTACT_EMAIL`, `PROD_VITE_CONTACT_EMAIL` | optional, web build | owner's contact address |
| `ADMIN_STAGING_VITE_FIREBASE_{API_KEY,AUTH_DOMAIN,APP_ID}`, `ADMIN_PROD_VITE_FIREBASE_{API_KEY,AUTH_DOMAIN,APP_ID}` | deploy-admin (after launch) | `web_env_admin_staging` / `web_env_admin_prod` |

`VITE_FIREBASE_PROJECT_ID` is taken from `GCP_PROJECT`/`onolys` in the workflow; `VITE_FIRESTORE_DATABASE` is hard-coded per workflow (see Terraform outputs).

Secrets: the only one is `ANTHROPIC_API_KEY`, read by `nightly.yml` (job `api-real-mode`, a live Claude run); it should hold the staging/test key, never the prod key (prod's key lives only in Secret Manager as `anthropic-api-key-prod`). Deploys use WIF, so no JSON key and no deploy secret exists. Do not add a GCP key.

Workflows: `deploy-staging.yml` runs after the `CI` workflow succeeds on `main` (also manual). `deploy-prod.yml` is manual (`workflow_dispatch`, input `sha`) or on a `v*` tag. `deploy-admin.yml` is for SP07 and needs `admin_enabled` true for that env first. `nightly.yml` runs 06:17 UTC daily.

## Operating Terraform

```bash
bash infra/scripts/install-tools.sh          # pinned terraform to ~/.local/bin
bash infra/bootstrap.sh                      # state bucket onolys-tfstate (idempotent)
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json
cd infra && terraform init && terraform plan     # add -lock=false for a read-only look
terraform apply
```

No `gcloud` needed; the providers use `user_project_override` with billing project `onolys`. `terraform plan/apply` is manual (no CI apply). Cloud Run images and `GIT_SHA` belong to CI: after a CI deploy `plan` may show `GIT_SHA` drift; apply with `-var git_sha=<deployed sha>` to keep it quiet.

Seed secret values outside state (values never printed, never in tfvars):

```bash
set -a; . ~/.config/onolys/keys.env; set +a
python3 infra/scripts/seed-secrets.py --env staging     # also: --env prod
```

It creates `uid-hmac-key-{env}` (random, only if missing) and writes the key for each `--map ENVVAR=base-id` (default `ANTHROPIC_API_KEY=anthropic-api-key`) into `<base-id>-{env}`, so `--env staging` and `--env prod` fill different secrets from the key in your shell. Re-running is a no-op unless a value changed.

### Cutover: shared `anthropic-api-key` to per-env secrets (one-time, owner decision 2026-11-20)

A Cloud Run revision that references a secret with no version fails to deploy, so the new secrets must have values before services switch. Terraform drops the old shared secret from state without deleting it (`removed` block, `destroy = false`), so live revisions keep working until you delete it. Order:

```bash
cd infra && terraform init
# (a) create only the empty per-env secrets; services still use the old secret
terraform apply -target='module.staging.google_secret_manager_secret.provider' -target='module.prod.google_secret_manager_secret.provider'
# (b) seed values: staging key, then a DIFFERENT prod key
cd .. && ANTHROPIC_API_KEY=<staging key> python3 infra/scripts/seed-secrets.py --env staging
ANTHROPIC_API_KEY=<prod key> python3 infra/scripts/seed-secrets.py --env prod
# (c) full apply: moves accessor grants and the worker env refs to the per-env secrets, forgets the old secret
cd infra && terraform plan && terraform apply
```

Then dispatch `deploy-staging` / `deploy-prod` (or just confirm the new worker revisions are healthy) and, once both envs work on the new keys, delete the orphaned shared secret `anthropic-api-key` in the console (or `gcloud secrets delete`). Rotate the old key since it was shared.

## Admin access

Who may use the admin app is a comma-separated list of emails in Secret Manager `admin-allowed-emails-{env}` (case-insensitive, spaces around commas ignored). The admin backend reads it as env `ADMIN_ALLOWED_EMAILS` (secret ref, `latest`). Anyone signed in but not on the list gets 403; no token gets 401.

Today (staging, same list intended for prod): `tejitpabari99@gmail.com`, `gitika.bose@gmail.com`, `falakpabari386@gmail.com`.

Edit in the console: Secret Manager, open `admin-allowed-emails-{env}`, **+ New version**, paste the FULL list (it replaces the old one), Add. A running revision keeps the old value, so make Cloud Run pick it up: Cloud Run, `onolys-admin-backend-{env}`, **Edit & deploy new revision**, **Deploy** (or re-run `deploy-admin.yml`).

Edit with the script (value never printed; staging shown, `--env prod` once prod admin is enabled):

```bash
ADMIN_ALLOWED_EMAILS="a@x.com,b@y.com" python3 infra/scripts/seed-secrets.py --env staging --admin
```

Then deploy a new revision as above. First-time order for an env: `terraform apply -target='module.<env>.google_secret_manager_secret.admin_allowed_emails'`, run the seed command, then the full `terraform apply` (a revision that references a secret with no version fails).

## Adding an LLM or STT provider

1. **tfvars line.** In a `terraform.tfvars` (local, not committed), extend the map, keeping the default entry:
   ```hcl
   llm_secrets = {
     ANTHROPIC_API_KEY = "anthropic-api-key"
     GEMINI_API_KEY    = "gemini-api-key"
   }
   ```
   STT keys go in `stt_secrets` (empty by default; Google STT uses the worker service account, not a key). The tfvars value is the BASE id; the module creates `<base>-staging` and `<base>-prod`. `terraform plan` must show exactly two new secret shells (one per env), their accessor bindings (that env's worker only) and one env ref per worker; existing resources unchanged. As in the cutover above, create the shells first with a `-target` apply, seed, then do the full apply, otherwise the new revision references a secret with no version.
2. **Seed the value** per env, with that env's own key: `GEMINI_API_KEY=<staging key> python3 infra/scripts/seed-secrets.py --env staging --map ANTHROPIC_API_KEY=anthropic-api-key --map GEMINI_API_KEY=gemini-api-key`, then the same with the prod key and `--env prod`. Pass every `--map` you want checked; unset variables keep their existing version.
3. **Route.** Add a route (or preset) in `config/{staging,prod}/routes.yaml` with `litellm_id: <provider>/<model>` and `api_key_env: GEMINI_API_KEY` (the map key). For STT, add a provider under `providers:` in `config/{env}/stt_providers.yaml`, then point `default`, `by_language` or a preset's `stt` at it.
4. **Ship.** PR, merge to `main` (deploys staging), then dispatch `deploy-prod`. The new secret is only mounted on a new revision, which the deploy creates. CI fails if a config file is missing for an env.

## Runbook: a user reports a failed session

The web error card shows a **reference id** (the `request_id`). All app logs are one JSON line per event on Cloud Run stdout (Cloud Logging `jsonPayload.*`); lines carry ids and codes, never content.

1. **Find the line by reference id** (Logs Explorer, project `onolys`):
   ```
   jsonPayload.request_id="<id>"
   ```
   Read `jsonPayload.session_id`, `run_id`, `step`, `error_code`, `exc_class` (and `code_version`, the deployed sha). Narrow to failures with `jsonPayload.status="failed"`; add `resource.labels.service_name=("onolys-api-prod" OR "onolys-worker-prod")` to pick the env.
2. **Whole trail for that session:**
   ```
   jsonPayload.session_id="<sid>"
   ```
   For one run add `jsonPayload.run_id="<rid>"`. Sort ascending to read in order.
3. **Match the `error_code`** below, fix or advise, then have the user run again.

Verified 2026-11-20 against the task-10 test lines (staging, `error_code t10_test`, written for the alert check) through the REST API `POST https://logging.googleapis.com/v2/entries:list` with body `{"resourceNames":["projects/onolys"],"filter":"jsonPayload.request_id=\"t10b-1795181702\"","orderBy":"timestamp desc"}`: it returned the one `onolys-worker-staging` line (`status failed`, `session_id synthetic`, `step test`); the filter `jsonPayload.session_id="synthetic"` returned that line plus the `onolys-api-staging` one (`request_id t10-1795181472`); the alert filter (`resource.type="cloud_run_revision"`, service name in the two staging services, `jsonPayload.status="failed"`) matched both.

Alerts (prod always on; staging only with `staging_alerts=true`): an email for each `status="failed"` line (at most one per 5 min) and for more than 5 api 5xx responses in 5 min. The email channel needs its verification click.

### `error_code` table

The code in the failed log line is the public code `to_public` (`api/src/onolys_api/adapters/error_map.py`) gives; the same code is in the session status and the error card. All codes: `api/src/onolys_api/errors.py`, schema `docs/contracts/public/public-error-response.schema.json`.

| `error_code` | Meaning | Usual fix |
|---|---|---|
| `upstream_unavailable` | LLM or STT provider failed or timed out (retryable; one retry is automatic) | Check Anthropic / Google status; check the worker has its secret ref and a valid key (`ANTHROPIC_API_KEY`); user runs again shortly |
| `transcription_failed` | STT failed twice, or a non-transient STT error | Ask for a different file; look at `exc_class` (`SttProviderError`); check `config/{env}/stt_providers.yaml` and the STT service agent's bucket access |
| `no_speech` | No usable speech found | Nothing to fix; user uploads another recording |
| `speakers_not_separated` | Diarization could not separate speakers | Nothing to fix; another recording |
| `deadline_exceeded` | Run exceeded its time limit (retryable) | Run again; if repeated check the provider's latency and worker timeout (900 s) |
| `rate_limited` | Provider or API rate limit | Wait; if frequent lower load or raise the provider tier, then `worker_max_instances` |
| `invalid_parameters` | Engine rejected the input (`InputError`) | Not an outage; see the session input; fix the request |
| `internal_error` | Anything else (pack error, unexpected exception, test fixture miss) | Read `exc_class`, then the trail; likely a bug or bad config (routes file, missing secret); roll back if it started with a deploy |
| `daily_cap_reached` | Per-user daily run cap (`DAILY_RUN_CAP`, 20) or concurrent-run limit (HTTP 429, status doc) | Expected; raise `DAILY_RUN_CAP` in Terraform only if intended |

Other public codes (`unauthenticated`, `not_found`, `invalid_state`, `conflict`, `unsupported_audio`, `audio_too_large`, `audio_too_long`, `audio_unreadable`, `rating_invalid`, ...) are returned to the client as 4xx and are not `status=failed` lines. A rise in 5xx without `failed` lines: filter `httpRequest.status>=500` on `onolys-api-{env}`.

### Rollback

Rollback = dispatch `deploy-prod` with the previous sha; it redeploys api, worker, web and rules from that commit.

Details (from `.github/workflows/deploy-prod.yml`): Actions > deploy-prod > Run workflow > `sha` = the full 40-char commit to return to. The commit must have been built by `deploy-staging` (image tagged with that sha in Artifact Registry) and its digest must have run on a staging service, otherwise `resolve` fails ("never ran on ... deploy it to staging first"). Approve the one `production` review prompt. After it finishes, the prod revisions carry `GIT_SHA=<sha>`, and `code_version` in new log lines shows it. Empty `sha` promotes the commit staging runs now. Firestore data is not rolled back.
