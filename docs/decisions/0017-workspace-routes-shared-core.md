# 0017. uv workspace, model routes and a shared `onolys_core`

**Audience:** contributors.

**Status:** accepted. Gate run 2026-11-20; STT 20-minute file cap resolved by a launch decision, see below.

**Context.** The platform (protocol audit, evaluation, API) needs the LLM client, speech-to-text and transcript types that lived inside `eaudit`, and `eval/` may not import `eaudit`. Model choice was three env vars with Anthropic-only quirks in the client, and no STT code existed. The owner widened the mission to the platform scope on 2026-11-20 (see [mission](../mission.md)).

**Decision.**

- **Workspace.** `eaudit/` moves to `engines/eaudit/`. A root virtual `pyproject.toml` declares a uv workspace (members `engines/*`, `api`, `admin/*`; `eval` excluded) with one root `uv.lock`. `eval/` stays standalone and talks to the backend over HTTP only. CI runs `uv sync --frozen --package <name>` from the root.
- **Shared core.** New package `engines/core` (dist `onolys-core`, import `onolys_core`) holds the LLM client and route registry, the provider-neutral STT interface with a Chirp 3 adapter, transcript types, the engine interface, `RunInfo`, PHI-safe logging and retry. `eaudit` imports from it; there are no re-export shims. The `stt-google` extra keeps the Google client out of the default install.
- **Routes.** A YAML route registry (packaged default, or the file named by `ROUTES_FILE`; `DEFAULT_PRESET` picks a preset) replaces the three tier env vars. Route names equal the old tiers (`cheap`, `mid`, `strong`) so recorded fixtures stay valid; task routes are aliases. Provider quirks (`structured_output_mode`, `caching_mode`, `supports_temperature`, `extra_params`) are per-route data. Swapping a model or provider is a YAML edit or one small adapter. Default routes are Claude Sonnet via the Anthropic API. See [llm-client](../implementation/llm-client.md).
- **Env prefix.** `IAUDIT_*` stays for engine and eval settings; platform deploy config is unprefixed.
- **Live gate.** `python -m onolys_core.llm.smoke --preset default` and `python -m onolys_core.stt.check --audio <ref> --preset default` run before paudit work starts; the results go in the section below.
- **STT location.** `us` multi-region; no data-residency claim is made.

**Alternatives.** Per-package path dependencies with separate locks; keeping `eaudit.llm` with shims; env-var-only model config. Each costs more consistency or a second cleanup pass.

**Consequences.** One lock for all Python packages. Core is importable by four consumers and may not import any engine (boundary test). The sample route config is proven only by the live gate.

## Gate result

Run 2026-11-20 with live credentials, preset `default`, by the Task 13 agent. **Caveat: the audio is synthetic.** The owner has not supplied a real sample, so the STT check used a short fictional two-speaker dialogue (25 turns, about 2.5 min) synthesized with Google Cloud Text-to-Speech (`en-US-Neural2-F` and `en-US-Neural2-D`, 16 kHz mono) and looped to the target length. Diarization and word-offset quality on clean synthetic voices is not evidence for real sessions. Re-running the STT check on a real 2-speaker sample of at least 10 minutes is an owner follow-up. The audio was uploaded temporarily to `gs://onolys-audio-staging/gate-t13/` and deleted afterwards; no audio is in the repo.

| Item | Result |
|---|---|
| LLM smoke (`onolys_core.llm.smoke`) | PASS, 6/6 routes (`cheap`, `mid`, `strong`, `paudit_code`, `paudit_globals`, `tips`), `json_object` through LiteLLM on `anthropic/claude-sonnet-5-5`. 54 input and 9 output tokens per call; latency 8.0 s on the first call (cold), 0.7-0.8 s on the rest. No route moved to `json_schema`. |
| STT check (`onolys_core.stt.check --language auto --min-minutes 10`), 17.4 min file | PASS twice: 167 turns, 2 speakers, `language=en` detected, offsets present and monotonic. Wall time 165.4 s and 251.5 s. |
| STT check, 24.9 min file | FAIL (provider limit, not a quality failure): `File ... is too long. Only audio files up to 20 minutes long are supported for BatchRecognize.` The rejection came back after 273 s. |
| (a) Are word time offsets present? | Yes. Every turn had `start_ms`/`end_ms`, monotonic. No fallback. |
| (b) Does diarization work with `language: auto`? | Yes on synthetic audio: 2 speakers found, language detected as `en`. `auto` stays in the SP05 list. Real-audio confirmation pending (caveat above). |
| (c) p95 latency for 25 minutes of audio | Cannot be measured as a single call: `BatchRecognize` rejects files over 20 minutes. For files under the cap, 2 runs of 17.4 min took 165 s and 252 s (about 0.16-0.24 s of wall time per audio second; two samples cannot give a real p95, so treat it as an estimate). Extrapolated to the 20 minute cap: about 3-5 min, and a 25 min recording split into two chunks run in parallel: about the same. Both are well inside the SP04 poll window (about 20 min). |

**Launch decision (owner, 2026-11-20): 20-minute cap; chunking deferred.** Session audio is capped at 20 minutes (`max_audio_s: 1200` on the STT provider entry; `validate` fails longer audio with `audio_too_long`; the web uploader blocks it first). A chunking provider can raise the value later. Original finding: The default STT path cannot take a recording longer than 20 minutes. The documented fallbacks in the table below (another model or provider) do not obviously fix it, so this was not changed here: it needs a design choice, either the adapter or SP04 splits audio into chunks under 20 minutes (with speaker labels and offsets stitched across the join), or another recognition mode or provider is used for long files. Owner/SP04 decision.

**Environment note.** The ADC quota project is another project (`juno-medical-clarity`), which has Speech-to-Text disabled. The first STT call failed with `SERVICE_DISABLED` until `GOOGLE_CLOUD_QUOTA_PROJECT=onolys` was set. Set it wherever the adapter runs with user credentials. APIs used (`speech`, `texttospeech`, `storage`) were already enabled on `onolys`; nothing was enabled by this run.

If (a) is no: use another STT model or provider through the adapter. If (b) is no: default language becomes `en-US` and `auto` leaves the web language list. If (c) exceeds the transcribe poll window (about 20 minutes): another model or provider as in (a).
