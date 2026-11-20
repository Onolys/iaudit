# onolys-api

Public `/v1` API + job worker (`onolys_api`). One image; `SERVICE_MODE=api|worker|combined`.

Local run: `uv run --package onolys-api uvicorn --factory onolys_api.app:create_app` (env: `.env.example`).

## OpenAPI (committed contract)
Regenerate (from repo root), then fail on drift:

    uv run --package onolys-api python -m onolys_api.openapi      # writes api/openapi.json
    git diff --exit-code api/openapi.json

`--out PATH` writes elsewhere; `--out -` prints to stdout. Output is deterministic (sorted keys, trailing newline).

## Audio upload and `validate`
`POST /v1/sessions/{id}/audio` (signed PUT to `uploads/{uid}/{sid}/{upload_id}`, canonical type in `required_headers`), `POST …/audio/complete` (202, enqueues `validate`), `GET …/audio` (signed read of the original). The `validate` worker step (`jobs/validate.py`) checks size, magic bytes and ffprobe (audio stream, no video, 1 s to 25 min), moves the object to `{uid}/{sid}/audio/original.{ext}`, transcodes to `canonical.flac` (16 kHz mono) and writes the `recordings/original` doc. It needs `ffmpeg`/`ffprobe` on PATH (in the image; CI `api` job installs them; the real-ffmpeg test is skipped when they are missing). Failure codes: `unsupported_audio` (bad magic bytes, video track), `audio_too_large`, `audio_too_long`, `audio_unreadable` (ffprobe/ffmpeg failure, no audio stream, under 1 s, object missing); each deletes every object of the session's audio. Over-300 MB and unreadable files fail before any transcode. `canonical_audio_ref()` (`audio.py`) builds the `AudioRef` STT receives.

### Validate peak memory (measured locally)
Reproduce: `uv run --package onolys-api python api/scripts/measure_validate_memory.py --minutes 25`.
2026-11-20, local, 25-min stereo 44.1 kHz 16-bit WAV sample (252 MiB, the largest realistic upload under the 300 MB cap), real ffprobe + ffmpeg, `FakeBlobStore`: validate 7.5 s, peak RSS **72 MiB** (Python worker) and **70 MiB** (ffmpeg, largest child); canonical FLAC 8 MiB (synthetic sine; speech is about 30 MB). Files are streamed to disk (never read whole into memory), so memory stays far under 1 GiB; the real cost is disk: on Cloud Run `/tmp` is memory-backed, so a 300 MB original plus the FLAC counts against the instance memory (about 0.35 GiB extra). Worker 2 GiB at concurrency 2 therefore has headroom (2 x ~0.45 GiB). Staging figure is SP09's; fallback if it disagrees: worker 4 GiB or concurrency 1.

## Rating card
`PUT/GET /v1/sessions/{id}/rating` (`routes/rating.py`): `final=false` overwrites one draft doc (size limits only); `final=true` validates and writes a new `ratings/{rating_id}` revision, copies `change_goal`/`coded_span` to the session, sets `rating_submitted`/`has_rating` and calls `maybe_start_first_run`. Firestore only; nothing is written to GCS. Validation is the single function `rating.validate_rating(card, final)`: jsonschema against the canonical SP02 schema, the MITI pack's `rating.schema.json` (loaded with `paudit.pack.load_pack`; `PAUDIT_PROTOCOLS_DIR` in the image). No fallback: `create_app` loads it at startup and fails if the pack is missing.

## Local run and image
One command, combined mode with fakes (no GCP): `api/scripts/dev.sh` (serves on `$PORT`, default 8000; `--quickstart` runs the OpenAPI quickstart against it and exits; `--check` preflights only).

Image (build from the repo root): `docker build -f api/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) -t onolys-api .` then `docker run --rm -p 8080:8080 -e ENV=local -e SERVICE_MODE=combined onolys-api`. The entrypoint (`api/docker-entrypoint.sh`) accepts `SERVICE_MODE=api|worker|combined` and serves on `$PORT` (Cloud Run injects it). Contains ffmpeg and the vendored Redoc; runs as non-root.

Acceptance: `uv run --package onolys-api pytest api -q -m "not live"` (add `FIRESTORE_EMULATOR_HOST` for the emulator params). `tests/test_acceptance_checklist.py` maps AC1-AC18 to their tests.
