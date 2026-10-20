# eval-tofueval-20261020

Project C of 4: TofuEval dataset plug-in for the eval framework (sentence- and summary-level consistency, 1,777 summary items).

## Sub-projects
| Sub-project | PRD | Scope | Depends on | Status |
|---|---|---|---|---|
| C1 Data & items | [PRD](01-data-and-items/PRD.md) | Pinned download + hashes, 1,777 items, transcript-to-turns, assessment with verified sentence offsets, schema-valid requests | B2 (adapter protocol, download hook), B4 (Download button) | draft |
| C2 Projection & metrics | [PRD](02-projection-and-metrics/PRD.md) | Gold + claim-to-sentence projection, frozen `mapping.json` v1.0.0, metric aliases and slices, paper references, `item_row`, integrity block | C1, B3, B1 | draft |

Brief: [brainstorming.md](brainstorming.md).

## Dependency graph
```mermaid
graph LR
  B2 --> C1 --> C2
  B3 --> C2
```

## Locked decisions
- Item id `{dataset}--{doc_slug}--{topic_slug}--{model_slug}`; `request_id` set by the engine.
- No role/speaker/timestamp inference; MeetingBank blob split into <=60-word turns, frozen at `adapter_version`.
- `mapping.json` v1.0.0 is frozen; A1 leaves it untouched; any later change is a separately versioned decision.
- Unresolved sentences count wrong in primary, excluded in secondary; original-five and Model-Extra are never pooled (`pool_all: false`).
- `gold_kind` is `tofueval_summary_sentences`; gold text/`exp` are never persisted.
- Audit deadline 100 s (`config.py`) is canonical; ADR 0008 fixed in B2.
- C1 extends `backend/eval/leakage.toml` to scan root `eval/data` (`test_prompt_leakage` skips when data absent).
- A claim overlapping two summary sentences flags both (accepted).
- Backend computes no tokens/cost; `cost_usd` shown only if present. Concurrency 4 accepted.
- Saved 1.1.0 items do not open in the item view after the 1.2.0 contract bump (accepted).
- Test-run count is informational only; contamination tag is run-level via start-run `tags`.

## Open questions and risks (after reconciliation)
- [OPEN] Paper segment lengths (970/930) vs measured 778/752 words: token-count explanation untested (C1).
- [OPEN] MediaSum `ccdv/mediasum` vs original `news_dialogue.json` equality (C1).
- [OPEN] Generic MediaSum speaker labels ("Unidentified Male") pass through (C1).
- [OPEN] Max item-id length after slugging not yet measured against the 128 limit (C1).
- [OPEN] Add `concern_match_given_detected`? `exp` persistence assumed on-demand only (C2).
- [DEFERRED] Long transcripts may still hit the 100 s deadline; checked by the first 5-item pilot run (C1).
- [DEFERRED] MeetingBank source equality vs annotated text (owner, C1); `concern_not_in_mapping` evidence for a future mapping decision; wide per-type CIs (C2).

## Manual (owner) steps
- Verify MeetingBank (and spot-check MediaSum) source equality [DEFERRED]; review `manifest.json` after the first UI download and commit `expected_sha256`; accept MediaSum and MeetingBank licenses (C1); review the `leakage.toml` change (C1).
- Set `tags.contamination` per run via the start-run request; optionally eyeball Table 3 on PDF p.7 (C2).
