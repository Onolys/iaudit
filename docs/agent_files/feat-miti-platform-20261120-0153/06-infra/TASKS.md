---
status: draft
summary: SP06 tasks: staging-minimal slice first (Terraform base, staging data plane + Cloud Run shells, rules, Identity Platform, WIF, first apply, deploy-staging), then alerts/budget, prod env, DNS, deploy-prod, runbook, acceptance.
date: 2026-11-20
---
# Tasks: SP06 infra — GCP resources, hosting/domains, CI/CD, config
Source of truth: 06-infra/PRD.md. Tasks 1-9 are the STAGING MINIMAL slice (SP00 previews and SP04/SP05 staging deploys wait on it; task 8 = staging live, task 9 = deploy-staging). Tasks 10-15 are alerts, prod, DNS, deploy-prod, docs, acceptance. Admin (SP07) resources exist only behind `admin_enabled=false`; no build tasks beyond the flag. Tasks needing owner steps first: 1 (GCP Owner), 6 (billing for Identity Platform), 8 (Anthropic key), 10 (alert email), 12 (DNS), 13 (GitHub `production` env).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Tooling, state bucket, Terraform skeleton | — (owner step: GCP Owner) | done |
| 2 | Project base: APIs, Artifact Registry, Hosting sites, `admin_enabled` flag | 1 | done |
| 3 | Environment module: Firestore DB, bucket, queue, service accounts (staging) | 2 | done |
| 4 | Secrets maps, `seed-secrets.py`, Cloud Run api+worker shells (staging) | 3 | done |
| 5 | Firestore rules, indexes wiring, emulator rules tests | 1 | done |
| 6 | Identity Platform, web apps, authorised domains, outputs | 2 (owner step: billing) | done |
| 7 | WIF pool + `deployer-staging` (incl. preview roles) | 3, 4 | done |
| 8 | First staging apply, seeding, IAM and egress checks | 4, 5, 6, 7 (owner step: Anthropic key) | done |
| 9 | `_deploy-cloudrun.yml` + `deploy-staging.yml` | 8, SP04 T1, SP04 T16, SP05 T1 | todo |
| 10 | Budget, failure alerts, alert email channel | 8 (owner step: alert email) | done |
| 11 | Prod environment + `deployer-prod` | 8, 10 | in-progress |
| 12 | Custom domain `app.onolys.com` + DNS output | 11 (owner step: DNS) | todo |
| 13 | `deploy-prod.yml`: gated promotion + rollback drill | 9, 11 (owner step: GitHub env) | todo |
| 14 | `docs/reference/infra.md` runbook + ADR 0022 | 10, 12, 13 | todo |
| 15 | Acceptance sweep + recorded measurements | 12, 13, 14, SP09 T8 | todo |

Parallel lanes: all of this is Lane B (platform) and goes first in that lane. After task 2, three streams can run at once: (a) 3 then 4 then 7 (module and IAM), (b) 5 (root Firestore rules; only needs 1 and the emulator), (c) 6 (project-level Identity Platform). 3/4/7 all touch the environment module, so keep them sequential; 6 only touches project-level files. 10 and 11 both edit the module, so run them one after another; 12 and 13 can then run in parallel. Sync points: SP00 `infra` job (`terraform fmt -check` + `validate`) must be green on every task that adds `infra/` files; SP00 previews wait on 2, 3, 4, 6, 7, 9; SP04 needs task 8 (staging) and ships the Dockerfile, `/v1/healthz` and `api/firestore.indexes.json`; SP05 needs task 6 outputs, task 9 and owns `web/firebase.json`; SP01 owns the contents of `config/{env}/*.yaml`; SP09 needs staging (task 8/9) and supplies the real-audio run that settles the worker-capacity measurement in task 15; SP08 prod release waits on 12/13; SP07 later flips `admin_enabled`.

## Task 1 — Tooling, state bucket, Terraform skeleton
What it is / what it means: everything Terraform needs to run from this machine with ADC and no gcloud (PRD R1, D1). Owner step first: Tejit's account is Owner on `onolys` with billing linked.
What changes at a high level: add `infra/scripts/install-tools.sh` (pinned terraform binary to `~/.local/bin`, `infra/.terraform-version`), `infra/bootstrap.sh` (curl + ADC creates the versioned private bucket `onolys-tfstate`, idempotent), and the root skeleton: pinned `google`/`google-beta` providers with `user_project_override=true` and `billing_project="onolys"`, GCS backend, variables (`project`, `region`, `admin_enabled`, `staging_alerts`, `monthly_budget_usd`, `llm_secrets`, `stt_secrets`, worker variables), no resources yet.
Done when: install script and `bootstrap.sh` run twice with the same result; `terraform init`, `fmt -check` and `validate` pass without changing the ADC quota project; `terraform plan` shows no changes; SP00's `infra` CI job (fmt + validate, no backend) passes on the branch.

## Task 2 — Project base: APIs, Artifact Registry, Hosting sites
What it is / what it means: project-level resources shared by both envs (PRD R2, R11, R12, D18 cuts).
What changes at a high level: `main.tf` enables the R2 API list (no `aiplatform`); Artifact Registry repo `onolys` in `us-central1` (no cleanup policy); Firebase Hosting sites `onolys-app` and `onolys-app-staging` created alongside landing's sites without touching them; `onolys-admin` and `onolys-admin-staging` plus the `admin_enabled` variable gating every admin resource (default `false`, `count` guard). Site ids are variables; use the `onolys-miti-app*` fallback names if an id is taken (record which). Root `.firebaserc` with targets `app`, `app-staging`, `admin`, `admin-staging`.
Done when: `terraform plan` lists the APIs, AR repo and two app sites and creates nothing for admin with `admin_enabled=false`; a plan with `admin_enabled=true` adds only admin resources (not applied); apply on this slice succeeds, a second plan is empty, `firebase hosting:sites:list` still shows landing's sites unchanged; `infra` CI job green.

## Task 3 — Environment module: Firestore DB, bucket, queue, service accounts (staging)
What it is / what it means: the data plane and identities for one env, instantiated for `staging` first (PRD R5, R6, R7, R9, D2, D7).
What changes at a high level: `infra/modules/environment/` creating the named Firestore DB (`staging`; `(default)` for prod; native, `us-central1`, PITR off, no backups, delete-protection variable), bucket `onolys-audio-{env}` (uniform access, public access prevention enforced, no versioning, soft-delete 0, `uploads/` 1-day lifecycle, CORS per env), Cloud Tasks queue `steps-{env}` (`max_attempts=2`, 5-30 s backoff, 5/s, dispatches computed as worker concurrency × max-instances), SAs `api-`, `worker-`, `tasks-invoker-{env}` with the R9 roles bound at resource level (DB-name condition, self token-creator, enqueuer, `serviceAccountUser` on tasks-invoker), and the Speech-to-Text service agent `objectViewer` on the bucket.
Done when: `terraform validate` and `plan` for `staging` show exactly the expected resources; after apply the bucket reports public access prevention enforced, soft-delete 0, CORS and lifecycle present; queue config shows max_attempts 2 and dispatches 6; DB `staging` exists with PITR disabled; second plan empty; `infra` CI green.

## Task 4 — Secrets maps, seed script, Cloud Run api + worker shells (staging)
What it is / what it means: provider keys as config and runnable service shells so deploys and previews have something to update (PRD R8, R10, R14, D9, D12).
What changes at a high level: `llm_secrets` (default `ANTHROPIC_API_KEY = "anthropic-api-key"`) and `stt_secrets` (empty) looped into secret shells, `secretAccessor` bindings (worker; admin-backend only under the flag) and Cloud Run secret refs; `uid-hmac-key-{env}` shell; `admin-allowed-emails-{env}` shell behind `admin_enabled`. `infra/scripts/seed-secrets.py` writes values (random HMAC key, supplied keys) outside state. Cloud Run `onolys-api-{env}` and `onolys-worker-{env}` with R8 limits, public placeholder image, `lifecycle.ignore_changes` on image and `GIT_SHA`, invokers (`allUsers` on api, tasks-invoker only on worker), and the R14 non-secret env vars (`FIRESTORE_DATABASE`, `ROUTES_FILE`, `DEFAULT_PRESET`, no STT vars). Admin-backend service behind the flag.
Done when: plan shows the new secrets/services; adding a second `llm_secrets` line in a scratch tfvars plans exactly one shell, its bindings and env refs and changes nothing else; `stt_secrets = {}` plans nothing; seed script is idempotent and leaves no value in `terraform show`; worker env has no `STT_*` var; `infra` CI green.

## Task 5 — Firestore rules, indexes wiring, emulator rules tests
What it is / what it means: client access to Firestore limited to an owner reading their own status doc (PRD R5, D11, D17). Owns only root files.
What changes at a high level: root `firestore.rules` (owner read of `session_status/{sid}` via `resource.data.uid`; everything else denied, all writes denied), root `firebase.json` listing both DBs with rules and `api/firestore.indexes.json`, a rules test suite run against the Firestore emulator (location agreed with SP00's `api` job emulator setup).
Done when: emulator tests pass for: owner reads own `session_status`; another user denied; all client writes denied; every other collection denied; listener cases (doc created as SP04's `POST /sessions` does, owner subscribes right after create and succeeds; another user's listen denied; listen on a missing doc denied); `firebase deploy --only firestore --dry-run`-style validation of the rules file passes; the tests run in CI where the emulator job exists (SP00).

## Task 6 — Identity Platform, web apps, authorised domains, outputs
What it is / what it means: auth config and the public web config SP05 builds against (PRD R4, R13 preview addition, D17). Owner step: billing linked so Identity Platform can upgrade.
What changes at a high level: `google_identity_platform_config` for email+password, min length 8 (REST-patch script as fallback if the provider lacks the password policy), open sign-up, enumeration protection, no MFA; authorised domains per R4 plus the staging preview channel hosts; one Firebase web app per host; outputs of `VITE_FIREBASE_*` and `VITE_FIRESTORE_DATABASE` per env. Try the wildcard `onolys-app-staging--pr-*.web.app`; if the API rejects it, record that and use the per-channel-host fallback from R13 (each host the SP00 workflow reports, added via the Identity Toolkit API).
Done when: plan/apply succeeds; reading the live config shows email sign-up on, min password length 8, no MFA, all authorised domains present; the wildcard outcome and chosen fallback are written down for SP00 task 9; outputs print the expected variable names; second plan empty; `infra` CI green. Google sign-in and email templates stay owner console steps.

## Task 7 — WIF pool and deployer-staging
What it is / what it means: keyless GitHub deploys for staging and for SP00's previews (PRD R9, R13, D5).
What changes at a high level: Workload Identity pool+provider `github` with condition `repository=='Onolys/onolys'` (fork PRs never match); `deployer-staging` SA with `run.developer` on staging services, `serviceAccountUser` on runtime SAs, AR writer, Hosting admin on `onolys-app-staging`, `firebaserules.admin` + `datastore.indexAdmin` on DB `staging`; plus the preview grants: Cloud Run admin conditioned on resource names `onolys-pr-*`, `serviceAccountUser` on `api-staging`, Hosting channel rights. Outputs: WIF provider name and deployer email.
Done when: `plan` shows only these resources; after apply, impersonation from a test workflow run in the repo succeeds and a run outside the repo condition is refused; the IAM condition on `onolys-pr-*` is visible in the policy and an attempt to deploy a differently named service is denied; second plan empty; `infra` CI green.

## Task 8 — First staging apply, seeding, IAM and egress checks
What it is / what it means: staging is live and verified before anything deploys to it (PRD R8 resolved checks, R10, AC1-4). Owner step: Anthropic API key supplied (and its rate tier, step 7a).
What changes at a high level: full staging `terraform apply`; run `seed-secrets.py` for the Anthropic key and HMAC key; record the org-policy result for `allUsers` on the api service (fallback `api.onolys.com` domain mapping if blocked) and verify Cloud Run egress to `api.anthropic.com`; run the IAM checks.
Done when: a second `terraform plan` shows no changes; anonymous call to api placeholder returns 200/404 (invokable) and to worker returns 401/403; a staging SA cannot read the (not yet created) prod resources per its role list (checked from policy output); worker has `ANTHROPIC_API_KEY` ref only; egress test result recorded; the `allUsers` outcome recorded (with fallback chosen if blocked). Staging minimal resources are now usable for SP04/SP00.

## Task 9 — _deploy-cloudrun.yml and deploy-staging.yml
What it is / what it means: the merge-to-main path to staging (PRD R13, R14 config guard, D5, D15). Needs SP04's Dockerfile and `/v1/healthz` and SP05's buildable `web/`; owner step: set GitHub repo variables from Terraform outputs.
What changes at a high level: reusable `_deploy-cloudrun.yml` (`workflow_call`, inputs `env`, `service`, `image`, `region`, WIF impersonation, deploy by digest); `deploy-staging.yml` on push to `main` after CI: build the image once, tag sha, push to AR, deploy api+worker with `GIT_SHA`, deploy Firestore rules/indexes to `staging`, build+deploy `web/` to `app-staging` with `VITE_FIRESTORE_DATABASE=staging`, smoke `GET /v1/healthz` through the Hosting rewrite. A guard step fails if `config/{staging,prod}/{routes,stt_providers}.yaml` is missing or not in the image. Per-env concurrency, `cancel-in-progress: false`, no JSON keys.
Done when: actionlint passes (in SP00's CI); a real run on main deploys with WIF and the smoke returns 200 through `https://<staging-site>.web.app/v1/healthz`; api and worker revisions carry `GIT_SHA` equal to the commit; the guard fails when a config file is removed on a scratch branch; a signed PUT from the staging origin passes CORS.

## Task 10 — Budget, failure alerts, alert email channel
What it is / what it means: cost visibility and owner notification on failures (PRD R15, R16, D16). Owner step: confirm alert email and click the verification mail.
What changes at a high level: `google_billing_budget` from `monthly_budget_usd` (alerts 50/90/100% actual, 100% forecast); Monitoring email channel; per env two alerts: log-match on `jsonPayload.status="failed"` from api/worker (1 per 5 min rate limit) and a log-based 5xx metric (`httpRequest.status>=500`, more than 5 in 5 min); staging alerts behind `staging_alerts` (default off).
Done when: plan/apply succeeds; budget and thresholds visible via API; with `staging_alerts=true` a test log line with `status=failed` sends one email, then the flag is set back; the 5xx metric and alert policy exist; the runbook log query (`jsonPayload.request_id=...`) finds that line; `infra` CI green.

## Task 11 — Prod environment and deployer-prod
What it is / what it means: second instance of the module, isolated by DB and IAM (PRD R5-R9, R13, D2, D6, AC3, AC6).
What changes at a high level: module call for `prod`: DB `(default)` with delete-protection on, `onolys-audio-prod` with prod CORS (`https://app.onolys.com`), queue (dispatches 6 from 2 × 3), api max 10 / worker max 3 services, SAs, secret shells, alerts on; `deployer-prod` with `run.developer`, AR reader, Hosting admin on `onolys-app`, rules/index admin on `(default)`, trusting only the `production` GitHub environment in the WIF binding. Seed prod secrets.
Done when: plan then apply succeed; second plan empty; policy output proves staging SAs have no role on prod bucket/DB and vice versa; prod worker anonymous call is 401/403; prod deployer impersonation is refused from the staging workflow and from a non-`production` job (test run); `infra` CI green.

## Task 12 — Custom domain app.onolys.com and DNS output
What it is / what it means: production URL, with the exact DNS values handed to Tejit (PRD R11, manual step 3, D10). Owner step: add the DNS records.
What changes at a high level: `google_firebase_hosting_custom_domain` for `app.onolys.com` on `onolys-app` (the `admin.onolys.com` domain behind `admin_enabled`); Terraform output `required_dns_updates` with exact TXT/A values; staging stays on `*.web.app` only.
Done when: apply succeeds; the output lists the real records for `app.`; after Tejit adds them, the domain status reads verified and the certificate active, and `https://app.onolys.com/v1/healthz` returns 200 once prod is deployed (task 13); plan with `admin_enabled=true` adds the admin domain but is not applied.

## Task 13 — deploy-prod.yml: gated promotion and rollback drill
What it is / what it means: prod deploys the exact image that ran in staging, behind approval (PRD R13, D5, D6, AC6, AC9). Owner step: create GitHub environment `production` with Tejit as required reviewer and set prod repo variables.
What changes at a high level: `deploy-prod.yml` on `workflow_dispatch` (input image sha, default latest staging-deployed) or tag `v*`, environment `production`; checks out that sha, promotes the same digest (no rebuild) to prod api+worker via `_deploy-cloudrun.yml` with `GIT_SHA`, deploys rules/indexes to `(default)`, builds and deploys `web/` to `app` with `VITE_FIRESTORE_DATABASE=(default)`, smoke test; concurrency per env.
Done when: actionlint passes; a run waits for approval, then deploys the staging digest (digest equal in both envs); smoke `GET https://app.onolys.com/v1/healthz` returns 200; prod revisions carry the right `GIT_SHA`; rollback drill once: dispatch with an earlier sha and see api, worker, web and rules redeployed from that commit.

## Task 14 — Infra runbook and ADR
What it is / what it means: the reference the owner and agents use to operate and debug (PRD R14, R16, AC8).
What changes at a high level: `docs/reference/infra.md` with resource names, env var table, outputs (incl. `VITE_FIRESTORE_DATABASE`), the exact `app.`/`admin.` DNS records copied from Terraform output, how to add an LLM/STT provider (tfvars line + seed + route), the runbook (reference id to log query to `session_id`/`run_id` trail; `error_code` table with the usual fix) and the rollback line; `docs/decisions/0022-infra-*` recording D1-D18 headlines, the STT `us` choice and dropped residency claims.
Done when: every resource name and command in the doc was checked against live Terraform output or a run (no stale names); the documented log query was run against the test line from task 10; the DNS section matches `required_dns_updates` verbatim; the repo docs check, if any, passes.

## Task 15 — Acceptance sweep and recorded measurements
What it is / what it means: tick the PRD acceptance criteria and record the build-time measurements with their fallbacks (PRD AC1-10, R8, R13).
What changes at a high level: walk AC1-10 and record evidence in the infra doc. Record the open-until-measured items: (a) worker `max-instances` stays 3 prod/staging until the Anthropic rate tier (owner step 7a) and an SP09 staging run are measured; if the tier allows, raise the tfvar and confirm queue dispatches follow (6 becomes 2 × new max); fallback: keep 3. (b) Preview-channel authorised domain outcome from task 6 confirmed against SP00 task 9. (c) Hosting `/v1` pass-through is SP09's acceptance, only referenced.
Done when: a `terraform plan` on both envs is empty; AC1-10 each have a recorded result (AC10 includes the alert test line); the worker capacity decision and its evidence are recorded whichever way it goes; no unresolved item left except those handed to SP09.

## Owner steps
Owner-only (Tejit), from the PRD Manual steps:
1. Confirm Owner on `onolys`, Billing Account Administrator on the billing account, billing linked (before task 1/6).
2. Choose `monthly_budget_usd` and confirm the alert email; click the channel verification mail (task 10).
3. Add DNS records for `app.onolys.com` from `required_dns_updates` (task 12); remove conflicting AAAA/CAA. `admin.onolys.com` only after SP07.
4. Firebase console: enable Google sign-in; add `https://app.onolys.com/__/auth/handler` (and staging host) to the OAuth client.
5. Customize verification/reset email templates; set sender domain `onolys.com` and add the DKIM/SPF DNS records the console shows.
6. Create GitHub environment `production` with himself as reviewer; set repo variables from Terraform outputs (WIF provider, deployer emails, `VITE_FIREBASE_*`, `VITE_FIRESTORE_DATABASE` per env) (tasks 9, 13).
7. Supply the Anthropic API key for seeding; confirm its rate-limit tier (task 8, 15).
8. After SP07 only: admin allowlist emails (value of `admin-allowed-emails-{env}`).
9. If task 6 shows wildcard authorised domains are rejected and the API fallback cannot manage them, add the staging preview channel hosts in the Identity Platform console.
