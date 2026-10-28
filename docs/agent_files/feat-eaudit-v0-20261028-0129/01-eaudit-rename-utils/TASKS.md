---
status: draft
summary: Fourteen tasks renaming backend/ to eaudit/, regrouping eval datasets with a product field, adding utils/ and one retry wrapper per language, a frontend product registry, and Haiku 5.5 as cheap tier.
date: 2026-10-28
---
# Tasks: SP01 eaudit rename, utils, retry wrapper, Haiku 5.5

Source of truth: [PRD.md](PRD.md). Pure refactor plus one default change: rename the product, regroup datasets, replace hand-rolled retries with one helper per language (same prompts, fixture keys and attempt counts), and move the cheap tier to Haiku 5.5. Agents run only offline checks, no live LLM calls.
Contract versioning rule: all schemas are schema_version "0.0.1"; the project is not deployed, so no legacy/back-compat code, version history or migration; a file or body not conforming to the current schema just shows a validation error and the owner deletes it.

Each task is one commit and must leave the eaudit/, eval/ and frontend suites green (same test counts as before, plus new retry tests where added).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Mechanical rename backend/ to eaudit/ | none | done |
| 2 | Delete .party/ | 1 | done |
| 3 | Regroup eval datasets under eaudit/ | 1 | done |
| 4 | `product` field on dataset metadata | 3 | done |
| 5 | Python utils/ and retry() | 1 | done |
| 6 | Frontend utils/: codepoints move and retry() | 1 | done |
| 7 | Swap retry into litellm_client | 5 | done |
| 8 | Swap retry into atomize stage | 5 | done |
| 9 | Swap retry into linker | 5 | done |
| 10 | Swap retry into verifier | 5 | done |
| 11 | Frontend retry: eval GETs and audit POST | 6 | in-progress |
| 12 | Product registry and eaudit names in frontend | 6 | done |
| 13 | Haiku 5.5 cheap tier | 1 | done |
| 14 | Acceptance sweep | 1-13 | todo |

## Task 1 — Mechanical rename backend/ to eaudit/
What it is / what it means: The product stops being named after the umbrella (R1, D1, D9). This commit is purely mechanical so history and review stay clean; no logic edits.
What changes at a high level: `git mv` the folder (including the ADHD harness under it), rename the source package to `eaudit`, set the project name and hatch packages accordingly, and regenerate the lockfile with `uv lock`. Rewrite `iaudit_backend` imports everywhere and `backend/` paths in CI workflows (job id becomes `eaudit`), scripts, READMEs, AGENTS.md, ADHD harness files, one eval test, the contract module and non-historical docs, plus the uvicorn target. Keep `IAUDIT_*` env vars, `iaudit_eval`, the `eval/` dir and `$id` URLs. Docs keep their current filenames (the API doc rename belongs to SP04); do not edit `docs/agent_files/**` or ADR narrative.
Done when: `grep iaudit_backend` is empty (excluding agent_files), no stray `backend/` paths remain except prose meaning the server role, all three suites and ruff pass, `scripts/dev.sh --check` passes, uvicorn serves `/healthz`.

## Task 2 — Delete .party/
What it is / what it means: Owner decision D11; nothing references it.
What changes at a high level: `git rm -r .party`, then grep to confirm no dangling references anywhere.
Done when: `git ls-files .party` is empty and no reference to it remains; suites still green.

## Task 3 — Regroup eval datasets under eaudit/
What it is / what it means: Datasets live under a product folder so a future paudit slots in (R3, D2, D3). Dataset ids stay flat (`tofueval`, `synthetic`); no compatibility for old paths or run records.
What changes at a high level: `git mv` both datasets under `eval/datasets/eaudit/`. The registry scans one level deeper (`datasets/<product>/<name>/metadata.json`), keeps the name-equals-folder rule and the synthetic package name, and raises `DatasetError` on a name collision across products. Update test paths and namespace imports (`datasets.eaudit.…`), and docs/metadata text pointing at the old location.
Done when: old `eval/datasets/tofueval` is gone, `GET /datasets` still lists both ids, eval suite green with no shim for old paths.

## Task 4 — `product` field on dataset metadata
What it is / what it means: The Eval UI needs to group datasets by product (R3, D10). The PRD's file paths for this were guessed.
What changes at a high level: The coding agent first verifies the real locations (eval API dataset listing and model, eval schemas dataset-meta part, frontend eval types and the dataset list UI) before editing. Add `product` (string, only "eaudit") to both `metadata.json` files, the API model, `GET /datasets` response, the dataset-meta schema, and the frontend eval types. The registry derives it from the folder and rejects a mismatch with metadata. The dataset list in the Eval UI groups by product. No schema version change (SP02 owns it).
Done when: each dataset reports `product: "eaudit"`, a mismatching metadata fails with a clear error, the UI groups under "eaudit", and tests cover derivation, mismatch and grouping.

## Task 5 — Python utils/ and retry()
What it is / what it means: The shared retry contract (R4, R5, D4, D5), Python side.
What changes at a high level: Create the `utils` package with `retry` per the PRD signature: call `fn(attempt)` (1-based), consult `should_retry` on result or raised error, stop on success, exhaustion, false decision or `can_continue` false, with constant or exponential delay via injectable sleep. On exhaustion return the last result or re-raise the last error. Cancellation is never retried. Move any genuinely pure helpers found (none pre-committed; `safe_log` and `scales` stay). The wrapper owns only the loop.
Done when: unit tests cover first-try success, retry then success, exhaustion return and raise, `can_continue` stop, exponential delays via injected sleep, and cancel not retried.

## Task 6 — Frontend utils/: codepoints move and retry()
What it is / what it means: Generic helpers get their own folder and the TS retry contract exists (R4, R5).
What changes at a high level: Move `codepoints.ts` into `frontend/src/utils/`, updating the import in the spans test and the re-export in `contract/index.ts`; spans/excerpts/analysis stay in `contract/`. Add `retry.ts` with the PRD's shape (outcome object for `shouldRetry`, `canContinue`, abort signal, injectable sleep) and `retry.test.ts`. Aborts are never retried and abort during sleep rejects immediately.
Done when: typecheck and tests pass, retry tests cover the same cases as Task 5 plus abort handling, and no behavior of existing contract exports changes.

## Task 7 — Swap retry into litellm_client
What it is / what it means: Transport retry loop replaced with the wrapper, behavior identical (R5 map row 1).
What changes at a high level: Attempts are `1 + llm_max_retries` when the request allows retry, else 1. Retry on timeout, bad output or unavailable errors unless `no_retry`; `can_continue` mirrors the deadline margin check; delay 0. `LLMResult.attempts` and metrics `ok/error_kind` stay unchanged.
Done when: `test_llm.py` and the rest of the eaudit suite pass with only import-level edits; no recorded fixture changes.

## Task 8 — Swap retry into atomize stage
What it is / what it means: Semantic retry via `fn(attempt)` (R5 map row 2, D4).
What changes at a high level: Attempts 2 when `atomize_retry`, else 1; retry when the checked result has errors; `can_continue` is remaining time at least `llm_timeout_s`. Attempt 1 uses the original prompt and fixture key; only attempt 2 builds the retry prompt and appends `.retry`. Caller keeps its fallback branch.
Done when: `test_atomize_call.py` passes unedited beyond imports and fixture keys are byte-identical.

## Task 9 — Swap retry into linker
What it is / what it means: Same pattern for link (R5 map row 3).
What changes at a high level: Attempts 2 when `link_retry`; retry when all items were dropped; same `can_continue`. `counts["retries"]=1` is set before attempt 2 as today. Request building and fallback stay in the caller.
Done when: `test_link_retry.py` passes unedited beyond imports, fixture keys unchanged.

## Task 10 — Swap retry into verifier
What it is / what it means: Same pattern for check (R5 map row 4).
What changes at a high level: Attempts 2 when `check_retry`; retry when items are left unjudged; same `can_continue`. `res.retries=1` is set before attempt 2. Caller retains request building and fallback.
Done when: `test_check_verifier.py` passes unedited beyond imports, recorded-replay tests pass, `git diff --stat -- '*recorded*'` shows renames only.

## Task 11 — Frontend retry: eval GETs and audit POST
What it is / what it means: The only two places the frontend retries automatically (R5, D6). Decisions use HTTP status only.
What changes at a high level: Idempotent eval GETs go through the wrapper (2 attempts, 300 ms delay, retry on network, timeout or 5xx; never 4xx). The audit POST in the transport client retries once with a small delay, only on HTTP 429 or 503, since the backend never ran the audit; never on 500, other statuses, network error, timeout or the 120 s client deadline. The user Retry button and polling stay as they are.
Done when: tests prove POST retried on 429 and 503 only and not on 500, 400, network error, timeout or deadline, and GET retry rules hold.

## Task 12 — Product registry and eaudit names in frontend
What it is / what it means: A drop-in tab list so paudit is one entry plus one component (R2, D8).
What changes at a high level: Add `products.ts` with the eaudit entry; `App.tsx` renders tabs from it plus the Eval tab (mode is a product id or "eval"), and the tab reads "eaudit". Set the `index.html` title to "eaudit review", fix the frontend README heading and package metadata only where it names the product, update visible strings in `App.test.tsx` and docs text, rename `AuditApp` to `EauditApp` only if it exists solely in App.tsx. The eval dataset storage key stays `iaudit.eval.dataset`; the `iaudit-frontend` npm name stays.
Done when: tab label comes from the registry, typecheck and tests pass.

## Task 13 — Haiku 5.5 cheap tier
What it is / what it means: Default model change (R6).
What changes at a high level: Set `model_cheap` to `anthropic/claude-haiku-5-5` in config, update the config test and the configuration reference row. Cost table keys on "haiku" so is unaffected. No live calls.
Done when: `config.model_cheap` equals the new id, config test and docs row match, suites green.

## Task 14 — Acceptance sweep
What it is / what it means: Offline proof of the PRD's acceptance criteria; fix leftovers only.
What changes at a high level: Re-run the greps (no `iaudit_backend`, no stale `backend/` paths, `.party` gone), full eaudit/eval/frontend suites plus ruff and typecheck, `scripts/dev.sh --check`, `/healthz`, `GET /datasets` product values, and the recorded-replay diff check. Fix any dangling link or path missed earlier.
Done when: every acceptance criterion in the PRD passes offline, with test counts equal to before plus new retry tests.

## Owner manual steps (not tasks)
- Delete and recreate venvs (`rm -rf eaudit/.venv && cd eaudit && uv sync`; also `eval/.venv` if it references the old path); `frontend/node_modules` untouched.
- Re-point local shell aliases, IDE run configs, `cd backend` habits, and external CI badges or branch-protection required-check names embedding `backend` (job id is now `eaudit`).
- Confirm the id `anthropic/claude-haiku-5-5` on the first live run (owner-run, not blocking). Renaming the GitHub repo is out of scope.
