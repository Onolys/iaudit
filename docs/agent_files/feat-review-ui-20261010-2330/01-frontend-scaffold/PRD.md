---
status: draft
summary: Vite + React + TS app skeleton in frontend/ with Vitest, env config, direct import of docs/contracts schemas, and a verdict/evidence visual-tokens module.
date: 2026-10-10
---
# PRD: 01 Frontend scaffold

Repo/branch: iaudit / `feat/review-ui` · Depends on: none (Phase 0) · Owns: `frontend/` (config, `src/main.tsx`, `src/App.tsx` placeholder, `src/config.ts`, `src/env.d.ts`, `src/tokens/`, `frontend/README.md`, `frontend/.env.example`, `frontend/.gitignore`)

## TL;DR
Create the empty-but-green `frontend/` project every later sub-project builds on: Vite + React + TypeScript, Vitest, ESLint, env config, a working import path to `docs/contracts/*.schema.json` (outside `frontend/`), and one shared tokens module for verdict and evidence-role styling. No product features.

## Problem
No frontend exists. SP02-06 need a toolchain that (a) builds, tests, lints, and typechecks from day one, (b) can import the contract schemas **in place** (no copies; drift is a named risk in the brainstorm), and (c) has one source of truth for verdict/role colour + icon + label so panes never hard-code styling.

## Goals / Non-Goals
**Goals**
- `npm run dev|build|test|lint|typecheck` all pass on a placeholder app.
- Schemas and examples importable from TS, in dev, build, and Vitest, via one alias.
- Typed env access; mock flag and audit URL.
- Tokens module with placeholder palette, swappable in SP06 by editing one file.

**Non-Goals**
- Any validation, transport, layout, or rendering logic (SP02-05).
- Final palette hex values (SP06, after colourblind check).
- Routing, state libraries, UI component kits, CSS frameworks, CI pipeline, Docker, deployment.
- Mobile layout, theming/dark mode.
- Any change to `docs/contracts/` or backend code.

## Requirements
1. **Project**: `frontend/package.json` (private, `"type": "module"`), Vite + `@vitejs/plugin-react`, React, TypeScript strict. npm is the package manager; commit `package-lock.json`. Pin exact resolved versions via the lockfile (do not hand-write version numbers in the PRD).
2. **Scripts**: `dev`, `build` (typecheck then `vite build`), `preview`, `test` (`vitest run`), `lint` (ESLint over `src`), `typecheck` (`tsc --noEmit -p .`).
3. **Contract alias**: `@contracts` -> `../docs/contracts` in `vite.config.ts` (`resolve.alias`; Vitest inherits it by using `defineConfig` from `vitest/config`), `tsconfig.json` `paths` `@contracts/*` -> `../docs/contracts/*`, `resolveJsonModule: true`. Dev server `server.fs.allow` includes `frontend/` and `docs/contracts/` only (not the whole repo). Examples (`@contracts/examples/*.json`) resolve through the same alias.
4. **Env**: `src/env.d.ts` types `ImportMetaEnv` (`VITE_AUDIT_URL?: string`, `VITE_MOCK?: string`). `src/config.ts` exports `getConfig(): { mock: boolean; auditUrl: string | null }`. `mock` is true only when `VITE_MOCK === "true"` (exact). Empty/missing URL -> `null`; never throws. `.env.example` documents both vars; `.env*.local` git-ignored.
5. **Tokens** (`src/tokens/`): a typed, framework-free module exporting, for each of the 5 verdicts and 3 evidence roles: `label`, `icon` (text glyph), `color` (placeholder hex), `underline` style (`solid` | `dashed` | `dotted`) for verdicts, plus `selectedClaimBackground` (neutral). Shape: `VERDICT_STYLE: Record<Verdict, VerdictStyle>`, `ROLE_STYLE: Record<EvidenceRole, RoleStyle>`. Table below. Exposed also as CSS custom properties from one stylesheet so CSS and TS cannot diverge.
6. **Placeholder app**: `App.tsx` renders a heading and a legend built from the tokens (proves tokens + env + schema import work). A smoke test asserts the legend lists all 5 verdicts with icon and label.
7. **`.gitignore`**: repo has **no** root `.gitignore` [verified: none at repo root]; add `frontend/.gitignore` (`node_modules`, `dist`, `.env*.local`, `*.tsbuildinfo`) so the PRD stays inside `frontend/`.
8. **README** (`frontend/README.md`, minimal): install, scripts, env vars, mock mode meaning, the `@contracts` alias rule, "schemas are never copied".

| Token | Icon | Underline | Label |
|---|---|---|---|
| supported | ✓ | solid | Supported |
| partially_supported | ◐ | solid | Partially supported |
| contradicted | ✕ | solid | Contradicted |
| insufficient_evidence | ? | dashed | Insufficient evidence |
| out_of_scope | ▨ | dotted | Out of scope |
| supporting / contradicting / qualifying | - | - | Supporting / Contradicting / Qualifying |

Colour is never the only signal: every consumer must show icon + label alongside colour; the tokens module makes omitting them impossible by bundling all three.

## Architecture
```
frontend/
  vite.config.ts      alias @contracts, fs.allow, vitest block (node env)
  tsconfig.json       strict, bundler resolution, paths, resolveJsonModule
  src/config.ts       getConfig()
  src/tokens/         verdict/role styles (+ tokens.css custom properties)
  src/contract/       (SP02)   src/transport/ (SP03)   src/app/ (SP04+)
```
- Tokens depend on nothing; SP02 types (`Verdict`, `EvidenceRole`) are the canonical unions. To avoid an SP01->SP02 cycle, SP01 declares the verdict/role string unions in tokens, and SP02 **re-exports/uses** them as the source of truth for those two unions (SP02 adds a drift test against the schema enums).
- Vitest default environment `node` (SP02 is pure TS). Component tests opt in per file with `// @vitest-environment jsdom`; jsdom + `@testing-library/react` installed here for SP03-05.
- Browser target: current evergreen desktop browsers; no polyfills.

**Verified spike** (scratch project, same layout): Vite 8.3 + Vitest + TypeScript 7.0 + Ajv 8; `vitest run`, `tsc --noEmit`, `vite build` pass, and the dev server serves `/@fs/.../docs/contracts/*.json` (HTTP 200) with the alias + `fs.allow` above. `[verified: spike run 2026-10-10]`. TypeScript 7 **rejects `baseUrl`** (TS5102): use `paths` alone, relative to the tsconfig.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Schema import | `@contracts` alias to `../docs/contracts` | Copy schemas; symlink into `frontend/`; npm workspace package | Locked: no copies. Alias works in Vite, Vitest, tsc; symlinks are fragile on Windows |
| 2 | `fs.allow` scope | `frontend/` + `docs/contracts/` | `searchForWorkspaceRoot`; whole repo | Least exposure in dev server |
| 3 | Package manager | npm + lockfile | pnpm, yarn | Present on machine (npm 10, node 22); no repo convention to match |
| 4 | Test runner | Vitest sharing Vite config | Jest | Reuses alias and transforms; zero extra config |
| 5 | Styling | Plain CSS + custom properties from tokens | Tailwind, CSS-in-JS | Thin app; palette must be swappable in one file |
| 6 | Mock flag parsing | Exactly `"true"` | Any truthy | Avoids `VITE_MOCK=false` string being truthy |
| 7 | Gitignore location | `frontend/.gitignore` | New root `.gitignore` | Stay inside owned dir |
| 8 | Verdict/role unions | Defined here, consumed by SP02 | Define in SP02 | Tokens must exist in Phase 0 |

## Risks / Open Questions
- [RESOLVED: alias + fs.allow, spike-verified] Importing JSON outside `frontend/` in dev/build/test.
- [RESOLVED: omit `baseUrl`] TS 7 removed it.
- [OPEN] ESLint config flavour (flat config + typescript-eslint is assumed); confirm the generated template at implementation time rather than hand-writing.
- [OPEN] `VITE_*` vars are inlined at build time, so `VITE_AUDIT_URL` is fixed per build. Acceptable for v1? Runtime config would need a different mechanism.
- [DEFERRED] Final palette hex + underline thickness (SP06).
- [DEFERRED] CORS/endpoint path agreement with backend (SP03 / integration).

## Acceptance Criteria
- From a clean clone: `cd frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build` all exit 0.
- `npm run dev` serves a page showing the legend with all 5 verdicts (icon + label + colour) and 3 evidence roles.
- A test imports `@contracts/audit-request.schema.json`, `audit-response.schema.json`, and `@contracts/examples/response.json` and asserts `schema_version === "1.0.0"`.
- `getConfig()` unit tests: `VITE_MOCK` `"true"` -> true; `"false"`, `""`, unset -> false; missing URL -> `null`.
- `git status` after install/build shows no untracked `node_modules`/`dist`.
- `docs/contracts/` unchanged; no schema copy exists under `frontend/`.
