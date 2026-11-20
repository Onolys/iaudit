# LLM client

Every model call goes through one interface. Code: `engines/core/src/onolys_core/llm/`.

**Audience:** maintainers and coding agents.

`LLMClient.complete_json(req, metrics)` takes an `LLMRequest` (tier, system text, user text, a pydantic `response_model`, a `call_tag`, optional cache prefixes, token cap, per-call timeout, fixture key, deadline, retry flag) and returns an `LLMResult` holding the parsed object, usage, latency, model and attempts.

## Tiers and routes

`LLMRequest.tier` names a **route**. Routes come from the registry in `llm/routes.py`, not from per-tier settings. Prompts name routes only, never model ids. The original tiers `cheap`, `mid` and `strong` are route names (so fixture keys are unchanged); `strong` is for offline use.

## Routes

Model choice is data. The registry loads `llm/routes.default.yaml`, or the file named by env `ROUTES_FILE`. Each route entry holds:

- `litellm_id`, `api_key_env` (the variable name, never the key).
- `structured_output_mode` (`json_object` or `json_schema`), `caching_mode` (`none`, `provider_implicit`, `anthropic_ephemeral`), `supports_temperature`, `extra_params`.
- `max_output_tokens`, `context_tokens`, `timeout_s` (a larger request value is clamped), `max_concurrency` (semaphore per route), `max_retries`, `backoff_s`.

A route may be an alias (`paudit_code: {alias: mid}`). A `presets:` section bundles route overrides plus an STT key; env `DEFAULT_PRESET` picks one (default `default`). Env overrides for the three tier ids keep older deploys working. Startup fails with an error naming the variable when a route's `api_key_env` is unset. The default routes are Claude Sonnet via the Anthropic API; adding Gemini or another provider is a YAML entry, not code. A live check of the shipped routes: `python -m onolys_core.llm.smoke --preset default`. Rationale: [ADR 0017](../decisions/0017-workspace-routes-shared-core.md).

## Implementations

| Class | Use |
|---|---|
| `LiteLLMClient` | Live calls. JSON-schema output, its own timeout and retry (LiteLLM's retries are off), a global concurrency semaphore. |
| `FixtureClient` | Replays recorded answers by key; raises `FixtureMiss` on an unknown key and never touches the network. |
| `RecordingClient` | Wraps a live client and writes fixtures (`IAUDIT_LLM_RECORD=1`, or the evaluation `--record`). |
| `StubClient` | Canned answers per call tag, for tests. |
| `FailingClient` | Always raises, for failure tests. |

`make_client(settings.llm_config())` picks one from `llm_mode`. `warm_then_fanout()` (`llm/warm.py`) sends one call first so a prompt cache entry exists before parallel calls.

## Errors

`LLMTimeout`, `LLMUnavailable`, `LLMRateLimited` and `LLMBadOutput` (all `LLMError`). A 429 or 529 raises `LLMRateLimited`; it backs off at least `retry-after` inside the deadline rather than consuming retries. A transport retry happens at most `llm_max_retries` times, only if the request deadline leaves room, and never for errors retrying cannot fix (authentication, not found). A request with `retry=False` is tried once.

## Caching

`cache_prefix` (one) or `cache_prefixes` (up to two, each a cache breakpoint) become leading system blocks marked ephemeral; the stage's own `system` text follows. A fixture key includes `cache_prefixes` only when present, so older recordings keep their keys.

## Metrics

`MetricsCollector` is per request and holds no prompt or output text: only tags, tiers, model, unit (a section or claim id), token counts, latency, attempts, ok, error kind.
