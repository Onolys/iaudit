# Run recipe: main app (web/ + api/), verified 2026-11-21

Worktree: `/root/projects/onolys/iaudit/.worktrees/review-full-app` (branch `review/full-app`, base origin/main a10373f). Admin app out of scope.

## Install (done)
- web: `cd web && npm ci` (node >=22; v22 present)
- api: `uv sync --all-packages` from repo root (workspace; engines are path deps). Run api via `uv run --package onolys-api ...`.
- Machine has java 21, uv, node. firebase-tools not installed globally: use `npx -y firebase-tools@15.37.0` (works). Firestore emulator jar cached in `~/.cache/firebase/emulators/`.
- NOTE: a foreign Firestore emulator (java, port 8080, started 19:53) runs on this machine; not ours, left alone.

## Mode A: web mock (MSW + fake auth). BOOTS.
```
cd web && npm run dev:mock        # http://localhost:5173 ; uses web/.env.mock
```
(VITE_USE_MOCKS=true, VITE_AUTH_MODE=fake, API served in-browser by MSW; `/mockServiceWorker.js` returns 200.) No backend, no login needed (fake auth, auto-verified: sign up with any email/password).

## Mode B: "most real" local: Firestore emulator + api (stub adapters) + web live. BOOTS (curl-verified).
Caveat: there is NO Auth emulator path. web `firebaseService` has no `connectAuthEmulator`, api `AUTH_MODE=idp` verifies against Google keys, and firebase.json only defines the firestore emulator. So real Firebase Auth cannot be exercised locally. Use api `AUTH_MODE=fake` (`Bearer test:<uid>`) + web `VITE_AUTH_MODE=fake` (also works outside mock mode; sends `test:<uid>`).

Terminal 1, Firestore emulator (ports: 8081 firestore, 4400 hub, 4500, 9150; ui disabled). From repo root:
```
npx -y firebase-tools@15.37.0 emulators:start --only firestore --project demo-onolys
```
Terminal 2, api (port 8000):
```
FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 ENV=local SERVICE_MODE=combined AUTH_MODE=fake ADAPTERS=stub \
GCP_PROJECT=demo-onolys AUTH_PROJECT=demo-onolys FIRESTORE_DATABASE='(default)' \
CORS_ORIGINS=http://localhost:5173 FAKE_BLOB_DIR=/tmp/onolys-blobs FAKE_BLOB_BASE_URL=http://127.0.0.1:8000 \
uv run --package onolys-api uvicorn --factory onolys_api.app:create_app --host 127.0.0.1 --port 8000
```
(`mkdir -p /tmp/onolys-blobs` first. Without FIRESTORE_EMULATOR_HOST, ENV=local uses in-memory FakeRepo. Env vars documented in `api/.env.example`.) Combined mode runs the worker in-process with stub STT/evaluation.
Simpler no-Firestore variant: `api/scripts/dev.sh` (all fakes; `--check` preflight, `--quickstart` needs ffmpeg+jq).

Terminal 3, web live (port 5173). CORS allows `http://localhost:5173` only; open it as `localhost`, NOT 127.0.0.1 (or add to CORS_ORIGINS):
```
cd web && VITE_USE_MOCKS=false VITE_AUTH_MODE=fake VITE_API_BASE_URL=http://127.0.0.1:8000/v1 \
VITE_FIRESTORE_EMULATOR=127.0.0.1:8081 VITE_FIREBASE_PROJECT_ID=demo-onolys VITE_FIRESTORE_DATABASE='(default)' \
npm run dev:live
```
(No vite proxy exists, hence the absolute API base URL.)

Verified by curl: `GET :8000/v1/healthz` -> `{"status":"ok","service_mode":"combined",...}`; `GET /v1/sessions` with `Authorization: Bearer test:alice` -> `{"items":[],"next_cursor":null}`; `POST /v1/sessions` `{}` -> 202 session created; CORS header for localhost:5173 present; Vite served on :5173. Browser UI against it was NOT driven (not requested/verified).

## Test accounts
- Mock/fake: any email+password in the sign-up form (auto-verified, in memory, lost on reload). API direct: `-H 'Authorization: Bearer test:<uid>'`, uid `[A-Za-z0-9_-]{1,128}`.
- Real Firebase Auth/emulator accounts: not possible (see caveat). Real staging login needs real `VITE_FIREBASE_*` + `AUTH_MODE=idp`, out of local scope.

## What does not work locally
- Real auth (no Auth emulator wiring).
- Real STT/LLM/evaluation (stub adapters). `ADAPTERS=real` needs GCP creds/provider keys.
- AI interview voice relay: real mode needs the voice service websocket (`wss://onolys-voice-*.run.app`); only fake relay in mock mode.
- Audio signed-URL uploads use `FakeBlobStore` (local dir); `validate` step needs ffmpeg/ffprobe on PATH (real-ffmpeg test skipped otherwise).
- Hosting `/v1` rewrite not emulated (web/firebase.json), hence absolute API URL.
- The older `scripts/dev.sh` targets legacy `engines/eaudit` + `frontend/` + `eval/`, not this app.

## Unit tests (run individually)
web (from `web/`):
```
npx vitest run src/auth/fakeService.test.ts      # one file (8 passed)
npx vitest run -t "name"                         # by test name
npm run typecheck ; npm run lint
```
api (from repo root):
```
uv run --package onolys-api pytest api/tests/test_acceptance_checklist.py -q -m "not live"   # 75 passed
uv run --package onolys-api pytest api/tests/<file>.py::<test> -q -m "not live"
```
Add `FIRESTORE_EMULATOR_HOST=127.0.0.1:8081` (emulator running) to include emulator-param tests.
Firestore rules tests: `firebase emulators:exec --config firebase.json --only firestore --project demo-onolys 'npm test --prefix firestore-rules-test'` (needs `npm ci` in firestore-rules-test; not run).
