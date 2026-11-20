---
status: draft
summary: Landing top bar gets "Sign up", "Log in" and "Try it out" links to app.onolys.com; "Get early access" leaves the top bar but the CtaButton component stays
date: 2026-11-20
---

# PRD: Landing top-bar auth links (SP08)

Repo/branch: `Onolys/onolys-landing` (local `/root/projects/onolys/miti`), branch `feat/app-auth-links` off `origin/main` · Depends on: none (links 404-safe until SP05 ships `/signup` `/login`; ship the landing after the app is live) · Owns: `src/components/TopBar.astro`, new `src/lib/app-url.ts`, `src/env.d.ts`, `scripts/check-env.mjs`, `.github/workflows/ci.yml`, tests listed below.

## TL;DR
On `miti.onolys.com` the top right shows **Log in** (text link), **Sign up** (outline) and **Try it out** (filled primary), all plain links to `app.onolys.com`. They replace the "Get early access" top-bar button. The `CtaButton` early-access component, `SignupDialog` and Apps Script posting stay in the repo and in all non-top-bar spots.

## Problem
The platform (SP05) opens sign-up to anyone. The landing still pushes visitors to an early-access waitlist, with no path into the app.

## Goals / Non-Goals
**Goals:** one-click path from the landing to sign-up and log-in; app URL configurable per build; GA4 click events; mobile top bar still usable at 320 px.
**Non-Goals:** removing/rewriting `CtaButton`, `SignupDialog`, `HeroForm`; changing section CTAs, hero or copy; enterprise-page changes; auth logic or session detection on the landing (no "logged-in" state); new tracking beyond existing GA4.

## Requirements
- **R1 Top bar.** Right side order: `Enterprise|Individuals` switch (unchanged), `Log in`, `Sign up`, `Try it out`. `Try it out` is the primary button (existing accent style); `Sign up` secondary (outline); `Log in` text link. All are `<a>` (no popup, no `data-open-popup`), same tab, `rel` not needed (own domain).
- **R2 Targets.** `Sign up` → `${APP}/signup`, `Log in` → `${APP}/login`, `Try it out` → `${APP}/signup`. No query params (no UTM, no PHI).
- **R3 Both pages.** Same top bar on `/` and `/enterprise` (shared `TopBar`); the enterprise top bar also shows the new links (single shared component; see D3).
- **R4 Mobile (<= 47.5rem).** Hamburger | brand | Enterprise switch stays; `Log in` + `Sign up` + `Try it out` do not fit at 320 px, so on mobile the bar shows only `Try it out` (button) and `Log in`; `Sign up` moves to the end of the side menu panel (links panel gets a separator and `Sign up`, `Log in`). Targets >= 44 px in the panel. Verified at 320, 375, 768 px with no horizontal scroll.
- **R5 Env.** `PUBLIC_APP_URL` build-time var, default `https://app.onolys.com`; validated as an `https://` origin with no path or trailing slash (trailing slash trimmed). Build fails on malformed value (same pattern as `PUBLIC_SIGNUP_URL` in `check-env.mjs`). PR-preview/staging builds set it to the staging app origin.
- **R6 Analytics.** On click, `track('app_link_click', { target: 'signup'|'login'|'try_it_out' })` via existing `src/lib/track.ts` (already adds `page`, `src`). Fire-and-forget; navigation never waits on GA. No GA fires if `PUBLIC_GA_ID` unset (existing behaviour).
- **R7 Keep early-access code.** `CtaButton.astro`, `SignupDialog.astro`, `HeroForm`, `Section`/`TeamSection` CTAs untouched; only the import and `<div class="cta">` in `TopBar.astro` change.
- **R8 Tests (test-first).** See Architecture.

## Architecture
```
PUBLIC_APP_URL --> src/lib/app-url.ts (appUrl(path)) --> TopBar.astro <a> x3 (+ mobile panel)
click --> inline script/delegated listener --> track('app_link_click')
```
- `appUrl(path)` reads `import.meta.env.PUBLIC_APP_URL ?? 'https://app.onolys.com'`; pure and unit-tested.
- Add `PUBLIC_APP_URL` to `src/env.d.ts`, `scripts/check-env.mjs` (optional, validated if set), CI `env` blocks in `.github/workflows/ci.yml` (test job: `https://app.test`; preview/deploy: `${{ vars.PUBLIC_APP_URL }}`, empty = default).
- Tracking: delegated `click` listener on `[data-app-link]` in TopBar's script, same style as `dialog.ts`.

**Tests affected** (all under `src/components/` unless noted) [verified: git grep on origin/main]:
| File | Change |
|---|---|
| `foundation.test.ts` L153 | `header [data-open-popup]` with trigger `topbar` no longer exists: replace with assertion that header has no `[data-open-popup]` and has 3 app links with correct hrefs. L18-23 (`CtaButton` render) unchanged. Secondary-link tests L84-85 unchanged. |
| `topbar-mobile.test.ts` | "secondary link just before the CTA" asserts `secondary.nextElementSibling` has class `cta`: update to new wrapper (e.g. `.auth`). Panel-links test (exact 4 section links): update if `Sign up`/`Log in` added to the panel (R4). |
| New `topbar-auth.test.ts` | hrefs/labels on both pages; env override via `appUrl`; panel links; `track` called with each target; no `data-open-popup` in header. |
| New `src/lib/app-url.test.ts`, extend `src/lib/check-env.test.ts` | default, override, trailing slash, invalid value. |
| `learner-page.test.ts` L31, `enterprise-page.test.ts` L32 | section CTAs `[data-open-popup]` stay: no change. |
| `signup-dialog.test.ts`, `hero-form.test.ts`, `benefits/evaluates/dialog/hero.test.ts` | no change: they test early-access dialog/forms that remain. |
| `hosting.test.ts`, `firebase.json` | no change (links only; no new hosts, no CSP on landing). |

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Link style | Plain `<a>`, same tab, no UTM | New tab; UTM params | Locked brainstorm: links only; auth app has no analytics |
| D2 | Hero/section "Get early access" | Top bar only changes | Replace all with "Try it out" | Tejit's words; waitlist capture stays while the app is new |
| D3 | Enterprise page top bar | Shows the same 3 links (shared component) | Hide on `/enterprise` | One component, enterprise visitors can still try it; its section CTAs keep early access |
| D4 | App origin | `PUBLIC_APP_URL`, default prod | Hard-coded | Staging previews point at staging app |
| D5 | Mobile | `Try it out` + `Log in` in bar, `Sign up` in panel | Hide all in panel; wrap bar | Primary action visible, bar fits 320 px |
| D6 | GA | One event `app_link_click` + `target` param | Three event names | Matches `popup_open` + `trigger` pattern; one report |
| D7 | Sign up vs Try it out | Both go to `/signup` | `Try it out` → demo | Locked brainstorm |

## Manual steps (owner)
- Set GitHub Actions variable `PUBLIC_APP_URL` (prod: leave empty or `https://app.onolys.com`; preview/staging: staging app origin).
- Merge/deploy the landing only after `app.onolys.com` serves `/signup` and `/login` (SP05/SP06 live, DNS added by Tejit).
- In GA4, optionally register `target` as a custom dimension.

## Risks
| Risk | Mitigation |
|---|---|
| Landing deployed before app is live -> dead links | Order: deploy after SP05/06; PR can merge earlier but is not released until then |
| Duplicate "Sign up" and "Try it out" confuse | Same target by design; copy locked by Tejit; revisit with GA data |
| Waitlist capture drops from top bar | Hero/section CTAs remain (D2) |
| Preview builds point at prod app | CI sets `PUBLIC_APP_URL` for previews |

## Open Questions
- [OPEN] Hero/other learner-page "Get early access" CTAs also become "Try it out"? Default: no, top bar only.
- [OPEN] Enterprise page: keep early access in sections (default yes) and show auth links in its top bar (default yes)?
- [RESOLVED: auto-free default] App base URL is `PUBLIC_APP_URL`, default `https://app.onolys.com`.
- [OPEN] Mobile layout (D5) and exact visual styling: confirm in preview.
- [DEFERRED] Logged-in awareness ("Open app" instead of Sign up/Log in); remove early-access dialog entirely.

## Acceptance Criteria
1. At >= 760 px top-right shows Log in, Sign up, Try it out as links with hrefs `https://app.onolys.com/login`, `/signup`, `/signup`; no "Get early access" in the header.
2. Same on `/enterprise`; its section CTAs still open the early-access dialog.
3. Building with `PUBLIC_APP_URL=https://staging.example.com` changes all three hrefs; malformed value fails the build.
4. At 320 and 375 px: no horizontal scroll; `Try it out` and `Log in` visible, `Sign up` in the menu panel; targets >= 44 px.
5. Each click sends one GA `app_link_click` with the right `target`; navigation works with GA blocked.
6. Updated/new tests pass locally and in CI; PR preview shows the change; `CtaButton.astro` still renders and its tests pass.
