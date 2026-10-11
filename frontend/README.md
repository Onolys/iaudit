# iaudit review UI

Vite + React + strict TypeScript + Vitest.

## Install and scripts

```bash
npm ci
npm run dev        # dev server
npm run build      # typecheck, then vite build
npm run preview
npm test           # vitest run
npm run typecheck  # tsc --noEmit
```

## Environment

Copy `.env.example` to `.env.local` (git-ignored).

- `VITE_AUDIT_URL`: audit endpoint URL. Inlined at build time, so it is fixed per build. Missing or empty means no URL.
- `VITE_MOCK`: mock mode is on only when this is exactly `true`. In mock mode the app serves bundled fixtures instead of calling the backend.

## Contract schemas

Import schemas and examples through the `@contracts` alias (`../docs/contracts`), e.g. `@contracts/audit-response.schema.json`. Schemas are never copied into `frontend/`; the files in `docs/contracts/` are the single source.

## Mock mode

Set `VITE_MOCK=true` to run without a backend. No request is sent; the reply comes from the example pairs in `docs/contracts/examples/` (loaded lazily, so a real-service session never fetches them) and goes through the same response validation as a real reply.

- A pair is `<name>.request.json` plus `<name>.response.json`. The bare `request.json` / `response.json` is the pair `default`. Other files in that folder (for example `error.json`) are ignored.
- The uploaded request is matched to a pair by exact `request_id`. A request with no `request_id` or no matching pair shows "No mock audit for this request"; there is no fallback to another pair.
- Replies arrive after a simulated 250 ms delay, which Cancel can interrupt.
- To add a mock, drop a new `<name>.request.json` / `<name>.response.json` pair into `docs/contracts/examples/` with a unique `request_id`. A test fails if a pair is incomplete or ids collide.
