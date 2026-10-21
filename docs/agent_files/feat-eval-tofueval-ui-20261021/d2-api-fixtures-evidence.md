---
status: done
summary: D2 task 3 audited existing API wrappers and completed schema-validated results/items fixtures; 464 frontend tests pass.
date: 2026-10-21
---
# D2 API and fixtures evidence

Worktree: `/root/projects/iaudit/.worktrees/feat/eval-ui-replay-foundation`
Branch: `feat/eval-ui-replay-foundation`
Task base: `a49c19dfef1874a792b79c6816a2557111ed8fa8`

## Implementation and acceptance

D1 already implemented `getMetrics`, `rescore`, `listItems`, `getItem`, and `compare`. Audited them and retained the wrappers/types unchanged. Added injected-fetch tests covering their real validation, methods, encoded run/item/query identifiers, HTTP 404/409 mapping, network rejection, and metrics-only 404 `not_found` as successful null. Existing tests continue covering malformed bodies, synchronous exceptions, request ID encoding errors, cancellation and timeout.

Completed the existing fixtures rather than duplicating the data layer:

- `metrics.json`: primary/secondary denominators, failure/coverage policy `none`, paper reference and caveat, grouped level/slice, `few_clusters`/`undefined` with null intervals.
- `run-finished.json`: commit/dirty provenance, model and prompt fingerprints, seed, mapping version, tags, mixed warning.
- `item-ok.json`: actual current-contract public example request/response, replay verified through `buildLoadResult`; fictional native-shaped TofuEval gold, sentence text/offsets drawn from the example assessment, and native error-type strings including a multi-label case.
- `item-failed.json`: valid example request, null response, saved failure fields, same fictional gold.
- `items.json`: matching, failed and mismatching rows, optional label, punctuation in identifiers.
- Existing shared comparison retained; added `comparison-zero-shared.json` and structured `error-cross-dataset.json`.

Every JSON remains registered exactly once in `fixtureCases`; existing Ajv route validation covers all. The structured error coverage assertion now compares unique codes, allowing multiple route fixtures to share a legitimate error code.

Changed files: new `d2ApiFixtures.test.ts`; `fixtureCases.ts`; `fixtures.test.ts`; the five completed JSON fixtures above; two new JSON fixtures; only D2 task 3 status cell in source TASKS; this evidence artifact. No `evalApi.ts`, `evalTypes.ts`, run error fields, API schema, backend, contracts, protected review components, later-task implementations or replay-foundation evidence changes.

## Red and green evidence

Before fixture changes:

```text
npm test -- --maxWorkers=2 src/eval/d2ApiFixtures.test.ts
Test Files 1 failed (1)
Tests 4 failed | 10 passed (14)
(exit 1)
```

The four failing assertions caught missing zero-shared comparison, non-replayable empty saved request/response, absent policy/failure metric coverage and missing run provenance. The ten wrapper tests passed against existing D1 wrappers, confirming reuse.

After fixture changes, in frontend:

```text
npm test -- --maxWorkers=2 src/eval/d2ApiFixtures.test.ts src/eval/fixtures.test.ts src/eval/evalApi.test.ts
Test Files 3 passed (3)
Tests 126 passed (126)
(exit 0)

npm test -- --maxWorkers=2
Test Files 33 passed (33)
Tests 464 passed (464)
(exit 0)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
160 modules transformed.
✓ built in 272ms
(exit 0)

git diff --check
(exit 0)
```

## Integration adaptation and commit

PRD expects cross-dataset comparison HTTP 409; actual backend `eval/src/iaudit_eval/server/reads.py` returns HTTP 422 `invalid_request`. Orchestrator approved preserving server behavior. The structured fixture validates as the requested 409 case; wrapper tests also exercise the actual 422 case. Future CompareView should render both through generic EvalError handling. No backend changes made.

One task commit: `02-results-and-items: Task 3 — complete results API fixtures and coverage`; resolve its SHA with `git log -1 --format=%H -- frontend/src/eval/d2ApiFixtures.test.ts`.

No live providers, downloads, real browser checks, push, or merge. Existing local dependencies reused. No owner-only actions required for task 3; later tasks remain untouched.
