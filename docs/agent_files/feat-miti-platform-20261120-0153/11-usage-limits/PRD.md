---
status: draft
summary: Generic per-user usage limits for two kinds (eval, interview) over two periods (UTC day, UTC month), enforced atomically in Firestore, defaults from config, per-user overrides in `users/{uid}.limits`, new `GET /usage` shape and error codes, first AI-linked evaluation exempt; replaces SP04 R8's single daily cap. Built after SP00-SP09.
date: 2026-11-20
---
# PRD: SP11 usage limits — per kind, day + month, per-user overrides

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP04 (caps, Firestore `Repo`, `GET /usage`, errors), SP05 (usage display, MSW mocks) — both landed first; SP10 brainstorm decisions 10/10b/11/12 · Owns: `api/src/onolys_api/jobs/caps.py` (generic limits), `config.py`, `repo/{base,firestore,fake,models}.py` (usage/limits parts only), `routes/usage.py`, `errors.py`, `api/openapi.json`, `docs/contracts/public/public-error-response.schema.json`, `docs/reference/{public-api,infra}.md`, `infra/modules/environment/{variables,services}.tf`, `.github/workflows/pr-preview.yml` (env line), `api/.env.example`, web usage hook + display (`web/src/features/usage/`, Dashboard, Settings, SessionPage, ReportPage, `api/errors.ts`, MSW mocks) · Shares with SP10: `jobs/caps.py` (`reserve`/`release`, kind `interview`), `GET /usage` shape, `useUsage()` + `<UsageLeft kind=…>` web pieces, `interview_id` seam on the session doc

## TL;DR
SP04 has one counter: runs per UTC day, cap 20. SP11 generalises it to a **kind** (`eval` = evaluation run, `interview` = AI interview) times a **period** (`day`, `month`): defaults 10/100 and 5/30 from config, per-user overrides in `users/{uid}.limits` (Tejit, Firebase console), one Firestore transaction per reservation, refund on early failure. `GET /usage` returns all four counters; the landing cards ("3 of 5 left today") and the cap checks in the web app read it. An evaluation that is the first run of an AI-interview-linked session is free. Concurrent-active-run limit stays as is. SP11 provides the reserve/release functions; SP10 calls them for `interview`.

## Problem
Spend control today is one daily eval cap (`DAILY_RUN_CAP=20`) [verified: config.py `daily_run_cap`, caps.py:33]. SP10 adds a second, costlier action (live AI voice) and the owner wants monthly ceilings and a different cap per action, adjustable per user without a deploy. Counters, error codes, `GET /usage` and the web display all assume a single daily number.

## Goals / Non-Goals
**Goals:** four limits server-enforced and atomic (no overshoot under concurrency); per-user overrides without a deploy or admin UI; one `GET /usage` call feeds both landing cards; SP10 needs only `reserve`/`release`; existing SP04 behaviour (refund, auto-start staying `awaiting_input`, concurrent limit) unchanged.
**Non-goals:** yearly limits; admin UI; per-minute rate limiting (`rate_limited` stays reserved); concurrent-interview limit; time-zone-aware (local-day) limits; billing/plans; the interview start/end endpoints and cards UI (SP10); changing the pipeline.

## Requirements
**R1 Kinds and periods.** `Kind = "eval" | "interview"`, periods `day` (UTC date) and `month` (UTC calendar month). Reserving a kind checks **both** periods; both must have room, else nothing is counted.
**R2 Config** (replaces `DAILY_RUN_CAP`, which is removed from `Settings`, `.env.example`, Terraform and docs; an old env var left on a service is ignored):
| Var | Default | Settings field |
|---|---|---|
| `EVAL_CAP_DAY` / `EVAL_CAP_MONTH` | 10 / 100 | `eval_cap_day`, `eval_cap_month` |
| `AI_CAP_DAY` / `AI_CAP_MONTH` | 5 / 30 | `ai_cap_day`, `ai_cap_month` |
Validation (`Settings.validate`, same style as today): integers, each >= 0 (0 disables the kind), and month >= day, else `ConfigError`. `MAX_ACTIVE_RUNS` untouched. Wiring: Terraform `var.daily_run_cap` -> four vars with the defaults above [verified: variables.tf:82, services.tf:19]; `pr-preview.yml:103` literal `DAILY_RUN_CAP=20` -> four vars; `api/.env.example:12`; `docs/reference/infra.md` env table (l69) and error table (l244); `docs/reference/public-api.md` (l40, l63). Older PRD text (SP04 R8/D14, SP06 R14/R15) is historical; not edited.
**R3 Overrides.** `users/{uid}.limits = {eval:{day?,month?}, interview:{day?,month?}}`, every leaf optional; missing leaf = config default. Effective cap = `limits.<kind>.<period>` > (eval day only) legacy `daily_cap` > default. Leaves must be ints >= 0; a malformed leaf (console typo, string, negative) is ignored with a warning log (`safe_log`, no values) and the default applies — never a 500. One pure function `effective_cap(user_dict, kind, period, defaults)` used by both `FirestoreRepo` and `FakeRepo` so the logic exists once. Client writes are already denied [verified: firestore.rules `/{document=**}` deny]; no rule change.
**R4 Usage docs and reserve/release.** See Architecture. One Firestore transaction reads `users/{uid}`, day doc, month doc; if both periods have room (month checked first for the error), increments both counters (plus `active_runs` for `eval`); a refusal writes nothing. `release(refund)` decrements both counters (floor 0) on the **reserved** day/month docs, and `active_runs` for `eval`. Same `_contended` retry as today [verified: firestore.py `_contended`].
**R5 Eval rules.** `POST /runs` and `start_first_run` use kind `eval`. **Exemption:** inside the `start_first_run` transaction, if the session doc has `interview_id` set (written by SP10 `POST /sessions`, validated server-side), that first run skips the eval day/month check and increments **no** eval counters; the concurrent-run limit still applies; the run doc stores `counted=false`. Its release never refunds (nothing to give back). Re-runs (`POST /runs`) always count, even on interview-linked sessions. Refund rule unchanged: a counted run that fails before any LLM call is refunded (day and month) [verified: jobs/run.py:83-88, first_run.py:57, delete.py:39].
**R6 Interview rules (provided to SP10).** SP10 calls `reserve(…, "interview")` in `POST /interviews`, stores the returned `Reservation` (`date`) on `interviews/{id}`, and calls `release(refund=True)` if the interview ends/abandons under `AI_ABANDON_COUNT_SECONDS` (120 s), else `refund=False`. SP11 does not know about interview lifecycle. An interview that later fails STT keeps its count (SP10 builder-check).
**R7 Errors** (HTTP 429, body per R9 of SP04). Added to the enum in all three places [verified: errors.py `ERROR_CODES`/`ErrorCode`, `public-error-response.schema.json` enum, `web/src/api/errors.ts` messages]:
| Situation | `details[].code` | extra |
|---|---|---|
| eval day cap, or concurrent-run limit (unchanged) | `daily_cap_reached` | `period=day` |
| eval month cap | `monthly_cap_reached` | `period=month` |
| interview day / month cap | `interview_cap_reached` | `period=day` or `month` |
`period` is a new **optional** `details[]` property (`"day"|"month"`) in the public schema and `ErrorDetail`. If both periods are exhausted the **month** error wins (its reset is later; telling a user "try tomorrow" would be wrong). At first-run auto-start a cap hit leaves `awaiting_input` with `error_code` = the code above (today only `daily_cap_reached`); the web timeline copy handles the new code.
**R8 `GET /usage`** (opId `getUsage`) — **replaced**, not extended (README/SP05 show no external API users; web is the only client; no compatibility shim):
`{ eval: {day: Period, month: Period}, interview: {day: Period, month: Period} }`, `Period = {used: int, cap: int, resets_at: datetime}`; `resets_at` = next UTC midnight / first of next UTC month; `cap` is the effective cap (overrides applied); `used` may exceed `cap` after an override is lowered (clients clamp remaining at 0). Read-only, three plain gets (non-transactional). Regenerate `api/openapi.json` and `web/src/api/schema.d.ts` (`npm run gen:api`).
**R9 Web.** One shared hook `useUsage()` (TanStack Query, key `["usage"]`; today four copies: Dashboard.tsx:26, Settings.tsx:23, SessionPage.tsx:49, ReportPage.tsx:68) and helpers `remaining(period)`, `blockingPeriod(kind)` (month if exhausted, else day, else null), `<UsageLeft kind period="day">` ("3 of 5 left today"). Updates: Dashboard (l30, l97) and Settings (l119) use it; SessionPage (l54) and ReportPage (l72) `atCap` = `blockingPeriod("eval") !== null`, copy and `resetsAt` from that period; `errors.ts` messages for `monthly_cap_reached` ("You've reached this month's limit.") and `interview_cap_reached`; `timeline.ts:138` accepts both eval codes. The landing cards themselves (layout, disabled-at-cap state) are SP10; SP11 supplies `useUsage`/`<UsageLeft>`. Invalidate `["usage"]` after run start, run again and (SP10) interview start/end. MSW: `getUsage` (stateMachine.ts:563) returns the new shape from per-kind day/month counters; mock caps configurable per test (existing `dailyCap`-style knob becomes `caps{eval,interview}{day,month}`); `POST /runs` mock returns the three eval/interview codes.
**R10 Docs.** `docs/reference/infra.md` gets a section "Per-user limits (Firebase console)" (the runbook that already lists env vars and error codes): open Firestore (db `(default)` prod / `staging`), collection `users`, doc = the user's uid (find it from the email in Firebase Auth), add map field `limits`, e.g. `limits.eval.day = 25`; delete a leaf to return to default; integers only; takes effect on the next request; usage counters live in `usage/` and can be edited the same way to grant a one-off reset.

## Architecture
**Usage docs** (decision D1): keep the existing day doc, add a month doc; both top-level `usage`, id by shape [verified: firestore.py `usage/{uid}_{date}`, models.py:201 `UsageDoc`].
| Doc | Id | Fields |
|---|---|---|
| day | `{uid}_{YYYY-MM-DD}` (existing) | `uid`, `date`, `runs` (eval count, name kept), `interviews`, `tokens` |
| month (new) | `{uid}_{YYYY-MM}` | `uid`, `month`, `runs`, `interviews` |
Kind -> field map `{"eval": "runs", "interview": "interviews"}` lives in one place. Old day docs already have `runs` = eval count, so **no migration**; missing field reads as 0. Month docs start empty at deploy, so the first partial month undercounts at most one day's worth (accepted, D1).
**Interfaces** (`jobs/caps.py`; names are the contract SP10 builds on):
- `Kind`, `Period` Literals; `Reservation(kind, date)` (frozen, `date` = UTC day key; month key = `date[:7]`, so refund after midnight hits the right docs).
- `reserve(repo, settings, uid, kind, now=None) -> Reservation` raises `ApiError.of(429, <code>, msg, period=…)`.
- `release(repo, uid, reservation, refund: bool) -> None`; thin wrappers `reserve_run`/`release_run` stay for eval so SP04 call sites keep working.
- `usage_view(repo, settings, uid, now=None) -> UsageView` (feeds R8).
- `Repo` protocol: `reserve_usage(uid, kind, date, defaults: LimitDefaults, max_active) -> "ok"|"day_cap"|"month_cap"|"concurrent"`, `release_usage(uid, kind, date, refund)`, `get_usage_docs(uid, date) -> (day, month)`; `start_first_run` loses `cap` (takes `LimitDefaults`), computes `exempt` from the session doc it already reads, writes `counted` on the run doc (`RunDoc.counted: bool = True`).
**Concurrency:** all counters for one uid live in 3 docs touched by one transaction; Firestore serialises contenders on those docs and the existing `_contended` retry covers abort storms; eval and interview reservations contend on the same day/month docs (correct: still no overshoot, only a retry).
**Seam with SP10:** `sessions/{sid}.interview_id: str | None` (set once at create, never client-settable after; SP10 validates ownership). SP11 reads only "is it set".

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Usage layout | Day doc (existing, + `interviews`) and a new month doc; `runs` keeps meaning "eval" | Rename to `eval`/`interview` with a read-fallback; one doc per month with a per-day map | Zero migration, zero compat code; reads/writes are 2 docs; the one-time month undercount only affects the deploy month |
| D2 | Kind naming in API | `eval` / `interview` keys in `GET /usage` and Python kinds; error codes `daily_cap_reached`, `monthly_cap_reached`, `interview_cap_reached` | Brainstorm's `evals`/`interviews`; `interview_daily_cap_reached` + `interview_monthly_cap_reached` | Keys match kind names and the error prefix; interview needs only one code since `details[].period` says which; eval keeps the already shipped daily code |
| D3 | `GET /usage` compatibility | Replace the shape | Keep `runs_today`/`daily_cap` alongside | No external users pre-launch; two shapes would linger and confuse |
| D4 | Both-periods-exhausted error | Month wins | Day wins | Reset time shown must be when the user can really act |
| D5 | Legacy `daily_cap` override | Honoured as fallback for `limits.eval.day`; deprecated, drop after launch | Ignore it; migrate docs | One line; avoids silently resetting any override Tejit set on staging |
| D6 | Bad override values | Ignore leaf + log, use default | Fail the request | A console typo must not lock a user out |
| D7 | First AI-linked run | Exempt via `session.interview_id`, decided inside `start_first_run`'s transaction; `counted=false` on the run | Client flag; decrement later | Server-derived (cannot be faked); atomic with the run creation |
| D8 | Concurrent-run limit | Unchanged (`MAX_ACTIVE_RUNS=2`, still `daily_cap_reached`, applies to exempt runs too) | Own code `too_many_runs` | Not asked; a code rename for a rare case is churn. Revisit if the day-cap copy confuses (see Open Questions) |
| D9 | Where the code lives | Evolve `jobs/caps.py` + wrappers | New package | SP04 call sites (`routes/runs.py:132`, `jobs/run.py:88`, `first_run.py:57`) stay valid |
| D10 | Config removal | Delete `DAILY_RUN_CAP`, four new vars | Keep as alias for `EVAL_CAP_DAY` | Alias means two ways to set one thing; staging/prod Terraform is edited in the same change |

## Manual steps
- Tejit: after deploy, set per-user overrides (if any) in the Firebase console per R10; check any staging user doc that still has `daily_cap`.
- Tejit/CI: `terraform apply` for staging then prod (new env vars); no new secrets.

## Risks / Open Questions
- Risk: first-run exemption means a failed (pre-LLM) first run on an AI session cannot be refunded and the next `POST /runs` counts. [OPEN: accept; default accept, since SP10 already charged the AI cap and a pre-LLM failure is rare (Tejit)]
- Risk: legacy `daily_cap` fallback plus new `limits` can confuse the console editor. Mitigated by R10 naming the new field only. [RESOLVED: deprecate `daily_cap` after launch]
- [OPEN: should the concurrent-run refusal get its own code/copy instead of `daily_cap_reached`? default: keep (D8)]
- [OPEN: do exempt (free) first runs still occupy a `MAX_ACTIVE_RUNS` slot? default yes — it is a real concurrent job]
- [RESOLVED: SP10 R5 stores reservation_date on interviews/{id}]
- [DEFERRED: per-user concurrent-interview limit, yearly limits, admin UI, local-time-zone days]
- [RESOLVED: usage counters are not deleted with a session (SP04 delete.py comment: counters are per user); account deletion is deferred in SP04]
- [RESOLVED: UTC day/month, atomic transaction, no admin UI, first evaluation free, interview cap at start with <120 s refund (Tejit 2026-11-20)]

## Acceptance Criteria
1. Config: defaults 10/100/5/30; env overrides parse; non-int, negative, or month < day raise `ConfigError`; `DAILY_RUN_CAP` is absent from `Settings`, `.env.example`, Terraform, `pr-preview.yml` and docs (grep clean).
2. Unit (FakeRepo, mirrors `test_caps.py`): 11th eval of a UTC day -> 429 `daily_cap_reached` `period=day`; 101st of a month -> `monthly_cap_reached` `period=month`; 6th/31st interview -> `interview_cap_reached` with the right `period`; both exhausted -> month code; new UTC day resets day only; new month resets both; a refused attempt counts nothing; kinds do not share counters.
3. Refund: `release(refund=True)` decrements day **and** month (floor 0) on the reserved docs, including across a midnight/month rollover between reserve and release; `refund=False` keeps counts; eval release also frees `active_runs`.
4. Overrides: partial `limits` (only `eval.day`) leaves other leaves at defaults; `limits` beats legacy `daily_cap`; legacy alone still works for eval day; override 0 blocks; malformed/negative/string leaf falls back to default without error.
5. Concurrency: 6 parallel `reserve` calls with cap 3 -> exactly 3 ok, usage == 3, for each kind and for a month cap; mixed eval+interview parallel calls never exceed either cap. Same test against the Firestore emulator via the repo-contract suite (`test_repo_contract.py` pattern, skipped without `FIRESTORE_EMULATOR_HOST`).
6. Exemption: first run on a session with `interview_id` counts 0 eval (usage unchanged), works at a full eval cap, still blocked by `MAX_ACTIVE_RUNS`; first run without `interview_id` counts 1; a later `POST /runs` on the interview-linked session counts 1; releasing the exempt run never refunds. Auto-start at cap leaves `awaiting_input` with the matching `error_code` (day or month).
7. `GET /usage`: new shape only, correct `used`/`cap`/`resets_at` for both kinds and periods, overrides reflected, per-user isolation; `openapi.json` regenerated and CI-clean; error schema validates all three new codes and the `period` property.
8. Web: `useUsage()` is the only `/usage` consumer; Dashboard/Settings show per-kind numbers; SessionPage/ReportPage disable "Run again" and show the month/day message by `blockingPeriod`; timeline handles `monthly_cap_reached`; MSW/state-machine tests cover all three codes and the new usage shape; `tsc`, lint and web tests pass.
9. Docs: `infra.md` has the Firebase-console limits section and updated env/error tables; `public-api.md` updated.
