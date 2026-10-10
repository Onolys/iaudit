---
status: draft
summary: Three tasks: Vite/React/TS/Vitest project with @contracts alias, env config, then tokens module and placeholder legend app.
date: 2026-10-10
---
# Tasks: 01 Frontend scaffold

Source of truth: docs/agent_files/feat-review-ui-20261010-2330/01-frontend-scaffold/PRD.md. Creates the empty-but-green `frontend/` project: toolchain, in-place contract schema import, typed env config, and the shared verdict/role tokens.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Project toolchain and @contracts alias | none | todo |
| 2 | Env config and README | 1 | todo |
| 3 | Tokens module and placeholder app | 1 | todo |

## Task 1 — Project toolchain and @contracts alias
What it is / what it means: The Vite + React + strict TypeScript + Vitest skeleton in `frontend/`, with npm and a committed lockfile (PRD Req 1-3, 7; Decisions 1-4, 7).
What changes at a high level: Create package.json with the dev/build/preview/test/typecheck scripts, Vite and tsconfig configs, and `frontend/.gitignore`. Wire the `@contracts` alias to `../docs/contracts` in Vite (shared with Vitest), tsconfig `paths` (no `baseUrl`, TS 7 rejects it) and `resolveJsonModule`. Restrict `server.fs.allow` to `frontend/` and `docs/contracts/`. Install jsdom and `@testing-library/react` (and Ajv) for later sub-projects; default test env is node. Add one test importing both schemas and `examples/response.json` via the alias, asserting `schema_version === "1.0.0"`.
Done when: typecheck, test and build pass; the dev server serves the schemas; nothing under `frontend/` copies a schema; `node_modules`/`dist` are untracked.

## Task 2 — Env config and README
What it is / what it means: Typed env access for the mock flag and audit URL, plus minimal docs (PRD Req 4, 8; Decision 6).
What changes at a high level: Add `env.d.ts` typing `VITE_AUDIT_URL` and `VITE_MOCK`, `getConfig()` returning `{ mock, auditUrl }` (mock only on exact `"true"`; empty or missing URL gives `null`; never throws), and `.env.example`. Write `frontend/README.md` covering install, scripts, env vars, what mock mode means, the `@contracts` alias rule and "schemas are never copied".
Done when: unit tests cover `"true"` true; `"false"`, `""` and unset false; missing URL `null`. README and `.env.example` exist and `.env*.local` is ignored.

## Task 3 — Tokens module and placeholder app
What it is / what it means: The single source of truth for verdict and evidence-role styling, with the final fixed palette (PRD Req 5-6; Decisions 5, 8).
What changes at a high level: Add a framework-free tokens module declaring the `Verdict` and `EvidenceRole` unions plus `VERDICT_STYLE`, `ROLE_STYLE` and `selectedClaimBackground`, with label, icon, colour and underline per the PRD table. Expose the same values as CSS custom properties from one stylesheet. Replace the placeholder `App.tsx` with a heading and a legend of the 5 verdicts and 3 roles built from the tokens. Add a jsdom smoke test asserting all 5 verdicts show icon and label.
Done when: the legend renders all verdicts (icon, label, colour) and roles; smoke test passes; tokens import nothing from SP02.
