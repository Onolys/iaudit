# Configuration

Every `IAUDIT_*` setting, read from `Settings` in `backend/src/iaudit_backend/config.py`. Set one as an environment variable named `IAUDIT_<NAME>` in upper case (for example `IAUDIT_AUDIT_DEADLINE_S=45`). `Settings` also reads a `.env` file in the directory the server starts in, which is normally `backend/`.

**Audience:** users.

Two things are not `Settings` fields. `IAUDIT_CONTRACTS_DIR` points at the schema directory (default: `docs/contracts` of the repo) and is read from the environment only, so `.env` does not set it. Provider keys are the standard variables LiteLLM reads, for example `ANTHROPIC_API_KEY`. They are never logged. With `IAUDIT_LLM_MODE=live` and no key present, the service starts, logs a warning, and audits fail with 503.

Values here are the defaults. Tuning values (thresholds, caps, windows) are guesses to be tuned against the evaluation harness; see [../testing/evaluation.md](../testing/evaluation.md).

## Limits and CORS

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_MAX_BODY_BYTES` | `2000000` | Largest request body, in bytes. Over it: 413. |
| `IAUDIT_MAX_TURNS` | `2000` | Most transcript turns. Over it: 413. |
| `IAUDIT_MAX_SECTIONS` | `50` | Most assessment sections. Over it: 413. |
| `IAUDIT_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated origins a browser may call from. |

## Models, timeouts, concurrency

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_MODEL_CHEAP` | `anthropic/claude-haiku-4-5-20251001` | LiteLLM model id for the cheap tier (prep tagging). |
| `IAUDIT_MODEL_MID` | `anthropic/claude-sonnet-5-5` | LiteLLM model id for the mid tier (atomize, link, check). |
| `IAUDIT_MODEL_STRONG` | `anthropic/claude-opus-5-5` | LiteLLM model id for the strong tier. Offline use only. |
| `IAUDIT_LLM_TIMEOUT_S` | `30` | Default call timeout for a stage with no `*_CALL_TIMEOUT_S` of its own, and the time a retry needs to fit. A stage cap replaces it, even when longer. |
| `IAUDIT_AUDIT_DEADLINE_S` | `100` | Hard cap for one audit. A startup warning is logged above 100. |
| `IAUDIT_LLM_MAX_RETRIES` | `1` | Retries of a failed model call (timeout, bad JSON, provider error). |
| `IAUDIT_LLM_MAX_CONCURRENCY` | `20` | Model calls in flight at once, across the whole service. |
| `IAUDIT_LLM_MODE` | `live` | `live` calls providers; `fixture` replays recordings from `fixture_dir`; `stub` makes every model call fail as unavailable. |
| `IAUDIT_LLM_RESPONSE_FORMAT` | `json_object` | `json_object` relies on the prompt for the schema and validates replies here. `json_schema` asks the provider for strict structured output; Haiku 5.5 often returns empty claims with it. |
| `IAUDIT_FIXTURE_DIR` | `tests/fixtures/llm` | Recordings for `fixture` mode. |

## Orchestration

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_PIPELINE` | `full` | `full` runs the audit; `stub` returns a valid empty audit. |
| `IAUDIT_ASSEMBLE_RESERVE_S` | `3` | Time kept at the end of the deadline for assembling the reply. |
| `IAUDIT_MIN_CALL_S` | `4` | No model call starts with less than this much budget left. |
| `IAUDIT_CANCEL_GRACE_S` | `1` | How long unfinished work gets to stop after the deadline. |
| `IAUDIT_PIPELINE_MAX_CLAIMS` | `80` | Claims audited per request. More are dropped and `input_truncated` is emitted. |
| `IAUDIT_PREP_CALL_TIMEOUT_S` | `10` | Per-call cap for prep tagging. |
| `IAUDIT_ATOMIZE_CALL_TIMEOUT_S` | `60` | Per-call cap for atomize. Replaces `IAUDIT_LLM_TIMEOUT_S` for this stage; the call is still bounded by the time left in the audit. |
| `IAUDIT_LINK_CALL_TIMEOUT_S` | `20` | Per-call cap for link. |
| `IAUDIT_CHECK_CALL_TIMEOUT_S` | `20` | Per-call cap for check. |
| `IAUDIT_CACHE_LAYOUT` | `per_stage` | `shared` gives link and check one cached system-plus-transcript prefix (whole mode). |
| `IAUDIT_CACHE_WARMUP` | `false` | Write those prefixes to the provider cache at the start of an audit. Live mode and shared layout only. |
| `IAUDIT_CACHE_MIN_PREFIX_TOKENS` | `1024` | Transcripts smaller than this skip warm-up. |
| `IAUDIT_WARMUP_MAX_WAIT_S` | `2` | Longest a stage waits for the warm-up. |
| `IAUDIT_SERVER_TIMING` | `true` | Add a `Server-Timing` header (durations only) to 200 replies. |
| `IAUDIT_LOG_LEVEL` | `INFO` | Logging level. Logs carry counts and ids only, never text. |

## Prep

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_PREP_SOFT_TIMEOUT_S` | `10` | After this, prep falls back to its rules-only result. |
| `IAUDIT_PREP_LLM` | `false` | Cheap-tier tagging of the turns the rules could not decide. |
| `IAUDIT_PREP_CHUNK_TURNS` | `30` | Undecided turns per tagging call. |
| `IAUDIT_PREP_CONTEXT_TURNS` | `3` | Read-only context turns either side of each tagging chunk. |

## Atomize

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_ATOMIZE_MAX_CLAIMS` | `30` | Most claims asked of the atomizer per section. |
| `IAUDIT_ATOMIZE_MAX_TOKENS` | `16000` | Output token cap for the atomizer call. Haiku 5.5 allows up to 128000 output tokens, but `atomize_call_timeout_s` (60 s) ends the call first on very long outputs. |
| `IAUDIT_ATOMIZE_RETRY` | `true` | Retry a section once when the atomizer answer fails validation. |

## Link

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_LINK_MODE` | `auto` | `auto` picks whole-transcript or shortlist by size; or force `whole` or `shortlist`. |
| `IAUDIT_LINK_WHOLE_MAX_TOKENS` | `8000` | Transcript size (estimated tokens) under which `auto` sends the whole transcript. |
| `IAUDIT_LINK_FALLBACK_MAX_TOKENS` | `24000` | Largest transcript sent whole when the shortlist is empty. |
| `IAUDIT_LINK_TOP_K` | `8` | Keyword hits kept for the shortlist. |
| `IAUDIT_LINK_CORRECTION_WINDOW` | `4` | Turns after a hit searched for a correction or a same-speaker follow-up. |
| `IAUDIT_LINK_MAX_SHORTLIST` | `30` | Cap on shortlist size. |
| `IAUDIT_LINK_MAX_ITEMS` | `8` | Most evidence items per claim. |
| `IAUDIT_LINK_MAX_TOKENS` | `1200` | Output token cap for the link call. |
| `IAUDIT_LINK_CONCURRENCY` | `20` | Link calls in flight at once. |
| `IAUDIT_LINK_RETRY` | `true` | Retry once when every returned item is rejected. |
| `IAUDIT_LINK_WIDEN_ON_EMPTY` | `false` | When the shortlist finds nothing, retry with the whole transcript. |
| `IAUDIT_LINK_PER_SPEAKER_FLOOR` | `2` | Hits a speaker with matches should have in the shortlist. `0` turns it off. |
| `IAUDIT_LINK_MAX_SPEAKER_ADDS` | `4` | Most turns the speaker floor may add. |
| `IAUDIT_LINK_LATER_CORRECTION_CAP` | `3` | Most later corrections pulled in. `0` turns it off. |
| `IAUDIT_LINK_FUSION` | `false` | Fuse the keyword ranking with a fuzzy-match ranking by reciprocal rank. |
| `IAUDIT_LINK_RRF_K` | `60` | The constant in reciprocal rank fusion. |
| `IAUDIT_LINK_CACHE_BREAKPOINTS` | `1` | `2` caches the transcript and the instruction block separately in whole mode. |

## Check

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_CHECK_CONCURRENCY` | `20` | Check calls in flight at once. |
| `IAUDIT_CHECK_MAX_TOKENS` | `1500` | Output token cap for the check call. |
| `IAUDIT_CHECK_MIN_CONF_P0` | `0.5` | Confidence floor for core observations. |
| `IAUDIT_CHECK_MIN_CONF_P1` | `0.6` | Confidence floor for the quick-pass flags. |
| `IAUDIT_CHECK_STEP_MATERIAL` | `1` | Smallest bucket gap that counts as a frequency or severity difference. |
| `IAUDIT_CHECK_CONTRADICT_GAP` | `3` | Bucket gap at which an inflated amount becomes a contradiction. |
| `IAUDIT_CHECK_RATE_RATIO` | `1.5` | Weekly-rate ratio between two speakers that flags conflicting accounts. |
| `IAUDIT_CHECK_CONF_LOW` | `0.3` | Worth of the verifier's `low` confidence against the floors. |
| `IAUDIT_CHECK_CONF_MEDIUM` | `0.6` | Worth of `medium`. |
| `IAUDIT_CHECK_CONF_HIGH` | `0.9` | Worth of `high`. The three must be in increasing order. |
| `IAUDIT_CHECK_SUGGEST_REVISION` | `true` | Ask the verifier for a suggested revision. |
| `IAUDIT_CHECK_RETRY` | `true` | Retry once when the verifier leaves evidence items unjudged. |

## Assembler

| Variable | Default | Meaning |
|---|---|---|
| `IAUDIT_FUZZY_THRESHOLD` | `90` | Minimum fuzzy score (0-100) to accept an evidence excerpt that is not an exact match. |
| `IAUDIT_CLAIM_FUZZY_THRESHOLD` | `90` | The same for locating a claim in its section. |
| `IAUDIT_FUZZY_MIN_LEN` | `12` | Shortest excerpt, in characters, that may match fuzzily. |
| `IAUDIT_COPY_NGRAM` | `8` | Word run copied from the transcript that triggers the copy check. `0` turns the check off. |
| `IAUDIT_OVERLAP_TRIM` | `true` | Trim the less severe of two partly overlapping claims instead of dropping it. |
| `IAUDIT_CROSS_TURN_SLACK` | `0` | Whitespace allowed at the seams when merging a cross-turn excerpt. |
