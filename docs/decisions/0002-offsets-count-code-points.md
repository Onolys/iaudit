# 0002. Offsets count code points

**Audience:** contributors.

**Status:** accepted.

**Context.** JavaScript strings count UTF-16 units; Python counts code points. An emoji would shift every later highlight.

**Decision.** All character offsets count Unicode code points. The UI slices with `Array.from(text)`.

**Consequences.** Highlights match on both sides. Slicing is slower on very long text, which is acceptable at this size.
