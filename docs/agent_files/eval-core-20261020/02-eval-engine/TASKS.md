---
status: done
summary: Twelve tasks building the root eval/ library (paths, contracts, dataset plug-in, synthetic data, run store, client, engine with resume and cost cap, download) tested offline on a fake backend, plus the ADR 0008 fix.
date: 2026-10-20
---
# Tasks: 02 Eval engine

Source of truth: [PRD.md](PRD.md). A standalone `eval/` uv project: library only, black-box over HTTP, schemas read from `docs/contracts/`, no import of `iaudit_backend`. Agents make no live LLM calls, real downloads or live runs; everything is tested offline with `httpx.MockTransport` and the synthetic dataset. Depends on B1 (contract 1.1.0 `run_info`).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Project skeleton, paths, gitignore, safe logging | none | done |
| 2 | Contract loader with value-free issues | 1 | done |
| 3 | Dataset plug-in: Item, Adapter, metadata, registry, selection | 1 | done |
| 4 | Synthetic dataset | 3 | done |
| 5 | Fake backend test harness | 2 | done |
| 6 | Audit client | 2, 5 | done |
| 7 | Run store: atomic writes, lock, reads | 1 | done |
| 8 | Engine core: preflight, canary, dispatch, abort, progress | 4, 6, 7 | done |
| 9 | Resume and fingerprint guard | 8 | done |
| 10 | Cost cap, estimate, probe | 8 | done |
| 11 | Download framework | 3, 4, 7 | done |
| 12 | README, ADR 0008 fix, boundary checks | all | done |

## Task 1 — Project skeleton, paths, gitignore, logging
What it is / what it means: The own-project home and the shared plumbing (R1, R2, R12, R13, D1, D3, D14).
What changes at a high level: Create `eval/` as uv project `iaudit-eval` (Python 3.12, hatchling, src layout, httpx, jsonschema, referencing; dev pytest, pytest-asyncio auto mode, ruff). Add `paths` (repo root from module location, `IAUDIT_CONTRACTS_DIR` and `IAUDIT_EVAL_HOME` overrides, never cwd), per-project `.gitignore`, and an allowlist-only `log` helper that drops text-like fields. Runs/data dirs created 0700, files 0600.
Done when: `uv run pytest` and `ruff check` pass; `git check-ignore` confirms `runs/` and `data/` (AC 14 part); a sentinel-word logging test passes; `uv.lock` committed if generation is possible, else noted.

## Task 2 — Contract loader
What it is / what it means: The single validator, reimplemented small to respect the boundary rule (R3, D2).
What changes at a high level: Load the three schemas in place through a `referencing` registry; expose request, response and error validators returning issues that carry schema path and keyword wording only, never instance values. No hard-coded schema version.
Done when: example request and response from `docs/contracts/` validate; a sentinel in a bad instance never appears in issue strings (AC 13 part); no schema copy exists under `eval/` (AC 2 part).

## Task 3 — Dataset plug-in and selection
What it is / what it means: The contract B3 and C1/C2 implement against (R5, R6, D4, D5).
What changes at a high level: `Item` and `Adapter` protocol with the optional hooks, `Unmapped`, `Dataset` with `items(split)` (including implicit `all` as de-duplicated union) and `split_sizes()`, metadata model per the PRD table preserving unknown keys, discovery of `datasets/*/metadata.json`, file-path adapter loading via `create(data_dir)`, `list_datasets()`/`load()`. `select(items, n, seed)` sorts by id, seeded sample, returns sorted. Preflight checks id uniqueness and charset.
Done when: tests cover discovery, unknown-key preservation, bad-id rejection, and AC 3 selection behaviour.

## Task 4 — Synthetic dataset
What it is / what it means: Fictional committed dataset for zero-spend tests (R10, Risks).
What changes at a high level: Folder with metadata, adapter implementing all four methods, 2 splits, 3 documents, ~8 items, `data_required=false`. Text avoids 8-word overlap with `prompts/*_fewshot.json` and the speaker ids `alex1/sam1/clinician1`; a read-only test checks this by path and skips if files are absent.
Done when: every `to_request` output validates against the request schema; overlap and speaker-id test passes.

## Task 5 — Fake backend harness
What it is / what it means: In-process stand-in for `POST /v1/audit` and `/healthz` used by all later tests (R11).
What changes at a high level: A `MockTransport` handler building schema-valid responses including `run_info`, with switches for 429, 503, 504, timeout, bad body, invalid error body, mismatched `request_id`, missing `cost_usd`, changed models/prompt hashes, unsupported version, plus request counting and in-flight concurrency tracking.
Done when: each switch produces its intended behaviour and default responses validate against the response schema.

## Task 6 — Audit client
What it is / what it means: One call, one classified outcome (R4, D11, D12).
What changes at a high level: `AuditClient` over `httpx.AsyncClient` with 120 s total and 5 s connect, validating request before send and response on receipt, returning `ok` or `failed` with the PRD's kinds, status, error code/message when the error body is valid, issues, and `attempts`. One retry after 2 s only for connect errors, 429, 502, 503; never for timeouts or 504. Echoed `request_id` is checked.
Done when: tests cover every failure kind, retry/no-retry cases (request counts asserted) and AC 5 client-side parts; backoff is injectable so tests stay fast.

## Task 7 — Run store
What it is / what it means: Crash-safe persistence where item files are the truth (R7, D6, D7, D14).
What changes at a high level: run id generation, `run.json` (`store_version: 1`) and `items/<id>.json` schemas per the PRD, atomic write (temp, fsync, replace, dir fsync), stale `.tmp` cleanup, `flock` on `run.lock`, `effective_state` deriving `interrupted`, `list_runs`, `load_run`, `iter_items`, `progress`, and totals recomputed from item files (token/cost sums null when unreported).
Done when: tests show no torn files after a simulated crash, `interrupted` derivation, second lock acquirer refused, 0700/0600 modes (AC 14 part), totals match items.

## Task 8 — Engine core
What it is / what it means: Start a run and drive it to a terminal state (R8, D9, D13, D15).
What changes at a high level: `start_run` and `RunHandle` (`run_id`, `state`, `wait`, `abort`), state machine, preflight (dataset ready, contracts load, every request built and validated before any POST), canary first item, then semaphore fan-out (default 4), engine-set `request_id` as `<run_id>:<item_id>`, git commit/dirty/diff hash capture, `schema_version` and fingerprint from the first valid response, progress callback, `on_finish` hook, abort that lets in-flight finish. Partial replies stored ok with `response_status=partial`.
Done when: AC 4, 5 (preflight zero POSTs), 9 (abort), 10 (max 4 in flight) pass on the fake backend with synthetic data.

## Task 9 — Resume and fingerprint guard
What it is / what it means: Cheap recovery without silently mixed runs (R8, D7, D8).
What changes at a high level: `resume` accepting stored terminal states and derived `interrupted`, re-sending only failed or missing items, never `ok` ones; comparing the first new response to the run fingerprint and raising `FingerprintChanged` unless `allow_mixed` (then `mixed` plus a `resumes` entry); git change adds only a resume entry and warning; schema version change always refused; lock prevents concurrent resumes; missing-dataset `failed` runs stay blocked until fixed.
Done when: AC 6, 7 and the second-resume-refused part of AC 9 pass, with fake backend request counts asserted.

## Task 10 — Cost cap, estimate, probe
What it is / what it means: Optional spend control and honest pre-run numbers (R8, D9, D10, D16).
What changes at a high level: `max_cost_usd` stopping dispatch at `spent >= cap` with in-flight finishing and state `aborted_cost`; fail closed to `failed` with `cost_missing` when a cap is set and a response lacks `cost_usd`; no cap means no cost handling. `estimate` fits per-char ratios from prior ok items that reported them, nulls otherwise, cold start `basis="none"` with the "run a small N first" note, always rough. `probe` does `/healthz` then an empty-body POST with the loaded `schema_version`, reading `unsupported_version` as mismatch.
Done when: AC 8 and 11 pass, and probe tests show reachable/accepts_version outcomes with zero audit work.

## Task 11 — Download framework
What it is / what it means: Generic fetcher for adapter-declared sources (R9).
What changes at a high level: streamed fetch to `.part`, hash while streaming, atomic replace, optional adapter `post_download` or full `download` override, atomic `download.json` with the four statuses, pinned-hash mismatch fails, unpinned hash recorded (trust on first use, later change added to run warnings), idempotent no-op when ready, `data_required` datasets refuse runs unless ready. Tests use `MockTransport` only.
Done when: AC 12 passes with no real network.

## Task 12 — README, ADR 0008 fix, boundary checks
What it is / what it means: Close-out docs and guardrails (R1, Owns, AC 2, AC 15).
What changes at a high level: `eval/README.md` with layout, how to run tests, adapter authoring, and a "Manual (owner) steps" section. Fix `docs/decisions/0008-*.md` title and body from 60 s to 100 s only. Add tests asserting no `iaudit_backend` import and no schema copies in `eval/`.
Done when: AC 1, 2 and 15 hold; the ADR diff touches only the stale number.

## Owner manual checks
Not tasks; for the owner after merge: real dataset download, and live runs against the real backend with provider keys (cap/cost reporting, canary, concurrency 4 latency behaviour); generate and commit `eval/uv.lock` if uv was unavailable to the agent; MeetingBank equality check remains deferred to C.
