# Frontend testing

How to test the review UI and what to check before a release.

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
- [ ] The [known limits](../concepts/review-ui.md#known-limits) are still accurate.

Open question: `.env.example` uses `/audit`, while the backend plan defines `POST /v1/audit`. Settle which is right before connecting.
