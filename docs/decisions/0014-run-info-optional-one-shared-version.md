# 0014. run_info is optional; one shared contract version

**Audience:** contributors.

**Status:** accepted.

**Context.** The evaluation needs to know which models and prompts produced a run, and the backend is the only place that knows. The contract has no field for it. All three schemas pin `schema_version`, and consumers must reject any other value, so a new field forces a coordinated bump.

**Decision.**
- Add an optional top-level `run_info` to the audit response: model ids per tier and a hash per prompt group. The backend emits it only for the `full` pipeline; `stub` omits it, because it would name models and prompts that were not used.
- Request, response and error schemas share one `schema_version`, now `1.1.0`. Producers send it and consumers reject anything else (`unsupported_version` in the backend, `wrong_version` in the frontend). Backend, frontend, validators, examples and docs move together.
- The backend does no token accounting or pricing. `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` and `cost_usd` are optional in the schema so consumers can show them when present. The backend never sets them and never sends fake zeros.
- A prompt hash is the first 16 hex chars of the sha256 of the prompt file bytes, the same as the `backend/eval` manifest, so eval and backend values compare directly.
- `run_info` holds ids, hashes and counts only, never transcript or assessment text.

**Alternatives.** Make `run_info` required. Bump only the response version. Accept both 1.0.0 and 1.1.0. Count tokens and compute cost in the backend. Full 64-char hashes or a `sha256:` prefix.

**Consequences.** Other producers and the stub stay valid without `run_info`. A 1.0.0 client gets a clear version error instead of a silent mismatch. Each later bump (for example the taxonomy change) repeats the coordinated move. Tokens and cost stay empty until some producer chooses to fill them.
