# Property/fuzz and mutation tests

Added by the 2026-11-21 full-app review (`docs/agent_files/review-full-app-20261121/findings-fuzz-mutation.md`).

## Property / fuzz tests (run with the normal suites)
- api: `api/tests/test_fuzz_review.py` (hypothesis, httpx via Starlette TestClient). Runs on the in-memory FakeRepo; the `[firestore]` params run when `FIRESTORE_EMULATOR_HOST` is set. `uv run --package onolys-api pytest api/tests/test_fuzz_review.py -q`
- web: `web/src/__fuzz_review__/*.property.test.ts` (fast-check). `cd web && npx vitest run src/__fuzz_review__`
- Tests assert correct behaviour. Known bugs are `xfail(strict=True)` (pytest) or `it.fails` (vitest), tagged with the finding id (A#/F#). When a bug is fixed the test XPASSes and fails the run: remove the marker. The two race tests (A11, A23) are non-strict xfail because they depend on timing.

- api smoke: `api/tests/test_schemathesis_smoke.py` (schemathesis, in-process ASGI app on FakeRepo, 4 examples per operation, `not_a_server_error` only; xdist-safe, ~6 s).
- Full schemathesis run (manual / nightly, not blocking; needs a running api with fake auth, e.g. [local-setup.md](local-setup.md) "Main app (web + api)" mode B):
  `uvx schemathesis run api/openapi.json --url http://127.0.0.1:8000 -H 'Authorization: Bearer test:alice' --checks not_a_server_error,status_code_conformance,content_type_conformance,response_schema_conformance --max-examples 40 --phases examples,fuzzing,stateful`
  Today it reports F1/F2/F4/F8/F9 (see findings-fuzz-mutation.md).
- Markers: the `[firestore]` params carry `pytest.mark.firestore` (registered/auto-applied by api/tests/conftest.py on main after PR #48); everything else is emulator-free.

## Mutation testing (manual, slow, not in CI)
- api (mutmut 3): from `api/`: `uv run --package onolys-api --with mutmut mutmut run 'onolys_api.auth*' 'onolys_api.repo.limits*' 'onolys_api.jobs.run*'`, then `mutmut results`. Config is `[tool.mutmut]` in `api/pyproject.toml` (only the auth/limits/run tests are used; `repo/firestore.py` needs the emulator and is not scored). Afterwards delete `api/mutants/` and the folders mutmut copies into `api/` (`config`, `docs`, `engines`, `protocols`).
- web (Stryker): from `web/`: `npx stryker run stryker.conf.json` (about 10 min; runs in a temp copy under `node_modules/.stryker-tmp` (`inPlace: false`)). Report in `web/reports/mutation/` (do not commit).
