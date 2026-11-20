---
status: draft
summary: Onolys MITI platform — clinician uploads a mock MI session + self-rating; Onolys rates it with MITI 4.2.1, compares, explains differences with evidence, gives tips
date: 2026-11-20
---

# Onolys MITI platform: brainstorm brief

## TL;DR
A clinician practising Motivational Interviewing (MI) records a mock interview, rates it themselves with MITI 4.2.1 and writes reasons. They upload the audio plus that rating to `app.onolys.com`. Onolys rates the same interview itself (protocol audit), checks the clinician's rating and reasons against the transcript (evidence audit), and returns one report: Onolys score, why, "Onolys disagrees, here's why" with transcript lines where the two differ, and 3-5 improvement tips. API-first, on Google Cloud, with every model/provider choice a parameter. Engines are protocol-agnostic; MITI is one protocol pack.

## Problem
Clinicians learning MI rate their own practice sessions but get no second opinion until a human coder ($40-95/h, 7-10 days) looks. They need a fast, evidence-linked second rating and concrete feedback. First users: clinicians practising MI who asked Tejit for this; single-person sign-up only.

## Decision log
| Decision | Alternative rejected | Why |
|---|---|---|
| User = clinician who ran the mock interview and self-rated (Tejit) | Trainer rating someone else | That is who asked |
| Protocol audit = Onolys rates the session with MITI; evidence audit = check the clinician's rating/reasons against the transcript (Tejit) | Evidence audit as a separate section | Folded into each item's comparison |
| Report per item: Onolys score, why, difference + evidence (supporting or not), then 3-5 tips (Tejit) | Coaching for a separate trainer | No trainer in the flow |
| MITI 4.2.1 (Tejit) | Older 4.x / waiting for a newer version | CASAA lists 4.2 as latest; no MITI 5 found |
| Engines live in the `onolys` repo (was `iaudit`); override iaudit mission/AGENTS.md exclusions on scoring and protocol review (Tejit) | New repo | Reuse eaudit code; Tejit approved the scope change |
| Engines are generic: `eaudit` (evidence), `paudit` (protocol), later `caudit` (clinician); protocol specifics in packs (Tejit) | MITI hard-coded in the engine | Reuse for other protocols later |
| All Google Cloud; STT provider, STT model, language, LLM routes, scoring-run count are parameters (Tejit) | Fixed vendors | Swap later per quality/language |
| Default STT Google Chirp 3 with diarization; Whisper later as an adapter (Claude's call, Tejit OK) | Whisper first | Whisper needs a separate diarizer |
| Session language: user dropdown, auto-detect default; report in English in v1 (Tejit) | Multilingual reports | Scope |
| Whole recording scored, max 25 min; optional "coded from-to" span limits scoring to what the clinician rated (Tejit) | 20-min random segment | Fair comparison, simple |
| Change goal required; taken from the upload if present, else typed (Tejit) | Optional | MITI requires it before coding |
| Rating input: paste + file upload (docx/pdf/xlsx/txt) parsed by a model into our schema; user confirms before the run; partial ratings allowed (Tejit) | Form only | No official MITI form exists (manual has none); Tejit is checking |
| Runs without a rating allowed: Onolys rating + tips only (Tejit) | Rating required | Useful for practice |
| Scoring runs N is a parameter, default 1; results stored as an array; report shows mean and spread when N>1 (Tejit) | Fixed 3 runs | Cost/quality dial |
| Each re-run creates a new report version; old ones kept; dashboard uses latest (Claude's default, not objected) | Overwrite | History and model comparison |
| Speaker check: after transcription show 3 lines per speaker, user picks the clinician; no transcript editing in v1 (Tejit) | Auto only | Wrong labels corrupt every count |
| Tone: "Onolys disagrees, here's why"; never "you are wrong"; not official MITI coding (Tejit) | Verdicts on the person | Human-vs-expert agreement on globals is only moderate |
| API-first: web app uses the public API; personal API keys in settings (Tejit) | UI-only | Integration with other systems |
| Delete session removes audio, transcript, ratings, all report versions; auto-expiry a setting, off by default (Tejit) | Fixed 30-day deletion | Tejit handles legal |
| Legal, BAA, HIPAA mode, MITI permission, price: Tejit owns; not blockers (Tejit) | Gating launch on them | Build PHI-ready controls anyway |
| Cut for hack: PDF export, team accounts, billing, email notifications, dashboard trends (Tejit) | Building them | Time |

## Design

### Hosts
| Host | What |
|---|---|
| `miti.onolys.com` | Landing (repo `onolys-landing`, Astro, Firebase Hosting). Top right: "Sign up", "Log in" → app. "Try it out" replaces the "Get early access" top-bar CTA; `CtaButton` component kept in the repo for later. |
| `app.onolys.com` | Web app + public API: auth, upload, jobs, reports, dashboard. |
| `admin.onolys.com` | Today's iaudit frontend + eval server, behind a login (Google IAP or similar), internal only. May move to its own repo if needed. |

### Repo layout (`onolys`)
| Path | Holds |
|---|---|
| `engines/eaudit/` | Today's evidence engine (currently `eaudit/`), generalised to accept a protocol pack and structured rating items |
| `engines/paudit/` | New protocol engine: utterance coding, globals, summary scores, driven by a pack |
| `engines/core/` | Shared: `LLMClient` (LiteLLM routes), STT interface, transcript model, spans, run_info |
| `protocols/miti-4.2.1/` | `pack.yaml` (items, codes, definitions, formulas, reference levels, input checks), `rules.py` (deterministic rules via `validate_codes`, `compute_summary`), `rating.schema.json`, `prompts/`, `report.yaml`, `fixtures/` |
| `api/` | Public HTTP API, job orchestration, storage access |
| `web/` | app.onolys.com frontend |
| `frontend/`, `eval/` | Admin UI and eval server (existing) |

### MITI pack content (from manual 4.2.1)
- Globals 1-5, default 3: Cultivating Change Talk, Softening Sustain Talk, Partnership, Empathy. "A 5 is generally not given when there are prominent examples of poor practice."
- Behaviour codes (clinician speech only): Giving Information, Persuade, Persuade with Permission, Question, Simple Reflection, Complex Reflection, Affirm, Seeking Collaboration, Emphasizing Autonomy, Confront. Each volley earns each code once; one reflection code per volley (Complex wins); prefer fewer parses; uncoded: greetings, structure, facilitative "okay", off-topic.
- Summary: Technical=(CCT+SST)/2; Relational=(P+E)/2; %CR=CR/(SR+CR); R:Q=reflections/questions; MIA=Seek+Affirm+Emphasize; MINA=Confront+Persuade. Reference levels fair/good: Relational 3.5/4, Technical 3/4, %CR 40/50%, R:Q 1:1/2:1 (labelled "reference levels, not pass marks").
- Checks: recording ≤25 min; change goal required; warn under 10 min (globals unreliable).

### Pipeline (async job per run)
1. Upload audio + optional rating (paste or file) + params (language, coded span, N runs).
2. Validate (duration, format, size).
3. Transcribe + diarize (STT interface; default Chirp 3).
4. User confirms which speaker is the clinician.
5. Parse rating into `rating.schema.json`; user confirms (skipped if no rating).
6. `paudit`: model proposes one code per utterance with quoted span; code validates quotes and applies `rules.py`; code computes counts and summaries; separate globals pass with cited lines; repeated N times, stored as an array.
7. `eaudit`: each clinician score and reason checked against transcript → supported / partly / not supported / not enough evidence, with lines.
8. Compare per item → difference + explanation + evidence.
9. Tips: 3-5, ranked, each tied to a MITI item, quoting lines, with one concrete alternative.
10. Assemble report version; store with run_info (models, prompt hashes, pack version, code version).
"Models propose, code decides" (existing ADR 0005) applies throughout.

### Data (Firestore + Cloud Storage)
User → Session (audio, transcript, speaker map, language, change goal, coded span) → Rating (raw upload, parsed, confirmed) → Run (params, status, run_info) → Report (versioned). Personal API keys stored hashed.

### Report
Header (change goal, MITI 4.2.1, models, date); scorecard (yours vs Onolys per item, difference chip); globals with cited lines; behaviour counts with clickable instances (note: a self-rating has tallies only, so we list our instances, not which of theirs differ); summary scores vs reference levels; reasons audit; 3-5 tips; method and limits note ("not official MITI coding").

### Dashboard (basic)
4 tiles (sessions rated, latest report, average global difference, share of items within one point) + recent reports list + "run again".

### Stack and cost
Cloud Run (api + worker), Cloud Tasks, Firestore, Cloud Storage, Identity Platform (no PHI in profiles or client SDK calls; PHI only through own API), Secret Manager, Speech-to-Text v2 Chirp 3, Gemini on Vertex; Claude via LiteLLM as a config swap. Estimate per 25-min session ≈ $0.14-0.47 (STT + Gemini Flash), fixed ≈ $0-10/month at launch (prices seen 2026-11-20; STT and Vertex figures partly unverified).

## Builder-check answers
Answered from the conversation or repo:
- Repos already renamed on GitHub (2026-11-20): `Onolys/onolys` (local folder still `iaudit`), `Onolys/onolys-landing` (local folder still `miti`). Landing edits happen in place in that repo.
- MITI permission is granted (Tejit); pack may embed manual definitions with citation.
- Admin UI product registry (`frontend/src/products.ts`) gains a `paudit` entry; `web/` is a separate app.

Claude's calls (minor, change nothing material; override freely):
| Topic | Call |
|---|---|
| Phasing | dev-design splits into sub-projects with separate PRs: core+engines, api+jobs, web app, landing CTA, admin deploy |
| Existing behaviour | Keep sync `POST /v1/audit`, eval harness and admin UI working through the move to `engines/eaudit/` |
| Admin auth | Identity Platform login with an email allowlist + MFA (no IAP/load balancer in v1) |
| Environments | One GCP project, separate `staging` and `prod` Cloud Run services and buckets |
| Landing buttons | Links only: "Sign up" → `app.onolys.com/signup`, "Log in" → `/login`, "Try it out" → `/signup` |
| API keys | One active key per user; create, revoke, regenerate; hashed at rest; simple per-key rate limit |
| Web stack | React + Vite + TypeScript (matches `frontend/`); reuse landing colours/fonts; reuse review-UI transcript highlighting for clickable instances |
| Rating schema v1 | change_goal, coded_span{from,to}, globals{cct,sst,partnership,empathy: 1-5 or null}, counts{10 codes: int or null}, reasons (free text, optional per item), notes |
| Unreadable upload | Image-only/unreadable file → ask the user to paste instead; no OCR in v1 |
| Difference rule | Globals: differ if abs diff ≥1; counts: any diff shown, flagged if abs diff ≥2 or ≥25%; "within one point" = abs diff ≤1 |
| N>1 runs | Compare against the mean; show spread; dashboard uses mean; no rating → difference tiles show "–" |
| Audio | mp3, wav, m4a, webm, ogg; ≤100 MB; ≤25 min; audio only (no video) in v1 |
| Job UX | Status polling every 3 s; target ≤5 min per session; one automatic retry per failed step, then a clear error with "run again" |
| PHI-ready controls v1 | Allowlist logging (existing pattern), no transcript/audio text in logs or analytics, private buckets with signed URLs, Google-managed encryption, single US region, access audit log on report/audio reads |
| Models | dev-design pins current Gemini Flash (coding, parsing) and Pro (globals, tips) on Vertex; Claude routes kept as alternates |

## Goals, non-goals, anti-goals
- **Goals:** the people who asked each sign up on miti.onolys.com, upload one recording + rating, and get a report on app.onolys.com without Tejit's help. Every feature reachable by API. Swapping STT/LLM/language/N is config only.
- **Non-goals (v1):** teams/orgs, billing, PDF export, email, dashboard trends, transcript editing, non-English reports, caudit, other protocols.
- **Anti-goals:** presenting results as official MITI coding or as a verdict on the person; any score not traceable to transcript lines; PHI in logs, analytics, or auth profiles; MITI specifics leaking into engine code.

## Open risks
| Risk | Cheapest test |
|---|---|
| Onolys globals disagree with experts (published AI-vs-expert r≈0.34-0.63) | Rate 3 role-plays also rated by a certified coder; compare |
| Diarization errors on 2-speaker role-plays | Run Chirp 3 on one role-play on day 1 |
| Cheaper dynamic-batch STT may not support Chirp 3 diarization | One API call |
| Gemini vs Claude quality on the eaudit engine (tuned on Claude) | Run eaudit eval set on both |
| Uploaded ratings come in many shapes | Collect 3 real self-ratings from the people who asked |
| No official MITI form; Tejit checking | Schema is ours; adjust if a form turns up |
