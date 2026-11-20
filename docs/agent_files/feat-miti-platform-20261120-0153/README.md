---
status: in-progress
summary: Onolys MITI platform — design plan, 8 sub-projects, PRDs in progress
date: 2026-11-20
---

# feat/miti-platform

Branch folder for the Onolys MITI platform (`app.onolys.com`). Brief: [brainstorm.md](brainstorm.md) (approved 2026-11-20).

## Sub-projects

| # | Folder | Scope | Depends on | Phase |
|---|---|---|---|---|
| 01 | `01-core/` | Create `engines/` and move `eaudit/` → `engines/eaudit/`; extract shared `engines/core/` (LLMClient with model-route registry params, STT interface + Google Chirp 3 adapter with provider/model/language params, transcript/turn/span types, run_info, PHI-safe logging); fix CI, eval and docs paths; update `docs/mission.md` + `AGENTS.md` for the wider scope (scoring + protocol review now in scope). Existing `POST /v1/audit` unchanged. | — | 1 |
| 02 | `02-paudit-miti-pack/` | Protocol pack format; `protocols/miti-4.2.1/` (pack.yaml, rules.py, rating.schema.json, prompts/, report.yaml, fixtures/); `engines/paudit/`: volley/utterance coding, globals with cited lines, summary scores, N runs as array. | 01 | 2 |
| 03 | `03-evaluation/` | Rating parser (paste/file → schema, user confirms); eaudit accepts structured rating items (scores + reasons); per-item compare; 3-5 tips; report data assembly, versioned. | 01, 02 | 3 |
| 04 | `04-api-jobs/` | `api/`: public API, Identity Platform token verification, personal API keys, uploads (signed URLs), async jobs (Cloud Tasks + worker): upload → transcribe → speaker confirm → rating confirm → run → report; Firestore model; versions; per-user daily cap; delete; access audit log. Built against stub engines first. | 01 (interfaces) | 2 |
| 05 | `05-web-app/` | `web/` (app.onolys.com): sign-up, sign-in, forgot password, Google sign-in, upload, speaker check, rating check, run status, report page, dashboard, settings (API key, delete). | 04 API contract | 3 |
| 06 | `06-infra/` | GCP project `onolys`: Identity Platform, Firestore, buckets, Cloud Run staging/prod, Cloud Tasks, Secret Manager, budget; deploy workflows; DNS records list for Tejit. | — | 1 |
| 07 | `07-admin/` | Today's frontend + eval server on `admin.onolys.com` behind allowlisted login; `paudit` tab in `frontend/src/products.ts`. | 01, 06 | 4 |
| 08 | `08-landing/` | Repo `onolys-landing` (local `/root/projects/onolys/miti`): top-right "Sign up" / "Log in" → app; "Try it out" replaces "Get early access" top-bar CTA; `CtaButton` component kept. PRD lives here; code goes to that repo. | — | any |

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
See the Decision log in [brainstorm.md](brainstorm.md). Headlines: clinician self-rates a mock MI session with MITI 4.2.1; Onolys rates independently, compares, explains with transcript lines, gives 3-5 tips; API-first; all Google Cloud with STT/LLM/language/N-runs as parameters; engines generic, MITI in a pack; one `engines/` folder.

## Status
PRDs: being written. Index of cross-cutting risks added when all 8 PRDs exist.
