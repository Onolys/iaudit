---
status: draft
summary: Review UI v1 MVP — 6 sub-projects, PRDs + tasks
date: 2026-10-10
---
# Review UI v1 — index

Hackathon MVP: read-only React + TS + Vite viewer (`frontend/`) over the audit contract in `docs/contracts/`. Upload a request, show the audit beside the text. Governing scope: `docs/mission.md`.

## Sub-projects
| # | Sub-project | Depends on | PRD | TASKS | Tasks |
|---|---|---|---|---|---|
| 01 | Frontend scaffold | none | [PRD](01-frontend-scaffold/PRD.md) | [TASKS](01-frontend-scaffold/TASKS.md) | 3 |
| 02 | Contract core | 01 | [PRD](02-contract-core/PRD.md) | [TASKS](02-contract-core/TASKS.md) | 4 |
| 03 | Transport, mock, errors | 01, 02 | [PRD](03-transport-mock-errors/PRD.md) | [TASKS](03-transport-mock-errors/TASKS.md) | 4 |
| 04 | Review shell + left pane | 01, 02, 03, 05 | [PRD](04-review-shell-left-pane/PRD.md) | [TASKS](04-review-shell-left-pane/TASKS.md) | 3 |
| 05 | Claim detail (right pane) | 01, 02 | [PRD](05-claim-detail-right-pane/PRD.md) | [TASKS](05-claim-detail-right-pane/TASKS.md) | 3 |
| 06 | Fixtures + hardening | 02, 03, 04, 05 | [PRD](06-fixtures-hardening/PRD.md) | [TASKS](06-fixtures-hardening/TASKS.md) | 3 |

## Dependency graph
```
01 -> 02 -> { 03, 04, 05 } -> 06
```
04/T3 composes 05's `ClaimDetail` (declared dependency, no placeholder); 04 also consumes 03/T3 (loader) and 03/T4 (state views). 05 is independent of 03/04.

## Locked decisions
- Stack: Vite + React + TS strict + Vitest (node env; jsdom per file), npm. No ESLint; `tsc --noEmit` + Vitest only.
- Read-only; no contract change, `schema_version` stays `1.0.0`. `VITE_MOCK === "true"` (exact) = mock; `VITE_AUDIT_URL` inlined at build time.
- Ajv: `ajv/dist/2020`, `allErrors`, `allowUnionTypes: true`, `strictTypes: false`.
- Schemas via `@contracts` alias (`../docs/contracts`); no `baseUrl` (TS 7). Mocks use a relative `import.meta.glob` (no alias).
- Mock naming `<name>.request.json` / `<name>.response.json`; bare `request.json`/`response.json` = `default`; match by exact `request_id`; no match -> `mock_no_match`.
- Offsets are code points; quoted text via `sliceCodePoints`/`walkSpan`. Input is normalized English, no emoji; no unicode fixtures.
- Fixed palette (SP01 tokens): supported `#1a7f37`, partially_supported `#b45309`, contradicted `#c62828`, insufficient_evidence `#6b7280`, out_of_scope `#9ca3af`, selected background `#e5e7eb`. No colour-blindness check (deferred).
- Timeout fixed 120 s (no env var); cancel/retry; stale responses dropped; `credentials: 'omit'`; nothing logged or stored.
- Generic error contract: non-2xx bodies validated against `error-response.schema.json`; show `error.message` if valid, else generic text.
- Turn number is 0-based `#index`. Shared-turn overlap = neutral highlight (no stripes).
- `ClaimDetail({claim, request, check})`, `check = analysis.checks[claim.id]`.
- Bad span flags that claim only; duplicate claim ids / wrong version / request_id mismatch reject the response.
- Layout: 55/45 panes, 2px underline (3px hover), no per-claim inline icons; wrap header below ~1100 px, min width 960 px.

## Resolved / deferred questions
| ID | Question | Resolution |
|---|---|---|
| O-01-1 | ESLint flavour | Resolved: dropped from MVP |
| O-01-2 | `VITE_AUDIT_URL` fixed per build | Resolved: accepted |
| O-02-1 | Shared-turn two-role painting | Resolved: SP05 owns; neutral highlight, no stripes |
| O-02-2 | Lone surrogates, JS vs Python offsets | Resolved: normalized English, no emoji; code-point slicing kept |
| O-02-3 | ZWJ/combining mid-grapheme spans | Resolved: same as O-02-2 |
| O-02-4 | Ajv message wording | Resolved: Ajv errors shown raw |
| O-02-5 | Perf on very long transcripts | Deferred |
| O-02-6 | Interface gaps (orderedClaims, notProcessed, ClaimCheck key, orderEvidence arg, checks) | Resolved: SP02 export table |
| O-03-1 | Endpoint path and CORS | Deferred: no backend; mock covers MVP |
| O-03-2 | 120 s timeout | Resolved: fixed constant, no env var |
| O-03-3 | Error-body shape | Resolved: validate vs `error-response.schema.json`; message if valid else generic |
| O-03-4 | `import.meta.glob` with alias | Resolved: relative path, no alias |
| O-03-5 | Contract README wording for extra fixtures | Resolved: handled by SP06 |
| O-04-1 | Narrow-desktop header | Resolved: wrap below ~1100 px; min 960 px |
| O-04-2 | Superscript icon noise | Resolved: no per-claim inline icons (D5) |
| O-04-3 | Pane ratio, underline thickness | Resolved: 55/45, 2px, 3px hover (D10) |
| O-04-4 | Assumed SP02 shapes | Resolved: aligned to SP02 table and SP03 `LoadResult`; unplaced = `!claimSpanOk` |
| O-05-1 | Shared-turn painting check | Resolved: neutral highlight |
| O-05-2 | Turn number base | Resolved: 0-based `#index` |
| O-05-3 | Very long turns | Resolved: no truncation in MVP |
| O-06-1 | `culori` colour-deficiency check | Resolved: cut, no colour-blindness checking |
| O-06-2 | Builder script location | Resolved: dropped; hand-authored fixtures + validation test |
| O-06-3 | Palette finals | Resolved: fixed in SP01 tokens |
| O-06-4 | ZWJ/lone-surrogate fixtures | Resolved: no unicode fixtures |

Also deferred: `long` fixture, perf checks, Playwright/visual regression, manual checklist doc (06); scroll-to-excerpt, persisting expansion (05); `partial` gating of claims, joining backend `span_out_of_range` warnings (02).

## Manual steps (human)
- Agree endpoint path and CORS (incl. OPTIONS preflight) with backend before real integration.

## Next step
Run `dev-code` over the TASKS.md files in dependency order: 01 -> 02 -> 03/04/05 -> 06.
