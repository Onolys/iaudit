# 0013. Recorded answers replay in tests; live evaluation is opt-in

**Audience:** contributors.

**Status:** accepted.

**Context.** Tests that call providers are slow, costly and unreliable.

**Decision.** Tests run offline against stubs and recorded answers. The evaluation harness replays recordings by default and calls providers only with `--live`, after printing a cost estimate.

**Alternatives.** Run live calls in CI.

**Consequences.** CI is deterministic and free. Recordings go stale when prompts change; the harness warns, and `--strict-fresh` fails.
