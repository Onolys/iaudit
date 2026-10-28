# Frontend testing

How to test the eaudit and Eval UI and what to check before a release.

**Audience:** contributors.

## Commands

Run in `frontend/` after `npm ci`.

```bash
npm test           # vitest run
npm run typecheck  # tsc --noEmit
npm run build      # typecheck, then vite build
```

If `npm test` fails writing `node_modules/.vite-temp` (read-only workspace), use `npx vitest run --configLoader runner`.

To try it by hand: `VITE_MOCK=true npm run dev`, then upload `docs/contracts/examples/request.json`.

## Layout

Tests sit next to the code (`*.test.ts(x)`), plus:

| Test | Proves |
|---|---|
| `src/contracts.test.ts` | The `@contracts` alias resolves the schemas and examples in place. |
| `src/fixtures/fixtures.test.ts` | Mock pairs are complete, ids are unique, each pair validates, and exactly the expected claims are flagged. |
| `src/e2e/mock-flow.test.tsx` | Upload → review for `default`, `partial`, `out-of-range`; a bad file shows an error and makes no network call. |
| `src/tokens/tokens.test.ts` | TypeScript styles match `tokens.css`. |

Transport tests inject `fetch`, config and the mock registry; no test touches a real network.

## Add a mock pair

1. Add `<name>.request.json` and `<name>.response.json` to `docs/contracts/examples/` with a unique `request_id`.
2. Update the expected list in `fixtures.test.ts`.
3. Run the tests.

## Before a release

- [ ] `npm test`, `npm run typecheck`, `npm run build` pass.
- [ ] Mock mode: all three pairs load and look right.
- [ ] Against the real service: a valid upload renders; a stopped service shows Retry; Cancel works.
- [ ] `VITE_AUDIT_URL` points at the real endpoint path (see below).
- [ ] Owner: open one real eval item after the dataset download and pilot run, compare
  GoldPanel with its source, and inspect run metrics and two-run comparison.
- [ ] Owner: reopen Eval mid-run and verify attachment; open the largest saved item.
- [ ] Owner: saved 1.1.0 (and older) items fail replay with the version error, while
  metrics/list/compare remain available. Stale-version behavior is covered offline.
- [ ] The [known limits](../concepts/review-ui.md#known-limits) are still accurate.

The current `.env.example` points eaudit at `http://localhost:8000/v1/audit`.
`VITE_MOCK` affects eaudit only; Eval tests use injected fake fetch, fictional fixtures
and fake timers. Do not interpret eaudit mock mode as an Eval application mock mode.


## Eval coverage

All agent verification is offline; live providers, real dataset downloads, live
smoke and real-browser checks above remain owner-only.

| Tests under `src/` | Proves |
|---|---|
| `app/Header.test.tsx`, `transport/screens.test.tsx`, `transport/runAudit.test.ts` | Optional upload/file action and shared response checks preserve Audit behavior. |
| `eval/evalApi.test.ts`, `eval/fixtures.test.ts`, `eval/d2ApiFixtures.test.ts` | Injected-fetch routes/errors/encoding, metrics-null 404, and every JSON fixture registered and Ajv-valid. |
| `eval/usePolling.test.tsx`, `eval/RunPanel.lifecycle.test.tsx`, `eval/RunsList.test.tsx`, `eval/EvalApp.runs.test.tsx` | Lifecycle, polling, resume, list navigation and cancellation. |
| `eval/buildLoadResult.test.ts` | Actual contract pair replay, stale 1.0.0, invalid requests/responses and zero fetch/JSON parsing. |
| `eval/MetricsTable.test.tsx`, `eval/RunInfoBlock.test.tsx` | Grouping, policies, authoritative item counts, paper evaluator identity, CI hints and provenance. |
| `eval/ItemList.test.tsx` | Filter requests, raw-ID actions, empty/dim loading, Retry and stale/unmount protection. |
| `eval/RunDetail.test.tsx`, `eval/RunDetail.item-refresh.test.tsx` | Scoring/rescore lifecycle, item refresh with filter preserved, failure/missing metrics, 409, lost contact and cleanup. |
| `eval/gold/GoldPanel.test.tsx` | Native gold, unknown/malformed JSON fallback and collapse behavior. |
| `eval/ItemDetail.test.tsx` | Real ReviewShell replay/remount, failed/stale/invalid/unmapped details, no audit/upload, issue cap and Retry. |
| `eval/CompareView.test.tsx` | Shared/zero comparisons, signed deltas/CI gating, 409/422 and item callbacks. |
| `eval/mock-flow.test.tsx` | Full run → item → back → comparison → open in A/B → back flow with no global fetch calls. |

Use `npm test -- --maxWorkers=2` when memory limits require at most two Vitest workers.
