---
status: approved
summary: AI practice interview (SP10, future) — clinician runs a live voice MI session with an AI client (Gemini Live) from a curated scenario; recording feeds the existing evaluate pipeline unchanged; SP10 also owns the new usage limits
date: 2026-11-20
---

# SP10 AI practice interview: brainstorm brief

## TL;DR
After login on `app.onolys.com` (SP05) the landing shows two cards, marketed as two products: **Start AI Interview** and **Evaluate Mock Interview**. Each shows "N of M left today". The Evaluate card is today's upload flow, unchanged. The AI card: pick a curated scenario, hold a live two-way voice interview in the browser with an AI playing the client, press End. The browser uploads the mixed recording through the **existing** signed-URL flow (SP04: `POST /sessions` -> `POST …/audio` -> PUT -> complete). The user lands on the normal evaluate screen (audio already uploaded): speaker check, optional rating card + notes (or no rating, as today), run, report. The report is identical to the upload path. The pipeline (validate, transcode, STT, paudit/eaudit/tips) does not change.

Built only after SP00-SP09 are done; sub-tasks added later via dev-design/dev-tasks. Until SP10 the platform keeps SP04's `DAILY_RUN_CAP=20`; SP10 owns the limits rework (SP04 R8, `GET /usage`, SP05 usage display).

## Problem
Clinicians learning MI need a partner to practise with, and a mock interview needs a second person. With an AI client they can practise alone, any time, then get the same MITI-based evaluation as for an uploaded recording.

## Decision log
| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| 1 | Real-time two-way voice (natural turn-taking, interruptions); best current model | Push-to-talk; text chat | Practice must feel like a real session (Tejit) |
| 2 | Voice engine = Gemini Live (Google realtime speech-to-speech, existing GCP project `onolys`, latest best Gemini Live model; exact model id pinned in config at build). Mechanical/plain voice is fine; goal is to build fast. Still behind a voice adapter so a swap stays small | ElevenLabs agent + Claude brain (new vendor, not needed); OpenAI Realtime (new vendor); Claude chained STT -> Claude -> TTS (no Claude realtime voice API; more code, 1-3 s lag) | Same Google project and vendor as STT, least code (Tejit). This makes "AI client brain = Gemini" an explicit exception to the platform's "all LLM work on Claude" rule; evaluation LLM work stays on Claude (Tejit) |
| 3 | Fallback only if Gemini plays the persona badly: browser speech recognition + Claude + browser `speechSynthesis` | Make the chained variant the main path | Cheap to try once; slower and more code, so not first (Tejit) |
| 3b | Recording is made by our own browser code (mic + AI audio mixed), not the vendor's | Vendor-side recording | Vendor swap never touches the pipeline (Tejit) |
| 3c | Spike shrinks to about 1 day: Gemini Live with 1 scenario, Tejit tries it; go/no-go. Kill question: does the AI client sound too agreeable or scripted? | Two-vendor bake-off with a clinician | Single vendor, fast decision (Tejit) |
| 4 | Curated scenario library only, files in the repo; change = deploy. SP10 ships a JSON Schema + ONE sample scenario; Tejit authors the rest (or with Claude) | User-written scenarios; DB/admin-edited scenarios | Quality control, no admin UI. Path `protocols/miti-4.2.1/scenarios/` (Claude's call) |
| 5 | Scenario `change_goal` prefills the session's change goal (pipeline requires one) | User types it | Already known from the scenario (Tejit) |
| 6 | Durations as config, AI interviews only: max 10 min, warning at 8, hard stop at 10; warn if under 5 min. Uploads keep 25 min max / under-10 warning | Reuse the 25 min limit | Cost control; limits change by config only. Warning at 8 (Claude's call) |
| 7 | End = clinician presses End; no pause; connection drop: resume within 60 s; on quit choose "evaluate what I have" or "discard"; abandoned interviews count toward the AI cap once longer than 2 min | Pause button; count every start | Keeps the recording one continuous take; stops cap dodging (Tejit) |
| 8 | No live captions during the interview | Live captions | Real conversations have none; less to build (Tejit) |
| 9 | No auto speaker mapping in v1; normal speaker-check screen (easy: one speaker is the AI) | Auto-map via mic-activity time list | Reversed by Tejit; zero change to the speaker flow (Tejit) |
| 10 | Server-enforced limits: evaluations 10/day, 100/month; AI interviews 5/day, 30/month; no yearly. Defaults in config (SP10 replaces `DAILY_RUN_CAP=20`); per-user overrides in `users/{uid}.limits`, edited only by Tejit in the Firebase console. UTC day / UTC calendar month. Checked atomically in the same Firestore transaction as today's run cap | Client-side limits; admin UI | Existing rules already deny client writes to `users/{uid}`; no admin UI in v1 (Tejit) |
| 10b | ALL limits (evaluation 10/day + 100/month with per-user override, AND AI 5/day + 30/month) are built in SP10, not added to SP00-SP09. SP10 owns the rework of SP04 R8, `GET /usage` and the SP05 usage display | Move eval limits into SP04/SP05 now | Do not disturb current work (Tejit) |
| 11 | AI session: first evaluation does not count toward the evaluation limit (AI cap covers it); "Run again" re-runs count | Count every run | Avoid double charging one practice (Tejit) |
| 12 | Cards show remaining usage ("3 of 5 left today"). `GET /usage` returns both limits (day + month) per kind. New error `interview_cap_reached` (HTTP 429) with `details[]` carrying `period` = `day`/`month`; eval cap keeps `daily_cap_reached` + `monthly_cap_reached` | Separate endpoint; one code per period | One call feeds both cards; reuse the R9 error body (Claude's call) |
| 13 | API-first (see below): `/v1` gains list scenarios, start interview, end interview. The upload session is linked server-side to the interview, so the server applies AI rules (10-min cap, free first eval, change-goal prefill). Live voice stream is web-only in v1 | Client declares "source=ai" on the session | A user cannot fake AI source to dodge the eval cap (Tejit) |
| 14 | Desktop Chrome/Edge/Safari fully supported; mobile best effort; headphones recommended | Mobile parity | AI voice echo into the mic confuses STT (Tejit) |
| 15 | Report does NOT use scenario "truth" in v1 (no "client hid X, did you elicit it") | Scenario-aware feedback | Would change SP03; later candidate (Tejit) |
| 16 | Future SP10, after SP00-SP09 | Build now | Core platform first (Tejit) |

## Design

### Flow
| Step | Who | What |
|---|---|---|
| 1 | Web | Landing: two cards + usage from `GET /usage`; session list below, AI sessions tagged |
| 2 | Web | `GET /scenarios`: pick one (title, difficulty, one-line setup) |
| 3 | API | `POST /interviews {scenario_id}`: checks AI cap, creates `interviews/{id}` (status, started_at, scenario_id), returns vendor session token (short-lived) |
| 4 | Web | Live voice via the voice adapter (Gemini Live); our code records mic + AI audio into one mixed file |
| 5 | Web/API | End (or limit hit): `POST /interviews/{id}/end`; then `POST /sessions {interview_id}` -> audio -> PUT -> complete (unchanged upload flow) |
| 6 | Web | Normal session page: speaker gate, optional rating + notes, run, report |

### Scenario schema (`scenario.schema.json` + one sample)
| Field | Notes |
|---|---|
| `id`, `title`, `difficulty` | easy / medium / hard |
| `persona` | name, age, situation |
| `change_goal`, `stage_of_change`, `ambivalence_level`, `emotional_state` | Drives the client's stance |
| `opening_line` | First thing the client says |
| `hidden_info` | Revealed only if earned by the clinician |
| `response_rules` | Good reflections -> opens up, more change talk; 2+ persuade/confront -> more sustain talk, resistance |

No script. The AI client reacts to MI quality within the persona bounds.

### API additions (`/v1`)
| Endpoint | Purpose |
|---|---|
| `GET /scenarios` | List curated scenarios (no hidden fields) |
| `POST /interviews` | Start; enforces AI cap; returns short-lived Gemini Live token |
| `POST /interviews/{id}/end` | End; records duration; sets state for upload linking |
| `GET /usage` (extended) | `{evals:{day,month}, interviews:{day,month}}` with used/cap/resets_at |
| `POST /sessions` (extended) | Optional `interview_id`; server validates ownership, applies AI rules |

Upload, STT and run endpoints are otherwise unchanged. Firestore: client writes stay denied; only `session_status/{sid}` is client-readable.

### Config (new)
`AI_MAX_SECONDS=600`, `AI_WARN_SECONDS=480`, `AI_MIN_SECONDS=300` (warning), `AI_ABANDON_COUNT_SECONDS=120`, `AI_RECONNECT_SECONDS=60`, `EVAL_CAP_DAY=10`, `EVAL_CAP_MONTH=100`, `AI_CAP_DAY=5`, `AI_CAP_MONTH=30`. Overrides: `users/{uid}.limits`.

## Goals, non-goals, anti-goals
- **Goals:** a clinician practises alone by voice, then gets the normal report; build fast; voice engine swappable via the adapter; limits enforced server-side; every feature reachable by API except the live stream.
- **Non-goals (v1):** auto speaker mapping, live captions, pause, user-written scenarios, scenario-aware report feedback, admin UI for limits, voice streaming via public API, video.
- **Anti-goals:** an AI client that is a pushover (always agrees) or scripted; any change to the evaluate pipeline contracts; limits enforceable only client-side; vendor lock-in of the recording.

## Open risks
| Risk | Cheapest test |
|---|---|
| Gemini plays the persona badly (too robotic, agreeable, breaks character, leaks hidden_info) | ~1-day spike: Gemini Live, 1 scenario, Tejit tries it; if bad try the Claude fallback once, else shelve |
| Echo/diarization of mixed AI + mic audio in STT | Run one spike recording through the SP01 STT check |
| Gemini Live cost per minute | Measure during the spike |
| Clinician audio sent to Google voice model (same vendor as STT): privacy | Tejit's (owner) call before go |
| Browser mic permission, Safari audio capture quirks | Manual check on spike, Chrome/Edge/Safari |

## Builder-check answers
| Question | Answer |
|---|---|
| Where does SP10 live? | New sub-project folder in this branch folder. PRD/TASKS come later via dev-design/dev-tasks; the branch `README.md` is updated then, not now (Claude's call) |
| Spike no-go? | SP10 shelved, or try the Claude fallback once (Claude's call) |
| Voice adapter | Modeled on SP01 `SttAdapter` + a config yaml entry (e.g. `voice_providers.yaml`); lives in `api/` (server side). Builds the system prompt from the scenario incl. `hidden_info` + `response_rules`, mints the short-lived session/token; the client never sees `hidden_info`. Exact shape is dev-design's job (Claude's call) |
| New endpoints | Follow SP04 conventions (mutations 202 + ids where async; a synchronous interview create returning the token is fine); dev-design reconciles. `POST /sessions` gains optional `interview_id`; server validates it belongs to the user and is ended (Claude's call) |
| `interviews/{id}` fields | uid, scenario_id, state (created/live/ended/abandoned/uploaded), started_at, ended_at, duration_s, session_id. API-only, no client-readable doc in v1 (Claude's call) |
| AI cap timing | Counted at start; refunded if the interview ends/abandons under 2 min; a server-side timeout cleanup marks never-ended interviews abandoned (Claude's call) |
| Recording | Browser `MediaRecorder` mixes mic + AI output (webm/opus), keeps recording across a resume within 60 s; on End uploads automatically via the existing signed-URL flow. Browser crash = recording lost (accepted v1) (Claude's call) |
| STT failure after an interview | If STT returns `speakers_not_separated`/`no_speech` the AI cap still counts (the interview happened); evaluation refund follows the existing SP04 refund rule (Claude's call) |
| "First evaluation free" | The run that sets `first_run_id` on the linked session; if it fails before any LLM call it is refunded as today; later `POST /runs` count (Claude's call) |
| Duration enforcement | Server enforces the 10-min max on interview-linked sessions at `validate` (new code e.g. `interview_too_long`, tolerance e.g. +30 s). Under-5-min is a session warning (e.g. `short_interview`) on the evaluate screen, replacing `short_recording` for AI sessions (Claude's call) |
| Scenarios | Baked into the image from `protocols/miti-4.2.1/scenarios/`; `GET /scenarios` returns public fields only (no `hidden_info`/`response_rules`); ids stable; sample includes `language` (en-US v1) and `voice` (config voice name); session language set from the scenario (Claude's call) |
| CSP / secrets | Interview page needs a `connect-src` exception for the Gemini Live endpoint (or the API proxies the stream; dev-design picks); no third-party SDK script beyond what is needed; secrets via the existing Secret Manager pattern (add a voice entry) (Claude's call) |
| Privacy of audio | Clinician audio goes to a Google voice model, same vendor as STT: Tejit's call |

## Owner tasks (Tejit)
- Try the ~1-day Gemini Live spike with 1 scenario; make the go/no-go call (and whether to try the Claude fallback).
- Decide privacy for clinician audio sent to the Google voice model.
- Author scenarios (or design with Claude).
- Set per-user limits in the Firebase console as needed.
(No new vendor account: Google, same project `onolys`.)
