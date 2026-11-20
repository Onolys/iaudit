---
status: draft
summary: "Design: 8 PRDs written, awaiting review"
date: 2026-11-20
---

# feat/miti-platform

Branch folder for the Onolys MITI platform (`app.onolys.com`). Brief: [brainstorm.md](brainstorm.md) (approved 2026-11-20). All 8 PRDs are written and reconciled against each other (seams, names, field names, env vars); next step is review, then `dev-tasks`.

## Sub-projects

| # | Folder | PRD | Scope | Depends on | Phase |
|---|---|---|---|---|---|
| 01 | `01-core/` | [PRD](01-core/PRD.md) (draft) | Create `engines/` and move `eaudit/` → `engines/eaudit/`; extract shared `engines/core/` (LLMClient with model-route registry + presets, STT interface + Google Chirp 3 adapter with provider/model/language/location params, transcript/turn/span types, `locate`, typed errors, run_info, PHI-safe logging); fix CI, eval and docs paths; update `docs/mission.md` + `AGENTS.md` for the wider scope (scoring + protocol review now in scope). Existing `POST /v1/audit` unchanged. | — | 1 |
| 02 | `02-paudit-miti-pack/` | [PRD](02-paudit-miti-pack/PRD.md) (draft) | Protocol pack format; `protocols/miti-4.2.1/` (pack.yaml, rules.py, rating.schema.json, prompts/, report.yaml, fixtures/); `engines/paudit/`: volley/utterance coding, globals with cited lines, summary scores, N runs as array. | 01 | 2 |
| 03 | `03-evaluation/` | [PRD](03-evaluation/PRD.md) (draft) | `engines/evaluation/`: rating parser (paste/file → schema, user confirms); reasons audit via eaudit with optional `profile`; per-item compare; 3-5 tips; versioned report JSON (`report.schema.json`). | 01, 02 | 3 |
| 04 | `04-api-jobs/` | [PRD](04-api-jobs/PRD.md) (draft) | `api/`: public API, Identity Platform token verification, personal API keys, uploads (signed URLs), async jobs (Cloud Tasks + worker): upload → transcribe → speaker confirm → rating confirm → run → report; Firestore model; versions; per-user daily cap; delete; access audit log. Built against stub engines first. | 01 (interfaces) | 2 |
| 05 | `05-web-app/` | [PRD](05-web-app/PRD.md) (draft) | `web/` (app.onolys.com): sign-up, sign-in, forgot password, Google sign-in, upload, speaker check, rating check, run status, report page, dashboard, settings (API key, delete). | 04 API contract, 03 report schema | 3 |
| 06 | `06-infra/` | [PRD](06-infra/PRD.md) (draft) | GCP project `onolys`: Identity Platform, Firestore (`(default)` prod + `staging`), buckets, Cloud Run staging/prod, Cloud Tasks, Secret Manager, Hosting sites, budget; Terraform; WIF deploy workflows; DNS records list for Tejit. | — | 1 |
| 07 | `07-admin/` | [PRD](07-admin/PRD.md) (draft) | Today's frontend + eval server on `admin.onolys.com` behind allowlisted login + TOTP; admin-only `POST /v1/paudit`; `paudit` tab in `frontend/src/products.ts`. | 01, 02, 06 | 4 |
| 08 | `08-landing/` | [PRD](08-landing/PRD.md) (draft) | Repo `onolys-landing` (local `/root/projects/onolys/miti`): top-right "Sign up" / "Log in" → app; "Try it out" replaces "Get early access" top-bar CTA; `CtaButton` component kept. PRD lives here; code goes to that repo. | — (release after 05/06 live) | any |

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
- API-first; the web app uses only the public `/v1` API; personal API keys; async jobs with a human gate for speaker and rating confirmation.
- All Google Cloud, project `onolys`, `us-central1` (STT Chirp 3 in `us` multi-region); STT provider/model/language/LLM routes/N runs are config (routes file + presets).
- Engines generic (`engines/{core,eaudit,paudit,evaluation}`), MITI lives in `protocols/miti-4.2.1/`; "models propose, code decides".
- Open sign-up; staging + prod in one project (Firestore DB `staging` / `(default)`); `app.` is a Hosting site with `/v1/**` rewritten to Cloud Run (same origin); `admin.` calls `admin-backend` directly (CORS).
- Delete = hard delete (audio, transcript, ratings, all report versions); PITR off; auto-expiry off by default; legal/BAA/price owned by Tejit.
- Cut for the hack: PDF export, teams, billing, email notifications, dashboard trends, transcript editing, non-English reports.

### Seams settled in the reconcile pass
Report JSON = SP03 `report.schema.json` (SP04 stores, SP05 renders); `GET /v1/sessions/{id}/transcript` + `GET /v1/presets` added to SP04; `n_runs` (1-5) + allowlisted `preset` under "Advanced" in web; Hosting site `onolys-app` same-origin rewrite; `FIRESTORE_DATABASE`, `ROUTES_FILE`, `STT_PROVIDERS_FILE`, `DEFAULT_PRESET`, `uploads/` staging prefix, extra SA roles; `coded_span{from_s,to_s}` everywhere; eaudit `profile` passthrough; `evaluation:` pack block; public `paudit.formula.evaluate`; admin-only `POST /v1/paudit`; admin services `onolys-admin-{backend,eval}-{env}`, bucket `onolys-admin-data-{env}` mounted at `/data`, reusable `_deploy-cloudrun.yml`; ADR numbers made unique (0017 SP01, 0018 SP02, 0019 SP03, 0020 SP04, 0021 SP05, 0022 SP06, 0023 SP07); rating file cap 10 MB (SP03 aligned to SP04/SP05); `locate` + typed errors added to core.

## Cross-cutting risks / open questions
Every remaining `[OPEN]` across the PRDs (34). "Tejit" = only he can answer; "build" = resolved by a spike or measurement during implementation.

| PRD | Open item | Default / cheapest test | Who |
|---|---|---|---|
| 01 | Dynamic-batch pricing may not support `chirp_3` diarization | One API call in the STT spike; fallback standard recognizer pricing | build |
| 01 | `uv` with excluded standalone `eval/` and not-yet-existing workspace members | `uv sync --project eval` before merging PR-A/B; fallback path deps / add members as SPs land | build |
| 01 | `json_schema` structured output for Gemini on Vertex via LiteLLM for all eaudit schemas | SP01 ships the switch; SP02/SP03 evaluate quality | build |
| 02 | Utterances crossing a turn boundary (diarizer splits one thought) may inflate counts | Treated as two utterances; measure on real transcripts | build (needs Tejit's transcripts) |
| 02 | Does a client "mm-hm" break a volley? | Any other-speaker turn breaks; `min_other_words` knob | build |
| 02 | Span boundary semantics for the user's coded from-to (partial turns) | Turn included by `start_ms` | Tejit |
| 02 | Gemini coding quality vs expert (r≈0.34-0.63) | Eval on 3 role-plays with certified-coder ratings | Tejit (data) + build |
| 02 | Prompt wording for "prefer fewer parses" and uncoded categories | Needs certified-coder review | Tejit |
| 03 | Where verifier flags enter the decision table (one filter point for `profile`) | Read `check/checker.py`/`group_a.py` first | build |
| 03 | Assessment span `Pointer.index` = section index? | Check `docs/contracts/examples`; else carry a section-id map | build |
| 03 | eaudit link step (BM25) ignores timestamps clinicians cite | Measure retrieval recall; deferred timestamp-hinted shortlist | build |
| 03 | Gemini vs Claude quality for atomize/check on first-person self-ratings | Run eval once real self-ratings exist | build (needs Tejit's ratings) |
| 03 | Real cost of reasons audit on a verbose rating; reason-length cap | Default 1,000 chars/item, truncate + warning | build |
| 03 | One tips call yields ≥3 valid quotes on Gemini? | Retry once built in; tune on real transcripts | build |
| 03 | Parser accuracy on messy xlsx | Fallback is paste | build |
| 04 | 5-min target with N>1 and Gemini Pro globals unproven | Per-run fan-out; measure at staging | build |
| 04 | Cloud Tasks cannot cancel mid-handler; write-after-delete race | Handlers re-check `deleting` before every write | build |
| 05 | Custom email-action handler for verify/reset links | Default Firebase handler accepted for v1 | build |
| 05 | CSP `frame-src`/`connect-src` for Identity Platform popup; `style-src` hashes | Confirm on staging | build |
| 05 | Contact address for account-removal requests (settings text) | none | Tejit |
| 06 | Chirp 3 diarization from `us` (batch vs sync); STT service agent needs bucket `objectViewer`? | Verify in SP01 spike; Terraform grants if needed | build |
| 06 | Gemini availability in `us-central1` vs `global`/`us` endpoint (residency claim) | Verify at model pinning | build |
| 06 | Org policy may block `allUsers` invoker on Cloud Run | Check at first apply; fallback `api.onolys.com` domain mapping (also public) | Tejit (Owner access) if blocked |
| 06 | Hosting site ids (`onolys-app`, `-app-staging`, `-admin`, `-admin-staging`) may be taken | Fallback `onolys-miti-app*` | build |
| 06 | GCS FUSE semantics for eval server | Day-1 spike; owned by SP07 | build |
| 06 | Terraform support for every Identity Platform setting (TOTP, password policy) | Fallback REST patch script | build |
| 07 | Does Identity Platform MFA apply to Google sign-in? | Email/password + TOTP only until a token with `sign_in_second_factor` is seen | build |
| 07 | Eval start/resume probes <60 s through Hosting rewrite | Rewrite for `/eval-api`, direct URL if not | build |
| 07 | GCS FUSE spike result (atomic rename, chmod) | Fallback: local disk + copy to bucket | build |
| 07 | Exact Hosting→Cloud Run timeout and header pass-through | Confirm on staging | build |
| 07 | "Do not paste real PHI until BAA" note on the paudit tab | Show the note; legal decision | Tejit |
| 08 | Hero/learner-page "Get early access" CTAs also become "Try it out"? | No, top bar only | Tejit |
| 08 | Enterprise page: keep early access in sections and auth links in its top bar? | Yes / yes | Tejit |
| 08 | Mobile top-bar layout and styling | Confirm in PR preview | Tejit |

Brainstorm-level risks (see [brainstorm.md](brainstorm.md)): AI-vs-expert agreement on globals, diarization errors on role-plays, many shapes of uploaded ratings, no official MITI form (Tejit checking).

## Manual steps for Tejit
Owner-only tasks, consolidated from the PRDs (agents supply exact values where noted):
1. **GCP access:** confirm his Google account is Owner on project `onolys` and Billing Account Administrator on the linked billing account; billing linked (SP06). Confirm Speech-to-Text v2 API enabled and Chirp 3 usable in the `us` multi-region (SP01/SP06).
2. **Budget:** choose `monthly_budget_usd` (placeholder 50) and the alert email (SP06).
3. **DNS:** add records for `app.onolys.com` and `admin.onolys.com` after `terraform apply` prints them (TXT `hosting-site=…` + A, expected `199.36.158.100`; remove conflicting AAAA/CAA). Staging uses `*.web.app` only (SP06).
4. **Auth console steps:** enable Google sign-in; add `https://app.onolys.com/__/auth/handler` (and staging host) to the OAuth client redirect URIs; customise verification/reset email templates (sender name, subject, link domain) (SP05/SP06). Authorized domains and TOTP MFA are Terraform (SP06 R4).
5. **GitHub:** create environment `production` with himself as required reviewer; set repo variables from Terraform outputs (WIF provider, deployer SA emails, `VITE_FIREBASE_*`) (SP06). In `onolys-landing`: set variable `PUBLIC_APP_URL` (empty = prod default; staging origin for previews); release the landing only after `app.onolys.com` serves `/signup` and `/login`; optionally register `target` as a GA4 custom dimension (SP08).
6. **Secrets/values:** admin allowlist emails (secret `admin-allowed-emails-{env}`); Anthropic key if an alternate Claude route is used (SP06/SP07).
7. **Data (needed for tuning and eval):** ≥3 real role-play transcripts each with ≥1 certified-coder rating; 3 real self-ratings in the formats users send (docx/pdf/xlsx/pasted); a short 2-speaker audio sample for the Chirp 3 diarization check and 2-3 real audio samples for format sanity; upload real data to `onolys-admin-data-{env}` under `eval/data/` by hand, never to the repo (SP01/SP02/SP03/SP04/SP07).
8. **Sign-offs:** MITI citation/permission wording in `pack.yaml › source`; tone `banned` list, report headline and method/limits text (SP02/SP03); certified-coder review of coding prompts ("prefer fewer parses", uncoded categories) (SP02).
9. **Product/legal:** contact address for account-removal requests (SP05); legal stance on content-free deletion tombstones, backup retention and real PHI in the admin paudit tab (SP04/SP07); landing CTA questions above (SP08); check for an official MITI self-rating form (brainstorm).
10. **Branch protection:** none today; if added, required job names are `eaudit` and `frontend` (SP01).

## Status
Design phase done: 8 PRDs written and reconciled, awaiting review. Next: `dev-tasks` per approved PRD.
