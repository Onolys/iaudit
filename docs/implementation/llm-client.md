# LLM client

Every model call goes through one interface. Code: `backend/src/iaudit_backend/llm/`.

**Audience:** maintainers and coding agents.

`LLMClient.complete_json(req, metrics)` takes an `LLMRequest` (tier, system text, user text, a pydantic `response_model`, a `call_tag`, optional cache prefixes, token cap, per-call timeout, fixture key, deadline, retry flag) and returns an `LLMResult` holding the parsed object, usage, latency, model and attempts.

## Tiers

`cheap`, `mid` and `strong` map to LiteLLM model ids in settings (`model_cheap`, `model_mid`, `model_strong`). Prompts name tiers only, never model ids. `strong` is for offline use.

## Implementations

| Class | Use |
|---|---|
| `LiteLLMClient` | Live calls. JSON-schema output, its own timeout and retry (LiteLLM's retries are off), a global concurrency semaphore. |
| `FixtureClient` | Replays recorded answers by key; raises `FixtureMiss` on an unknown key and never touches the network. |
| `RecordingClient` | Wraps a live client and writes fixtures (`IAUDIT_LLM_RECORD=1`, or the evaluation `--record`). |
| `StubClient` | Canned answers per call tag, for tests. |
| `FailingClient` | Always raises, for failure tests. |

`make_client(settings)` picks one from `llm_mode`.

## Errors

`LLMTimeout`, `LLMUnavailable` and `LLMBadOutput` (all `LLMError`). A transport retry happens at most `llm_max_retries` times, only if the request deadline leaves room, and never for errors retrying cannot fix (authentication, not found). A request with `retry=False` is tried once.

## Caching

`cache_prefix` (one) or `cache_prefixes` (up to two, each a cache breakpoint) become leading system blocks marked ephemeral; the stage's own `system` text follows. A fixture key includes `cache_prefixes` only when present, so older recordings keep their keys.

## Metrics

`MetricsCollector` is per request and holds no prompt or output text: only tags, tiers, model, unit (a section or claim id), token counts, latency, attempts, ok, error kind.
