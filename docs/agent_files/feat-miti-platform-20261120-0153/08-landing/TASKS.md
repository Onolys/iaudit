---
status: draft
summary: 5 tasks for SP08 — app-url + env plumbing first, then top bar auth links, Try it out CTAs, existing e2e/CI-test fallout, preview check.
date: 2026-11-20
---
# Tasks: SP08 landing sign-up/log-in links and "Try it out" CTAs
Source of truth: [PRD.md](PRD.md). Lane C. Code goes to `Onolys/onolys-landing` (local `/root/projects/onolys/miti`), branch `feat/app-auth-links` off `origin/main`. CI there already runs on push and PR: `npm ci`, `astro check`, `vitest run`, build, and the existing Playwright smoke job (`test:e2e`); PRs already get a Firebase Hosting preview channel (`pr-<n>`, 7 days) with a PR comment via `FIREBASE_SERVICE_ACCOUNT`. So no CI-wiring or preview task is needed; only `PUBLIC_APP_URL` has to reach the CI env blocks (Task 1) and the existing e2e specs that assert the popup must follow the change (Task 4). No new Playwright tests are added. Tests are written first in every task.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | `appUrl()` helper and `PUBLIC_APP_URL` env plumbing (types, build check, CI, `.env.example`) | none | done |
| 2 | Top bar: Log in + Sign up, desktop and mobile | 1 | done |
| 3 | `TryItButton` replaces early-access CTAs in Hero, Section, TeamSection | 1 | in-progress |
| 4 | Fix existing e2e specs and CI-config test for the new CTAs | 2, 3 | todo |
| 5 | PR preview verification at 320/375/768 px and kept-code check | 4 | todo |

Parallel lanes: Task 1 first (small). Then Tasks 2 and 3 are independent (TopBar files vs Hero/Section/TeamSection files) and can split between two people. Task 4 merges both; Task 5 is last. Cross-lane sync: do not release (merge to `main` triggers production deploy) until `app.onolys.com` serves `/signup` and `/login` (SP05/SP06 prod). The PR can be opened and reviewed earlier.

## Task 1 — `appUrl()` helper and `PUBLIC_APP_URL` env plumbing
What it is / what it means: the single source of the app origin. Traces to R6, D5, AC3.
What changes at a high level: `src/lib/app-url.ts` with `appUrl(path)` reading `PUBLIC_APP_URL`, default `https://app.onolys.com`, trailing slash trimmed; `src/env.d.ts` type; `scripts/check-env.mjs` validates it when set (https origin, no path) and fails `build:prod` on a malformed value, leaving `PUBLIC_SIGNUP_URL` rules intact; `.env.example` entry; `.github/workflows/ci.yml`: test job `https://app.test`, preview and deploy jobs `${{ vars.PUBLIC_APP_URL }}` (empty means default).
Done when: new `src/lib/app-url.test.ts` covers default, override, trailing slash and path join; `src/lib/check-env.test.ts` covers valid, empty, malformed (http, path, garbage); `src/lib/ci.test.ts` (existing workflow test) still passes with the new env lines. `npm run check` and `npm test` green.

## Task 2 — Top bar: Log in + Sign up, desktop and mobile
What it is / what it means: the top-right auth links on both pages. Traces to R1, R2, R4, R5, D2, D6, AC1, AC4, AC5.
What changes at a high level: `TopBar.astro` drops the early-access trigger; right side order is the Enterprise/Individuals switch, `Log in` (text link), `Sign up` (accent button), all plain same-tab `<a>` with `data-app-link` and `data-trigger`, hrefs `${APP}/login` and `${APP}/signup`, no query params. On mobile (<= 47.5rem) `Sign up` stays in the bar and `Log in` shows in the bar if it fits 320 px, else moves to the side-menu panel after a separator. Targets >= 44 px. No GA event added.
Done when: new `topbar-auth.test.ts` covers labels and hrefs on `/` and `/enterprise`, env override through `appUrl`, no `data-open-popup` in the header, panel links; `foundation.test.ts` (header popup assertion) and `topbar-mobile.test.ts` (secondary-link sibling and exact panel links) updated and green. Measure-and-record: whether `Log in` fits in the bar at 320 px, and note the outcome in the PR.

## Task 3 — `TryItButton` replaces early-access CTAs in Hero, Section, TeamSection
What it is / what it means: every other "Get early access" CTA becomes a link into sign-up, on learner and enterprise pages. Traces to R2, R3, R8, D3, D4, D8, AC2, AC6.
What changes at a high level: new `TryItButton.astro` (`<a>`, label `Try it out`, prop `trigger`, same visual style as the old CTA, href `${APP}/signup`, `data-app-link`); used in `Section.astro` `cta-row` (trigger `section:${id}`), `TeamSection.astro` (trigger `team`), and in `Hero.astro` in place of `HeroForm` (trigger `hero`). `CtaButton`, `HeroForm`, `SignupDialog`, `popup.ts`, `signup/*` and their tests are not touched; the `Base.astro` dialog mount is kept (PRD default).
Done when: new `try-it-button.test.ts`; `learner-page`, `enterprise-page`, `benefits`, `evaluates`, `features`, `team` and (if it asserts the form) `hero` tests updated to assert one `Try it out` link per CTA with correct href and trigger, hero has the link and no popup trigger; the untouched early-access tests (`hero-form`, `signup-dialog`, `popup`, `signup/__tests__`) pass unchanged.

## Task 4 — Fix existing e2e specs and CI-config test for the new CTAs
What it is / what it means: keep the existing CI green. Not named in the PRD's affected-tests table; it follows from R3 and AC6 (tests pass in CI). Existing `e2e/` specs (`enterprise`, `learner`, `signup`, `signup-accessibility`, `smoke`) drive the popup from page CTAs. [OPEN until measured: run `npm run test:e2e` after Tasks 2 and 3 to list the failures.]
What changes at a high level: update only the failing specs. Page-CTA assertions become link assertions (`Try it out`, href). Specs that exercise the dialog itself (accessibility, signup submit) are kept running by opening it through the existing `miti:open-popup` event or a test-only trigger rather than deleting coverage of the kept code; if that needs a design choice beyond that, record it in the PR.
Done when: `npm run test:e2e` (the existing Playwright smoke job, run locally) and `npm test` and `npm run check` are all green; the CI `test` job passes on the PR; the kept dialog code still has its tests.

## Task 5 — PR preview verification at 320/375/768 px and kept-code check
What it is / what it means: the PRD's manual acceptance pass on the preview the CI already posts. Traces to R5, R6, AC3, AC4, AC5, AC6, Risks (preview pointing at prod app).
What changes at a high level: nothing in code unless a check fails. Open the PR; check the preview channel build. Confirm the preview's links point at the staging app origin (so owner variable `PUBLIC_APP_URL` set for previews), at 320, 375, 768 px there is no horizontal scroll and `Sign up` plus `Log in` are reachable with targets >= 44 px, links navigate with JavaScript blocked, no new GA event fires, and `CtaButton`, `SignupDialog`, `HeroForm` still render in their own tests.
Done when: the checks above are recorded in the PR description; a Vitest test (in `topbar-auth.test.ts`) proves `appUrl` output changes every app href when the override is set; any layout fix found is made with a test. Measure-and-record: staging origin used.

## Owner steps
- Set the GitHub Actions variable `PUBLIC_APP_URL` on `Onolys/onolys-landing`: staging app origin for preview builds; for production leave empty or `https://app.onolys.com`. Note: one repo variable feeds both preview and deploy jobs in the current `ci.yml`; split via environment-scoped variables or accept that the preview shows prod links until the app goes live (decide when setting it).
- Add the `app.onolys.com` DNS (SP06) and merge/release the landing only after `/signup` and `/login` are live in prod.
