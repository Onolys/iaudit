---
status: approved
summary: Taxonomy v2 detection - add opinion_as_fact, calculation_error, meaning_shift, unsupported_inference; narrow certainty_inflation/quantity_mismatch/context_stripping; code-gated verifier flags; TofuEval mapping.json rewritten as a refinement (NMS and RE become concern-scored); mission rewritten to 17 checks in 4 groups.
date: 2026-10-28
---
# PRD: SP03 Taxonomy v2 (backend detection, eval mapping, mission)

Repo/branch: iaudit / `feat/eaudit-v0` · Depends on: SP01 (rename `backend/` to `eaudit/`, package `eaudit`; datasets to `eval/datasets/eaudit/{tofueval,synthetic}`), SP02 (17-type enum, `concerns[].group`, schemas `0.0.1`) · Owns: `docs/mission.md`, `eaudit/src/eaudit/check/{models,synth,templates}.py`, `eaudit/src/eaudit/prompts/check_system.md`, `check_fewshot.json`, `eaudit/src/eaudit/atomize` (prompt wording only, if needed), `eval/datasets/eaudit/tofueval/{mapping.json,mapping.py}`, `eval/datasets/eaudit/synthetic/adapter.py`, backend + eval tests, `eval/leakage.toml` (only if needed). Paths are post-rename.

## TL;DR
Four new concern types, three narrowed. Same pattern as `quantity_mismatch` (taxonomy v1): the verifier **observes** (a flag, or a failed inference step), code **gates and decides**, fixed templates explain. Every type maps to at most one TofuEval label, so TofuEval's 7 labels are recoverable by merging ours; `mapping.json` is rewritten from that crosswalk and NMS and RE are now concern-scored. Mission becomes 17 checks in 4 groups. Prompt changes invalidate recorded fixtures; re-recording is an owner step. TofuEval baseline/after runs are [DEFERRED: owner runs TofuEval later, outside this initiative]; no merge is gated on them.

## Problem
- TofuEval's labels split our coarse types badly: "believes X" stated as fact, wrong sums, near-synonym swaps ("recommended" to "ordered") and joined-true-facts have no home. Today they are steered by two labelling rules into `unsupported_claim` / `contradictory_evidence` [verified: `docs/concepts/how-an-audit-decides.md:36-37`, `check_system.md` Rules "Changed action", "Merged facts"].
- `certainty_inflation` (mission 6) mixes "hedge dropped" with "secondhand becomes fact"; `quantity_mismatch` (13) mixes wrong figure with wrong sum; `context_stripping` (8) mixes dropped qualifier with broadened scope. Mixed types cannot map to one TofuEval label.
- `mapping.json` has NMS and RE as recall-only and maps "Opinion as Fact" to `certainty_inflation`/`wrong_attribution`, which is a stretch [verified: mapping.json v1.0.0].

## Goals / Non-Goals
**Goals**
- Detection for the 4 new types with deterministic gates; narrowed definitions of 3 types; REVISABLE decision; explanation templates.
- Superset property: each of our 17 types maps to at most one TofuEval label (table below).
- `mapping.json` rewritten; mission rewritten (17 checks, definitions, examples, 4 groups); labelling rules removed.
- Synthetic fictional cases per new type. (TofuEval before/after runs: [DEFERRED: owner runs TofuEval later, outside this initiative].)

**Non-Goals**
- Contract/enum/`group` field/UI (SP02); concept/research/groups docs (SP04); rename/retry/model (SP01).
- Scoring `quantity_mismatch`, `frequency_severity_inflation`, `context_stripping` against TofuEval (uncertain, deferred by owner).
- Deterministic arithmetic or numeric extraction in code [DEFERRED].
- TofuEval baseline or before/after runs [DEFERRED: owner runs TofuEval later, outside this initiative].
- Versioning machinery. **Rule: every schema is `0.0.1`; project not deployed; no legacy or back-compat code, no version history, no migration; non-conforming files just error.**

## Requirements
1. **Definitions** (mission, prompt, templates agree):

| Type (group) | Definition | TofuEval |
|---|---|---|
| opinion_as_fact (Changed detail) | a belief, opinion or reported view stated as fact: "mother believes the pills cause headaches" to "the pills cause headaches" | OF |
| calculation_error (Changed detail) | wrong total or arithmetic from figures the interview gives: "missed two in March and one in April" to "missed five" | RE |
| meaning_shift (Changed detail) | a word or action swapped for one with a different meaning: "recommended physio" to "ordered physio"; "announced" to "approved" | NMS |
| unsupported_inference (Not in interview) | an unstated relation joining two individually true facts, or an overgeneralization: "some panel members" to "the panel" | RE |
| certainty_inflation (narrowed) | hedge dropped only: "I think twice" to "twice" | TAM |
| quantity_mismatch (narrowed) | wrong value only: 20 mg to 10 mg; totals move to calculation_error | none (unscored) |
| context_stripping (narrowed) | dropped qualifier or condition only; broadened scope moves to unsupported_inference | none (unscored) |

2. **Groups** (SP02 implements; this map is the single source, SP02/SP04 copy it exactly and cross-reference these requirement numbers): Not in interview = unsupported_claim, unsupported_causal_link, question_as_answer, unsupported_inference. Opposite of interview = contradictory_evidence, negation_reversal. Changed detail = wrong_attribution, timeframe_mismatch, quantity_mismatch, frequency_severity_inflation, certainty_inflation, opinion_as_fact, calculation_error, meaning_shift. Missing context = context_stripping, correction_ignored, conflicting_accounts_flattened.
3. **Detection** per Architecture. Model never decides verdict or explanation.
4. **Labelling rules removed** ("changed action", "two true facts joined") from `check_system.md` and from `how-an-audit-decides.md` (the doc edit itself is SP04; SP03 states the removal and replacement semantics).
5. **Mission**: 17 checks numbered in enum order (14 opinion_as_fact, 15 calculation_error, 16 meaning_shift, 17 unsupported_inference, appended; this order is the single source: SP02's enum and SP04's docs copy it exactly), each with definition + example, a 4-group section, check 6/8/13 narrowed, "Reported explanations and assessor inferences are different" principle linked to check 14, "Numerical score calculations" boundary bullet kept (scoring rules only) with totals of interview figures under check 15.
6. **Mapping** rewritten (below); `mapping_version` `"0.0.1"`.
7. **Templates**: fixed text per new type, neutral vocabulary, no digits, no transcript text, banned-words rule unchanged.

## Architecture
**Detection** (all follow `flag -> synth.judge gate -> _FLAG_CONCERN -> dedup -> template`)

| Type | Path | Code gate (suppressed and counted `flags_suppressed` if it fails) |
|---|---|---|
| opinion_as_fact | verifier flag, keys = items where the view is someone's belief | conf floor P1; claim not `hedged`; every `claim.reported_by.source` in {assessor, unspecified} (a claim that already names the believer is faithful); for causal links, `CausalLink.source == "assessor"` in the atomize output when a link covers the claim [verified: `atomize/models.py` CausalLink.source] |
| calculation_error | verifier flag, keys = the addend items | claim has a number token (`has_number_token`) AND the cited turns carry at least two number tokens in total (reuse `_quantity_flag_grounded` extended); single differing figure stays quantity_mismatch |
| meaning_shift | verifier flag, keys = item stating the original word or action | keys non-empty and known; conf floor P1. No item stating the original means `unsupported_claim`, not this |
| unsupported_inference | (a) code-derived: a link inference group with `step_acceptable=false` while all premises entail (today demoted, then labelled `unsupported_claim` at D6/D7 via `inf_keys`) [verified: synth.py `resolve_inferences`, D6/D7 branch]; (b) verifier flag for scope broadening | flag: items entail the narrower claim; if `has_causal_cue(claim)` the causal flag is preferred |

- `check/models.py`: `FlagType` += `opinion_as_fact`, `calculation_error`, `meaning_shift`, `unsupported_inference`. `ItemObs` unchanged.
- `synth._FLAG_CONCERN` += 4 mappings; the `cited` set in `judge` includes the four, so a `not_addresses` item the flag rests on still counts as partial support (v1 lesson). D6/D7 `inf_keys` concern becomes `unsupported_inference`, not `unsupported_claim`.
- **Dedup `_CHAIN`** (earlier suppresses later on shared keys): wrong_attribution, negation_reversal, frequency_severity_inflation, quantity_mismatch, **meaning_shift**, contradictory_evidence. So a swapped action on a contradicting item shows `meaning_shift`, not generic contradiction (D4 `kept` filter keeps chain types). Yields: `opinion_as_fact` suppresses `certainty_inflation`, `unsupported_causal_link`, `unsupported_inference` on shared keys; `unsupported_causal_link` suppresses `unsupported_inference`; `calculation_error` suppresses `quantity_mismatch` on shared keys; existing `_QUANTITY_YIELDS_TO` kept. `_ORDER` follows enum order.
- **Verdict**: all four are Changed-detail or inference-style discrepancies on supported content: `partially_supported` (D8), `contradicted` (D4) only when the verifier's `relation` is `contradicts` (meaning_shift, calculation_error with a single-claim figure). unsupported_inference as a failed inference at D6/D7 stays `insufficient_evidence`.
- **Prompt** (`check_system.md`): four flag definitions with boundaries (certainty = a speaker's own hedge dropped; opinion = someone's view about the world stated as fact; calculation vs quantity; meaning_shift vs negation vs wrong_attribution); delete the two labelling rules; `context_stripping` line loses "or replaces narrower with wider"; `certainty_inflation` line loses secondhand. Few-shot (also the mitigation for the opinion_as_fact vs certainty_inflation boundary): ~8 fictional examples (one positive + one faithful negative per new type, e.g. a faithful sum, a faithful paraphrase), outside TofuEval vocabulary (leakage test).
- **Templates** (fixed, neutral): opinion_as_fact "The related passage gives this as someone's view or belief, but the claim states it as fact"; calculation_error "The total or result the claim states may differ from the figures the supplied interview gives; a reviewer may wish to confirm the calculation"; meaning_shift "The claim uses a word or action whose meaning may differ from what the related passage describes; a reviewer may wish to confirm"; unsupported_inference "The claim links facts, or generalizes beyond them, in a way the supplied interview does not establish". Narrowed templates: certainty/quantity/context_stripping wording trimmed to match.
- **REVISABLE** = existing set + opinion_as_fact, meaning_shift, unsupported_inference (a revision restating the view as attributed, using the source's word, or narrowing is checkable by `vet_revision` filters and a human). **calculation_error excluded**: code cannot verify the model's arithmetic in the revision.

**Eval mapping** (`eval/datasets/eaudit/tofueval/mapping.json`, replaced in place):

| TofuEval label | allowed | Notes |
|---|---|---|
| Extrinsic Information | unsupported_claim, question_as_answer | |
| Mis-Referencing | wrong_attribution | `datasets: [mediasum]` kept (MeetingBank has no speaker labels) |
| Stating Opinion as Fact | opinion_as_fact | meetingbank override removed |
| Tense/Modality | timeframe_mismatch, certainty_inflation | |
| Contradiction | contradictory_evidence, negation_reversal | |
| Reasoning Error | unsupported_causal_link, calculation_error, unsupported_inference | no longer recall-only |
| Nuanced Meaning Shift | meaning_shift | no longer recall-only |

Unscored (no allowed set contains them; counted under `concern_not_in_mapping`): quantity_mismatch, frequency_severity_inflation, context_stripping (deferred), correction_ignored, conflicting_accounts_flattened (no TofuEval equivalent). `mapping_version` stays because compare/integrity code requires the string [verified: `compare.py:69`, `tofueval/integrity.py:30`]; reset to `"0.0.1"`. Delete the `mapping_history` clause in `mapping.py` docstring (no version history). Semantics unchanged: any predicted concern in the allowed set matches.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Flag vs derived | Flags for opinion_as_fact, calculation_error, meaning_shift, scope broadening; derived from failed inference for the joined-facts case | Per-item `stance` observation for opinion; code recomputes sums | Matches `quantity_mismatch` precedent; recompute needs numeric extraction (v1 Decision 4 alt b, [DEFERRED]); failed inference already exists in link/check |
| 2 | Opinion gate | Claim unhedged, reporter assessor/unspecified | Gate on item certainty | The faithful case is a claim that names the believer; item hedging belongs to certainty_inflation |
| 3 | Dedup of specific over generic | Chain + yields above | Stack concerns | "One discrepancy, one concern" (v1) |
| 4 | NMS and RE scored | Both concern-scored, all datasets | Keep recall-only | Types now exist; recall-only was a stopgap. Cost: RE/NMS concern-match will start low; reported, not tuned on test |
| 5 | Left-out types | quantity_mismatch, frequency_severity_inflation, context_stripping unmapped | Map to RE/EI/NMS | Owner: uncertain; map only on dev evidence |
| 6 | Mapping history | Replace in place, version `0.0.1` | Keep v1.0.0 + bump | Versioning rule above; eval code needs the string |
| 7 | REVISABLE | Add 3, exclude calculation_error | Add all / none | Arithmetic not verifiable in code |
| 8 | Labelling rules | Removed; semantics by types | Keep as fallback | They contradict the new types |
| 9 | Mission numbering | Append 14-17 in enum order | Regroup numbering by group | Contract lists mirror mission; keeps ADHD buckets 1-13 stable |
| 10 | calculation_error verdict | Same as other Changed-detail types | Always contradicted | Mission: contradicted = explicit conflict |

## Manual steps
- Owner: approve mission wording (17 checks, 4 groups) before code lands.
- Owner (needs API keys): re-record fixtures; prompt hash changes invalidate recordings (ADR 0013 `--strict-fresh`) [verified: `docs/decisions/0013`]. Agents run no live calls.
- [DEFERRED: owner runs TofuEval later, outside this initiative] Any TofuEval baseline/before/after/test runs. Not a merge gate. When run later, integrity rules apply (mapping frozen before test runs, tuning on dev only, no TofuEval text in prompts).
- Group map and enum order: single source is Requirements 2 and 5 here; SP02 and SP04 copy them (verified consistent at approval).

## Risks / Open Questions
- [RESOLVED: if the owner later runs baseline and after, they use different mappings; compare binary and per-type recall and flag counts only, concern-match is not comparable and the report says so]
- [RESOLVED: SP03 Requirements 2 and 5 are the single source; SP02 and SP04 copy exactly and cross-reference them] Enum order 14-17 and group map.
- [RESOLVED: check ADHD/oracle gold for bucket-1-via-inference cases and regenerate if affected; part of SP03 tasks] Failed-inference relabelling (`unsupported_claim` to `unsupported_inference`).
- [RESOLVED: mitigate with fictional few-shot examples; measurement deferred to owner (with TofuEval, outside this initiative)] opinion_as_fact vs certainty_inflation boundary.
- [RESOLVED: check `atomize_system.md`; tweak if needed so "mother believes X" yields `reported_by` of the believer (prompt hash changes then; fixtures re-recorded by owner)] Atomizer prompt.
- [DEFERRED] Mapping quantity_mismatch/frequency_severity_inflation/context_stripping; code-side arithmetic recompute; removing `recall_only` support from `mapping.py` (unused but harmless).
- Risk: more flags, more false positives; precision measured by owner later (deferred). Prompt growth (~+2k cached tokens) vs 100 s deadline: compare p95.

## Acceptance Criteria
- Mission has 17 checks with definitions and examples, 4 groups; checks 6, 8, 13 narrowed; mission, `ConcernType`, schema enum, group map agree.
- Unit tests (scripted verifier output): each new flag yields the type, correct verdict and role; each gate suppresses (hedged or attributed claim for opinion; one-figure claim for calculation; no keys for meaning_shift); dedup yields pinned (opinion over certainty/causal/inference, causal over inference, calculation over quantity, meaning_shift over contradictory); failed inference yields `unsupported_inference`; `REVISABLE` excludes calculation_error; templates contain no digits or banned words.
- Failed-inference relabelling checked against ADHD/oracle gold; gold regenerated if affected. `atomize_system.md` checked; tweaked only if needed.
- Synthetic eval: per new type at least 2 fictional flagged items and 1 faithful near-miss in `eval/datasets/eaudit/synthetic` plus backend boundary pairs; zero-spend CI green; no TofuEval or brief text (`test_prompt_leakage`).
- Mapping: validates against the enum; every mapped concern exists; each of our types appears in at most one TofuEval row; mapping tests updated (NMS and RE no longer recall-only); `mapping_version` `0.0.1`.
- No remnant of the two labelling rules in prompts; no `mapping_history`.
- `uv run pytest`, `ruff check`, frontend typecheck/tests green after SP02 sync.
- [DEFERRED: owner runs TofuEval later, outside this initiative] TofuEval before/after report. Not an acceptance gate.
