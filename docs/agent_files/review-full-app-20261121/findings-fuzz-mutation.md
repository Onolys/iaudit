# Fuzz + mutation findings (api + web)

Env: api :8010 (combined, fake auth, stub adapters) on own Firestore emulator :8091 (demo-fuzz). Tools: schemathesis 4.33.4 (1030 cases, all 26 ops, 4 checks + stateful), hypothesis, fast-check 4.10, mutmut 3, Stryker 10.1. Durable tests: `api/tests/test_fuzz_review.py`, `web/src/__fuzz_review__/*.property.test.ts` (known bugs = strict xfail / `it.fails`, tagged with ids below). How to run: `docs/testing/fuzz-and-mutation.md`.

## 1. Fuzz findings

Counts (new, deduped): medium 3, low 6. Plus 6 static findings confirmed live (below). 0 high/critical.

| ID | Sev | Route / function | Minimal repro | Expected vs actual | Dup of | Conf |
|---|---|---|---|---|---|---|
| F1 | medium | Every `/v1/sessions/{id}*`, `/v1/interviews/{id}` (firestore repo) | `GET /v1/sessions/__x__` or `/v1/sessions/%2e` (same for DELETE, transcript, speakers, runs, rating, reports, audio) | 404 / 422; actual 500 (Firestore InvalidArgument). Fake repo fine | A3 | high |
| F3 | low | `GET /v1/runs/{run_id}` (firestore) | run_id = 5000 x "0" | 404; actual 500 (doc id too long) | A3 (extends: length, not only reserved ids) | high |
| F4 | medium | `GET /v1/sessions?cursor=` | `cursor=é` -> 500 on BOTH fake and firestore repos; firestore also `.`, `%`, `=========`, `!!!!` -> 500 | 422; actual 500. Non-ASCII crash is in cursor decode, not Firestore | A3 (extends: fake repo too) | high |
| F5 | medium | web `auth/next.ts readNext` | `?next=%2F%09%2Fevil.com` -> returns `"/\t/evil.com"`; `new URL(r, origin)` strips the tab -> `//evil.com` -> origin evil.com. Same with `\n`, `\r` | same-origin path only; actual: protocol-relative host after browser URL normalisation (open redirect if consumer does not re-validate; used by `Navigate` in PublicOnly/RequireUnverified). Not browser-verified | not in A#; check against web W# list | medium |
| F2 | low | `POST /v1/sessions`, `/audio`, `/runs` | body = single byte `\xff` with `content-type: application/json` -> 400 `request_rejected` | documented 422 `invalid_parameters`; 400 not in openapi (schemathesis ST103) | A14 | high |
| F6 | low | web `lib/format.ts formatElapsed` | `formatElapsed(NaN)` -> `"NaN:NaN"`, `Infinity` -> `"Infinity:NaN"` | `m:ss`; actual garbage. Only reachable if a non-finite ms is passed | new | high |
| F7 | low | web `lib/codepoints.ts sliceCodePoints` | `sliceCodePoints("abc", -1, 2)` -> `"ab"`; `(“abc”,2,1)` -> `"c"` | `""`; negative/reversed offsets fall back to head/tail. Not reachable via `buildSegments` (validates first) | new | high |
| F8 | low | `GET /v1/sessions/{id}/transcript`, `/speakers` | fresh session -> 409 `invalid_state` | openapi documents only 200/401/404/429/500 (schemathesis ST103) | A14-class (contract drift) | high |
| F9 | low | `POST /v1/interviews` | `{"scenario_id":"0"}` -> 422 `invalid_parameters` | 422 not documented (201/401/429/500) | A14-class | high |

Confirmed live by tests (strict xfail, no new id): A4 (20 concurrent `POST /sessions` all 202), A6 (`preset: claude` -> 202), A11 (concurrent `POST /api-key` leaves several live keys; reproduced on firestore, not on fake), A12 (no `Cache-Control: no-store` on `/speakers`), A18 (`language: zz` -> 202), A23 (idempotent replay after delete returns deleted session id; concurrent same-key create NOT reproduced, passes on both repos).

Clean (no finding): no 5xx from random path ids on fake repo, `limit` ints, create-session bodies (language/n_runs/preset/title/interview_id), arbitrary rating PUT / speakers-confirm bodies, idempotency keys (0-260 chars, unicode), cross-user isolation; schemathesis response-schema and content-type conformance clean on all reachable ops. web: `mapAuthError`/`errorCode`/`messageForCode`/`parseErrorBody`/`describeError`/`failureAction` never throw, never leak raw text, prototype keys (`__proto__`, `constructor`) fall to generic; `loginUrl/verifyUrl` round-trip through `readNext`; `buildSegments` always re-concatenates to the text, no empty segments.

Not covered: schemathesis stateful ops needing real audio/report data stayed at 404 (7 ops: audio GET/complete, reports/{version}, speakers/confirm, runs/{id}, interviews GET/end); concurrent usage-reserve race on firestore (existing `test_caps` params are flaky under emulator contention).

## 2. Mutation testing

Scores = killed / (killed + survived); "uncovered" = no selected test reaches it.

| Module | Tool | Mutants | Killed | Survived | Uncovered | Score |
|---|---|---|---|---|---|---|
| api `auth/deps.py` | mutmut | 136 | 108 | 28 | 0 | 79.4% |
| api `auth/idtoken.py` | mutmut | 85 | 58 | 21 | 6 | 73.4% |
| api `auth/keys.py` | mutmut | 21 | 20 | 1 | 0 | 95.2% |
| api `auth/oidc.py` | mutmut | 63 | 0 | 0 | 63 | untested by selected tests (0% coverage) |
| api `repo/limits.py` | mutmut | 171 | 148 | 23 | 0 | 86.5% |
| api `jobs/run.py` | mutmut | 422 | 322 | 100 | 0 | 76.3% |
| api `repo/firestore.py` | mutmut | 1250 | 0 | 0 | 1250 | not scored: selected tests (fake repo) never reach it. Emulator run of `reserve_usage`/`release_usage` aborted: clean baseline of `test_repo_contract.py` had 1 failure under emulator (contention) |
| web `auth/next.ts` | Stryker | 40 | 40 | 0 | 0 | 100% |
| web `auth/errors.ts` | Stryker | 66 | 59 | 4 | 3 | 93.7% (89.4% with uncovered) |
| web `api/errors.ts` | Stryker | 98 | 85 | 13 | 0 | 86.7% |
| web `auth/guards.tsx` | Stryker | 46 | 33 | 12 | 1 | 73.3% (71.7% with uncovered) |

Note: web numbers include the new property tests (next.ts would be lower without them). api runner: `test_auth, test_limits, test_run, test_caps, test_first_run`. About half of the surviving api mutants are log/message string-case mutants (low value) and are omitted below.

| ID | File:line | Surviving mutation | Missing test |
|---|---|---|---|
| M1 | auth/idtoken.py (verify, `sub` check) | `len(sub) > 128` -> `>= 128` / `> 129`; `or` -> `and` in `not isinstance(sub,str) or not sub or ...` | sub length 128/129, empty sub, non-str sub, `/` in sub (uid injection into Firestore path) |
| M2 | auth/idtoken.py `verify` | `header.get("kid")` -> `"KID"` | key-rotation refresh: token with kid not in cached certs triggers exactly one refetch (also the A2 DoS surface) |
| M3 | auth/idtoken.py `_get_certs` | `> ttl` -> `>= ttl`; default `force=False`->`True`; `_fetched_at` init | cert cache TTL boundary and "no refetch within TTL" |
| M4 | auth/idtoken.py `_decode` | `clock_skew_in_seconds` arg dropped | token slightly in the future / just expired is accepted/rejected per CLOCK_SKEW_S |
| M5 | auth/deps.py `Authenticator.__init__` | `project = auth_project or gcp_project` -> `and` / `None`; `verifier is None and not project` -> `or` | idp mode: AUTH_PROJECT fallback to GCP_PROJECT; error only when both unset |
| M6 | auth/deps.py `_from_api_key` | dummy hash `"0"*64` -> `"0"*65`; `last_used_at` `>=` -> `>` | constant-time unknown-key path; last_used throttle boundary |
| M7 | auth/deps.py `_ensure_user`, `current_user` | `_SEEN_CAP` `>=`->`>`; `request.state.auth_kind = None` | seen-set eviction at cap; auth_kind logged for token vs key |
| M8 | auth/oidc.py (all 63) | no test reaches OIDC verifier for `/tasks/*` | any unit test of OIDC audience/issuer/email checks (relates A8) |
| M9 | repo/limits.py `effective_cap` | `elif sub is not None` -> `is None`; `elif limits is not None` -> `is None` | per-user override of cap present vs absent, partial override (`{"limits":{"eval":{"day":25}}}` only tests one branch) |
| M10 | repo/limits.py `decide_start` | `_at_active_limit(user or {}, ...)` -> `user and {}` | start decision with `user=None` vs real user active count |
| M11 | jobs/run.py `release_once` | `{"released": True}` -> `False` / key `"RELEASED"`; `cap_date or date` -> `and` | released flag actually persisted (test asserts the run doc afterwards; idempotent second release; A7 area) |
| M12 | jobs/run.py `_evaluate` | `any(True for _ in errors)` -> `any(False ...)` | an out-of-schema report must raise PermanentError (invalid report currently passes unnoticed by tests) |
| M13 | jobs/run.py `_evaluate` | `rating_card = card if (has_rating and not no_rating)` -> `or True` / `or`; `language: a or b` -> `and`; `coded_span` -> `and False` | rating card/coded_span/language passed to the evaluation call for each combination |
| M14 | jobs/run.py `_evaluate` | `deadline = monotonic() + max(0.0, remaining)` -> `-` / `max(1.0,...)` / `None` | engine deadline derived from task remaining time |
| M15 | jobs/run.py `make_run_handler` | `retryable = isinstance(e,TimeoutError) or e.retryable` -> `and`; `ctx.attempt >= MAX_ATTEMPTS` -> `>`; `to_public(e, attempt)` arg changes | retry vs permanent classification and last-attempt boundary (A1/A20 area) |
| M16 | jobs/run.py `_execute` | `get_report(..., resolve=False)` -> `True`/`None`/omitted; `state != "report_ready"` string case; `stage` None | resume path for an already-written report |
| M17 | web auth/guards.tsx 27,42 | `status === "loading"` -> `false`; `<Loading/>` body emptied | loading state renders spinner, not a redirect, in PublicOnly and RequireUnverified |
| M18 | web auth/guards.tsx 28,35,45 | `user?.emailVerified` -> `false`; `/verify-email` and `/login` redirect targets with `next` | PublicOnly signed-in-verified redirects to `next`; RequireUnverified logged-out -> `/login?next=...` (line 45 fully unverified) |
| M19 | web api/errors.ts 105-114 | `filter(...)` removed; `&&` -> `||` in detail validation; `request_id` check -> true | `parseErrorBody` drops malformed detail entries; non-string request_id ignored (property test only checks well-formed) |
| M20 | web api/errors.ts 40,74 | `isKnown`/`failureAction` guard -> `true` | `failureAction(undefined)` is `run_again`; unknown code not treated as known |
| M21 | web auth/errors.ts 28,34,36,37 | cases `cancelled-popup-request`, `requires-recent-login`, `user-disabled` emptied; `user-disabled` uncovered | each mapped code has a test; `errorCode` with non-string `code` |

Caveat: Stryker ran `inPlace` with the full vitest suite (440 tests, ~9 min); mutmut only the five api files above.

## 3. Added tests (durable)
- `api/tests/test_fuzz_review.py`: 151 non-emulator cases (126 pass, 7 strict/non-strict xfail on fake; ~14 s) + 46 emulator cases (`firestore` marker, ~12 s, 30 xfail, 1 non-strict xpass).
- `api/tests/test_schemathesis_smoke.py`: 25 cases, ~6 s, FakeRepo, in-process.
- `web/src/__fuzz_review__/*.property.test.ts`: 25 tests (22 pass, 3 `it.fails` = F5, F6, F7), ~1.5 s.
- New dev deps: api `hypothesis`, `schemathesis`; web `fast-check`, `@stryker-mutator/core`, `@stryker-mutator/vitest-runner`.
