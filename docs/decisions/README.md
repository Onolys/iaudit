# Decisions

Why is it like this? Architecture decision records.

**Audience:** contributors.

| ADR | Decision |
|---|---|
| [0001](0001-frontend-owns-the-contract.md) | The frontend owns the contract |
| [0002](0002-offsets-count-code-points.md) | Offsets count code points |
| [0003](0003-mock-matches-on-request-id.md) | Mock mode matches on `request_id` |
| [0004](0004-reject-bad-replies-flag-bad-spans.md) | Reject broken replies; flag bad spans |
| [0005](0005-models-propose-code-decides.md) | Models propose, code decides |
| [0006](0006-excerpts-not-offsets.md) | Models return verbatim excerpts; code computes offsets |
| [0007](0007-bm25-and-fuzzy-retrieval.md) | BM25 and fuzzy matching for retrieval, no embeddings |
| [0008](0008-synchronous-call-sixty-second-cap.md) | One synchronous call with a 100 second cap |
| [0009](0009-litellm-three-tiers.md) | LiteLLM with cheap, mid and strong tiers |
| [0010](0010-understatement-reuses-inflation-concern.md) | Understatement is reported under frequency or severity inflation |
| [0011](0011-role-optional-never-guessed.md) | Role is optional and never guessed |
| [0012](0012-failure-policy-no-empty-audit.md) | Stalled claims degrade; an audit with nothing usable fails |
| [0013](0013-recorded-replay-in-ci.md) | Recorded answers replay in tests; live evaluation is opt-in |
| [0014](0014-run-info-optional-one-shared-version.md) | `run_info` is optional; one shared contract version |
| [0015](0015-add-quantity-mismatch-widen-attribution-and-context-stripping.md) | Add `quantity_mismatch`; widen attribution and context stripping |
| [0016](0016-contract-reset-0-0-1-groups-optional-speaker-error-details.md) | Reset the contract; group concerns; allow missing speakers; detail errors |
