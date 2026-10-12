# 0006. Models return verbatim excerpts; code computes offsets

**Audience:** contributors.

**Status:** accepted.

**Context.** Models miscount characters, and an offset that is off by one highlights the wrong text.

**Decision.** A model returns the exact text it relies on. The assembler locates it (exact, then normalised, then fuzzy) and computes code-point offsets. An excerpt that cannot be located is dropped.

**Alternatives.** Ask the model for offsets and verify them.

**Consequences.** Highlights are always real positions in the input. Some valid evidence is lost when the model paraphrases instead of copying; link and atomize validate for this.
