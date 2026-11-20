---
status: draft
summary: Landing top right = Sign up + Log in; every other early-access CTA becomes "Try it out" linking to app sign-up; CtaButton/SignupDialog kept in the repo
date: 2026-11-20
---

# PRD: Landing sign-up/log-in links and "Try it out" CTAs (SP08)

Repo/branch: `Onolys/onolys-landing` (local `/root/projects/onolys/miti`), branch `feat/app-auth-links` off `origin/main` · Depends on: none (links 404-safe until SP05 ships `/signup` `/login`; ship the landing after the app is live) · Owns: `src/components/TopBar.astro`, new `src/components/TryItButton.astro`, `Hero.astro`, `Section.astro`, `TeamSection.astro`, new `src/lib/app-url.ts`, `src/env.d.ts`, `scripts/check-env.mjs`, `.github/workflows/ci.yml`, tests listed below.

## TL;DR
On `miti.onolys.com` the top right of the top bar shows only **Log in** (text link) and **Sign up** (primary button), plain links to `app.onolys.com`. Every other "Get early access" CTA on the site (learner hero, section CTAs, team CTA, enterprise page CTAs) becomes **Try it out**, a plain link to `${PUBLIC_APP_URL}/signup`, replacing the early-access popup trigger. The `CtaButton` and `SignupDialog` early-access components, `HeroForm` and the Apps Script sign-up stay in the repo, unused or kept for later, not deleted.

## Problem
The platform (SP05) opens sign-up to anyone. The landing still pushes visitors to an early-access waitlist, with no path into the app.

## Goals / Non-Goals
**Goals:** one-click path from every landing CTA to sign-up and log-in; app URL configurable per build; GA4 click events; mobile top bar usable at 320 px.
**Non-Goals:** deleting `CtaButton`, `SignupDialog`, `HeroForm`, the Apps Script endpoint or its tests; copy changes beyond the CTA label; auth logic or session detection on the landing (no "logged-in" state); new tracking beyond existing GA4.

## Requirements
- **R1 Top bar.** Right side order: `Enterprise|Individuals` switch (unchanged), `Log in`, `Sign up`. `Sign up` is the primary button (existing accent style); `Log in` is a text link. There is no "Try it out" and no "Get early access" in the top bar. All are `<a>` (no popup, no `data-open-popup`), same tab.
- **R2 Targets.** Top bar `Sign up` -> `${APP}/signup`, `Log in` -> `${APP}/login`. Every `Try it out` -> `${APP}/signup`. No query params (no UTM, no PHI).
- **R3 "Try it out" everywhere else.** New `TryItButton.astro` (`<a>` styled like the old CTA, label `Try it out`, prop `trigger`) replaces `CtaButton` in `Section.astro` (`cta-row`, trigger `section:${id}`), `TeamSection.astro` (trigger `team`) and, in `Hero.astro`, the `HeroForm` email form (trigger `hero`). This covers the learner page and the enterprise page (both use these shared components). `CtaButton.astro`, `HeroForm.astro`, `SignupDialog.astro`, `lib/popup.ts`, `lib/signup/*` are not edited or deleted; `Base.astro` may keep mounting the dialog (inert, no trigger) or drop the mount while keeping the file (builder's choice, decide in the PR; default keep the mount to minimise change).
- **R4 Both pages.** Same top bar on `/` and `/enterprise` (shared `TopBar`).
- **R5 Mobile (<= 47.5rem).** Hamburger | brand | Enterprise switch stays; the bar shows `Sign up` (button) and `Log in` (link) if they fit at 320 px; if not, `Log in` moves to the side-menu panel (separator plus `Log in`) and `Sign up` stays in the bar. Targets >= 44 px. Verified at 320, 375, 768 px with no horizontal scroll.
- **R6 Env.** `PUBLIC_APP_URL` build-time var, default `https://app.onolys.com`; validated as an `https://` origin with no path or trailing slash (trailing slash trimmed). Build fails on malformed value (same pattern as `PUBLIC_SIGNUP_URL` in `check-env.mjs`). PR-preview/staging builds set it to the staging app origin. `PUBLIC_SIGNUP_URL` stays valid for the kept early-access code.
- **R7 Analytics.** On click, `track('app_link_click', { target: 'signup'|'login'|'try_it_out', trigger })` via existing `src/lib/track.ts` (already adds `page`, `src`); `trigger` = `topbar`, `hero`, `section:<id>` or `team`. Fire-and-forget; navigation never waits on GA. No GA fires if `PUBLIC_GA_ID` unset (existing behaviour). `popup_open` is no longer emitted from the site (code kept).
- **R8 Keep early-access code.** `CtaButton.astro`, `SignupDialog.astro`, `HeroForm.astro`, `lib/popup.ts`, `lib/signup/*` and their own tests remain as they are; only their usages in `TopBar`, `Hero`, `Section`, `TeamSection` change.
- **R9 Tests (test-first).** See Architecture.

## Architecture
```
PUBLIC_APP_URL --> src/lib/app-url.ts (appUrl(path)) --> TopBar.astro <a> x2 (+ mobile panel)
                                                     --> TryItButton.astro <a> (Hero, Section, TeamSection)
click --> delegated listener on [data-app-link] --> track('app_link_click')
```
- `appUrl(path)` reads `import.meta.env.PUBLIC_APP_URL ?? 'https://app.onolys.com'`; pure and unit-tested.
- Add `PUBLIC_APP_URL` to `src/env.d.ts`, `scripts/check-env.mjs` (optional, validated if set), CI `env` blocks in `.github/workflows/ci.yml` (test job: `https://app.test`; preview/deploy: `${{ vars.PUBLIC_APP_URL }}`, empty = default).
- Tracking: delegated `click` listener on `[data-app-link]`, same style as `lib/popup.ts`.

**Tests affected** (all under `src/components/` unless noted) [verified: `git grep -n "early access\|data-open-popup" origin/main -- src`, 2026-11-20]:
| File | Change |
|---|---|
| `foundation.test.ts` L153 | `header [data-open-popup]` (trigger `topbar`) no longer exists: replace with assertion that header has no `[data-open-popup]` and has 2 app links (`Sign up`, `Log in`) with correct hrefs. L18-35 (`CtaButton` render, `noCta`) unchanged (component kept). Secondary-link tests L84-85 unchanged. |
| `topbar-mobile.test.ts` | "secondary link just before the CTA" asserts `secondary.nextElementSibling` has class `cta`: update to the new wrapper (e.g. `.auth`). Panel-links test (exact 4 section links): update if `Log in` moves into the panel (R5). |
| `learner-page.test.ts` L30-33 | Section CTAs: `[data-open-popup]` x1 per section becomes one `a[data-app-link]` with text `Try it out`, href `${APP}/signup`, `data-trigger` `section:${id}`; `#hero [data-open-popup]` null stays true; add hero `Try it out` assertion. |
| `enterprise-page.test.ts` L23, L31-32 | Same change for enterprise sections; `#hero` has no popup trigger (stays null) and no early-access CTA. |
| `benefits.test.ts` L29-31, `evaluates.test.ts` L34-36 | Assert one `Try it out` link (not `[data-open-popup]` / `Get early access`). |
| `features.test.ts` L60 | `.cta-row > [data-open-popup]` becomes `.cta-row > a[data-app-link]`. |
| `team.test.ts` L57-58 | One `Try it out` link with trigger `team` (not `[data-open-popup]`). |
| `hero.test.ts` (if it asserts the `HeroForm` in hero) | Hero shows `Try it out` link instead of `HeroForm`; check when implementing. |
| New `topbar-auth.test.ts` | hrefs/labels on both pages; env override via `appUrl`; panel links; `track` called with each target; no `data-open-popup` in header. |
| New `try-it-button.test.ts`, `src/lib/app-url.test.ts`; extend `src/lib/check-env.test.ts` | link render; default, override, trailing slash, invalid value. |
| `hero-form.test.ts`, `signup-dialog.test.ts`, `src/lib/popup.test.ts`, `src/lib/signup/__tests__/dialog.test.ts`, `.../hero.test.ts` | No change: they test components/code that stay (early-access dialog, forms, popup lib, Apps Script client). |
| `hosting.test.ts`, `firebase.json` | No change (links only; no new hosts, no CSP on landing). |

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Link style | Plain `<a>`, same tab, no UTM | New tab; UTM params | Locked brainstorm: links only; auth app has no analytics |
| D2 | Top bar | `Sign up` + `Log in` only | Include "Try it out" in top bar | Tejit 2026-11-20 (change of design) |
| D3 | Other CTAs | Every "Get early access" CTA (hero, sections, team, enterprise) becomes `Try it out` -> `${APP}/signup` | Keep waitlist in sections | Tejit 2026-11-20: "everywhere"; app sign-up is open |
| D4 | Early-access code | `CtaButton`, `SignupDialog`, `HeroForm`, Apps Script kept, unused | Delete | Tejit: keep for later; easy revert |
| D5 | App origin | `PUBLIC_APP_URL`, default prod | Hard-coded | Staging previews point at staging app |
| D6 | Mobile | `Sign up` in bar; `Log in` in bar if it fits at 320 px else in panel | Both in panel; wrap bar | Primary action visible, bar fits 320 px |
| D7 | GA | One event `app_link_click` + `target` + `trigger` | Three event names | Matches old `popup_open` + `trigger` pattern |
| D8 | Enterprise page | Same top bar and same `Try it out` CTAs (shared components) | Keep early access there | Tejit: "everywhere" |

## Manual steps (owner)
- Set GitHub Actions variable `PUBLIC_APP_URL` (prod: leave empty or `https://app.onolys.com`; preview/staging: staging app origin).
- Merge/deploy the landing only after `app.onolys.com` serves `/signup` and `/login` (SP05/SP06 live, DNS added by Tejit).
- In GA4, optionally register `target` and `trigger` as custom dimensions.

## Risks
| Risk | Mitigation |
|---|---|
| Landing deployed before app is live -> dead links | Order: deploy after SP05/06; PR can merge earlier but is not released until then |
| Waitlist capture (Apps Script) stops entirely | Intended (Tejit); code kept, re-enable by swapping components back |
| Preview builds point at prod app | CI sets `PUBLIC_APP_URL` for previews |
| Unused `SignupDialog` still shipped in page JS | Acceptable; may drop the mount in `Base.astro` (R3) |

## Open Questions
- [RESOLVED: top right = Sign up + Log in only; every other early-access CTA (learner hero, sections, team, enterprise) becomes "Try it out" -> `${PUBLIC_APP_URL}/signup`; early-access component kept (Tejit 2026-11-20)] Landing CTAs.
- [RESOLVED: enterprise page uses the same top bar and "Try it out" CTAs (Tejit 2026-11-20)]
- [RESOLVED: auto-free default] App base URL is `PUBLIC_APP_URL`, default `https://app.onolys.com`.
- [RESOLVED: top bar shows Sign up + Log in on mobile as well; exact fit confirmed in the PR preview (Tejit 2026-11-20)] Mobile layout (D6).
- [DEFERRED] Logged-in awareness ("Open app" instead of Sign up/Log in); removing the early-access dialog and Apps Script code entirely.

## Acceptance Criteria
1. At >= 760 px top-right shows only Log in and Sign up as links with hrefs `https://app.onolys.com/login` and `/signup`; no "Get early access" or "Try it out" in the header.
2. Every former "Get early access" CTA (learner hero, every section, team, and all enterprise page CTAs) reads "Try it out", is an `<a>` with href `https://app.onolys.com/signup` and does not open the popup.
3. Building with `PUBLIC_APP_URL=https://staging.example.com` changes every app href; malformed value fails the build.
4. At 320 and 375 px: no horizontal scroll; `Sign up` visible, `Log in` visible in bar or panel; targets >= 44 px.
5. Each click sends one GA `app_link_click` with the right `target` and `trigger`; navigation works with GA blocked.
6. Updated/new tests pass locally and in CI; PR preview shows the change; `CtaButton.astro`, `SignupDialog.astro`, `HeroForm.astro` still render and their own tests pass.
