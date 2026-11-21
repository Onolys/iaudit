# 0020. Public `/v1` API contract

**Audience:** contributors.

**Status:** accepted.

**Context.** The web app (a generated TypeScript client) and API-key users depend on one HTTP contract. It had to be stable, discoverable without credentials, and checkable in CI.

**Decision.**

- **Source of truth.** The FastAPI models generate `api/openapi.json` (`python -m onolys_api.openapi`, sorted keys, fixed test settings so output never depends on the environment). It is committed; CI job `api` regenerates it and fails on a diff. `docs/contracts/public/*.schema.json` are generated from the same models (`python -m onolys_api.contracts`) and checked the same way; the error schema is hand-written and a test ties it to the model.
- **Stable names.** Every operation has a fixed camelCase `operationId`. Path ids are `{id}` (session), `{run_id}`, `{version}` (report, by integer version) and `{report_id}` (reserved). No `/presets`, `/dashboard` or top-level `/reports` paths.
- **Errors.** Every operation lists each error status it can return (401, 404 where an id is in the path, 409, 422, 429, 500, 503 as applicable) as the one `ErrorResponse` model. `details[]` gains optional `field` (dotted path) and `issue` (code) so a client can attach `rating_invalid` problems to the right card field without parsing text; paths only, never card content.
- **Docs.** `GET /v1/openapi.json` and `GET /v1/docs` (Redoc) need no auth. The Redoc 2.1.5 standalone bundle (MIT, about 0.9 MB) is vendored in the package and served from `/v1/docs/redoc.standalone.js`; the page names no other host. The quickstart is a bash/curl script in the OpenAPI description; a test extracts it and runs it against `SERVICE_MODE=combined` with stub adapters.
- **Idempotency.** `Idempotency-Key` is declared on `POST /sessions` only.

**Alternatives.** A CDN-hosted Redoc (a third-party script on a page next to authenticated API traffic, and a runtime dependency); hand-written contract files (drift); `operationId`s derived from function names (a rename would break clients).

**Consequences.** Any API change shows up as a diff in `api/openapi.json` and `docs/contracts/public/`. Upgrading Redoc means replacing one vendored file. The quickstart cannot rot without failing a test.
