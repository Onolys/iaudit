# 0009. LiteLLM with cheap, mid and strong tiers

**Audience:** contributors.

**Status:** accepted.

**Context.** Stages need different model sizes, and providers change.

**Decision.** All calls go through one client over LiteLLM. Stages ask for a tier; settings map tiers to model ids. `strong` is for offline use.

**Alternatives.** Call one provider's SDK directly.

**Consequences.** Swapping a model is a setting. Prompts must not name model ids, and cache behaviour has to be confirmed on a live run.
