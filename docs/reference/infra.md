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
| Cloud Run admin backend | `onolys-admin-backend-staging` (`admin_enabled.staging=true`) | none (prod admin removed 2026-11-21, `admin_enabled.prod=false`) |
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

Admin (SP07) resources (`onolys-admin`, `onolys-admin-staging` sites, `admin.onolys.com`, `onolys-admin-backend-{env}`, `admin-allowed-emails-{env}`) exist only per env while `admin_enabled` (a map, default `{ staging = true, prod = false }`) is true for that env. Owner decision 2026-11-21: staging is the ONLY admin environment and serves `admin.onolys.com` (it auto-deploys from `main`; admin uses only synthetic MITI fixtures, no user data). Staging owns the `onolys-admin-staging` site, its web app, `onolys-admin-backend-staging` (CORS allows `https://admin.onolys.com` and `https://onolys-admin-staging.web.app`), `admin-allowed-emails-staging`, the `admin.onolys.com` Hosting custom domain and the `admin.onolys.com` / `onolys-admin-staging.web.app` authorised domains. The prod admin (`onolys-admin` site and web app, `onolys-admin-backend-prod`, its SA, invoker, secret and IAM, prod admin deployer IAM) was destroyed. `onolys-admin-backend-staging` is public at Cloud Run (`allUsers` invoker) on purpose; access is enforced in the app (Firebase ID token + allowlist), timeout 130 s, runs as `admin-backend-staging`.

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
| `web_env_admin_staging`, `web_env_admin_prod` | `null` until `admin_enabled` is true for that env (`web_env_admin_prod` stays `null`) |
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

`admin.onolys.com` is a custom domain on the staging admin site `onolys-admin-staging`; its records are in `required_dns_updates` (CNAME to `onolys-admin-staging.web.app` plus the `_acme-challenge` TXT); the owner adds them. No other staging custom domain (`onolys-app-staging.web.app` only).

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
| `ADMIN_STAGING_VITE_FIREBASE_{API_KEY,AUTH_DOMAIN,APP_ID}` | deploy-admin | `web_env_admin_staging` (no prod admin vars) |

`VITE_FIREBASE_PROJECT_ID` is taken from `GCP_PROJECT`/`onolys` in the workflow; `VITE_FIRESTORE_DATABASE` is hard-coded per workflow (see Terraform outputs).

Secrets: the only one is `ANTHROPIC_API_KEY`, read by `nightly.yml` (job `api-real-mode`, a live Claude run); it should hold the staging/test key, never the prod key (prod's key lives only in Secret Manager as `anthropic-api-key-prod`). Deploys use WIF, so no JSON key and no deploy secret exists. Do not add a GCP key.

Workflows: `deploy-staging.yml` runs after the `CI` workflow succeeds on `main` (also manual). `deploy-prod.yml` is manual (`workflow_dispatch`, input `sha` or `version`) or on a `v*` tag. `deploy-admin.yml` deploys the staging admin only (backend + `onolys-admin-staging` site): automatically on push to `main` touching `admin/`, `frontend/`, `engines/`, `protocols/`, contracts or deps; also manual. There is no prod admin. `nightly.yml` runs 06:17 UTC daily.

## Operating Terraform

```bash
bash infra/scripts/install-tools.sh          # pinned terraform to ~/.local/bin
bash infra/bootstrap.sh                      # state bucket onolys-tfstate (idempotent)
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json
cd infra && terraform init && terraform plan     # add -lock=false for a read-only look
terraform apply
```

No `gcloud` needed; the providers use `user_project_override` with billing project `onolys`. `terraform plan/apply` is manual (no CI apply). Cloud Run images and `GIT_SHA` belong to CI: after a CI deploy `plan` may show `GIT_SHA` drift; apply with `-var 'git_sha={staging="<staging sha>",prod="<prod sha>"}'` (root map var, one value per env) to keep it quiet. CI-set labels: `commit-sha`, `managed-by` (service + template) and `goog-terraform-provisioned` (template) are ignored via `lifecycle`.

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

## Deploy workflow guard (fork safety)

`deploy-staging.yml` runs after CI via `workflow_run`. That trigger's `branches: [main]` filter matches the head branch name, so a fork PR from a branch named `main` would match, and the deploy job would check out fork code with WIF access. The `build` job therefore requires `workflow_run.event == 'push'`, `head_repository.full_name == github.repository` and `head_branch == 'main'`; every other job `needs` it. `scripts/ci/test_workflow_run_guard.py` (run in CI) enforces this for any `workflow_run` workflow and bans `pull_request_target`. The WIF `attribute_condition` in `infra/deployer.tf` only checks the repository; tightening it to a ref is a separate owner apply.

## Admin access

Who may use the admin app is a comma-separated list of emails in Secret Manager `admin-allowed-emails-{env}` (case-insensitive, spaces around commas ignored). The admin backend reads it as env `ADMIN_ALLOWED_EMAILS` (secret ref, `latest`). Anyone signed in but not on the list gets 403; no token gets 401.

Today (staging, same list intended for prod): `tejitpabari99@gmail.com`, `gitika.bose@gmail.com`, `falakpabari386@gmail.com`.

Edit in the console: Secret Manager, open `admin-allowed-emails-{env}`, **+ New version**, paste the FULL list (it replaces the old one), Add. A running revision keeps the old value, so make Cloud Run pick it up: Cloud Run, `onolys-admin-backend-{env}`, **Edit & deploy new revision**, **Deploy** (or re-run `deploy-admin.yml`).

Edit with the script (value never printed; staging shown, `--admin` is staging only, prod admin is removed):

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

### Slow or stuck transcription

`transcribe` logs `stt_started` (`stt_operation` = the Chirp operation name, `stt_started`) and every poll logs `stt_poll` (`poll_n`, `elapsed_s`, `stt_operation`, `outcome` pending|ready). Trail: `jsonPayload.session_id="<sid>" jsonPayload.event=("stt_started" OR "stt_poll")`; look the operation name up in the Speech-to-Text v2 operations API to see Chirp's own state.

Limits: the poll cap is `clamp(STT_CAP_FACTOR x audio seconds, STT_CAP_MIN_S, STT_TIME_LIMIT_S)` (defaults 3, 300 s, 1200 s; stored on the step as `stt_limit_s`), then `transcription_failed`. Each poll queues the next poll before it asks Chirp, so a poll that dies cannot stop the chain; a failed enqueue answers 5xx (Cloud Tasks retries the same poll) and, on the last attempt, fails the session. There is no scheduler. If a chain still stops, the session is failed on the next `GET /v1/sessions/{id}` or list call once `updated_at` is older than cap + 60 s (`session_stale` log line, `status=failed`, `exc_class=StaleSession`); the web app does not poll, so the session shows `transcribing` until something reads it through the API.

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

Release = dispatch `deploy-prod` with `sha` empty (promotes the commit staging runs now) or a specific `sha`. Every successful deploy is tagged `prod-<UTC date>.<n>` (annotated tag on the promoted commit, message has sha, image digest, run URL) by the final `tag` job; rollbacks are tagged too, and only after the healthz smoke passes. The newest `prod-*` tag = last fully successful deploy; to undo a bad release, roll back to the tag before it. After a failed run prod may be mixed (check `/v1/healthz` `code_version` or the revisions' `GIT_SHA`). Rollback = dispatch `deploy-prod` with `version=<prod tag>`; it redeploys api, worker, web and rules from that tag's commit. `v*` = optional human release trigger; `prod-*` = bot record of each successful deploy; roll back only by `prod-*` version or `sha`.

If a rollback deploy succeeds but its `tag` job fails, prod is on the new commit but untagged (the newest `prod-*` tag is then stale): check `/v1/healthz` `code_version` for what is really live.

List prod versions: `git ls-remote --tags --refs --sort=-v:refname origin 'prod-*' | head`.

Details (from `.github/workflows/deploy-prod.yml`): Actions > deploy-prod > Run workflow > `version` = e.g. `prod-2026-11-21.1` (or `sha` = the full 40-char commit; set one, not both; empty both promotes the commit staging api runs now). The commit must have been built by `deploy-staging` (image tagged with that sha in Artifact Registry), and that image (the tag's index digest or one of its platform digests) must have run on both staging api and staging worker with `GIT_SHA=<sha>`, otherwise `resolve` fails ("never ran on ... deploy it to staging first"). Approve the one `production` review prompt. After it finishes, the prod revisions carry `GIT_SHA=<sha>`, and `code_version` in new log lines shows it. The `prod-*` tags cannot trigger `deploy-prod` (they do not match `v*`, and tags pushed with `GITHUB_TOKEN` trigger nothing). Firestore data is not rolled back.

### Prod promotion + rollback drill (2026-11-21)

**(a) Promotion, run 44922391380.** Promoted `096e3edde31fe4134cb588c092201691bf774a83`; production review approved; all jobs passed (resolve, rules, web, deploy-api, deploy-worker, smoke, tag) in ~4.5 min.

- Prod api revision `-00003-brc`, worker `-00004-nh4`, `GIT_SHA` `096e3ed`.
- Prod api digest equals staging: `sha256:88045a94675bc4417eed09e22acf5647bc8d408b192a5750845f02e758580c9f`.
- Healthz `https://onolys-app.web.app/v1/healthz` returned 200, `code_version` `096e3ed`.
- Tag created: `prod-2026-11-21.1`.

**(b) Rollback, run 44922869893.** Rolled back to `205a03fa48aa2a43416d8be1dacd130a9a20d9a0`. Deploys and smoke passed:

- api `-00004-hjw`, worker `-00005-96t`, `GIT_SHA` `205a03f`.
- Digest `sha256:ff0fad588e301b216d548b2dcd0214da70f190ab5ced8149a75b16c0980f07c9`; healthz 200.
- The `tag` job FAILED: "refusing to allow a GitHub App to create or update workflow .github/workflows/ci.yml without workflows permission". Cause: the shallow checkout in the tag job made the push upload the old commit's objects (including the workflow file). Fix is in PR #42 (full history checkout).
- Prod currently runs `205a03f`, untagged.

**(c) Roll-forward by tag: not run.** Deferred by the owner (2026-11-21). To finish later: merge #42, dispatch `deploy-prod` with `version=prod-2026-11-21.1` (expect a new tag), then a blank dispatch for the main head.

**Earlier failed attempts** (nothing deployed by either): 44914754450 (checkout deleted the creds file, fixed in #40); 44918021819 (index digest vs platform digest mismatch, fixed in #41).

## Acceptance sweep (SP06, 2026-11-21)

Measured live on 2026-11-21 (about 16:50-17:05 UTC) with ADC REST calls (Cloud Run v2, Cloud Tasks, Storage, Firestore, Identity Toolkit admin v2, Service Usage, Secret Manager, IAM, Monitoring, Logging, Billing Budgets), `curl`, `gh`, the Firestore emulator and `terraform plan` (read-only, `-lock=false`, no apply). PRD: `docs/agent_files/feat-miti-platform-20261120-0153/06-infra/PRD.md` AC1-AC10, R8, R13. Prod runs `205a03f` (rollback of `096e3ed`); staging api live traffic is `096e3ed`.

| AC | Result | Evidence |
|---|---|---|
| AC1 | MET | `terraform` 1.9.8 in `~/.local/bin`, ADC quota project still `juno-medical-clarity`, no `gcloud`. `terraform init` + `validate` ("configuration is valid") + `plan` succeed. `plan -target=module.prod` (with `staging_alerts=true` and the live `git_sha` map): **No changes**. Unscoped plan: see "Terraform plan results" below (staging drift only, not a gap in the sweep) |
| AC2 | MET | Per env: bucket `onolys-audio-{env}` public access prevention `enforced`, uniform access on, soft-delete `0s`, versioning off, `uploads/` delete lifecycle (age 1), CORS PUT/HEAD for the env origin. Queue `steps-{env}` `maxAttempts 2`, backoff 5-30 s. Cloud Run limits match R8 (table below). Firestore `(default)` and `staging`: `FIRESTORE_NATIVE`, `us-central1`, PITR disabled (`(default)` delete-protection on). All 21 APIs in `local.apis` enabled (Service Usage). Identity Platform: email sign-in enabled, sign-up not disabled, password policy `ENFORCE` with `minPasswordLength 8`, `mfa.state DISABLED`. Rules emulator tests (`firestore-rules-test`, `firebase-tools` 14.27.0 `emulators:exec`): 16 pass, 0 fail, including the 3 listener cases (owner listen after create ok, other user denied, missing doc denied). Live rules releases exist for `cloud.firestore` (prod, 16:16Z) and `cloud.firestore/staging` (16:01Z) |
| AC3 | MET | Bucket IAM: `storage.objectAdmin` only for that env's `api-{env}`/`worker-{env}` (plus Speech service agent `objectViewer`). `datastore.user` bindings are conditioned `resource.name == "projects/onolys/databases/staging"` (staging SAs) and `.../(default)` (prod SAs). Secret IAM: each env's secrets list only its own SAs. Anonymous `GET` on `onolys-worker-prod` and `onolys-worker-staging` returns 403; worker `run.invoker` is only `tasks-invoker-{env}`; api (`/v1/healthz` direct run.app URL) returns 200 and its invoker is `allUsers` |
| AC4 | MET | Worker env in both envs has `ANTHROPIC_API_KEY` (secret ref `anthropic-api-key-{env}`) and no other provider key; no `STT_*` var (full env list checked). `stt_secrets = {}`: no STT secret exists. Plan with an extra `llm_secrets` entry `GEMINI_API_KEY` (prod-targeted): creates exactly `provider["GEMINI_API_KEY"]` shell, `admin_llm` and `worker_provider` accessor bindings, and updates the worker and admin-backend services (env refs); 3 to add, 2 to change, 0 to destroy; nothing else touched. Image carries `config/` (`api/Dockerfile` `COPY config /app/config`) and `deploy-staging.yml` runs `test -s /app/config/<env>/<file>.yaml` per file against the image digest before deploy; both envs run `ROUTES_FILE=config/{env}/routes.yaml` and serve `/v1/healthz` 200 |
| AC5 | MET | `deploy-staging` run 44922123760 (workflow_run after CI 44921577408 on `096e3ed`) succeeded. Repo secrets: only `ANTHROPIC_API_KEY` (nightly); no GCP JSON key; WIF vars only. `https://onolys-app-staging.web.app/v1/healthz` 200 with `code_version 096e3ed`. Signed PUT CORS: preflight `OPTIONS` to `onolys-audio-staging` with the staging origin returns 200 and `access-control-allow-origin: https://onolys-app-staging.web.app`; real signed-URL upload through that origin passed in SP09 (`staging-e2e.md`) |
| AC6 | MET | `deploy-prod` run 44922391380: `production` environment approved by Tejit, all jobs passed, api digest equal to staging (`sha256:88045a94...`). GitHub environment `production` has `required_reviewers` (tejitpabari99) and a branch policy. `deployer-prod` can be impersonated only by `principalSet .../attribute.environment/production`; the provider condition is `assertion.repository=='Onolys/onolys'` (state ACTIVE), so forks and other workflows cannot mint a token for it |
| AC7 | MET | Budget `onolys monthly` (USD 20; 50 %, 90 %, 100 % current, 100 % forecast) with channel `Onolys owner email` (id 749283734341274206), project-scoped. Note: a second, non-Terraform budget `onolys` (USD 20; 50/80/100 %, project-level recipients) also exists on the billing account; left untouched. Cloud Run: api max 10 prod / 3 staging, concurrency 80; worker concurrency 2, max 3 both envs. Queues: `maxConcurrentDispatches 6` in both (2 x 3), `maxDispatchesPerSecond 5` |
| AC8 | MET | This page: resource names, env var table, outputs (incl. `VITE_FIRESTORE_DATABASE`), DNS records, runbook (reference id query, `error_code` table, rollback). DNS section refreshed against `terraform output` today: `app.onolys.com` is now `OWNERSHIP_ACTIVE`, `HOST_ACTIVE`, `CERT_ACTIVE` (was missing on 2026-11-20); `admin.onolys.com` still `OWNERSHIP_MISSING`, `HOST_UNHOSTED`, `CERT_VALIDATING` (needs the owner's DNS records, below) |
| AC9 | MET (drill partial) | Live revisions carry the deployed commit: staging api (traffic revision `onolys-api-staging-096e3ed-34-1`) and worker `GIT_SHA=096e3ed...`; prod api and worker `205a03f...` (healthz `code_version` agrees on `app.onolys.com`, `onolys-app.web.app` and the run.app URL). Rollback drill run 44922869893 (earlier sha `205a03f`) redeployed rules, web, api and worker and passed smoke; its `tag` job failed (fix in PR #42, unmerged). Roll-forward by tag deferred by the owner; see the drill section above |
| AC10 | MET (owner confirmed email arrived, 2026-11-21) | Test line written to prod at launch check: `request_id sp06-sweep-1795279972`, `status=failed`, `error_code sp06_sweep_test`, service `onolys-worker-prod`, 16:52:52Z. Alert `0.ofa4aj5s6bk0` on policy `Onolys failed step/run (prod)` opened 16:53:06Z (14 s later), state OPEN. Runbook query `jsonPayload.request_id="sp06-sweep-1795279972"` through `entries:list` returned that one line. Policies `Onolys api 5xx rate (prod|staging)` and metrics `onolys-api-5xx-{env}` exist and are enabled. The agent did not read the owner's inbox: owner to confirm one email "Onolys failed step/run (prod)" arrived. Staging precedent: 71 s incident, SP09 Task 10 |

Cloud Run limits as measured (R8): api 1 CPU / 1 GiB, 60 s, concurrency 80; worker 2 CPU / 2 GiB, 900 s, concurrency 2; admin-backend 1 CPU / 1 GiB, 130 s, concurrency 20 (max 3). Prod admin-backend was removed 2026-11-21. R13: `deploy-staging.yml`, `deploy-prod.yml`, `_deploy-cloudrun.yml` exist; every deploy authenticates by WIF.

### Terraform plan results

Command: `cd infra && terraform plan -var staging_alerts=true -var 'git_sha={staging="096e3edde31fe4134cb588c092201691bf774a83",prod="205a03fa48aa2a43416d8be1dacd130a9a20d9a0"}' -lock=false`.

- `-target=module.prod`: **No changes** (prod has no drift).
- Unscoped: `Plan: 0 to add, 2 to change, 0 to destroy`, both on staging, both known and pre-existing, not a sweep failure:
  - `module.staging...google_cloud_run_v2_service.api`: its template is currently the no-traffic PR-42 preview revision (`onolys-api-staging-pr-42-fc89744-14-1`: `SERVICE_MODE=combined`, `ADAPTERS=stub`, preview `CORS_ORIGINS`, `GIT_SHA=fc89744`, `cpu_idle=false`) while 100 % of traffic stays on `onolys-api-staging-096e3ed-34-1`. A preview deploy replaces the service template. Plan would reset it to the real template.
  - `module.staging...admin_backend[0]`: `GIT_SHA` is `205a03f`, plan sets `096e3ed` (admin deploys come from `deploy-admin.yml`, not `deploy-staging`).
  - Staging worker is not drifting (`GIT_SHA` already `096e3ed`).
  - Follow-up (not done here): make the preview workflow deploy with `--no-traffic --tag` without replacing the service template, or accept and re-apply after each preview. No apply was run.

### Open-until-measured items (Task 15)

**(a) Worker `max-instances`: KEEP 3 (prod and staging).** Evidence: the Anthropic rate tier (owner step 7a) is not recorded anywhere (`docs/implementation/infra-staging-first-apply.md`: "unknown, owner to confirm"). SP09 measured N=1 only: no back-off, every run 1 attempt, 42-68 s to `report_ready` (default preset, 8,486 in / 1,303 out tokens); N=6 parallel is not measured; no real prod runs exist yet. Worker memory is not a constraint (`validate` peak 0.23 of 2 GiB). Decision: `worker_max_instances` stays 3, so the queue cap stays 6 (2 x 3). To raise: once the tier is confirmed and an N>1 staging run shows no 429 / back-off, set `worker_max_instances` (tfvar); the dispatch cap follows as 2 x new max, then confirm `maxConcurrentDispatches` with the Cloud Tasks API.

**(b) Preview-channel authorised domain (vs SP00 task 9): wildcard REJECTED.** `onolys-app-staging--pr-*.web.app` returns `400 INVALID_AUTHORIZED_DOMAIN` (checked 2026-11-20, `testing.md` "Preview auth domains"); this is not retried. SP00 task 9 fallback (add each channel host through the Identity Toolkit API) exists as `infra/scripts/identity-config.py --domains-only --add-domain HOST` (add-only; Terraform ignores `authorized_domains` drift) but is not wired into the preview workflow. Owner decision 2026-11-21: Google sign-in on previews is not needed (email/password works there), so no workflow step and no `firebaseauth.admin` on the preview deployer. Live list today: `localhost`, `onolys.firebaseapp.com`, `onolys.web.app`, `app.onolys.com`, `onolys-app.web.app`, `onolys-app-staging.web.app`, `onolys-admin-staging.web.app`, `admin.onolys.com`, `onolys-admin.web.app`; no `pr-*` host. Closed (won't-fix, owner).

**(c) Hosting `/v1` pass-through: SP09's acceptance, referenced only.** `staging-e2e.md` Task 11(a): Hosting forwards `Authorization`, `/v1` not cached (`no-cache`, no `HIT`/`Age`), AC11 there. Spot check today: `/v1/healthz` returns 200 through `app.onolys.com`, `onolys-app.web.app` and `onolys-app-staging.web.app`.

### Owner confirmations (2026-11-21)

- AC10 prod alert email ARRIVED: "[ALERT - No severity] Onolys failed step/run (prod)" for `onolys-worker-prod` revision `onolys-worker-prod-00005-96t` (Google Cloud Alerting, 11:53 local). AC10 fully met.
- Worker `max-instances`: keep 3 (owner decision).
- Unmanaged budget `onolys`: keep (owner decision).

### Needs the owner

- DNS for `admin.onolys.com` (now on the staging admin site, 2026-11-21): `CNAME admin.onolys.com -> onolys-admin-staging.web.app` (change from `onolys-admin.web.app` if already added) and `TXT _acme-challenge.admin.onolys.com = xxXeEebxmc605rHqNrOZN69RxCiSd4SQOsPva57mgKs` (re-read `terraform output required_dns_updates` first; the TXT value is per certificate).
- Anthropic rate tier (step 7a) if `worker_max_instances` is ever raised (currently kept at 3).
- Merge PR #42 (tag job fix); then the deferred roll-forward-by-tag drill if wanted.
