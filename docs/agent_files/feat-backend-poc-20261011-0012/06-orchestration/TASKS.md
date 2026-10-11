---
status: approved
summary: Seven core tasks wiring prep, atomize, link, check and assemble into a deadline-bounded FullPipeline with 503/504 on nothing usable; one gated optional row.
date: 2026-10-11
---
# Tasks: 06 Orchestration + latency

Source of truth: [PRD.md](PRD.md). The async `FullPipeline` that runs prep ‖ atomize, then per-claim link and check, then assemble, inside a 60 s deadline.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Time-budget helpers and sibling R8 entry points | 05 | done |
| 2 | `RunState`, supervisor, per-claim fan-out | 1 | done |
| 3 | Deadline, assemble reserve, per-call timeouts, prep soft timeout | 2 | done |
| 4 | Degradation map, 503/504 guard, claim cap | 3 | done |
| 5 | Basic metrics and `audit_done` log line | 2 | done |
| 6 | Default pipeline flipped to `full`; `DeadlineExceeded` | 4 | done |
| 7 | ADHD faithful + 8 variants replay through `FullPipeline` | 6, 07a/T3 | done |
| 8 | [OPTIONAL, gated] Optional items | all core in every SP | todo |

## Task 1 — Budget helpers and entry points
What it is / what it means: The interfaces 06 needs from 01-05 (R8, R2).
What changes at a high level: `RequestContext.remaining()` and `call_timeout()`, deadline-gated retries in the stages, and the single-unit entry points (`atomize_section`, `build_link_context`/`link_one`, `check_one`).
Done when: each entry point is callable from a test with a stub client.

## Task 2 — Fan-out
What it is / what it means: Concurrency without losing partial results (R1, R4, D1, D3-D5).
What changes at a high level: Write-once `RunState`, a supervisor that tracks per-section and per-claim tasks (no `TaskGroup`), events rather than `await task`, never catching `CancelledError`. Global semaphore 20 stays the real limit; FIFO (resolved O-5).
Done when: a cancelled claim leaves others intact and the semaphore returns to its limit.

## Task 3 — Deadline
What it is / what it means: Every request ends inside 60 s (R2, D2, D10, D14).
What changes at a high level: `AUDIT_DEADLINE_S` 60, `ASSEMBLE_RESERVE_S` 3, `MIN_CALL_S`, stage call timeouts as stated (O-7 deferred), `PREP_SOFT_TIMEOUT_S`, `CANCEL_GRACE_S`.
Done when: a stub client with an injected sleep and a tiny deadline still returns a valid partial audit.

## Task 4 — Degradation and guard
What it is / what it means: One mapping from failures to contract output (R3, D6, D7, D11).
What changes at a high level: Section failures become `section_not_processed` + `partial`; stalled claims become `insufficient_evidence` + `other`. When nothing usable completes, return 503 `unavailable`, or 504 when the deadline is hit (resolved O-1). No section escalation (resolved O-2). Claim cap 80, first come first served, `input_truncated` (resolved O-4).
Done when: tests cover all-fail → 503, deadline → 504, all `out_of_scope` → 200, and the cap.

## Task 5 — Metrics
What it is / what it means: Basic timings for the log line (R5 core).
What changes at a high level: Per-stage first-start/last-end, claim and section counters, `deadline_hit`, one `audit_done` line via 01's allowlist.
Done when: the log line carries counters and no text.

## Task 6 — Wiring
What it is / what it means: `full` becomes the default (R7).
What changes at a high level: Flip `IAUDIT_PIPELINE` default to `full`, add core `Settings` keys, add `DeadlineExceeded`. Tests keep pinning `stub` where they need it.
Done when: the app starts with `full` and existing 01 tests still pass.

## Task 7 — Replay test
What it is / what it means: End-to-end proof offline (acceptance 1).
What changes at a high level: Run the ADHD faithful fixture and all 8 variants through `FullPipeline` with `FixtureClient`.
Done when: each fixture matches its expected verdict and concern.

## Task 8 — [OPTIONAL, gated] Optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: Prompt-cache layout and warm-up, latency suite, rich metrics, `Server-Timing`, priority.
Done when: each optional acceptance part passes.
