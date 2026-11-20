---
status: draft
summary: "Design: 8 PRDs, r6 decisions applied, ready for dev-tasks"
date: 2026-11-20
---

# feat/miti-platform

Branch folder for the Onolys MITI platform (`app.onolys.com`). Brief: [brainstorm.md](brainstorm.md) (approved 2026-11-20). All 8 PRDs are written and reconciled against each other (seams, names, field names, env vars); Tejit's round-5 and round-6 answers (2026-11-20) are resolved in the PRDs (r6: Claude Sonnet for all LLM work, rating card only, Firestore status listeners, no MFA, eval server deferred); next step is `dev-tasks`. Priority: ship to customers fast, app speed matters; the eval harness is not a priority and may break; no extra work for data residency or BAA.

## Sub-projects

| # | Folder | PRD | Scope | Depends on | Phase |
|---|---|---|---|---|---|
| 01 | `01-core/` | [PRD](01-core/PRD.md) (draft) | Create `engines/` and move `eaudit/` → `engines/eaudit/`; extract shared `engines/core/` (LLMClient with model-route registry + presets, all default routes Claude Sonnet `anthropic/claude-sonnet-5-5` via the Anthropic API, STT interface + Google Chirp 3 standard-recognition adapter with provider/model/language/location params, transcript/turn/span types, `locate`, typed errors, run_info, PHI-safe logging); fix CI, eval and docs paths; update `docs/mission.md` + `AGENTS.md` for the wider scope (scoring + protocol review now in scope). Existing `POST /v1/audit` unchanged. | — | 1 |
| 02 | `02-paudit-miti-pack/` | [PRD](02-paudit-miti-pack/PRD.md) (draft) | Protocol pack format; `protocols/miti-4.2.1/` (pack.yaml, rules.py, rating.schema.json, prompts/, report.yaml, fixtures/); `engines/paudit/`: volley/utterance coding, globals with cited lines, summary scores, N runs as array; `rating.schema.json` = the in-app rating card (nested score/reason/example, count/note, additional notes). | 01 | 2 |
| 03 | `03-evaluation/` | [PRD](03-evaluation/PRD.md) (draft) | `engines/evaluation/`: `validate_rating` for the rating card (no parser); reasons audit via eaudit with optional `profile` (audits reasons, examples and the additional-notes box; MI-relevant checks; timestamp-hinted retrieval); per-item compare; 3-5 tips (retry once, Claude); versioned report JSON (`report.schema.json`). | 01, 02 | 3 |
| 04 | `04-api-jobs/` | [PRD](04-api-jobs/PRD.md) (draft) | `api/`: public API (every mutation returns 202 + ids), Identity Platform token verification, personal API keys, uploads (signed URLs), async jobs (Cloud Tasks + worker) that write a PHI-free `session_status/{id}` Firestore doc: upload → transcribe (starts at once) ‖ rating card → speaker confirm → run starts automatically → report; no rating file upload/parse; Firestore model; versions; per-user daily cap; delete; access audit log. Built against stub engines first. | 01 (interfaces) | 2 |
| 05 | `05-web-app/` | [PRD](05-web-app/PRD.md) (draft) | `web/` (app.onolys.com): sign-up, sign-in, forgot password, Google sign-in, upload, speaker check, in-app rating card + separate additional-notes box (soft caps, filled while transcription runs), live run status via Firestore `onSnapshot` (no polling), report page, dashboard, settings (API key, delete). | 04 API contract, 03 report schema | 3 |
| 06 | `06-infra/` | [PRD](06-infra/PRD.md) (draft) | GCP project `onolys`: Identity Platform (no MFA, min password 8), Firestore (`(default)` prod + `staging`) with rules (owner read of `session_status`, all else denied), buckets, Cloud Run staging/prod (api, worker, admin-backend), Cloud Tasks, Secret Manager (incl. Anthropic key), Hosting sites, budget; no Vertex AI; STT service agent bucket read; Terraform; WIF deploy workflows; DNS records list for Tejit. | — | 1 |
| 07 | `07-admin/` | [PRD](07-admin/PRD.md) (draft) | Today's eaudit review UI + new `paudit` tab (`frontend/src/products.ts`) on `admin.onolys.com` behind Identity Platform sign-in limited to Tejit's email allowlist (no MFA); admin-only `POST /v1/paudit`; one Cloud Run service `admin-backend`; eval server/Eval tab not deployed in v1 [DEFERRED]. | 01, 02, 06 | 4 |
| 08 | `08-landing/` | [PRD](08-landing/PRD.md) (draft) | Repo `onolys-landing` (local `/root/projects/onolys/miti`): top right = "Sign up" + "Log in" → app; every other "Get early access" CTA becomes "Try it out" → `${PUBLIC_APP_URL}/signup`; `CtaButton`/`SignupDialog` early-access components kept in the repo, unused. PRD lives here; code goes to that repo. | — (release after 05/06 live) | any |

## Dependency graph
```
Phase 1: 01 core ─┬─ 08 landing (other repo, any time)
                  └─ 06 infra
Phase 2: 02 paudit+pack   04 api+jobs (stub engines)
Phase 3: 03 evaluation    05 web
Phase 4: 07 admin, then end-to-end on staging with Tejit's transcripts
```
Max 2 sub-projects built at once.

## Locked decisions
See the Decision log in [brainstorm.md](brainstorm.md). Headlines:
- Clinician self-rates a mock MI session with MITI 4.2.1; Onolys rates independently, compares per item, explains differences with transcript lines ("Onolys disagrees, here's why"), gives 3-5 tips. Not official MITI coding.
- API-first; the web app uses the public `/v1` API plus one read-only Firestore listener on its own PHI-free status doc; personal API keys; async jobs (every mutation returns 202) with a human gate for speaker confirmation only; the rating is an in-app card (no upload/parse).
- All Google Cloud, project `onolys`, `us-central1` (STT Chirp 3 standard recognition in `us` multi-region; residency claims dropped); Google is used for speech-to-text only, all LLM work is Claude Sonnet via the Anthropic API (`ANTHROPIC_API_KEY`); STT provider/model/language/LLM routes/N runs are config (routes file + presets).
- Engines generic (`engines/{core,eaudit,paudit,evaluation}`), MITI lives in `protocols/miti-4.2.1/`; "models propose, code decides".
- Open sign-up; staging + prod in one project (Firestore DB `staging` / `(default)`); `app.` is a Hosting site with `/v1/**` rewritten to Cloud Run (same origin); `admin.` calls `admin-backend` directly (CORS), no MFA, email allowlist.
- Delete = hard delete (audio, transcript, ratings, all report versions); PITR off; auto-expiry off by default; legal/BAA/price owned by Tejit.
- Cut for the hack: PDF export, teams, billing, email notifications, dashboard trends, transcript editing, non-English reports.

### Seams settled in the reconcile pass
Report JSON = SP03 `report.schema.json` (SP04 stores, SP05 renders); `GET /v1/sessions/{id}/transcript` + `GET /v1/presets` added to SP04; `n_runs` (1-5) + allowlisted `preset` under "Advanced" in web; Hosting site `onolys-app` same-origin rewrite; `FIRESTORE_DATABASE`, `ROUTES_FILE`, `STT_PROVIDERS_FILE`, `DEFAULT_PRESET`, `uploads/` staging prefix, extra SA roles; `coded_span{from_s,to_s}` everywhere; eaudit `profile` passthrough; `evaluation:` pack block; public `paudit.formula.evaluate`; admin-only `POST /v1/paudit`; admin service `onolys-admin-backend-{env}`, reusable `_deploy-cloudrun.yml`; ADR numbers made unique (0017 SP01, 0018 SP02, 0019 SP03, 0020 SP04, 0021 SP05, 0022 SP06, 0023 SP07); `locate` + typed errors added to core.

## Cross-cutting risks / open questions
After round 6 one `[OPEN]` remains across the PRDs (it came out of applying r6, not from earlier rounds); round-5 and round-6 items are listed below. "Tejit" = only he can answer; "build" = resolved by a spike or measurement during implementation.

| PRD | Open item | Default / cheapest test | Who |
|---|---|---|---|
| 03 | r6 asks for paudit, eaudit and tips in parallel, but tips are built from paudit's counted instances (SP03 D7), so they cannot start before paudit ends | Default: tips start when paudit finishes and run alongside eaudit/compare; a transcript-only tips pass (fully parallel) loses the tie to Onolys's scores | Tejit |

**Resolved/deferred by Tejit 2026-11-20 (round 6):**
- Models (A): Google = speech-to-text only; all LLM work (paudit coding/globals, eaudit stages, tips) on Claude Sonnet `anthropic/claude-sonnet-5-5` via the Anthropic API through the LiteLLM client, key `ANTHROPIC_API_KEY` in Secret Manager; routes still swappable by config; Gemini/Vertex only an optional future route; Vertex AI API/IAM removed from SP06. Resolves SP01 Gemini `json_schema`, SP06 Gemini-location. SP02/SP03 "Gemini quality" items become "Claude Sonnet quality, measured on Tejit's transcripts". [RESOLVED] [DEFERRED: Claude Sonnet quality on Tejit's transcripts]
- STT (B): Chirp 3 standard recognition (not dynamic batch), cost not a concern, from `us`; STT service agent gets bucket read; residency claims dropped. Resolves SP01 dynamic-batch, SP06 diarization/service-agent and residency items. [RESOLVED]
- Rating input (C): in-app rating card only (change goal, coded span, per-global score + reason ≤1,000 + optional timestamped example, per-code count + note ≤1,000) plus ONE separate "Additional notes / evaluation reasoning" box (≤3,000) audited by eaudit as extra claims, not parsed; soft caps in UI, hard limits at API; no upload, paste-to-parse, parser step, `extract_text`/`parse_rating`, xlsx risk or `awaiting_rating_confirm`; `validate_rating` kept. Resolves SP03 xlsx and reason-length items. [RESOLVED]
- Async + listeners (D): every mutation returns 202; worker writes PHI-free `session_status/{id}`; Firestore rules = owner read only, all writes server-only, other collections denied; web uses `onSnapshot`, no polling/ETag; SP06 deploys rules; Firestore hosts in the CSP plan. [RESOLVED]
- Speed (E): transcription starts at upload complete; rating card filled meanwhile; run starts once transcript + speaker confirm + card (or "no rating") are in; paudit N runs and eaudit in parallel, tips alongside eaudit (see the open item); Claude prompt caching for shared prefixes; ≤5 min measured at staging. [RESOLVED]
- Delete race / mid-run cancel (F, SP04): not handled in v1; "re-check `deleting` before every write" dropped. [DEFERRED: edge case, Tejit]
- Auth (G): no MFA anywhere; admin = Identity Platform sign-in + email allowlist from Tejit; password min 8 chars, no other rules. Resolves SP06 TOTP/password-policy and SP07 MFA items. [RESOLVED]
- Admin (H): `admin.onolys.com` = eaudit review UI + paudit tab only; eval server/Eval tab, `admin-eval`, GCS FUSE volume and admin data bucket not deployed in v1; SP06/SP07 GCS FUSE and eval-probe-timeout items moot; Hosting→Cloud Run header/timeout: confirm on staging (async API keeps requests short). [RESOLVED] [DEFERRED: eval server deploy]
- Eval harness (I): may break; fix if cheap, else disable/skip blocking eval CI jobs; resolves SP01 uv/eval workspace item. [RESOLVED]
- eaudit for MI (J): keep MI-relevant checks, drop the rest, add MI-specific ones if needed; filter point chosen at build; timestamp-hinted retrieval is in v1; contract details (e.g. `Pointer.index`) may change with a `schema_version` bump; tips retry once on Claude. Resolves the three SP03 eaudit items and the tips item. [RESOLVED]
- Accepted defaults (K): SP02 "mm-hm" (any other-speaker turn breaks a volley, `min_other_words` knob); SP04 5-min target (parallel fan-out, measure at staging); SP05 email-action handler (default Firebase handler); SP05 CSP (confirm on staging); SP06 org policy `allUsers` invoker (check at first apply, fallback `api.onolys.com`, also verify Cloud Run egress to `api.anthropic.com`); SP06 Hosting site ids (fallback names if taken). [RESOLVED]

**Resolved/deferred by Tejit 2026-11-20 (round 5):**
- Real PHI in the admin paudit tab and deletion tombstone/backup retention (SP04, SP07): not a blocker; admin is internal-only (staff allowlist), separate from what users see; legal/BAA is Tejit's. Engineering defaults kept (PITR off, soft-delete 0). [RESOLVED]
- Coded span partial turns (SP02): include any clinician turn that overlaps the span. [RESOLVED]
- Certified-coder review of coding prompts, real transcripts and ratings (SP02, SP03): Tejit supplies later; build and test on synthetic fixtures now. [DEFERRED: Tejit supplies transcripts and coder ratings] (SP02 turn-boundary utterances, Gemini coding quality, prompt wording; SP03 Gemini vs Claude on self-ratings)
- Landing CTAs (SP08): top right = Sign up + Log in only; every other "Get early access" CTA (learner hero, sections, team, enterprise) becomes "Try it out" -> app sign-up; early-access component kept; mobile = Sign up + Log in. [RESOLVED]
- Account-removal contact (SP05): Tejit's Onolys contact address, exact address filled by Tejit before launch (Manual steps). [RESOLVED]

Brainstorm-level risks (see [brainstorm.md](brainstorm.md)): AI-vs-expert agreement on globals, diarization errors on role-plays, many shapes of uploaded ratings, no official MITI form (Tejit checking).

## Manual steps for Tejit
Owner-only tasks, consolidated from the PRDs (agents supply exact values where noted):
1. **GCP access:** confirm his Google account is Owner on project `onolys` and Billing Account Administrator on the linked billing account; billing linked (SP06). Confirm Speech-to-Text v2 API enabled and Chirp 3 usable in the `us` multi-region (SP01/SP06).
2. **Budget:** choose `monthly_budget_usd` (placeholder 50) and the alert email (SP06).
3. **DNS:** add records for `app.onolys.com` and `admin.onolys.com` after `terraform apply` prints them (TXT `hosting-site=…` + A, expected `199.36.158.100`; remove conflicting AAAA/CAA). Staging uses `*.web.app` only (SP06).
4. **Auth console steps:** enable Google sign-in; add `https://app.onolys.com/__/auth/handler` (and staging host) to the OAuth client redirect URIs; customise verification/reset email templates (sender name, subject, link domain) (SP05/SP06). Authorized domains and the password policy (min 8) are Terraform (SP06 R4); there is no MFA.
5. **GitHub:** create environment `production` with himself as required reviewer; set repo variables from Terraform outputs (WIF provider, deployer SA emails, `VITE_FIREBASE_*`) (SP06). In `onolys-landing`: set variable `PUBLIC_APP_URL` (empty = prod default; staging origin for previews); release the landing only after `app.onolys.com` serves `/signup` and `/login`; optionally register `target` as a GA4 custom dimension (SP08).
6. **Secrets/values:** the Anthropic API key (secret `anthropic-api-key`, exposed as `ANTHROPIC_API_KEY`; required, all LLM work uses it) and the admin allowlist emails (secret `admin-allowed-emails-{env}`) (SP01/SP06/SP07).
7. **Data (needed for tuning and eval):** ≥3 real role-play transcripts each with ≥1 certified-coder rating; 3 real self-ratings to sanity-check the rating-card fields (SP03/SP05); a short 2-speaker audio sample for the Chirp 3 diarization check and 2-3 real audio samples for format sanity; keep real data out of the repo and images (SP01/SP02/SP03/SP04/SP07; no admin data bucket in v1).
8. **Sign-offs:** MITI citation/permission wording in `pack.yaml › source`; tone `banned` list, report headline and method/limits text (SP02/SP03); certified-coder review of coding prompts ("prefer fewer parses", uncoded categories) (SP02).
9. **Product/legal:** his Onolys contact address for account-removal requests, exact address to fill in before launch (SP05); legal/BAA stance on deletion tombstones, backup retention and real PHI in the admin paudit tab (SP04/SP07; not blockers); the data in step 7 for the deferred certified-coder prompt review (SP02/SP03); check for an official MITI self-rating form (brainstorm).
10. **Branch protection:** none today; if added, required job names are `eaudit` and `frontend` (SP01).

## Status
Design phase done: 8 PRDs written, reconciled, Tejit's round-5 and round-6 answers applied (1 `[OPEN]` left, see above). Next: `dev-tasks` per approved PRD.
