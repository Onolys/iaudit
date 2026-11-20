---
status: draft
summary: "Design: 10 PRDs (SP00 foundation: CI, testing, PR previews; SP07 admin after launch), r7 audit + r8 decisions applied (no Playwright, 3 build lanes), tasks generated (r8), ready for dev-code"
date: 2026-11-20
---

# feat/miti-platform

Branch folder for the Onolys MITI platform (`app.onolys.com`). Brief: [brainstorm.md](brainstorm.md) (approved 2026-11-20). Ten PRDs are written and reconciled against each other (seams, names, fields, states, error codes, env vars, paths, commands). Tejit's round-5 to round-8 answers (2026-11-20) are applied; round 8 added SP00 (CI + testing first, per-PR previews, no Playwright, 3 parallel lanes); round 7 followed an audit by two reviewers (fixes, 4 scope cuts, 3 additions). Tasks are generated (10 `TASKS.md`, 121 tasks, see the table). Next step is `dev-code`. Goal: the platform up and running fast, professional enough for the first early-access users. Hard requirement: the LLM and speech-to-text (STT) models are swappable by config or one small adapter. The eval harness is not a priority and may break.

## Sub-projects

| # | Folder | PRD | Tasks | Scope | Depends on | When |
|---|---|---|---|---|---|---|
| 00 | `00-foundation/` | [PRD](00-foundation/PRD.md) (draft) | [TASKS](00-foundation/TASKS.md) (9) | CI + test conventions first (pytest markers `unit`/`integration`/`live`, vitest, per-package `ci.yml` jobs skipped until the package exists, no Playwright); per-PR preview (`pr-preview.yml`: Cloud Run `onolys-pr-<N>` combined mode + fake adapters, Hosting channel `pr-<N>`, PR comment) and cleanup on close; `docs/reference/testing.md`. | CI: none; preview: 06 staging minimal, 04 combined mode, 05 `web/` | Start of build (CI), preview once 04/05/06 minimal exist |
| 01 | `01-core/` | [PRD](01-core/PRD.md) (draft) | [TASKS](01-core/TASKS.md) (13) | One PR: move `eaudit/` → `engines/eaudit/`; shared `engines/core/` (`onolys_core`): LLM client with task-named routes + presets (all default routes Claude Sonnet via the Anthropic API), provider-neutral STT (`SttAdapter.start/poll`, adapters return words, `words_to_turns`, `stt_providers.yaml`, Google Chirp 3 adapter), transcript types, `locate`, typed errors, `RunInfo`, PHI-safe logging; live STT check + LLM smoke as a gate before SP02; `docs/mission.md` + `AGENTS.md` widened. Existing `POST /v1/audit` tests still pass. | — | Slice 0 (parallel track) |
| 02 | `02-paudit-miti-pack/` | [PRD](02-paudit-miti-pack/PRD.md) (draft) | [TASKS](02-paudit-miti-pack/TASKS.md) (14) | Protocol pack format; `protocols/miti-4.2.1/`; `engines/paudit/`: volley/utterance coding, globals with cited lines, summary scores, `n_runs` (default 1); routes `paudit_code`/`paudit_globals`; `rating.schema.json` = the in-app rating card; live `python -m paudit.cli check`. | 01 (gate passed) | Slice 0 (parallel track) |
| 03 | `03-evaluation/` | [PRD](03-evaluation/PRD.md) (draft) | [TASKS](03-evaluation/TASKS.md) (10) | `engines/evaluation/`: `validate_rating` (draft/final), reasons audit via eaudit with optional `profile` (suppress list + context note), per-item compare, 3-5 tips (route `tips`), versioned report JSON; one entry point `run_evaluation(..., progress_cb)`; live `python -m onolys_evaluation.check`. | 01, 02 | before Slice 1 |
| 04 | `04-api-jobs/` | [PRD](04-api-jobs/PRD.md) (draft) | [TASKS](04-api-jobs/TASKS.md) (16) | `api/`: public `/v1` API (every mutation returns 202 + ids), Identity Platform tokens + personal API keys, signed-URL upload (≤300 MB) + transcode to canonical FLAC, Cloud Tasks worker (`validate`, `transcribe` + polls, ONE `run` task), PHI-free `session_status/{id}` doc, state machine with `awaiting_input` + flags, rating drafts/revisions, versioned reports, daily cap, delete, `/v1/docs`. Built and accepted on fake adapters. | 01 (interfaces) | Slice 0 |
| 05 | `05-web-app/` | [PRD](05-web-app/PRD.md) (draft) | [TASKS](05-web-app/TASKS.md) (14) | `web/` (app.onolys.com): sign-up/in, upload, speaker check, rating card with autosave + notes box, live status via Firestore `onSnapshot`, report page, session-list dashboard, public `/sample-report`, settings (API key). Languages `en-US`, `en-GB`, `auto`. | 04 API contract, 03 report schema | Slice 0 |
| 06 | `06-infra/` | [PRD](06-infra/PRD.md) (draft) | [TASKS](06-infra/TASKS.md) (15) | GCP project `onolys`: Identity Platform, Firestore (`(default)` prod + `staging`) with rules, buckets, Cloud Run api/worker, Cloud Tasks (dispatches ≤ worker concurrency × max-instances), Secret Manager (`llm_secrets`/`stt_secrets` maps), Hosting, WIF deploys with `GIT_SHA`, failure alerts + runbook + rollback, budget; Terraform. Admin resources only with SP07. | — | Slice 0 (staging), then prod |
| 07 | `07-admin/` | [PRD](07-admin/PRD.md) (draft, **after launch**) | [TASKS](07-admin/TASKS.md) (13) | `admin.onolys.com`: eaudit review UI + paudit tab behind an email allowlist. Cut from v1 (r7); until then results are inspected with `python -m paudit.cli` locally and the run artifacts in GCS. | 01, 02, 06 | After launch |
| 08 | `08-landing/` | [PRD](08-landing/PRD.md) (draft) | [TASKS](08-landing/TASKS.md) (5) | Repo `onolys-landing` (local `/root/projects/onolys/miti`): top right = "Sign up" + "Log in" → app; every other "Get early access" CTA becomes "Try it out" → `${PUBLIC_APP_URL}/signup`; early-access components kept, unused; click analytics after launch. PRD lives here; code goes to that repo. | — (release after 05/06 live) | any; release with prod |
| 09 | `09-integration/` | [PRD](09-integration/PRD.md) (draft) | [TASKS](09-integration/TASKS.md) (12) | Real `Stt` + `Evaluation` adapters in the worker, engine-error → public-code mapping, run artifacts + `run_info`, staging end-to-end on real audio (web + API key), the staging checks SP04/05/06 handed over. | 02, 03, 04, 06 (05 for the web check) | Slice 1 |

## Dependency graph and build order (3 parallel lanes, r8)
```
Start     00 CI + test conventions (Lane C, first; nothing else starts before CI is green on main)
Lane A  engine:    01 core (workspace PR lands first) ─► gate (STT check + LLM smoke) ─► 02 paudit ─► 03 evaluation
Lane B  platform:  06 infra minimal (staging) ─► 04 api+jobs (stub pipeline) ─► 09 integration (needs 02, 03, 04, 06)
Lane C  web:       00 CI ─► 05 web on MSW mocks ─► 00 PR preview (needs 06 staging minimal + 04 combined mode + 05 buildable) ─► 08 landing
Prod      06 prod env + DNS ─► deploy-prod ─► 08 landing release
After launch: 07 admin
```
| Sync point | Why |
|---|---|
| SP01 workspace PR lands first | SP04 needs its types/workspace; SP00's eaudit CI path changes with the move |
| SP03 report schema -> SP05 | web types are generated from `report.schema.json` |
| SP04 `api/openapi.json` -> SP05 | generated client; until then SP05 builds on MSW mocks |
| SP06 staging minimal + SP04 skeleton + SP05 buildable -> SP00 preview | preview deploys api image + `web/` |
| SP09 needs 02, 03, 04, 06 | real adapters, staging end-to-end |
- **Slice 0:** CI first; SP06 minimal + SP04 stub pipeline + SP05 on mocks, deployed to staging; in parallel the SP01 gate and SP02 `paudit.cli` on one real transcript.
- **Slice 1:** SP09 real adapters (needs SP03 done). **Then prod.**
- Three people, three lanes (A, B, C); each lane builds its sub-projects one after another. The old max-2 cap is replaced by this (r8).

## Lane start
First tasks with no dependencies (start today; all Status `todo`). Task numbers are per sub-project (`SPxx Tn`).

| Lane | Person starts today | Then (needs a sync point below) |
|---|---|---|
| A engine 01 → 02 → 03 | SP01 T1 (workspace + types; push first). Then SP01 T7 (STT core) after T1 | SP01 T2/T3 after SP00 T2 is green; SP02 T1 after SP01 T1; SP02 T8+ after SP01 T3, T5, T6 |
| B platform 06 → 04 → 09 | SP06 T1 (Terraform skeleton; owner step: GCP Owner). Then SP06 T2, T5 | SP04 T1 after SP01 T1; SP09 T1, T7 after SP01 / SP04 pieces |
| C CI → web → previews → landing | SP00 T1 and SP00 T2 (parallel), SP05 T1 (scaffold, no deps), SP08 T1 (no deps; release waits on prod) | SP00 T3-T5 after T2; SP00 T7 after previews inputs below |

Rule: lanes A and B open no feature PR until SP00 T2 is green on main.

Cross-lane sync points:
- SP00 T2 → SP01 T2 (eaudit CI path); SP00 T3-T5 light up when SP01/SP02/SP03/SP04/SP05 add packages
- SP01 T1 → SP02 T1, SP03 T1, SP04 T1, SP07 T1
- SP01 T13 (gate) → SP02 T14; the gate also precedes SP02 T8 live use
- SP02 T2 (rating schema) → SP03 T1, SP04 T10, SP05 T6
- SP02 T3 (result schema) → SP03 T1
- SP03 T1 (report schema) → SP04 T12, SP05 T13
- SP04 T1 (openapi + combined mode) → SP05 T13, SP00 T7; SP04 T15 (final openapi) → SP05
- SP04 T16 (Dockerfile) → SP06 T9; SP05 T1 (buildable `web/`) → SP06 T9, SP00 T7
- SP06 T9 (staging deploy) → SP00 T7 (preview); SP06 T8 (staging apply) → SP09 T8
- SP03 T9 (`run_evaluation`) → SP09 T3; SP04 T6 (adapter Protocols) → SP09 T2, T3; SP04 T12 → SP09 T4, T5
- SP05 T14, SP06 T9, SP06 T10 → SP09 T8; SP09 T8 → SP06 T15
- SP06 T12, T13 (prod domain + deploy-prod) → SP08 release

## Swapping models
| Swap | What changes | Checks to run |
|---|---|---|
| LLM, same provider | One line in the routes YAML (`config/{env}/routes.yaml`, the route's `litellm_id`) | `python -m paudit.cli check` and `python -m onolys_evaluation.check` |
| LLM, other provider | Routes YAML (id, `api_key_env`, `structured_output_mode`, `caching_mode`) + one `llm_secrets` line in tfvars + the secret value seeded | `python -m onolys_core.llm.smoke`, then the two checks above |
| STT | One adapter (`start/poll` → words) + one `stt_providers.yaml` entry + optional `stt_secrets` line | `python -m onolys_core.stt.check` |
No engine, API or web code changes in any of the three.

## Locked decisions
See the Decision log in [brainstorm.md](brainstorm.md) (round-6 and round-7 rows supersede its older Design text). Headlines:
- Clinician self-rates a mock MI session with MITI 4.2.1; Onolys rates independently, compares per item, explains differences with transcript lines ("Onolys disagrees, here's why"), gives 3-5 tips. Not official MITI coding.
- API-first; the web app uses the public `/v1` API plus one read-only Firestore listener on its own PHI-free status doc; personal API keys; every mutation returns 202; the only human gate is speaker confirmation; the rating is an in-app card (autosaved drafts, final revisions).
- One Cloud Task runs the whole evaluation (`run_evaluation`); paudit failure fails the run, eaudit/tips failure still ships the report with a warning.
- All Google Cloud, project `onolys`, `us-central1` (STT Chirp 3 standard recognition in the `us` multi-region); Google is used for speech-to-text only; all LLM work is Claude Sonnet via the Anthropic API; both are config (routes file + presets, `stt_providers.yaml`).
- Engines generic (`engines/{core,eaudit,paudit,evaluation}`), MITI lives in `protocols/miti-4.2.1/`; "models propose, code decides".
- Open sign-up; staging + prod in one project (Firestore DB `staging` / `(default)`); `app.` is a Hosting site with `/v1/**` rewritten to Cloud Run (same origin).
- Delete = hard delete (audio, transcript, ratings, all report versions, run artifacts); PITR off; auto-expiry off by default.
- After launch (r7 cuts): the admin site (SP07); web Advanced settings, `GET /presets`, multi-run range UI; plan CI workflow (`infra-plan.yml`), access log, per-request rate counters, toy second pack + malformed-pack tests, dual contract versions, two-PR split with shims, landing analytics events, dashboard stat tiles, browser API-key restriction; timestamp-hinted retrieval in eaudit.
- r8 [RESOLVED: Tejit r8 (2026-11-20)]: CI + testing set up first (SP00); every PR gets a preview deployment (`pr-preview.yml`, fake adapters by default); no Playwright for now (Vitest/MSW flow tests + manual click-through on the preview); three people build in parallel in 3 lanes.
- Cut earlier: PDF export, teams, billing, email notifications, dashboard trends, transcript editing, non-English reports.

### Seams (names as they stand after r7)
- Report JSON = SP03 `report.schema.json` (SP04 stores verbatim, SP05 renders); header carries `stt`, `preset`, `code_version`.
- `run_evaluation(ctx, pack, transcript, speaker_map, params, rating, paudit_result, progress_cb) -> EvaluationOutput{report, artifacts{paudit, eaudit, tips}}`; `progress_cb(stage, status)`, stage `paudit|eaudit|tips|compare|assemble`, status `started|done|failed`; report warnings `reasons_audit_failed`, `reasons_audit_partial`, `tips_failed`.
- States `created|uploading|validating|transcribing|awaiting_input|running|report_ready|failed|deleting`; flags `transcript_ready, speaker_confirmed, rating_submitted, has_rating`; `first_run_id`.
- Routes `cheap|mid|strong`, `paudit_code`, `paudit_globals`, `tips`; preset = `{routes, stt: <key in stt_providers.yaml>}`; env `ROUTES_FILE`, `DEFAULT_PRESET`, `FIRESTORE_DATABASE`, `GIT_SHA`, `ADAPTERS`, `VITE_FIRESTORE_DATABASE`; no STT env vars (`stt_providers.yaml` sits next to the routes file).
- Paths: `uploads/{uid}/{sid}/{upload_id}` (staging prefix), `{uid}/{sid}/audio/{original.{ext},canonical.flac}`, `{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json`.
- Transcription error codes `no_speech`, `speakers_not_separated`, `transcription_failed`; cap code `daily_cap_reached`; engine errors map to public codes in SP09 R3.
- Time target: ≤5 min from run start to `report_ready` at N=1 (paudit ≤90 s p95); transcription time is separate and measured.
- Queue rule: Cloud Tasks `max_concurrent_dispatches` ≤ worker concurrency × max-instances (6 in prod).
- `coded_span{from_s,to_s}` everywhere; eaudit `profile` passthrough (contract `0.0.2`); `evaluation:` pack block; public `paudit.formula.evaluate`; ADR numbers 0017 SP01, 0018 SP02, 0019 SP03, 0020 SP04, 0021 SP05, 0022 SP06, 0023 SP07.

## Cross-cutting risks / open questions
Remaining open items (all are measurements, none needs a decision from Tejit):

| PRD | Open item | What settles it | Who |
|---|---|---|---|
| SP01 | [OPEN until the gate runs] `json_object` mode through LiteLLM on the default route; Chirp 3 word offsets and diarization with `language: auto`; p95 transcription time for 25 min | The gate (`onolys_core.llm.smoke` + `onolys_core.stt.check`); its decision table says what changes (other STT entry, `auto` dropped, `json_schema`) | build |
| SP02 | [OPEN until measured] Token defaults (`code_max_tokens` 8000, `globals_max_tokens` 3000) and the ≤90 s p95 target | `python -m paudit.cli check`; tune pack `params` | build |
| SP09 | [OPEN until measured] ≤5 min run-start-to-report target and transcription time on real 25-min audio | Staging end-to-end run; levers are route config and `worker_max_instances` | build |
| SP09 | [OPEN until measured] `validate` peak memory with a 300 MB upload | Staging run; fallback worker memory 4 GiB or concurrency 1 | build |

Cross-cutting risks:
- **Quality vs experts.** AI-vs-expert agreement on globals is only moderate; Claude Sonnet coding quality is measured on Tejit's transcripts later (SP02/SP03 deferred). The report says "not official MITI coding".
- **STT gate outcome.** The gate may force another STT model/provider or drop `auto`; the adapter + `stt_providers.yaml` keep that a small change (SP01).
- **LLM rate limits.** Up to 6 runs at once in prod, each with many calls; the client backs off, so runs slow down rather than fail. The Anthropic key's rate tier decides when `worker_max_instances` can rise (SP06/SP09).
- **Verification email in spam** unless the sender domain has DKIM/SPF (SP06 manual step 5a).
- **Hard delete is final.** PITR off and no backups: an erroneous prod delete cannot be undone (accepted, SP06). Delete race / mid-run cancel is not handled in v1 (SP04, deferred).
- **Budget alert is not a cap**; spend is bounded by Cloud Run max-instances, the dispatch rule and the daily run cap (SP06).
- **Large uploads on iOS Safari** and the Google popup: redirect fallback + manual phone check (SP05/SP09).
- **Hosting rewrite** must forward `Authorization` and not cache `/v1`; fallback `api.onolys.com` + CORS (SP09 check).
- Diarization errors on role-plays stop early with `speakers_not_separated` instead of producing a wrong report (SP04).

**Resolved/deferred by Tejit 2026-11-20 (round 7, after the audit):** see the r7 rows of the Decision log in [brainstorm.md](brainstorm.md). In short: single run task + partial-failure rule; `awaiting_input` + flags + first-run transaction; rating autosave and revisions; provider-neutral STT + canonical FLAC + 300 MB cap; task-named LLM routes with rate-limit backoff and warm-then-fan-out; run record fields; four live checks with a gate; API additions; SP09 integration; 4 cuts and 3 additions. Supersedes round 6 on: timestamp-hinted retrieval (now After launch), the admin site (now After launch), per-stage tasks, two wait states.

**Resolved/deferred by Tejit 2026-11-20 (round 6):**
- Tips timing (SP03): tips start when paudit finishes (they need its counted instances) and run alongside eaudit; paudit and eaudit run in parallel. Rating-card example text capped at 1,000 chars. [RESOLVED]
- Models (A): Google = speech-to-text only; all LLM work on Claude Sonnet via the Anthropic API through the LiteLLM client, key `ANTHROPIC_API_KEY` in Secret Manager; routes swappable by config. [RESOLVED] [DEFERRED: Claude Sonnet quality on Tejit's transcripts]
- STT (B): Chirp 3 standard recognition (not dynamic batch), cost not a concern, from `us`; STT service agent gets bucket read. [RESOLVED]
- Rating input (C): in-app rating card only plus ONE separate "Additional notes / evaluation reasoning" box (≤3,000) audited by eaudit as extra claims, not parsed; soft caps in UI, hard limits at API; `validate_rating` kept. [RESOLVED]
- Async + listeners (D): every mutation returns 202; worker writes PHI-free `session_status/{id}`; Firestore rules = owner read only, all writes server-only; web uses `onSnapshot`. [RESOLVED]
- Speed (E): transcription starts at upload complete; rating card filled meanwhile; run starts once transcript + speaker confirm + final card (or "no rating") are in; paudit and eaudit in parallel, tips after paudit; prompt caching with one warm call first. [RESOLVED]
- Delete race / mid-run cancel (F, SP04): not handled in v1. [DEFERRED: edge case, Tejit]
- Auth (G): Identity Platform sign-in, password min 8 chars, no second factor; admin = email allowlist. [RESOLVED]
- Admin (H): eval server/Eval tab not deployed [DEFERRED]; the admin site itself moved to After launch in r7.
- Eval harness (I): may break; fix if cheap, else disable/skip blocking eval CI jobs. [RESOLVED]
- eaudit for MI (J): suppress list + `context_note`; contract details may change with a `schema_version` bump; tips retry once. [RESOLVED] (timestamp-hinted retrieval moved to After launch in r7)
- Accepted defaults (K): SP02 "mm-hm" (any other-speaker turn breaks a volley); SP05 email-action handler (default Firebase handler); SP06 org policy `allUsers` invoker (check at first apply, fallback `api.onolys.com`, verify egress to `api.anthropic.com`); SP06 Hosting site ids (fallback names if taken). [RESOLVED]

**Resolved/deferred by Tejit 2026-11-20 (round 5):**
- Deletion backup retention (SP04): not a blocker; engineering defaults kept (PITR off, soft-delete 0). [RESOLVED]
- Coded span partial turns (SP02): include any clinician turn that overlaps the span. [RESOLVED]
- Certified-coder review of coding prompts, real transcripts and ratings (SP02, SP03): Tejit supplies later; build and test on synthetic fixtures now. [DEFERRED: Tejit supplies transcripts and coder ratings]
- Landing CTAs (SP08): top right = Sign up + Log in only; every other "Get early access" CTA becomes "Try it out" -> app sign-up; early-access component kept. [RESOLVED]
- Account-removal contact (SP05): Tejit's Onolys contact address, filled by Tejit before launch. [RESOLVED]

## Manual steps for Tejit
Owner-only tasks, consolidated from the PRDs (agents supply exact values where noted). Steps marked "Slice 0" are needed first.
1. **GCP access (Slice 0):** confirm his Google account is Owner on project `onolys` and Billing Account Administrator on the linked billing account; billing linked (SP06). Confirm Speech-to-Text v2 API enabled and Chirp 3 usable in the `us` multi-region (SP01/SP06).
2. **Budget and alert email:** choose `monthly_budget_usd` (placeholder 50); confirm the email address for budget and failure alerts and click the channel verification mail (SP06).
3. **Anthropic key (Slice 0, for the SP01 gate):** supply the Anthropic API key (secret `anthropic-api-key`, env `ANTHROPIC_API_KEY`; required, all LLM work uses it) and confirm its rate-limit tier (decides when worker max-instances can go above 3) (SP01/SP06/SP09).
4. **Audio samples:** one 2-speaker sample of at least 5 min for the STT check (SP01 gate; minimum lowered from 10 min, owner decision 2026-11-20, real sample is 6.7 min); 2-3 real mock-interview recordings of 10-25 min for the staging end-to-end run (SP09); keep real data out of the repo and images.
5. **Auth console steps:** enable Google sign-in; add `https://app.onolys.com/__/auth/handler` (and the staging host) to the OAuth client redirect URIs; customise verification/reset email templates; set the custom sender domain `onolys.com` and add the DKIM/SPF DNS records the console shows (SP05/SP06).
6. **DNS (prod):** add records for `app.onolys.com` after `terraform apply` prints them (TXT `hosting-site=…` + A, expected `199.36.158.100`; remove conflicting AAAA/CAA). Staging uses `*.web.app` only (SP06).
7. **GitHub:** create environment `production` with himself as required reviewer; set repo variables from Terraform outputs (WIF provider, deployer SA emails, `VITE_FIREBASE_*`, `VITE_FIRESTORE_DATABASE` per environment: `staging` / `(default)`) (SP06). In `onolys-landing`: set variable `PUBLIC_APP_URL` (empty = prod default); release the landing only after `app.onolys.com` serves `/signup` and `/login` (SP08).
8. **Phone check:** sign-in and a large upload on an iPhone against staging (SP09).
9. **Data for tuning (not a launch blocker):** ≥3 real role-play transcripts each with ≥1 certified-coder rating; 3 real self-ratings to sanity-check the rating-card fields (SP02/SP03/SP05).
10. **Sign-offs:** MITI citation/permission wording in `pack.yaml › source`; tone `banned` list, report headline and method/limits text (SP02/SP03); certified-coder review of coding prompts (SP02, deferred with the data in step 9).
11. **Product:** his Onolys contact address for account-removal requests, filled in before launch (SP05); check for an official MITI self-rating form (brainstorm).
12. **Branch protection:** none today; if added, required job names are `eaudit` and `frontend` (SP01).
13. **PR previews (SP00, before the first preview):** in the Identity Platform console add the staging channel hosts (`onolys-app-staging--pr-*.web.app`; per channel host if wildcards are refused) to authorised domains, unless SP06 Terraform manages them; GitHub repo variables for the preview workflows come from the same Terraform outputs as step 7.
14. **After launch, with SP07 only:** DNS for `admin.onolys.com` and the admin allowlist emails (secret `admin-allowed-emails-{env}`).

## Status
Tasks generated (r8); next: dev-code. 10 PRDs reconciled; round-5 to round-8 answers applied. 4 `[OPEN until …]` items remain, all settled by measurement during the build (table above). SP07 is after launch. Slice 0 → Slice 1 → prod order.
