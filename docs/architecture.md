# Architecture

High-level design: how the system fits together.

**Audience:** everyone.

v1 is one synchronous JSON exchange. The frontend owns the contract in [contracts/](contracts/). It sends an `AuditRequest` (transcript turns plus assessment sections). The backend returns an `AuditResponse` (claim verdicts, concern types, and positions into that same input). There is no streaming and no background job.

`label` and `score` are display-only. The response locates claims and excerpts by index and character offset. It does not copy transcript text or timestamps.

## Backend

The backend ([../backend/](../backend/)) serves `POST /v1/audit` and calls model providers through LiteLLM. It reads the schemas in [contracts/](contracts/) in place. For each claim in the assessment, a model proposes evidence and a verdict, and code decides what is reported. The model never returns positions. Code computes them. Endpoint, errors, settings and warnings: [reference/backend-api.md](reference/backend-api.md).

One call, one reply. The target is 30 to 45 seconds, the hard cap is 60 (`IAUDIT_AUDIT_DEADLINE_S`), and the review UI waits up to 120.

```
review UI --POST /v1/audit--> backend --LiteLLM--> model providers
```

Five stages, with claims streaming through stages 2 and 3 as soon as stage 1 produces them:

| Stage | Job | By |
|---|---|---|
| 0 Prep | Index the turns, tag questions, answers and corrections, pair questions with replies | Rules (a cheap model for undecided turns, off by default) |
| 1 Atomize | Split each section into claims | Model, then code validates |
| 2 Link | Find evidence turns for each claim | Retrieval in code, a model proposes, code validates |
| 3 Check | Observe how the evidence relates to the claim, then pick the verdict and concerns | Model observes, code decides |
| 4 Assemble | Turn text into positions, repair the rules, validate the reply | Code only |

Where the code lives, under `backend/`:

| Path | Holds |
|---|---|
| `src/iaudit_backend/app.py`, `api/`, `config.py`, `contract.py` | The endpoint, error mapping, settings, schema loading |
| `src/iaudit_backend/llm/` | The one interface to every model call |
| `src/iaudit_backend/prep/`, `atomize/`, `link/`, `check/`, `assembler/` | Stages 0 to 4 |
| `src/iaudit_backend/pipeline/` | Orchestration, deadline, metrics |
| `eval/`, `tests/` | The evaluation harness and the test suite |

Details: [implementation/](implementation/), [concepts/](concepts/), [decisions/](decisions/).

## Review UI

The frontend is a browser app (React + TypeScript, in [../frontend/](../frontend/)). It never edits the assessment. Flow:

1. The reviewer uploads a request JSON file. The app checks it against the request schema.
2. The app sends it to the audit endpoint with one `POST`. In mock mode it picks a bundled example reply instead.
3. The app checks the reply against the response schema. A broken reply is rejected whole.
4. It checks every span against the request text (a bad span flags only its claim) and counts verdicts.
5. It shows the assessment on the left and the selected claim's detail on the right.

| Module | Job |
|---|---|
| `contract/` | Validation, span maths, claim ordering, excerpt grouping. No UI. |
| `transport/` | Read file, POST or mock, error mapping, loading state. |
| `app/` | Page shell, left pane, verdict navigation. |
| `claim-detail/` | Right pane: verdict, concerns, excerpts, suggestion. |
| `tokens/` | Verdict and evidence colours, icons, labels. |

More: [how to read the screen](concepts/review-ui.md), [facts and settings](reference/review-ui.md), [internals](implementation/frontend.md), [testing](testing/frontend.md), [decisions](decisions/).
