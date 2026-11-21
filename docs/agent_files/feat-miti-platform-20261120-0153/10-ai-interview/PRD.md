---
status: approved
summary: AI practice interview — clinician holds a live voice MI session with an AI client (Gemini Live on Vertex, via a server-side WebSocket relay on a new Cloud Run service); browser records the mix and feeds the unchanged upload/evaluate pipeline; spike gate first
date: 2026-11-20
---
# PRD: SP10 AI practice interview

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP00-SP09 done; **SP11** (usage limits: reserve/release, `GET /usage` shape, usage component, free-first-run rule); SP01 (`SttAdapter` pattern, config loader), SP04 (sessions, validate, upload flow), SP05 (web shell, upload feature), SP06 (Terraform) · Owns: `engines/core/src/onolys_core/voice/**`, `config/{env}/voice_providers.yaml`, `protocols/miti-4.2.1/scenarios/**` (schema + 1 sample), `api/src/onolys_api/{routes/interviews.py,routes/scenarios.py,voice/**,jobs/interview_sweep.py}`, validate changes, `api/openapi.json`, `web/src/features/interview/**` + landing cards, `web/src/mocks/**` additions, `web/firebase.json` CSP, `infra/modules/environment/{voice.tf}`, `docs/reference/public-api.md` update. Brief: `../brainstorm.md` (decisions 1-16 all apply).

## TL;DR
Landing gets two cards. "Start AI Interview": pick a curated scenario, speak with an AI client in the browser, press End; the browser uploads its own mixed recording through the **existing** signed-URL flow and lands on the normal session page (speaker check, rating card with change goal prefilled, run, report). The AI voice runs through a **backend WebSocket relay** (new Cloud Run service `onolys-voice-{env}`) to Vertex AI Gemini Live using the service account (no API key). The persona prompt incl. `hidden_info` never leaves the server. Pipeline contracts are unchanged. A ~1-day **spike gate** comes first.

## Problem
MI learners need a practice partner; a mock interview needs a second person. See brief.

## Goals / Non-Goals
**Goals:** natural real-time voice practice alone; AI client reacts to MI quality (not a pushover, not scripted); same report as uploads; voice engine swappable (server-side adapter); server-enforced durations; API-first except the live stream.
**Non-goals (v1):** live captions, pause, auto speaker mapping, user-written scenarios, scenario-aware report feedback, mobile parity, video, storing AI-side transcripts, custom voice domain, usage limit logic (SP11).

## Requirements
**R0 Spike gate (first task, go/no-go).** Minimal relay (local or staging) + one scenario + bare browser page; Tejit talks to it. Measure: persona fidelity (agreeable? scripted? leaks hidden_info?), latency, cost/min, voice audition, Chrome/Edge/Safari mic + echo, one recording through `python -m onolys_core.stt.check` (echo + diarization). Compare `gemini-3.8-live` vs `gemini-2.5-flash-native-audio`. No-go: shelve, or try the brief's Claude fallback once. Nothing below ships before go.
**R1 Scenarios.** `protocols/miti-4.2.1/scenarios/scenario.schema.json` + `sample-*.json` (brief fields plus `language` (en-US), `voice`, `public{title,difficulty,summary}`). Loader validates all files at API start (fail fast); baked into the image. `GET /scenarios` returns public fields only (`id,title,difficulty,summary,language`); never `persona/hidden_info/response_rules`.
**R2 Persona prompt builder** (server-only, `api/voice/prompt.py`): system prompt from scenario: stay in character always (no meta-talk, no "as an AI", no coaching the clinician), speak as a client would (short turns, hesitation), no script, apply `response_rules` (reflections open up; 2+ persuade/confront raise sustain talk), reveal `hidden_info` only if earned, never volunteer the change goal as a decision, `opening_line` first. Held in memory per relay connection; never logged, never sent to the client, never stored in Firestore.
**R3 Voice adapter.** `onolys_core/voice/`: `VoiceAdapter` Protocol `open(params: VoiceParams{provider, model, voice, language, system_prompt, resumption_handle?, options}) -> VoiceSession`; `VoiceSession`: `send_audio(pcm16k)`, async `events()` yielding `AudioOut(pcm24k) | Interrupted | TurnComplete | ResumptionHandle(h) | GoAway | Closed(reason)`, `close()`. `voice_providers.yaml` (`providers:{key:{provider, model, voice, options}}`, `default`; also lists the allowed voices) located like `stt_providers.yaml` (`locate_config_file`); `gemini_live_vertex` adapter (ADC, `location` option, session resumption on, context window compression optional/off), `fixture` adapter (deterministic tone/silence + scripted events; failure injection) for tests, PR previews, MSW. API seam `Voice` Protocol in `adapters/base.py`, registry `real.py`, fake in `fake.py`, `ADAPTERS=stub|real`.
**R4 Relay endpoint** `wss://<voice-host>/v1/voice/{interview_id}` (SERVICE_MODE `voice`, same image). First client frame must be `auth` (Firebase ID token, same verifier as `current_user`; token not in URL); Origin must be an allowed app origin; interview must belong to uid and be `created|live`. Relay builds the prompt, opens the upstream session, pumps audio both ways, **owns the clock**: counts connected live seconds, sends `warn` at `AI_WARN_SECONDS`, `time_up` + closes at `AI_MAX_SECONDS`, writes `duration_s`/`state` to `interviews/{id}`. Upstream drop or `GoAway`: reopen with the latest resumption handle (handle stored on the interview doc, server-only) without the client noticing. Client drop: close upstream, mark `disconnected_at`; a reconnect within `AI_RECONNECT_SECONDS` re-attaches (new upstream with handle, elapsed carried over). Optional mic gate: relay drops upstream mic frames while the AI is speaking when `AI_MIC_GATE=true`.
**R5 Interview API + state.** `POST /interviews {scenario_id, voice?}` (sync 201): calls SP11 `reserve(repo, settings, uid, "interview")` first (its own transaction; raises 429); on success creates `interviews/{id}` {uid, scenario_id, state=created, created_at, `reservation_date` (= `Reservation.date`), ...}; if the create fails, calls `release(repo, uid, reservation, refund=True)`; returns `{interview_id, voice_url, scenario public fields, limits{max_s, warn_s}}`; errors from SP11 pass through (`interview_cap_reached`). A user's earlier unfinished interview is lazily abandoned first (same refund rule). `GET /interviews/{id}` (state, elapsed). `POST /interviews/{id}/end {discard?: bool}` (idempotent): `ended` (or `abandoned` if `discard`). States `created→live→ended|abandoned→uploaded`. [R5 refund threshold is `AI_ABANDON_COUNT_SECONDS`, now 30 s.[CHANGED by owner 2026-11-21: 120 → 30 s]] **Sweeper:** at create, enqueue a delayed Cloud Task `interview-sweep` due `AI_MAX_SECONDS + AI_RECONNECT_SECONDS + 60 s`; if still `created|live`, mark `abandoned`, using relay-recorded `duration_s`. No Cloud Scheduler. Refund: when an interview becomes `ended|abandoned` with `duration_s < AI_ABANDON_COUNT_SECONDS`, call SP11 `release(repo, uid, Reservation("interview", reservation_date), refund=True)` (uses the stored `reservation_date`); otherwise `refund=False`/stays counted. Firestore rules unchanged (`interviews/*` client-denied).
**R6 Session link.** `POST /sessions` gains optional `interview_id`: must be owned, `ended`, not already linked (else `409 conflict`/`invalid_state`); sets `sessions.interview_id`, language from scenario, default `title` = scenario title, `interviews.session_id`. Server writes a **draft rating** (`ratings/draft`, same doc `PUT rating final=false` uses) with `change_goal` from the scenario, so any client (web or API) sees it prefilled; the user can edit it, and a "no rating" run is still allowed (paudit treats `change_goal` as optional: `params.get("change_goal")` in `engines/paudit/src/paudit/engine.py:329`; [RESOLVED: verified `api/src/onolys_api/jobs/run.py:152` passes `session.change_goal or ""`, `engines/paudit/src/paudit/code_pass.py:138` omits an empty goal, report schema `change_goal` is a plain string; fixture `protocols/miti-4.2.1/fixtures/evaluation/report_no_rating.json`]). Interview → `uploaded` on `audio/complete` success. SP11 reads `session.interview_id` for the free-first-run rule.
**R7 Validate.** Interview-linked: max `AI_MAX_SECONDS + AI_TOLERANCE_SECONDS` (600+30) → fail `interview_too_long` (new public error code); warning `short_interview` below `AI_MIN_SECONDS` (300) **replaces** `short_recording` (SHORT_RECORDING_S=600, `audio.py:22`); the STT `max_audio_s` (1200 s) still applies. Uploads without `interview_id` unchanged.
**R8 Web.** Routes: `/` landing = two cards above the session list (SP05 `Dashboard`), cards render SP11's usage component; AI sessions tagged in the list; `/interviews/new` scenario picker (incl. voice choice) + headphone tip + mic permission check; `/interviews/:id` live page: timer, warning toast at 8 min, auto-End at 10, End button, "reconnecting…" state, leave prompt ("evaluate what I have" = End + upload / "discard"). After End: upload via the existing upload logic (reused, not forked), then navigate to `/sessions/:id` (draft change goal already there). Desktop Chrome/Edge/Safari; mobile best effort.
**R9 Audio.** AudioWorklet capture (16 kHz mono PCM16 frames ~20-40 ms; resample in the worklet from the context rate) and playback (24 kHz PCM from the relay via a ring buffer; resample to context rate; on `interrupted` flush the buffer). `getUserMedia` with `echoCancellation` + `noiseSuppression`. Recording graph: mic `MediaStreamSource` + AI playback `GainNode` → `MediaStreamDestination` → `MediaRecorder` (webm/opus); playback also → `ctx.destination`. Recorder runs through reconnects. Browser crash = recording lost (accepted).
**R10 CSP/hosting.** Relay host added to `connect-src` as `wss://…` in both hosting entries of `web/firebase.json`; update `csp.ts` parsing/`hosting.test.ts`. Worklet modules served same-origin (`script-src 'self'`; no blob: worklets).
**R11 Mocks.** MSW handlers for scenarios/interviews/usage; a browser-side fake relay (in-page `WebSocket` stub) for Storybook/PR previews.
**R12 Infra** (see Architecture). **R13 Docs.** `docs/reference/public-api.md`, ADR for the Gemini exception + relay choice, branch README index.

## Architecture
```
Browser ──REST /v1/** (Hosting rewrite, same origin)──> Cloud Run onolys-api-{env} ──> Firestore interviews/{id}, Cloud Tasks (sweep), SP11 reserve/release (reserve first, then create doc)
Browser ══wss (direct, Firebase ID token in first frame)══> Cloud Run onolys-voice-{env} ══> Vertex AI Gemini Live (ADC)
Browser: mic ─worklet→ relay ; relay → worklet → speakers ; mic + AI → MediaRecorder → signed-URL upload (existing)
```
**Relay protocol** (JSON text frames + binary audio frames):
| Dir | Message | Notes |
|---|---|---|
| C→S | `{type:"auth", id_token}` | must be first; 4401 close otherwise |
| C→S | binary | PCM16 16 kHz mono |
| C→S | `{type:"end"}` | graceful end |
| S→C | `{type:"ready", resumed, elapsed_s, max_s, warn_s}` | after upstream open |
| S→C | binary | PCM16 24 kHz mono (AI) |
| S→C | `{type:"ai_speaking", on}` · `{type:"interrupted"}` | UI + flush playback |
| S→C | `{type:"warn", at_s}` · `{type:"time_up"}` | server clock |
| S→C | `{type:"error", code}` | `upstream_unavailable`, `interview_not_live`, … then close |
Module split: `voice/prompt.py` (R2), `voice/relay.py` (loop, clock, resumption), `voice/clock.py`, `routes/interviews.py`, `interviews` repo methods behind the existing `Repo` protocol (uid-scoped; FakeRepo too).
**Infra:** new Cloud Run service `onolys-voice-{env}` (same image, `SERVICE_MODE=voice`), own SA with `roles/aiplatform.user` only (+ Firestore access to `interviews`), request timeout 3600 s, concurrency 10, max-instances low (cost/abuse cap), session affinity on (best effort; correctness does not depend on it), CPU always allocated while connected, ingress all + `allUsers` invoker (auth is in-app: ID token + Origin). Env: `VOICE_PROVIDERS_FILE`, caps. Config table: `AI_MAX_SECONDS=600`, `AI_WARN_SECONDS=480`, `AI_MIN_SECONDS=300`, `AI_TOLERANCE_SECONDS=30`, `AI_ABANDON_COUNT_SECONDS=30`, `AI_RECONNECT_SECONDS=60`, `AI_MIC_GATE=false`; cap values are SP11's. [CHANGED by owner 2026-11-21: 120 → 30 s] (`AI_ABANDON_COUNT_SECONDS`).

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Connection | Backend WS relay to Vertex Gemini Live | Browser-direct with ephemeral token | Persona/`hidden_info` must stay server-side; no new API key; token-locked systemInstruction reported unreliable; adapter stays server-side |
| 2 | Relay placement | **Separate service `onolys-voice-{env}`**, same image | New route in `onolys-api` | Firebase Hosting has a hard 60 s request timeout [verified: firebase.google.com/docs/hosting/cloud-run] and docs do not mention WebSocket support [verified: absence; unproven either way], so same-origin `/v1` cannot carry a 10-min socket. Separate service gives 3600 s timeout, own concurrency/max-instances, own SA (Vertex role off the API SA), no impact on API latency. api service is 60 s/80 concurrency (`services.tf`) |
| 3 | Browser reaches relay | Direct to Cloud Run `run.app` URL, wss, CSP entry | Custom `voice.onolys.com`; load balancer | No DNS or LB needed; custom domain is a later swap of one env var + CSP entry. Cost: public URL (mitigated by token + Origin + max-instances) |
| 4 | Auth to relay | ID token in first WS frame | Query param; IAM invoker | URLs get logged; browsers cannot send IAM tokens |
| 5 | Model | Config; default `gemini-3.8-live` (confirmed by spike, owner 2026-11-21); spike also `gemini-2.5-flash-native-audio` (affective dialog, 2.5 only); owner picks | Hardcode | Preview models shift; 09-2025 preview is discontinued 2026-03-19 per Vertex docs [verified: search listing] |
| 6 | Region | `us-central1` for Vertex location option | `global` | Same region as the stack; native-audio models listed there [verified: Vertex docs listing; per-project access reports vary — confirm in spike] |
| 7 | Resumption | Enabled; handle held server-side; browser reconnect simple (retry same interview ≤60 s) | No resumption | Cheap via relay (owner: support if easy) |
| 8 | Elapsed time | Relay-owned connected seconds | Client timer | Server enforces cap; client cannot extend |
| 9 | Persona rules | Always in character; reveal only if earned; no coaching | Disclose AI on request | Practice fidelity; user knows it is an AI and End is the exit |
| 10 | Change goal prefill | Server writes draft rating with scenario `change_goal` at session create | Web-only prefill | API-first; web simply shows the draft |
| 11 | Sweeper | Delayed Cloud Task per interview | Cloud Scheduler (SP06 non-goal); lazy only | Reuses queue; bounded delay |
| 12 | Unfinished earlier interview | Lazily abandoned on next `POST /interviews` | 409 until sweep | User who closed the tab is not blocked |
| 13 | Interview audio retention | No AI transcript stored; only recording via existing flow | Store AI text | Less PHI surface |
| 14 | Usage seam | SP10 calls SP11 `reserve(repo, settings, uid, "interview")` then creates the doc (stores `reservation_date`); on create failure `release(refund=True)`; later `release` uses the stored date; SP11 reads `interview_id` | SP10 owns limits | Separate sub-project |
| 15 | Platform LLM rule | Gemini for the client voice is an owner-approved exception; evaluation stays Claude | — | Brief D2 |
| 16 | Voice choice | User picks from the full provider voice list (30) on `/interviews/new`; scenario `voice` is the default; `POST /interviews` takes optional `voice`, validated server-side against the configured list | Fixed voice per scenario | Owner 2026-11-21: let users choose |

## Manual steps (owner)
1. Try the spike (R0), pick model + voice, go/no-go; decide whether to try the Claude fallback if no-go.
2. Author scenarios; sign off the sample scenario and persona rules.
3. Enable the Vertex AI API in project `onolys` / confirm Live model access (Terraform enables API; model access may need console confirm).
4. Optional later: DNS for `voice.onolys.com` (CNAME/Cloud Run domain mapping) — not needed for v1.

## Risks
| Risk | Mitigation |
|---|---|
| Persona too agreeable / leaks `hidden_info` | Spike kill question; prompt tuning; leak test list in spike |
| Hosting WebSocket behaviour unproven | Not relied on: direct connection [verify with one staging test only if a same-origin path is ever wanted] |
| Echo → STT diarization confusion | Headphone tip; AEC; optional mic gate; spike STT check [WAIVED by owner 2026-11-21: 5-min recording and echo check; spike recordings (75-198 s, 2 separable speakers) accepted] |
| 24 kHz playback on 48 kHz hardware (pitch/glitch) | Explicit resample in worklet; manual Chrome/Edge/Safari test |
| Public relay URL abuse/cost | ID token + Origin + max-instances + SP11 caps + 10 min clock |
| Safari WebAudio/MediaRecorder codec (mp4 vs webm) | Pick supported `mimeType` at runtime; server already accepts mp4/m4a aliases |
| Preview model churn | Model in config; adapter isolates changes |
| Short-interview refund loop (unbounded <30 s refunds → free Gemini time / voice capacity) | [ACCEPTED by owner 2026-11-21: no per-user refund cap] |

## Open Questions
| Q | Status |
|---|---|
| Gemini model id for default (`gemini-3.8-live` unverified; 2.5 id seen as `gemini-live-2.5-flash-native-audio`) | [RESOLVED: gemini-3.8-live (owner 2026-11-21, spike)] |
| SP03 `run_evaluation` with no `change_goal` / no rating | [RESOLVED: verified run.py:152, code_pass.py:138; no-goal run accepted] |
| Cost per minute | [RESOLVED: measured ~$0.04/min on gemini-3.8-live (owner live sessions of 1.3-3.3 min; $0.022-0.051/min), ~$0.11/min projected at 10 min; context is re-billed each turn so the cap bounds it (spike RESULTS.md)] |
| Hosting-to-Cloud Run WebSocket support | [DEFERRED: not needed; 60 s timeout rules it out for this use] |
| Privacy of clinician audio sent to Google | [RESOLVED: owner "don't worry" 2026-11-20] |
| Reconnect scope | [RESOLVED: supported via relay, kept simple] |
| Does api `ADAPTERS=real` need Vertex SDK dependency footprint in the shared image | [RESOLVED: google-genai added to shared image (+19 MB, ~4%, spike)] |
| Free first eval + usage component specifics | [DEFERRED: SP11] |

## Acceptance Criteria
All without real Gemini via the fixture adapter, unless marked LIVE.
1. Scenario schema validates the sample; invalid scenario fails API start; `GET /scenarios` JSON contains no `hidden_info`/`response_rules`/`persona` (test scans keys).
2. Prompt builder includes `hidden_info` + rules + opening line; a test proves no relay→client frame, log line, or `/v1` response contains `hidden_info` text.
3. `POST /interviews` reserve then create (doc stores `reservation_date`); failure after reserve refunds; cap error propagates; another user cannot read/end it (404).
4. Relay (fixture adapter): bad/missing `auth` closes 4401; wrong owner rejected; audio echoes through; `warn` at 480 s and `time_up` at 600 s using an injected clock; client drop then reconnect ≤60 s resumes with elapsed carried; >60 s does not.
5. Upstream drop/`GoAway` in the fixture triggers reopen with stored handle; client sees no error.
6. End/discard/sweeper transitions per state table; `<30 s` calls SP11 release exactly once (idempotent), `≥30 s` does not. [CHANGED by owner 2026-11-21: 120 → 30 s]
7. `POST /sessions {interview_id}`: rejects non-ended/foreign/already-linked; sets language, title, `interview_id`, draft change goal; `GET rating` returns the draft.
8. Validate: 640 s interview audio → `interview_too_long`; 250 s → `short_interview` and no `short_recording`; plain upload behaviour unchanged (existing tests green).
9. Web (MSW + fake relay): landing shows two cards + usage; picker → live page → End → upload → `/sessions/:id`; warn toast at 8 min; reconnect banner; discard path; CSP test passes with the relay host; `openapi.json` regenerated, client regenerated, CI clean.
10. LIVE spike: owner completes a 10-min session on staging; persona stays in character; hidden info only when earned; recording passes `onolys_core.stt.check` with two separable speakers; cost/min recorded; Chrome/Edge/Safari mic and playback pitch checked. [WAIVED by owner 2026-11-21: 5-min recording and echo check; spike recordings (75-198 s, 2 separable speakers) accepted]
11. LIVE staging: end-to-end interview → report; relay survives a forced network drop of 20 s; terraform plan shows voice SA has only `aiplatform.user` (+ Firestore), api SA unchanged.
