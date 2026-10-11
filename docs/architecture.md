# Architecture

High-level design: how the system fits together.

**Audience:** everyone.

v1 is one synchronous JSON exchange. The frontend owns the contract in [contracts/](contracts/). It sends an `AuditRequest` (transcript turns plus assessment sections). The backend returns an `AuditResponse` (claim verdicts, concern types, and positions into that same input). There is no streaming and no background job.

`label` and `score` are display-only. The response locates claims and excerpts by index and character offset. It does not copy transcript text or timestamps.

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
