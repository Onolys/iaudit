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
