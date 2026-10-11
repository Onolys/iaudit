# Local Preview

Repository-specific instructions for running this project locally and
exposing it through Party Preview. Global Preview skills explain how to
call `party preview`; this file explains how this repository runs.

Fill in verified details as they are discovered during Preview or other
local-setup work. Do not invent repository-specific values.

## Dependency setup

<!-- How to install language toolchains, packages, and other local deps. -->

## Required services

<!-- Databases, caches, queues, or other processes that must be running. -->

## Environment prerequisites

<!-- Required variable names only. Never record secret values. -->

## Startup commands

<!-- The exact command(s) that start the app the Preview should proxy. -->

## Host, port, and networking

<!-- Bind address, port, proxy, HMR, allowed hosts, and similar behavior. -->

## Verification

<!-- Health checks, expected log lines, or other proof the app is ready. -->

## Quirks and troubleshooting

<!-- Repository-specific failures, workarounds, and notes for later sessions. -->

## Verified (frontend)

- Install: `cd frontend && npm ci`.
- Start: `cd frontend && VITE_MOCK=true npm run dev -- --host 0.0.0.0 --port 5173` (mock mode needs no backend; upload `docs/contracts/examples/request.json`).
- Tests: `npm test` and `npm run typecheck` in `frontend/`.
- Read-only workspaces: `npm test` can fail writing `node_modules/.vite-temp`; use `npx vitest run --configLoader runner`.
