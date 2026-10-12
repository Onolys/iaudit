# 0007. BM25 and fuzzy matching for retrieval, no embeddings

**Audience:** contributors.

**Status:** accepted.

**Context.** Link needs to shortlist turns for long transcripts. Embeddings would add a heavy dependency.

**Decision.** Keyword ranking (BM25 over stemmed tokens) plus neighbours of each hit, with optional rank fusion against fuzzy matching. No embedding or NLP model dependency.

**Alternatives.** Embedding retrieval now.

**Consequences.** The default environment stays small. Embeddings are worth adding only if linked-mode recall improves F1 by 0.05 or more at acceptable cost, which the evaluation harness can measure.
