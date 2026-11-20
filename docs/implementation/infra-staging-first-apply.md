# Staging first apply: verification record (SP06 Task 8)

Date: 2026-11-20. Project `onolys`, env `staging`. Re-run any time: `python3 infra/scripts/check-staging.py [--egress]` (ADC, no gcloud; tests: `python3 -m pytest infra/scripts -q`). Final reference doc `docs/reference/infra.md` should link here.

| Check | Result |
|---|---|
| `terraform plan -detailed-exitcode` after apply | exit 0, no changes |
| Seeding (`seed-secrets.py --env staging`, dev Anthropic key via env) | `uid-hmac-key-staging` and `anthropic-api-key` have a version; re-run = unchanged. Dev key, owner rotates after dev |
| `allUsers` invoker on `onolys-api-staging` | **Allowed**: binding exists, no org-policy block. `api.onolys.com` fallback not needed |
| Anonymous call to api | HTTP 200 (placeholder image) |
| Anonymous call to worker | HTTP 403 |
| Worker env | `ANTHROPIC_API_KEY` as secret ref only; no other `*_API_KEY`, no `STT_*`, no plaintext |
| Staging SA isolation | Project-level grants for `api-/worker-/tasks-invoker-/deployer-staging` are all conditioned to the `staging` DB, staging site/rulesets, or `onolys-pr-*`, except `speech.client` and `serviceusage.serviceUsageConsumer` (shared, no data). `onolys-audio-prod` and `uid-hmac-key-prod` do not exist yet (404); no staging SA is bound on them |
| Cloud Run egress to `api.anthropic.com` | **Works**: one-off Cloud Run job (python:3.12-slim via mirror.gcr.io, SA `worker-staging`) got an HTTP reply; job deleted afterwards |
| Anthropic rate tier (step 7a) | unknown, owner to confirm; worker max instances stays 3 |

Prod IAM isolation must be re-checked when prod is created (same script, prod resources then exist).
