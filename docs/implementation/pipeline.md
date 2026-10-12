# Pipeline

How one audit runs. Code: `backend/src/iaudit_backend/pipeline/`.

**Audience:** maintainers and coding agents.

## Shape

`FullPipeline.run` (`full.py`) starts, at once: prep (`flow.prep_flow`), one atomize flow per section (`flow.section_flow`), and, if enabled, the cache warm-up. Each atomized claim spawns its own `claim_flow`: wait for prep, build the link context once, `link_one`, then `check_one`, write the draft. Claims stream: the first claim's link call starts as soon as its section is atomized, not after every section. After the flows finish, the drafts go to the assembler (`../assembler/`) and the reply is validated.

```
prep ──────────────────────────────┐
atomize s0 ─▶ claim flows ─▶ link ─▶ check ─┐
atomize s1 ─▶ claim flows ─▶ link ─▶ check ─┼─▶ assemble ─▶ reply
(warm-up, optional) ... cache writes        ─┘
```

## State and cancellation

`RunState` (`state.py`) is write-once per result. Flows write into it as they finish; the supervisor reads it after cancelling, so a claim that finishes at the buzzer still counts. Tasks are tracked, never awaited from other flows: waits go through events (`prep_ready`, `warm_ready`), so cancelling one flow cannot cancel a task others share. There is no `TaskGroup`, because one bug-induced exception would cancel siblings and lose finished work.

## Deadline

`audit_deadline_s` is the request budget. Stages see an LLM deadline earlier by `assemble_reserve_s`, which is kept for assembling. `RequestContext.call_timeout(stage)` returns the per-call timeout, or `None` when less than `min_call_s` is left, in which case the call is not started. At the LLM deadline, unfinished tasks get `cancel_grace_s` to stop. A backstop in the API layer (`run_with_backstop`) stops a run that overshoots anyway.

## Degradation

| Situation | Result |
|---|---|
| A link or check call times out or fails | That claim: `insufficient_evidence` plus a warning. Status stays `complete`. |
| A section's atomize fails | `section_not_processed` warning, status `partial`. |
| Prep passes `prep_soft_timeout_s` | Rules-only prep result; claims continue. |
| More claims than `pipeline_max_claims` | Extra claims dropped, `input_truncated`. |
| Nothing usable finished | `guards.assess` raises: 503 if every unit saw an unavailable provider, 500 for an unexpected error, otherwise 504. A run of only out-of-scope claims is valid. |

## Cache layout and warm-up (optional)

`layout.py` builds the shared prompt: common system text, then the transcript, then each stage's instructions, with the per-claim block last. `warmup.py` writes those prefixes at the start of a live audit, only in whole-transcript mode and above `cache_min_prefix_tokens`. Both are off by default. Whether the provider really shares the cache across the two stages has to be checked on a live run: look at `cache_hit_ratio` in the metrics snapshot.

## Metrics

`ctx.metrics.snapshot()` holds the per-call records (tier, model, unit, token counts, latency, attempts, ok, error kind), the cache hit ratio, per-stage spans, and counters. `metrics.py` writes the `audit_done` log line. `Server-Timing` is built from the same summary. A stage's `calls` counts the units it ran (sections or claims), not model calls.
