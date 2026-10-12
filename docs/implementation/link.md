# Link

Stage 2: find evidence for each in-scope claim. Code: `backend/src/iaudit_backend/link/`.

**Audience:** maintainers and coding agents.

## Choosing what the model sees

`build_link_context` picks a mode once per request from the estimated transcript size (`link_mode`, `link_whole_max_tokens`):

- **Whole.** The model sees the full transcript. Its prompt prefix is identical across claims.
- **Shortlist.** Code selects turns first (`shortlist.py`): a keyword ranking (BM25 over stemmed tokens, with a short reply carrying the question it answers), plus neighbours (the question for a reply, the replies for a question, a following correction), plus optional additions (a per-speaker floor, later corrections, rank fusion with fuzzy matching). Gaps of one turn are filled. An empty shortlist falls back to the whole transcript if it is small enough.

Retrieval is behind a `Retriever` protocol, and `shortlist_only` runs it with no model, so evaluation can measure recall.

## The call and its validation

One mid-tier call per claim returns evidence items: role, link type (quote, paraphrase, inference), verbatim segments, premises for inferences. `validate.py` checks every segment against the shown turns, snaps a question and its short reply together, derives an `answer_status` (endorsed, question only, non answer, n/a) from the prep acts, and drops invalid items. If every item is rejected, one semantic retry resends with an error summary of kinds and counts, never text.

A stalled link (timeout, unavailable, bad output, all dropped) is returned as a stalled `LinkResult`, not raised.
