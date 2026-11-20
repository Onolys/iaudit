# 0019. Evaluation engine: one in-process run, concern suppression before the decision table

**Audience:** contributors.

**Status:** accepted. Measurements below come from two live runs on the synthetic fixture; a full-length session is still unmeasured.

**Context.** A clinician rates their own session on a card. Onolys must compare that card with its own rating (`paudit`), audit the clinician's written reasons (`eaudit`), and write tips, all into one report the web app renders. `eaudit` was built for clinical write-ups, and several of its 17 checks are noise on a self-rating. See [ADR 0005](0005-models-propose-code-decides.md) (models propose, code decides) and [ADR 0018](0018-protocol-pack-data-vs-code.md) (protocol facts live in the pack).

**Decision.**

- **One library, one call.** `engines/evaluation` (import `onolys_evaluation`) exposes `run_evaluation(...)`, which runs everything in one process with asyncio: `eaudit` starts with `paudit`; tips start when `paudit` finishes and run next to `eaudit`; compare and `build_report` follow. A `paudit` failure fails the run; an `eaudit` or tips failure ships the report with a warning. `progress_cb(stage, status)` reports stages.
- **Protocol-agnostic engine.** No protocol strings in `engines/evaluation/src` or the `eaudit` filter code (the one allowed hit is the report field `not_official_miti_coding`). The suppress list, context note, tone rules, thresholds and layout live in the pack. The evaluation engine never imports the `api` package. Grep and import tests enforce all three.
- **`eaudit` MI scope = suppress list + `context_note`, nothing else.** A request may carry an optional `profile {suppress_concerns, context_note}` (contract `0.0.2`). Profile-less requests are unchanged, including the cache prefix of their prompts.
- **Filter point (chosen at build time).** `eaudit/check/synth.py`, function `synthesize` (reached from `check/checker.py::_check`), applies `suppress` before the decision table. It drops each verifier flag whose concern type is suppressed (`_FLAG_TYPE_CONCERN` maps every flag type to its concern type) and skips the item-level checks behind `timeframe_mismatch`, `conflicting_accounts_flattened` and `unsupported_inference`. `decide` (same file) then gets the filtered signals plus `suppress`, which also gates `frequency_severity_inflation` and `certainty_inflation` candidates. The verdict is therefore recomputed from what remains: a claim whose only flag was suppressed gets the no-flag verdict, and a claim with one suppressed and one kept flag keeps the kept flag's verdict. No concern is hidden after the fact. One point covers all flag types and derived concerns.
- **Live proof.** `python -m onolys_evaluation.check [--pack ID@VERSION] [--preset NAME]` runs the pack's fixture transcript and final card (`fixtures/evaluation/rating_card.json`) on the real model. It passes (exit 0) with at least 3 tips whose quote is exactly the transcript text at the stated offsets and `reasons_audit.status: ran`. It prints the tips quote-valid rate (verified tips over model-proposed tips), per-stage latency, tokens per engine and an estimated cost. The pass/fail logic (`evaluate`) is pure and unit-tested; the live wrapper test `tests/test_live_check.py` is marked `live` and is not run in PR CI. Quality on real self-ratings stays deferred.

**Alternatives.** Post-filtering concerns after the verdict (leaves verdicts that cite hidden concerns); hard-coding the list in `eaudit` (leaks the protocol into the engine); one Cloud Task per stage (cross-task state for no gain at this size).

**Consequences.** Adding a protocol means a new pack with its own `evaluation:` block; no engine edit. Cost per session is bounded by the reasons-audit caps (15 sections, 1,000 chars each, notes 3,000).

## Measurements

Two live runs on 2026-11-20, `python -m onolys_evaluation.check` (the second through the `live` pytest wrapper), default preset, all routes `anthropic/claude-sonnet-5-5`, N=1. Input is the synthetic fixture: 22 turns, about 2.6k characters, a full card (4 globals, 10 counts, 5 reasons incl. notes).

| Item | Run 1 | Run 2 |
|---|---|---|
| Result | PASS | PASS |
| Valid tips | 5 | 5 |
| Tips quote-valid rate (verified / proposed) | 100% (5 of 5) | 100% (5 of 5) |
| `reasons_audit.status` | ran | ran |
| Wall time | 27.1 s | 28.6 s |
| Stage latency, `paudit` | 16.9 s | 12.5 s |
| Stage latency, `eaudit` | 27.1 s | 22.9 s |
| Stage latency, tips | 7.5 s | 16.2 s |
| Stage latency, compare and assemble | under 0.1 s | under 0.1 s |
| LLM calls (paudit / eaudit / tips) | 2 / 23 / 1 | 2 / 20 / 1 |
| Input tokens (paudit / eaudit / tips) | 8,713 / 183,016 / 3,581 | 8,713 / 149,548 / 3,619 |
| Output tokens (paudit / eaudit / tips) | 2,345 / 13,815 / 978 | 2,268 / 11,552 / 2,175 |
| Cache-read tokens (paudit / eaudit / tips) | 7,255 / 85,471 / 1,231 | 7,301 / 75,683 / 1,231 |
| Cache-write tokens | 46 / 0 / 0 | 0 / 0 / 0 |
| Estimated cost per session | $0.87 | $0.75 |

**Cost is an estimate.** Prices used, USD per million tokens, Claude Sonnet published list prices: input 3.00, output 15.00, cache write (5 min) 3.75, cache read 0.30. They are assumed to apply to `claude-sonnet-5-5`, and it is assumed that `input_tokens` excludes cache reads (if the provider counts them inside, the cost is a little lower). Cost is tokens times those prices, summed over the three engines' `run_info.usage`.

**What this does and does not show.** Wall time is the longest stage (`eaudit`) plus assembly, about 25 to 30 s, well under the R8 estimate of 1.5 to 2.5 minutes. That estimate stays [unverified] for real sessions: the fixture is about 2.6k characters, a 20 to 30 minute session is much longer, and `paudit` and the `eaudit` retrieval scale with transcript length. Re-run the check with a long fixture before quoting a production latency or cost.
