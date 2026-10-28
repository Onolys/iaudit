---
status: approved
summary: Rename the evidence-audit product backend/ to eaudit/ (package eaudit, product-grouped eval datasets, "Audit" tab becomes "eaudit"), add utils/ folders plus one retry wrapper (Python + TS) replacing the ad-hoc retries without changing behaviour or fixture keys, and move the cheap tier to Haiku 5.5.
date: 2026-10-28
---
# PRD: SP01 eaudit rename, utils, retry wrapper, Haiku 5.5

Repo/branch: iaudit / `feat/eaudit-v0` · Depends on: none (Phase 1) · Owns: `backend/` → `eaudit/` (all of it incl. `eaudit/eval/` ADHD harness and `eaudit/uv.lock`), `eval/datasets/**` regroup, `eval/src/iaudit_eval/datasets/registry.py`, `scripts/{dev.sh,README.md}`, `.github/workflows/{ci,nightly}.yml`, `.party/` (deleted), `README.md`, `AGENTS.md`, path/command fixes in `docs/**` (not content), `frontend/{index.html,package.json,README.md}`, `frontend/src/{App.tsx,utils/**,eval/{RunPanel.tsx,evalTypes.ts,evalApi.ts}}`, `eval/src/iaudit_eval/{api,schemas}` dataset metadata (`product` field), `eval/schemas/*` dataset-meta part, `eaudit/src/eaudit/{utils/**,llm/litellm_client.py,atomize/stage.py,link/linker.py,check/verifier.py,config.py}`

## TL;DR
Pure refactor plus one default change. (1) `git mv backend eaudit`, package `iaudit_backend` → `eaudit`, every import/path/command follows; `.party/` deleted. (2) Eval datasets move under `eval/datasets/eaudit/`; dataset ids stay `tofueval` / `synthetic`; dataset metadata gains `product` ("eaudit") and the Eval UI groups by it. (3) Frontend gets a small product registry (tab label "eaudit"), `frontend/src/utils/`, and `eaudit/src/eaudit/utils/` hold generic helpers. (4) One `retry()` helper per language replaces the hand-rolled loops (frontend also retries the audit POST on HTTP 429/503 only); request prompts, fixture keys and attempt counts are unchanged. (5) `model_cheap` → `anthropic/claude-haiku-5-5`. No behaviour change otherwise; the existing suites are the proof.

## Contract-versioning rule (whole initiative)
All schemas reset to `0.0.1` (SP02). The project is not deployed, so **no legacy/back-compat code, version history or migration**. A file that does not match the current schema shows a validation error; the user deletes it. SP01 touches no schema version (the new `product` dataset field ships in the eval schemas that SP02 resets to `0.0.1`); it must not add any compat shim (e.g. for old dataset paths or old run records, see D3).

## Problem
- The product is named after the umbrella (`iaudit_backend`), blocking a second product (`paudit`). [verified: grep -rI 'iaudit_backend' (excl. agent_files) → 520 matches; ~190 are test imports under `backend/tests`]
- Generic helpers sit in domain folders (`contract/codepoints.ts`); no `utils/` exists in either tree.
- Retry logic is duplicated five ways: transport loop in `litellm_client.py` (`llm_max_retries`, `no_retry`, `_can_retry` vs deadline); semantic retries in `atomize/stage.py:126`, `link/linker.py:95`, `check/verifier.py:270` (each `cfg.*_retry` + `ctx.remaining() >= cfg.llm_timeout_s`, prompt rewritten, `fixture_key + ".retry"`). `pipeline/warmup.py` only passes `retry=False`; not a loop.
- Cheap tier still `claude-haiku-4-5-20251001`. [verified: config.py:21]

## Goals / Non-Goals
**Goals:** rename with zero broken links/commands; one retry helper per language with identical observable behaviour; Haiku 5.5 default; paudit can later slot in (tab registry, `eval/datasets/<product>/`).
**Non-goals:** schema/contract changes (SP02); taxonomy/prompts (SP03); docs rewrites (SP04); renaming the GitHub repo or `iaudit_eval` / `IAUDIT_*` env vars / `iaudit-eval-server` (umbrella, keep); any frontend retry beyond the 429/503 audit POST and idempotent eval GETs (R5); any change to the semantic retry prompts.

## Requirements
### R1 Backend rename
- `git mv backend eaudit` (history preserved); `src/iaudit_backend` → `src/eaudit`; `[tool.hatch…] packages = ["src/eaudit"]`; project `name = "eaudit"`; `uv.lock` regenerated (`uv lock`, not hand-edited; `name = "iaudit-backend"` at lock line 398).
- Rewrite `iaudit_backend` → `eaudit` in: all `eaudit/tests/**` and `eaudit/eval/**`, `eval/tests/{test_synthetic_dataset,test_contracts}.py`, `eval/tests/tofueval/test_acceptance.py`, `scripts/{dev.sh:130,README.md}`, docs. `uvicorn eaudit.app:app`.
- Path rewrites `backend/` → `eaudit/` in `.github/workflows/{ci,nightly}.yml` (`working-directory`, `cache-dependency-glob`), `README.md`, `AGENTS.md`, `eaudit/README.md`, `eaudit/eval/{README.md,leakage.toml,run.py,build_adhd.py}`, `eval/tests/test_scoring_boundaries.py`, `eaudit/src/eaudit/contract.py`, and 19 docs files [verified: grep -rIl 'backend/' excl. agent_files → 26 files].
- Keep (umbrella/not the product): `IAUDIT_*` env vars incl. `IAUDIT_BACKEND_URL`, `iaudit_eval`, `eval/` dir, `iaudit-frontend` npm name, `$id https://iaudit.local/schemas/…` (SP02 owns `$id`/versions). Prose "backend" meaning the server role stays.
- Do not edit historical `docs/agent_files/**` or ADRs' narrative (links inside ADRs that break are fixed; text is not).
- `.party/` is deleted entirely (`git rm -r .party`); fix any reference to it (grep found none outside `.party/` itself).
- `docs/reference/backend-api.md` is renamed to `docs/reference/eaudit-api.md` by SP04 (links fixed there). SP01 only fixes path contents it breaks, under the current filename.

### R2 Frontend names and tab registry
- Tab currently reads "Audit" (not "iaudit") [verified: App.tsx:17]; set it to "eaudit". New `frontend/src/products.ts`: `PRODUCTS = [{id:"eaudit", label:"eaudit"}]` plus the Eval tab; `App.tsx` renders tabs from the list (state `mode: ProductId | "eval"`). Adding paudit = one entry + one component.
- `frontend/index.html` title "eaudit review"; `frontend/README.md` heading; `RunPanel.tsx` `datasetStorageKey` stays `"iaudit.eval.dataset"` (umbrella eval UI). `AuditApp` component name stays unless it exists as `AuditApp` only inside App.tsx (rename to `EauditApp`).
- User-visible strings in `App.test.tsx`/docs screenshots text updated.

### R3 Dataset regroup
- **`product` field**: dataset metadata gains `product` (string; only value now `"eaudit"`, equal to the parent folder). Add to `metadata.json` of both datasets, `DatasetMeta` (eval API model + `eval/schemas` dataset-meta schema, in the `0.0.1` reset owned by SP02), `GET /datasets` response, frontend `evalTypes.ts`, and group the dataset list in the Eval UI (`RunPanel.tsx`) by product. `registry` derives it from the folder and rejects a mismatch with metadata. Dataset ids stay flat (D2).
- `git mv eval/datasets/{tofueval,synthetic} eval/datasets/eaudit/`. Tests keep importing via `datasets.eaudit.tofueval.pairs` (namespace packages, no `__init__`, folder names have no hyphen; test paths `EVAL / "datasets/tofueval/…"` become `…/datasets/eaudit/tofueval/…`, ~25 refs across `eval/tests/{tofueval,datasets/tofueval}`).
- `registry.list_datasets` / `load` scan `datasets/<product>/<name>/metadata.json` (one level deeper); `_read_meta` rule `meta.name == folder.name` stays; the synthetic-package name `iaudit_eval_dataset_<name>` stays (name unique across products; collision → `DatasetError`).
- Dataset ids unchanged (D2). `eval/data/<name>/` unchanged. `datasets_root` param semantic = the `datasets/` dir (product level inferred).
- `docs/**` and `metadata.json` text pointing at `eval/datasets/tofueval/…` updated (e.g. `test_split_note` references, local-setup.md:81).

### R4 utils/
- `eaudit/src/eaudit/utils/{__init__,retry}.py`. Move candidates (conservative; each only if it has no import from domain code): `safe_log.py` and `scales.py` are domain-coupled, **stay**. Any pure helpers found during task execution (text/JSON/time) move; none are pre-committed.
- `frontend/src/utils/{codepoints.ts,retry.ts,retry.test.ts}`; `codepoints.ts` has no own test (covered via `contract/spans.test.ts`) → update that import and the re-export in `contract/index.ts` (`export … from "../utils/codepoints"`). `spans/excerpts/analysis` stay in `contract/`.

### R5 Retry wrapper
Contract (both languages): call `fn(attempt)` (1-based); after each outcome ask `should_retry(outcome)` where outcome is the result **or** the raised error; stop on success, on `attempts` exhausted, on `should_retry` false, or when optional `can_continue()` is false; wait `delay * backoff**(n-1)` between tries. On exhaustion return the last result / re-raise the last error (callers keep their own fallback branches, so semantics match today). Defaults: `attempts=2`, `delay=0`, `backoff=1` (constant; exponential when >1), `can_continue=None`.

```python
async def retry(fn: Callable[[int], Awaitable[T]], *, should_retry: Callable[[T | BaseException], bool],
                attempts: int = 2, delay: float = 0.0, backoff: float = 1.0,
                can_continue: Callable[[], bool] | None = None,
                sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> T: ...
```
```ts
export async function retry<T>(fn: (attempt: number, signal?: AbortSignal) => Promise<T>, o: {
  shouldRetry: (outcome: {ok: true; value: T} | {ok: false; error: unknown}) => boolean;
  attempts?: number; delayMs?: number; backoff?: number; canContinue?: () => boolean; signal?: AbortSignal;
  sleep?: (ms: number, s?: AbortSignal) => Promise<void> }): Promise<T>;
```
- `CancelledError`/aborts are never retried; abort during sleep rejects immediately.

Replacement map (behaviour must be identical):
| Site | attempts | should_retry | can_continue | Notes |
|---|---|---|---|---|
| `litellm_client.complete_json` | `1 + llm_max_retries` if `req.retry` else 1 | error is `LLMTimeout/BadOutput/Unavailable` and not `no_retry` | `req.deadline` is None or `deadline - now >= timeout_s + RETRY_MARGIN_S` | `LLMResult.attempts` and metrics `ok/error_kind` unchanged; delay 0 |
| `atomize/stage.py` | `2` if `cfg.atomize_retry` else 1 | `checked.errors` | `ctx.remaining() >= cfg.llm_timeout_s` | `fn(2)` builds `_retry_user` prompt and `f"{key}.retry"` |
| `link/linker.py` | `2` if `cfg.link_retry` | all items dropped | same | `counts["retries"]=1` set before attempt 2 |
| `check/verifier.py` | `2` if `cfg.check_retry` | items unjudged (`missing`) | same | `res.retries=1` before attempt 2 |
`fn(1)` uses the original request/fixture key; only `fn(2)` appends `.retry`, so recorded-replay keys (ADR 0013) stay byte-identical.
- Frontend: no automatic retries exist today; every "Retry" is a user button and `usePolling` is a cadence loop with a 3-miss stale rule [verified: grep -rli retry frontend/src → App.tsx + eval/* are button/state names]. Ship `retry.ts` + tests and apply it in two places: (a) idempotent eval GETs in `evalApi.ts` (attempts 2, delay 300 ms, retry on network/timeout/5xx, not 4xx); (b) the audit POST in `transport/client`, **only when the HTTP status is 429 or 503** (the backend never ran the audit, so no LLM cost is re-spent; attempts 2, small delay). Never retry the audit POST on 500, any other status, a network error/timeout, or the 120 s client deadline (the backend may have run and spent LLM cost). Retry decisions use HTTP status only, never detail codes (SP02). The existing user Retry button stays.

### R6 Haiku 5.5
`model_cheap: str = "anthropic/claude-haiku-5-5"` (same style as mid/strong, undated aliases `config.py:22-23`); update `tests/test_config.py:13` and `docs/reference/configuration.md:24` row. Cheap tier is used only by prep tagging (`prep_llm` default false), so blast radius is small. Cost table keys on fragment "haiku" → unaffected [verified: eaudit/eval/prices.json].

## Architecture
```
repo/  eaudit/{src/eaudit/{utils,llm,atomize,link,check,...},tests,eval}   # was backend/
       eval/{src/iaudit_eval, datasets/eaudit/{tofueval,synthetic}}        # paudit/ later
       frontend/src/{products.ts, utils/, contract/, transport/, eval/}
```
Retry call-site shape (link, same for atomize/check):
```python
out = await retry(lambda n: call(req if n == 1 else retry_req(req, v)),
                  should_retry=lambda r: not isinstance(r, BaseException) and all_dropped(r),
                  attempts=2 if cfg.link_retry else 1, can_continue=lambda: ctx.remaining() >= cfg.llm_timeout_s)
```
Sequencing inside SP01: (a) rename commit alone (mechanical, tests green); (b) dataset regroup; (c) utils + retry + call-site swaps, one commit per site; (d) frontend names/registry; (e) Haiku. Keep the rename commit free of logic edits so `git log --follow` and review stay clean.

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| D1 | Python package/dist name | `eaudit` / `eaudit` | `iaudit_eaudit`; keep dist `iaudit-backend` | Matches locked naming; one grep-able token |
| D2 | Dataset ids | unchanged (`tofueval`, `synthetic`); product = parent folder | `eaudit/tofueval` ids | `_NAME_RE`, `/datasets/{name}` routes, run records, UI storage and the eval API schema all assume a flat id; ids unique across products today; no back-compat needed anyway |
| D3 | Existing run records / `eval/data` | no migration; stale run references simply error | read old paths | Initiative rule: not deployed |
| D4 | Retry owns | the loop only; callers keep request building and fallback | wrapper builds retry requests | Preserves prompts + fixture keys exactly |
| D5 | Deadline awareness | injected `can_continue` callback | pass `deadline` into wrapper | Three different deadline sources (req.deadline vs ctx.remaining) |
| D6 | Frontend retry scope | util + idempotent eval GETs + audit POST on HTTP 429/503 only | retry POST on any failure; wrap polling | 429/503 mean the backend never ran the audit (no re-spend); 500/timeouts may have run it; polling already has stale semantics |
| D10 | `product` on dataset metadata | add `product` to `DatasetMeta`/`GET /datasets`, eval schema, frontend types; UI groups by it | derive in UI from path only | Eval UI needs it for paudit later; SP01 owns the dataset regroup |
| D11 | `.party/` | delete whole folder | fix contents; rename `backend.md` | Owner decision; nothing references it |
| D7 | `iaudit_eval`, `IAUDIT_*`, `eval/` | keep | rename to `eval-core` etc. | Umbrella tooling serves all products |
| D8 | Tab registry | `products.ts` list | hardcode second button later | Cheap now, paudit drop-in |
| D9 | `eaudit/eval/` (ADHD harness) | moves with eaudit unchanged | merge into `eval/datasets/eaudit/` | Out of scope; merge is separate work |

## Manual steps (human-only)
- Delete and recreate venvs (`rm -rf eaudit/.venv && cd eaudit && uv sync`; also `eval/.venv` if it references the old path); `frontend/node_modules` untouched.
- Re-point any local shell aliases, IDE run configs, `cd backend` habits, and external CI badges/branch-protection required-check names if they embed `backend`.
- Renaming the GitHub repo is **not** in scope. Real LLM verification of Haiku 5.5 (live run) is owner-run and not blocking; owner confirms the id `anthropic/claude-haiku-5-5` on the first live run. Agents run no live calls.

## Risks / Open Questions
- [RESOLVED: eaudit/eval/ keeps its relative layout; `python -m eval.run` still resolves because CI runs from `eaudit/`, but note the name clash with top-level `eval/` already exists] ADHD harness move.
- [RESOLVED: CI job id `backend` renamed `eaudit`; required-check name changes, noted in Manual steps] CI naming.
- [RESOLVED: use `anthropic/claude-haiku-5-5`; owner confirms on first live run, not blocking] LiteLLM id. Pattern matches mid/strong and fixtures use `claude-haiku-5-5`.
- [RESOLVED: yes, add `product` (only "eaudit" for now) to eval API dataset metadata, eval schema and frontend types/UI grouping; in SP01 scope, schema reset to 0.0.1 in SP02] `product` field.
- [RESOLVED: delete the entire `.party/` folder (`git rm -r .party`), fix any references] `.party/`.
- [RESOLVED: rename to `docs/reference/eaudit-api.md` in SP04 with all links fixed; SP01 only fixes path contents it breaks] backend-api.md.
- [DEFERRED] Moving more helpers into `utils/` beyond codepoints; wait for second consumers (paudit).
- [DEFERRED] Replacing `usePolling` stale logic with retry; different concern.
- [RESOLVED: yes, semantic retries use `fn(attempt)` not a duplicated request] Fixture-key stability, guarded by `test_link_retry.py`, `test_check_verifier.py`, `test_atomize_call.py`, `test_llm.py` (renamed, not edited beyond imports).

## Acceptance Criteria
- `grep -rI 'iaudit_backend' . --exclude-dir={.git,node_modules,.venv,agent_files}` → 0 matches.
- No `backend/` path remains in `.github/`, `scripts/`, `README.md`, `AGENTS.md`, non-historical `docs/` (excl. `docs/agent_files/`), except prose meaning the server role.
- `cd eaudit && uv run pytest -q && ruff check src tests`, `cd eval && uv run pytest -q`, `cd frontend && npm run typecheck && npm test` all pass with the same test counts as before (+ new retry tests).
- `scripts/dev.sh --check` passes; `uv run uvicorn eaudit.app:app` serves `/healthz`.
- `eval/datasets/eaudit/{tofueval,synthetic}` exist; `GET /datasets` still lists `synthetic` and `tofueval`, each with `product: "eaudit"`; Eval UI groups them under "eaudit"; old `eval/datasets/tofueval` gone.
- `.party/` no longer exists (`git ls-files .party` empty); no dangling references.
- Frontend retry tests: audit POST retried on 429 and 503 only (once, attempts 2); not retried on 500, 400, network error, timeout or the 120 s deadline; eval GET retry as above.
- Recorded-replay tests pass with no fixture/recording file edited (`git diff --stat -- '*recorded*'` shows renames only).
- Retry unit tests cover (py + ts): success first try, retry then success, exhaustion returns/raises last, `can_continue` false stops, exponential delays via injected sleep, cancel/abort not retried.
- Tab reads "eaudit" (sourced from `products.ts`); `frontend/index.html` title updated.
- `config.model_cheap == "anthropic/claude-haiku-5-5"`; configuration.md row matches.
