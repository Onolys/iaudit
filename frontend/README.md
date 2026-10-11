# iaudit review UI

Vite + React + strict TypeScript + Vitest. Upload a request JSON, see the audit.

## Quickstart

```bash
npm ci
cp .env.example .env.local   # then set VITE_AUDIT_URL, or VITE_MOCK=true
npm run dev
```

Other scripts: `npm run build`, `npm run preview`, `npm test`, `npm run typecheck`.

With `VITE_MOCK=true`, upload `../docs/contracts/examples/request.json`.

## Docs

- [Architecture](../docs/architecture.md#review-ui)
- [How to read the screen](../docs/concepts/review-ui.md)
- [Settings, mock mode, errors](../docs/reference/review-ui.md)
- [Internals](../docs/implementation/frontend.md)
- [Testing](../docs/testing/frontend.md)
- [Contract](../docs/contracts/README.md) (imported via the `@contracts` alias, never copied)
