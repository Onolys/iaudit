---
status: draft
summary: 9 tasks for SP11 usage limits — config, error codes, override logic, atomic reserve/release per kind and period, first-run exemption, new GET /usage, web hook and pages, docs.
date: 2026-11-21
---
# Tasks: SP11 usage limits — per kind, day + month, per-user overrides
Source of truth: [PRD.md](PRD.md). Generalises SP04's single daily cap into kind (`eval`, `interview`) x period (`day`, `month`). Built after SP00-SP09; SP10 later consumes `reserve`/`release`, the `GET /usage` shape, `useUsage()` and `<UsageLeft>`. No SP10 work here (no interview endpoints, no landing-card layout). Tests follow existing conventions (api: pytest with FakeRepo plus emulator-skipped repo-contract suite; web: vitest and MSW); only impacted tests run per task, the full suite runs in dev-ship. CI already exists.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Config: four caps, validation, `DAILY_RUN_CAP` removed everywhere | SP04 | todo |
| 2 | Error codes + `period` detail (api, schema, web messages) | SP04 | todo |
| 3 | Usage models + pure `effective_cap` | 1 | todo |
| 4 | Atomic `reserve` / `release` / `usage_view` (both repos) | 1, 2, 3 | todo |
| 5 | First-run exemption + SP04 call-site migration | 4 | todo |
| 6 | New `GET /usage` + OpenAPI/schema regeneration | 4 | todo |
| 7 | Web: `useUsage()`, helpers, `<UsageLeft>`, MSW mocks | 2, 6, SP05 | todo |
| 8 | Web: Dashboard, Settings, SessionPage, ReportPage, timeline | 7 | todo |
| 9 | Docs: infra console runbook, env/error tables, public-api | 1, 2, 6 | todo |

## Task 1 — Config: four caps, validation, `DAILY_RUN_CAP` removed everywhere
What it is / what it means: replace the one daily cap setting with four limits from config. Traces to R2, D10, AC1.
What changes at a high level: `Settings` gains `eval_cap_day/month` (10/100) and `ai_cap_day/month` (5/30) from `EVAL_CAP_*`/`AI_CAP_*`; `validate` rejects non-integers, negatives, and month < day with `ConfigError`; `daily_run_cap` is removed with no alias. Terraform `var.daily_run_cap`, `pr-preview.yml`, and `api/.env.example` switch to the four vars. `MAX_ACTIVE_RUNS` untouched.
Done when: config tests prove defaults, env overrides, and each `ConfigError` case; a grep test or check shows `DAILY_RUN_CAP`/`daily_run_cap` absent from Settings, `.env.example`, Terraform and `pr-preview.yml` (docs are Task 9); `terraform validate` passes.

## Task 2 — Error codes + `period` detail
What it is / what it means: the public vocabulary for the new refusals. Traces to R7, D2, D4, AC7 (schema part).
What changes at a high level: add `monthly_cap_reached` and `interview_cap_reached` to `ERROR_CODES`/`ErrorCode`, the public error schema enum, and web `errors.ts` messages ("You've reached this month's limit."); add optional `details[].period` (`day|month`) to the schema and `ErrorDetail`; `ApiError.of` accepts `period`. Concurrent-run refusal stays `daily_cap_reached`.
Done when: schema-validation tests accept all three codes and the `period` property and reject bad periods; an enum-parity test keeps the three code lists (api, schema, web) identical; error-body test shows `period` serialised.

## Task 3 — Usage models + pure `effective_cap`
What it is / what it means: data shapes and the single override-resolution function. Traces to R3, D5, D6, AC4.
What changes at a high level: month usage doc model, `interviews` on the day doc, `RunDoc.counted` (default true), `LimitDefaults`, kind-to-field map in one place; `effective_cap(user_dict, kind, period, defaults)` applying `limits.<kind>.<period>` > legacy `daily_cap` (eval day only) > default, ignoring malformed leaves with a `safe_log` warning (no values).
Done when: unit tests cover partial `limits`, `limits` beating legacy, legacy alone, override 0, and malformed/negative/string leaves falling back without raising or logging values.

## Task 4 — Atomic `reserve` / `release` / `usage_view`
What it is / what it means: the transactional core SP10 builds on. Traces to R1, R4, R6, D1, D4, AC2, AC3, AC5.
What changes at a high level: `Repo` gains `reserve_usage`, `release_usage`, `get_usage_docs`, implemented in `FirestoreRepo` (one transaction over user, day, month docs; month checked first; refusal writes nothing; existing `_contended` retry) and `FakeRepo`, both using `effective_cap`. `jobs/caps.py` exposes `Kind`, `Period`, frozen `Reservation(kind, date)`, `reserve`, `release(refund)`, `usage_view`, plus `reserve_run`/`release_run` wrappers. Refund decrements day and month on the reserved docs (floor 0); eval also moves `active_runs`.
Done when: caps unit tests (FakeRepo) cover the 11th/101st eval, 6th/31st interview with right code and `period`, month-wins, day/month rollover resets, refused attempt counts nothing, kinds independent, refund incl. rollover between reserve and release, `refund=False`, `active_runs` freed; the 6-parallel-reserve-cap-3 test passes per kind, for a month cap, and mixed kinds, plus the same in the emulator repo-contract suite.

## Task 5 — First-run exemption + SP04 call-site migration
What it is / what it means: the first AI-linked evaluation is free; existing call sites move to the new API. Traces to R5, D7, D8, D9, AC6.
What changes at a high level: `start_first_run` drops `cap`, takes `LimitDefaults`, and in its transaction skips eval day/month checks and counters when the session has `interview_id`, still enforcing `MAX_ACTIVE_RUNS` (exempt runs occupy a slot); the run doc stores `counted=false` and its release never refunds. `POST /runs` always counts. SP04 call sites (`routes/runs.py`, `jobs/run.py`, `first_run.py`, `delete.py`) use the wrappers; auto-start at cap leaves `awaiting_input` with the matching `error_code`.
Done when: tests show exempt first run leaves usage unchanged and works at a full cap, is blocked by `MAX_ACTIVE_RUNS`, non-linked first run counts 1, later `POST /runs` counts 1, exempt release never refunds, auto-start at day and month cap yields the right `error_code`; existing SP04 run/first-run tests still pass.

## Task 6 — New `GET /usage`
What it is / what it means: one call returning all four counters, replacing the old shape. Traces to R8, D3, AC7.
What changes at a high level: `routes/usage.py` returns `{eval:{day,month}, interview:{day,month}}` with `Period={used, cap, resets_at}` from `usage_view` (effective caps, UTC resets), read-only; old fields removed. Regenerate `api/openapi.json` and `web/src/api/schema.d.ts` (`npm run gen:api`).
Done when: route tests check `used`/`cap`/`resets_at` for both kinds and periods, overrides reflected, `used` above `cap` after a lowered override, per-user isolation; the OpenAPI diff check is clean with regenerated files committed.

## Task 7 — Web: `useUsage()`, helpers, `<UsageLeft>`, MSW mocks
What it is / what it means: the shared web pieces SP10 will reuse. Traces to R9, AC8 (hook and mocks).
What changes at a high level: one `useUsage()` (TanStack key `["usage"]`) in `web/src/features/usage/`, helpers `remaining(period)` and `blockingPeriod(kind)` (month if exhausted, else day, else null), `<UsageLeft kind period>` ("3 of 5 left today"); `["usage"]` invalidated after run start and run again. MSW `getUsage` returns the new shape from per-kind counters, caps configurable per test (`caps{eval,interview}{day,month}`), and `POST /runs` mock returns the three codes.
Done when: unit tests cover helpers (clamp at 0, month precedence, null) and `<UsageLeft>` text; state-machine tests exercise all three codes and the new usage shape; `tsc` and lint pass.

## Task 8 — Web: Dashboard, Settings, SessionPage, ReportPage, timeline
What it is / what it means: replace the four scattered usage reads with the hook and make cap handling period-aware. Traces to R7, R9, AC6 (web copy), AC8.
What changes at a high level: Dashboard and Settings show per-kind numbers via `useUsage`; SessionPage and ReportPage compute `atCap` from `blockingPeriod("eval") !== null` and take copy and `resetsAt` from that period; `timeline.ts` accepts both eval codes. No landing-card layout (SP10).
Done when: component tests show "Run again" disabled with the month or day message by period, timeline renders `monthly_cap_reached`, a grep/lint check finds `useUsage()` as the only `/usage` consumer; web tests, `tsc`, lint pass.

## Task 9 — Docs: infra runbook, env/error tables, public-api
What it is / what it means: operators can set limits without a deploy. Traces to R2, R10, AC1 (docs grep), AC9.
What changes at a high level: `docs/reference/infra.md` gets "Per-user limits (Firebase console)" (db, `users/{uid}`, `limits` map, integers only, delete leaf for default, next request, usage counters editable for one-off reset) and updated env and error tables; `public-api.md` updated for the new codes, `period`, and `GET /usage` shape.
Done when: grep shows `DAILY_RUN_CAP` gone from all docs listed in the PRD (historical SP04/SP06 PRDs excluded); a doc-consistency check lists the three codes in both docs; AC1 and AC9 checked off.

## Owner steps (not agent work)
- Tejit: after deploy, set any per-user overrides in the Firebase console per Task 9's runbook; check staging user docs still carrying legacy `daily_cap`.
- Tejit/CI: `terraform apply` for staging then prod (new env vars, no new secrets).
