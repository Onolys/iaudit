---
status: approved
summary: Backend POC (FastAPI, contract 1.0.0) - 8 sub-projects, PRDs settled (0 open) + TASKS.md per sub-project
date: 2026-10-11
---
# Backend POC - index

FastAPI proof of concept in `backend/` that serves the audit contract 1.0.0 (`POST /v1/audit`) through a staged pipeline: prep, atomize, link, check, assemble. Source: [brainstorm.md](brainstorm.md). Governing scope: `docs/mission.md` (wins on conflict). Locked overrides from dev-design are listed below and win over the brainstorm.

## Sub-projects
| # | Sub-project | Depends on | PRD | Phase | Core / Optional |
|---|---|---|---|---|---|
| 01 | Scaffold + API | none | [PRD](01-scaffold-api/PRD.md) | Foundation | Core (optional: streaming cap, metrics depth, Server-Timing, multi-breakpoint cache) |
| 02 | Assembler + contract enforcement | 01 | [PRD](02-assembler/PRD.md) | Core stage | Core (optional: 8-gram copy check, partial-overlap trim) |
| 03 | Prep + Atomize | 01 | [PRD](03-prep-atomize/PRD.md) | Core stage | Core (optional: LLM act tagging, leak CI test, soft-timeout path) |
| 04 | Link | 01, 02, 03 | [PRD](04-link/PRD.md) | Core stage | Core (optional: speaker floor, correction pull, RRF fusion, recall hook, cache tuning, leak test) |
| 05 | Check | 02, 03, 04 | [PRD](05-check/PRD.md) | Core stage | Core, incl. timeframe check (optional: calibration, rate-ratio, cue refinements, leak tests) |
| 06 | Orchestration + latency | 01, 02, 03, 04, 05 | [PRD](06-orchestration/PRD.md) | Integration | Core (optional: prompt caching/warm-up, latency suite, rich metrics, Server-Timing, priority) |
| 07a | Fixtures + smoke script | 01 (smoke script needs 06) | [PRD](07-eval/PRD.md) | Validation | Core |
| 07b | Eval harness | 01, 02 (harness); 03-05 (Linked mode); 06 (end-to-end) | [PRD](07-eval/PRD.md) | Validation | Optional (gated) |
| 08 | Docs update | 01-07 | [PRD](08-docs-update/PRD.md) | Docs (last) | Core (optional: ADRs, concepts, implementation, testing, examples, drift test) |

## Build order (hackathon)
1. Core critical path: 01 -> {02, 03, 07a} -> 04 -> 05 -> 06 -> 08-core (+ 07a smoke run).
2. Optional (gated) items from every PRD's "Scope tiers" section, only after all core is done.
3. Up to 5 sub-agents in parallel.

## Core simplifications
- 01: body size via Content-Length else read-then-check; one `cache_prefix`; simple append-only metrics list; no Server-Timing.
- 02: rule 9 = quoted-span/timestamp checks + drop exact-substring notes (no 8-gram); partial overlap drops less severe claim + `other` warning.
- 03: `prep()` rules-only, unsure -> no act; no leak CI test (hand-checked few-shot); no soft-timeout path.
- 04: plain BM25 top-k + neighbors (no speaker floor, correction pull, RRF); one `cache_prefix`; 07 reads shortlist from stub-linker run.
- 05: timeframe check is core (V5 -> `insufficient_evidence` + `timeframe_mismatch`, gated); fixed floors 0.5/0.6; verifier flag 11 only; minimal at-least cue list.
- 06: no caching/warm-up, basic metrics, basic deadline tests with injected sleep; no latency suite.
- 07: 07a only = ADHD fixtures + 8 variants + expected JSON + smoke script; harness/gold/modes deferred.
- 08: backend README + `backend-api.md` + short architecture blurb + index links; ADRs/concepts/etc. deferred.

## Dependency graph
```
01 -> {02, 03}; {01, 02, 03} -> 04; {02, 03, 04} -> 05; {02, 05} -> 06 (full: 01-05)
07: harness after 01, 02; Linked mode after 03-05; e2e after 06
all -> 08
```
Per PRD headers: 04 depends on 01, 02, 03; 05 on 02, 03, 04; 06 on 01-05.

## Locked decisions
- Code in `backend/`, src layout `backend/src/iaudit_backend/`. Python 3.12 + uv + ruff + pytest.
- `POST /v1/audit` + `GET /healthz`; CORS from env allowlist; no auth.
- `role` optional: missing role skips checks 3/9 and adds `ambiguous_speaker` (overrides brainstorm "always supplied").
- Retrieval: BM25 + rapidfuzz. No embeddings/spaCy/torch unless linked-mode gain >= 0.05 F1.
- LLM via LiteLLM, model tiers (cheap/mid); fixture replay in tests (no network); live runs opt-in.
- No body/transcript logging (allowlist logging only).
- Limits: 2,000 turns / 50 sections / 2 MB body.
- Section failure -> `section_not_processed` + `partial`. Claim stall (link/check fail, timeout) -> `insufficient_evidence` + `other` warning.
- 02 `locate()` is the single matcher; `ClaimDraft` uses `segments` + `span_hint` (no `claim_text`/`char_hint`).
- Shared prompt-cache layout: system -> transcript -> stage -> claim; warmed at t=0.
- `IAUDIT_PIPELINE` defaults to `stub` in SP01; SP06 flips default to `full`; tests always set `stub` explicitly.
- Understatement reuses `frequency_severity_inflation` with "understates" wording (no new concern type).
- Contract stays 1.0.0 (no schema change); `mission.md` check 7 wording becomes "exaggerates or understates" (user-approved, applied in 08).
- Offsets are code points. 60 s request deadline (configurable).
- POC gate = ADHD faithful returns no concerns + all 8 single-fault variants (V5 included) return expected verdict/concern.
- Nothing usable -> 503 `unavailable` (504 on deadline), not a 200 partial.
- Models: cheap `anthropic/claude-haiku-4-5-20251001`, mid `anthropic/claude-sonnet-5-5`. 60/20/20 split, P0 precision gate, P1 suppression deferred.
- Explanations are code templates (neutral, no transcript copying); LLM observes, code decides verdicts.

## Gaps found in the brainstorm
| Gap | Resolution |
|---|---|
| Role "always supplied" vs contract | Role optional (locked override) |
| No HTTP path / CORS | `POST /v1/audit`, env CORS allowlist |
| No input limits | 2,000 turns / 50 sections / 2 MB |
| No API keys on machine | Manual step (below) |
| No offline test strategy | LLM fixture replay in CI |
| PHI logging unspecified | Allowlist logging, no bodies |
| 60/20/20 split impossible with 1 interview | POC gate now; split deferred |
| Gold ambiguities V2/V4 | Resolved (07 O-1 / O-2) |
| Claim-level timeout undefined | Locked: stall -> `insufficient_evidence` + `other` warning |
| Heavy deps (embeddings, spaCy, torch) | Deferred (>= 0.05 F1 rule) |
| Python tooling unspecified | uv / ruff / pytest |
| Mission check 7 says "exaggerates"; understatement flag added | Resolved: "exaggerates or understates" (08 O-1) |
| Faithful S5 "repeatedly" false-understate risk | 05 at-least cue list (05 O-2) |
| 02/03 claim-shape mismatch | Resolved: `segments` + `span_hint`, single `locate()` |

## Tasks
One `TASKS.md` per sub-project, every task `todo`, each ending with one gated Optional row.
| # | Tasks |
|---|---|
| 01 | [TASKS](01-scaffold-api/TASKS.md) |
| 02 | [TASKS](02-assembler/TASKS.md) |
| 03 | [TASKS](03-prep-atomize/TASKS.md) |
| 04 | [TASKS](04-link/TASKS.md) |
| 05 | [TASKS](05-check/TASKS.md) |
| 06 | [TASKS](06-orchestration/TASKS.md) |
| 07a/07b | [TASKS](07-eval/TASKS.md) |
| 08 | [TASKS](08-docs-update/TASKS.md) |

## Execution plan (waves)
| Wave | Runs in parallel | Waits for |
|---|---|---|
| 1 | 01 | none |
| 2 | 02, 03 (tasks 1-5), 07a tasks 1-4 | 01. 03 task 6 also waits for 02 task 2 (`locate()`) |
| 3 | 04 | 02, 03 |
| 4 | 05 | 02, 03, 04 |
| 5 | 06 | 01-05; its task 7 also needs 07a task 3 |
| 6 | 07a task 5 (smoke), 08 tasks 2-3 | 06 |
| 7 | 08 tasks 1 and 4 | smoke script, 08 task 3 |
| 8 | Optional rows from every SP | all core done |
Critical path: 01 -> 02 -> 04 -> 05 -> 06 -> 08.

## Open question resolutions
All items are now tagged inline in each PRD as `[RESOLVED: ...]` or `[DEFERRED]`. Open counts: 0 in every PRD.
| Item | Resolution |
|---|---|
| 06 O-1, 08 O-2, 02 O-7 | Nothing usable -> 503 `unavailable` (504 on deadline). A section with no located claims stays `section_not_processed`. |
| 08 O-1 | Mission check 7 becomes "exaggerates or understates"; wording only, contract stays 1.0.0. |
| 07 O-3 | Timeframe check moved into 05 core; V5 is gated, so all 8 variants must pass. |
| 07 O-13 | Variant 1 wording approved. |
| 01 O-1 | Cheap `anthropic/claude-haiku-4-5-20251001`, mid `anthropic/claude-sonnet-5-5`; one live call in 01 task 10 confirms. |
| 01 O-3 | Duplicate-id errors give a count only. |
| 03 O-3, O-4 | Assessor observations are `unobservable`; dropped claims go to logs only. |
| 04 O-1f, O-8, O-9 | 04 fills `ambiguous_turns` for evidence turns; keep question snapping; V6 turn 23 accepts either label. |
| 05 O-2, O-3, O-7, O-8, O-11, O-12 | Minimal at-least cue list; no-quantity limit accepted; locked missing-role rule; `wrong_attribution` beats `negation_reversal`; `suggested_revision` on; 03 exposes `oos_reason`. |
| 06 O-2, O-4, O-5, O-8 | No section escalation; claim cap 80 first-come; FIFO semaphore; no in-flight audit cap. |
| 07 O-1, O-2, O-4, O-6, O-9, O-12, O-15 | Gold roles as proposed; `fixture_key` from `RequestContext`; collateral false alarms reported, not gated; gold stays `supported`; adapter derives `proposition`, S1 is `often`. |
| 08 O-4, O-5 | Re-verify file names in the docs task; no frontend back-link for now. |
| Deferred (measurement) | 01 O-2, O-4; 02 O-1, O-2, O-3; 03 O-2, O-5, O-6; 04 O-2, O-3, O-4, O-7; 05 O-1, O-4, O-5, O-9, O-10; 06 O-3, O-6, O-7; 08 O-3. Stated defaults ship. |
| Deferred (07b, user input) | 07 O-5, O-10, O-11 (multi-fault text, CDR file); 05 O-13 / 07 O-8 (new variants for buckets 1, 2, 10). |

## Manual steps (human)
- Set provider API key(s) (`ANTHROPIC_API_KEY` or other); confirm model ids.
- Approve multi-fault ADHD variant text (07 O-5, 07b only).
- Supply real CDR transcript file (07b only).
- Add iaudit row to `/root/projects/README.md` (machine index, outside repo; note only).
- DAIC-WOZ licence signer (non-blocking).

## Next step
Create one Party tasks Issue per sub-project in the wave order above, then implement one sub-project at a time.
