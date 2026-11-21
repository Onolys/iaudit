---
status: draft
summary: 13 tasks for SP10 — R0 spike go/no-go first, then voice adapter + scenarios in parallel, interview API/relay/sweeper/session-link, infra and web audio in parallel, web feature, staging proof, docs.
date: 2026-11-21
---
# Tasks: SP10 AI practice interview
Source of truth: [PRD.md](PRD.md) (approved; brief: [../brainstorm.md](../brainstorm.md)). Tests follow repo conventions: `unit` / `integration` / `live` markers, default `-m "not live"`; CI (`.github/workflows/ci.yml`) already runs them, so no CI task. Everything below uses the `fixture` voice adapter and FakeRepo unless marked LIVE.

External dependency (not SP10 work): **SP11 usage limits**, built before SP10 except the spike, provides `reserve` / `release` / `Reservation`, the `GET /usage` shape, `useUsage()` / `<UsageLeft>`, and reads `session.interview_id`. Tasks 4, 6, 7, 11 name it where used.

**Gate:** Task 1 is the go/no-go. No other task starts before go. On no-go: shelve SP10, or try the brief's Claude fallback once (owner decision).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | R0 spike go/no-go gate | none (owner in the loop) | todo |
| 2 | Scenario schema, loader, `GET /scenarios`, persona prompt builder | 1 | todo |
| 3 | Core voice adapter (`VoiceAdapter`, Gemini Live Vertex, fixture, config) | 1 | todo |
| 4 | Interview API + state + SP11 reserve/release seam | 2, 3, SP11 | todo |
| 5 | Voice relay service (auth, pump, clock, resumption, reconnect) | 2, 3, 4 | todo |
| 6 | Sweeper task + short-interview refund | 4, SP11 | todo |
| 7 | Session link (`interview_id`, draft rating) + validate rules | 4, SP11 | todo |
| 8 | Infra: `onolys-voice-{env}` Cloud Run service | 1 | todo |
| 9 | Web audio engine (worklet capture/playback, recording graph) | 1 | todo |
| 10 | Web CSP + MSW mocks + in-page fake relay | 4, 5, 9 | todo |
| 11 | Web interview feature + landing cards | 7, 9, 10, SP11 | todo |
| 12 | Staging end-to-end (LIVE) | 5, 6, 7, 8, 11 | todo |
| 13 | Docs: public API, ADR, branch README | 1-12 | todo |

Parallel lanes (disjoint files): after 1, run 2 / 3 / 8 / 9 together. After 2+3 and 4, run 5 / 6 / 7 together (5 in `voice/`, 6 in `jobs/`, 7 in sessions + validate; 6 and 4 both touch `routes/interviews.py`, hence sequential). 10 follows once 4's OpenAPI exists. Each API task regenerates `api/openapi.json`; do not run them concurrently.

## Task 1 — R0 spike go/no-go gate
What it is / what it means: a ~1-day throwaway proof that a live AI client is good enough and affordable before any product code. Traces to R0, D1, D5, D6, risks, AC10 (spike part).
What changes at a high level: a minimal relay (local or staging), one scenario, and a bare browser page, kept out of the shipped tree. The owner talks to it and records: persona fidelity (not agreeable, not scripted, `hidden_info` not leaked), latency, cost per minute, voice audition, Chrome/Edge/Safari mic + echo, `gemini-3.8-live` vs `gemini-2.5-flash-native-audio`. Also settles the exact model id, cost/min, and whether `google-genai` bloats the shared image.
Done when: one recording passes `python -m onolys_core.stt.check` (echo + diarization, two separable speakers); written go/no-go with chosen model, voice, cost/min, image-footprint verdict, and leak-test results; owner sign-off recorded. Tests: the spike's leak-test prompt list is kept for reuse in Tasks 2 and 12. LIVE.

## Task 2 — Scenario schema, loader, `GET /scenarios`, persona prompt builder
What it is / what it means: curated scenarios as data, and the server-only persona prompt. Traces to R1, R2, D9, AC1, AC2.
What changes at a high level: `scenario.schema.json` plus one sample (brief fields + `language`, `voice`, `public`) under the miti protocol; loader validates every file at API start and fails fast; `GET /scenarios` exposes `id,title,difficulty,summary,language` only. `voice/prompt.py` builds the system prompt (in character, short turns, `response_rules`, earned `hidden_info`, `opening_line`); held in memory, never logged or sent out.
Done when: tests cover the sample validating, an invalid scenario failing startup, the `GET /scenarios` key scan excluding `persona` / `hidden_info` / `response_rules` (AC1), and the prompt containing `hidden_info`, rules and opening line while a leak test over responses, relay frames and captured logs finds none of it (AC2).

## Task 3 — Core voice adapter
What it is / what it means: swappable voice engine in the core package, mirroring the STT adapter pattern. Traces to R3, D5, D6, D7, Open Question (image footprint).
What changes at a high level: `onolys_core/voice/` with `VoiceAdapter` / `VoiceSession` / `VoiceParams` and the event union (`AudioOut`, `Interrupted`, `TurnComplete`, `ResumptionHandle`, `GoAway`, `Closed`); `voice_providers.yaml` via `locate_config_file`, `default` key; `gemini_live_vertex` adapter (ADC, location option, resumption on, compression optional/off) using the Task 1 model; `fixture` adapter with deterministic audio, scripted events and failure injection. Adds `google-genai`, applying the Task 1 footprint verdict.
Done when: unit tests cover config location/validation, fixture event sequences and failure injection, the Gemini adapter against a faked SDK (params mapping, handle and GoAway surfacing), and no provider name leaking outside the adapter/config. A `live` test opens a real session (not in PR CI).

## Task 4 — Interview API + state + SP11 seam
What it is / what it means: the REST surface and persistence for interviews. Traces to R5, D11-D14, AC3, AC6 (transitions).
What changes at a high level: API `Voice` Protocol in `adapters/base.py`, real registry, `fake.py`, `ADAPTERS=stub|real`; uid-scoped `interviews` repo methods (Repo protocol + FakeRepo); `POST /interviews` (SP11 `reserve` first, create doc with `reservation_date`, `release(refund=True)` on create failure, SP11 errors pass through, earlier unfinished interview lazily abandoned with the same refund rule); `GET /interviews/{id}`; idempotent `POST /interviews/{id}/end {discard?}`; states `created→live→ended|abandoned→uploaded`; response carries `voice_url` and limits. OpenAPI regenerated.
Done when: tests prove reserve-then-create, refund on failed create, `interview_cap_reached` propagation, foreign-user 404, lazy abandon, end/discard idempotency and the state table, using FakeRepo and a fake SP11 seam (AC3, AC6). External: SP11 `reserve`/`release`.

## Task 5 — Voice relay service
What it is / what it means: the WebSocket relay that owns the persona, upstream session and clock. Traces to R4, D1, D4, D7, D8, AC4, AC5, AC2.
What changes at a high level: `SERVICE_MODE=voice` entry plus `voice/relay.py` and `voice/clock.py`: first-frame `auth` with the same ID-token verifier, Origin check, ownership and `created|live` check; builds the prompt, opens the adapter, pumps audio, sends `ready` / `ai_speaking` / `interrupted` / `warn` / `time_up` / `error` per the protocol table; counts connected seconds and writes `duration_s`/`state`; reopens upstream on drop or `GoAway` with the stored handle; client-drop re-attach within `AI_RECONNECT_SECONDS`; optional `AI_MIC_GATE`; caps from config.
Done when: tests with the fixture adapter and an injected clock prove bad/missing auth closes 4401, wrong owner rejected, audio echo, `warn` at 480 and `time_up` at 600, reconnect at under 60 s resumes with elapsed carried and over 60 s does not, upstream drop/`GoAway` invisible to the client, mic gate, and no `hidden_info` in frames or logs (AC2, AC4, AC5).

## Task 6 — Sweeper and short-interview refund
What it is / what it means: guarantees every interview reaches a terminal state and short ones refund the usage slot. Traces to R5 (sweeper, refund), D11, D12, AC6.
What changes at a high level: at create, enqueue a delayed Cloud Task `interview-sweep` due `AI_MAX_SECONDS + AI_RECONNECT_SECONDS + 60 s` (stub queue in fake mode); `jobs/interview_sweep.py` marks still `created|live` interviews `abandoned` using relay `duration_s`; a single refund routine used by End, discard, lazy abandon and sweep: `duration_s < AI_ABANDON_COUNT_SECONDS` calls SP11 `release(refund=True)` with the stored `reservation_date`, exactly once. No Cloud Scheduler.
Done when: tests prove sweep timing and idempotency, no-op on already-ended, refund called once under `<120 s` across all four paths and never at or above 120 s (AC6). External: SP11 `release`.

## Task 7 — Session link and validate rules
What it is / what it means: ties a finished interview to the normal session pipeline. Traces to R6, R7, D10, AC7, AC8.
What changes at a high level: `POST /sessions` accepts optional `interview_id` (owned, `ended`, unlinked, else `409`); sets `sessions.interview_id`, language, default title, `interviews.session_id`, and writes `ratings/draft` with the scenario `change_goal`; interview becomes `uploaded` on `audio/complete` success. Validate: interview-linked audio over `AI_MAX_SECONDS + AI_TOLERANCE_SECONDS` fails `interview_too_long` (new public code); under `AI_MIN_SECONDS` warns `short_interview` replacing `short_recording`; plain uploads unchanged. OpenAPI regenerated. External: SP11 reads `interview_id`.
Done when: tests cover reject non-ended/foreign/already-linked, prefilled draft returned by `GET rating`, a no-rating run still allowed, 640 s fails, 250 s warns without `short_recording`, existing validate tests green (AC7, AC8).

## Task 8 — Infra: voice Cloud Run service
What it is / what it means: separate service so a 10-minute socket is possible and Vertex rights stay off the API SA. Traces to R12, D2, D3, AC11 (plan part).
What changes at a high level: `infra/modules/environment/voice.tf`: service `onolys-voice-{env}` on the same image with `SERVICE_MODE=voice`, own SA with `roles/aiplatform.user` plus Firestore access to `interviews`, 3600 s timeout, concurrency 10, low max-instances, session affinity, CPU always allocated, public invoker; env for `VOICE_PROVIDERS_FILE` and caps (`AI_*`); Vertex AI API enabled; output of the relay URL for web config.
Done when: `terraform validate` and plan checks pass in CI/local; a plan assertion shows the voice SA holds only `aiplatform.user` + Firestore and the API SA is unchanged (AC11 plan part).

## Task 9 — Web audio engine
What it is / what it means: browser capture, playback and mixed recording. Traces to R9, risks (echo, 24 kHz, Safari codec).
What changes at a high level: same-origin AudioWorklet modules for 16 kHz mono PCM16 capture and 24 kHz playback via ring buffer with resample and flush on `interrupted`; `getUserMedia` with echo cancellation and noise suppression; recording graph (mic + AI gain node into `MediaStreamDestination` → `MediaRecorder`, runtime `mimeType` pick, kept running through reconnects); playback also to speakers. Pure audio module with no UI.
Done when: unit tests cover resample math, frame sizing, ring-buffer underrun/flush, and mimeType fallback with a mocked AudioContext/MediaRecorder; manual Chrome/Edge/Safari pitch check recorded in Task 12.

## Task 10 — Web CSP, MSW mocks, in-page fake relay
What it is / what it means: let the web connect to the relay and run offline. Traces to R10, R11, AC9.
What changes at a high level: relay `wss://` host in `connect-src` of both hosting entries in `web/firebase.json`; update `csp.ts` parsing and `hosting.test.ts`; MSW handlers for scenarios, interviews, usage (using regenerated client types); an in-page `WebSocket` stub playing the relay protocol (ready, audio, warn, time_up, drop) for Storybook and PR previews.
Done when: the hosting/CSP test passes with the relay host, handler and fake-relay unit tests pass, no blob: worklet allowance added (AC9 CSP part).

## Task 11 — Web interview feature + landing cards
What it is / what it means: the user-facing flow. Traces to R8, D7, D10, AC9.
What changes at a high level: landing shows two cards above the session list, rendering SP11's `<UsageLeft>`; AI sessions tagged in the list; `/interviews/new` (scenario picker, headphone tip, mic check); `/interviews/:id` (timer from relay events, 8-min toast, auto-End at 10, End button, "reconnecting…" state, leave prompt: evaluate or discard); after End, reuse the existing upload logic, create the session with `interview_id`, navigate to `/sessions/:id` showing the prefilled change goal. Client regenerated.
Done when: component/integration tests on MSW + fake relay cover cards + usage, picker → live → End → upload → session page, warn toast, reconnect banner, discard path (AC9). External: SP11 `useUsage()` / `<UsageLeft>`.

## Task 12 — Staging end-to-end (LIVE)
What it is / what it means: proof on real infra. Traces to AC10, AC11.
What changes at a high level: deploy to staging with the real adapter; owner runs a 10-minute interview through to the report; forced 20 s network drop; Chrome/Edge/Safari mic and playback pitch check; recording passes `onolys_core.stt.check`; cost/min recorded against the spike figure.
Done when: owner-verified LIVE checklist covers persona fidelity, no hidden-info leak, relay surviving the drop, interview to report end to end, and the plan check from Task 8; results written into the branch folder (AC10, AC11).

## Task 13 — Docs
What it is / what it means: reference docs and decision record. Traces to R13, D15.
What changes at a high level: update `docs/reference/public-api.md` (interviews, scenarios, `interview_id`, new error codes, relay protocol); ADR for the Gemini exception and relay choice; branch README index; confirm `openapi.json` is current.
Done when: doc-lint/link checks pass in CI, `openapi.json` regeneration produces no diff, and all PRD acceptance criteria are mapped to a passing test or recorded LIVE result.

## Owner steps (PRD Manual steps)
1. Run/judge the R0 spike; pick model + voice; decide go/no-go (and whether to try the Claude fallback on no-go).
2. Author scenarios; sign off the sample scenario and persona rules.
3. Confirm Vertex AI Live model access in project `onolys` (Terraform enables the API; console confirm may be needed).
4. Optional later: DNS for `voice.onolys.com` (not needed for v1).
