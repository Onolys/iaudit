# 0021. Web app hosting and privacy guarantees

**Audience:** contributors.

**Status:** accepted. Exact CSP hosts for the sign-in popup and the Firestore listener are confirmed on staging in SP09.

**Context.** The web app handles session data that may contain PHI. It must be served so that the browser can only talk to a short, known list of hosts, and it must not leak data through analytics, storage, titles or logs.

**Decision.**

- **One origin.** Firebase Hosting serves `web/dist`. `/v1/**` is rewritten to Cloud Run (`onolys-api-prod` for target `app`, `onolys-api-staging` for `app-staging`, region `us-central1`) and comes before the `**` fallback to `/index.html`, so the API needs no CORS. `web/firebase.json` has one hosting entry per target; the repo-root `firebase.json` stays Firestore-only.
- **CSP.** `default-src 'self'; script-src 'self' https://apis.google.com; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firestore.googleapis.com https://storage.googleapis.com; frame-src 'self' https://accounts.google.com https://*.firebaseapp.com; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'`. Two additions to the PRD list, both read from the shipped `firebase/auth` code: it loads Google's gapi script from `https://apis.google.com/js/api.js` for popup and redirect sign-in (`script-src`), and its helper iframe lives on our own auth domain (`frame-src 'self'`). Other headers: `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-cache` on everything and `public, max-age=31536000, immutable` on `/assets/**` (listed after, so it wins).
- **Mock worker.** `public/mockServiceWorker.js` is for `dev:mock` only. `vite build` removes it from `dist/` unless `--mode mock`, and `firebase.json` ignores it as a second guard.
- **Tests.** Vitest (`web/src/hosting/`) asserts the rewrite order, CSP, headers and ignore list; that every host the app can reach (a config table of API, Auth, Firestore listener, GCS uploads, plus any absolute URL in source or `.env` templates) is allowed by the right directive; no analytics code or dependency, only `firebase/app|auth|firestore` imported; no `localStorage`, `sessionStorage`, IndexedDB, cookies or persistence calls and a memory-cache Firestore; a static title, no `document.title`, and the one `console` call logs ids only. A production build in a temp directory is checked for inline `<style>`, `style=` attributes, inline scripts and the mock worker.

**Measured.** After a production build (Vite 8, 2026-11-20) `index.html` has no inline style or script, styles are one external CSS file, the font is an external `.woff2`, and no bundle creates a `<style>` element. `style-src 'self'` therefore needs no hashes today. The fallback if a library later injects styles is to add `'sha256-...'` hashes for those styles. The Firebase bundle contains the string `googletagmanager.com` only in the SDK's Trusted Types allow-list; no code loads it, and our CSP would block it anyway.

**Alternatives.** Serving the SPA from Cloud Run (no CDN, no shared pattern with landing); a separate `api.` domain with CORS (preflights, more hosts in the CSP); style hashes from day one (brittle across builds).

**Consequences.** Adding a host the app talks to means editing `firebase.json` and the test table together. SP09 must confirm on staging that the popup and the listener work under this CSP and that Hosting forwards `Authorization` on `/v1` and does not cache it.
