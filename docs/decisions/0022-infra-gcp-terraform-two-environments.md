# 0022. Infrastructure: one GCP project, Terraform, two environments

**Audience:** contributors.

**Status:** accepted. Operating detail and resource names: [reference/infra.md](../reference/infra.md).

**Context.** The platform needs a reproducible home (hosting, API, worker, data, secrets, deploys) that one owner can run with no gcloud CLI, with small cost and no long-lived deploy keys.

**Decision.** Headlines of the SP06 decisions (D1-D18):

- **D1 Terraform**, state in GCS, run locally with ADC (not scripts or Pulumi: drift detection, IAM idempotence).
- **D2 One project, two environments**: Firestore named DB `staging` plus `(default)` for prod, per-env buckets, queues, service accounts and secrets.
- **D3 Region**: `us-central1` everywhere except STT, which uses the `us` multi-region because Chirp 3 is not offered in `us-central1`.
- **D4 Same-origin API**: Hosting site with a `/v1/**` rewrite to Cloud Run (no CORS, no load balancer).
- **D5 Deploy auth**: Workload Identity Federation with one deployer service account per env; prod trusts only the `production` GitHub environment.
  - Firebase deploys also need `firebase.projects.get` (custom role `firebaseProjectGet`, both deployers) and `firebaserules.admin` at project level: firebase-tools calls rulesets `:test`/create on the bare project resource, which IAM conditions on `resource.name` did not match (403 in CI). Trade-off: `deployer-staging` could release prod rules; accepted (same repo trust, workflow targets `firestore:staging` only). `datastore.indexAdmin` stays limited per database.
  - Hosting: `firebasehosting.admin` is also project level for both deployers (app and admin sites). Conditions on `resource.name` never matched Hosting calls (403 on `sites/<id>/versions`, run 44812626576) and Policy Troubleshooter does not support Hosting site resources. Trade-off: a deployer could deploy to any site, prod included; accepted (same repo trust; workflows target their own site only).
- **D6 Prod promotion**: the same image digest that ran in staging, after manual approval; no rebuild.
- **D7 Backups**: PITR off, no backups, GCS soft-delete 0, prod DB delete-protection on, so "delete removes everything" holds. An erroneous prod delete cannot be recovered (accepted v1 risk).
- **D8 Admin**: Hosting site plus Cloud Run, app-level email allowlist, no MFA; behind `admin_enabled` (default off, after launch).
- **D9 Secret values** are seeded by a script, never in Terraform state.
- **D10 Staging domain**: `*.web.app` only.
- **D11 Firestore rules**: owner read of `session_status/{sid}` only; every write and every other collection denied (Admin SDK bypasses rules).
- **D12 Provider keys**: `llm_secrets` / `stt_secrets` maps looped into secret shells, accessor bindings and Cloud Run env refs; adding a provider is one tfvars line, a seeded value and a route. **Amended 2026-11-20: per-environment keys.** The maps hold base ids; the environment module creates `<base>-{env}` (e.g. `anthropic-api-key-staging`, `anthropic-api-key-prod`), and each env's service accounts get accessor only on their own env's secrets. Staging and prod use separate provider keys (no shared project-level key). The old shared `anthropic-api-key` is dropped from state and removed by hand after cutover.
- **D13 STT settings** live in `config/{env}/stt_providers.yaml` in the image; no STT env vars.
- **D14 Worker sizing**: concurrency 2, max 3 instances in prod until measured; queue dispatches = concurrency x max instances.
- **D15 Version stamp**: CI sets `GIT_SHA` on api and worker; the rollback target is a sha.
- **D16 Failure visibility**: two log-based alerts (failed step/run, api 5xx) to the owner's email, plus the runbook.
- **D17 Status listener**: `VITE_FIRESTORE_DATABASE` per web build, because staging uses the named DB.
- **D18 Cut to after launch**: `infra-plan.yml` with a `tf-plan` service account, Artifact Registry cleanup policy, browser API-key restriction, Data Access audit logs. PR previews stay in v1 (SP00).

**STT location `us`.** Chirp 3 is documented for the `us` and `eu` multi-regions only. The worker therefore calls `us-speech.googleapis.com`; that is a provider option in the config file, not infrastructure.

**Dropped residency claims.** Data-residency is not a requirement the owner holds for v1, and no residency engineering or claim is made: the STT multi-region is not a promise about where data stays, and no BAA/legal work is part of this platform. LLM work goes to the Anthropic API; Google is used for speech-to-text only (no Vertex).

**Alternatives.** Two projects (more isolation, more setup and cost); collection prefixes for environments (weaker boundary); IAP behind a load balancer for admin (about $18 a month, slower to ship); a service-account JSON key in GitHub (long-lived secret in a public repo).

**Consequences.** Cold starts are accepted (min instances 0). Budgets alert but do not stop spend; caps are max instances, dispatch limits and the per-user daily run cap. `terraform apply` is manual. Rollback redeploys a previous sha through `deploy-prod`; data is not rolled back.
