---
status: approved
summary: Add quantity_mismatch as mission check 13 (13th enum value, contract 1.2.0), widen wrong_attribution and context_stripping, add two labelling rules, amend the mission's score-arithmetic exclusion; everything justified from the mission, measured on TofuEval dev with mapping v1.0.0 untouched.
date: 2026-10-20
---
# PRD: A1 Taxonomy v1

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: B1 (contract 1.1.0, ADR 0014), B2-B4 (eval engine/metrics/API), C1-C2 (TofuEval baseline run, mapping.json v1.0.0), D1-D2 (eval UI used for the before/after) · Owns: `docs/mission.md`, `docs/contracts/{audit-response.schema.json,README.md,examples}`, `docs/decisions/0015-*.md`, `docs/concepts/{how-an-audit-decides,severity-and-frequency}.md`, `docs/examples/mock/*` (+ one new fixture), `backend/src/iaudit_backend/{models/audit.py,check/{models,synth,templates,verifier}.py,prompts/check_system.md,prompts/check_fewshot.json}`, `backend/eval/{leakage.toml,tests/*}` and backend tests, `frontend/src/{contract/types.ts,contract/validate.ts,claim-detail/concernLabels.ts}` + tests

## TL;DR
Add one concern, `quantity_mismatch` (mission check 13), appended as the 13th enum value so every eval bucket 1-12 and all ADHD gold stay put. Widen two definitions (`wrong_attribution` to person, source or entity; `context_stripping` to dropped qualifier or broadened scope) and add two labelling rules with no new type. Detection reuses the existing pattern: the verifier LLM **observes** a `quantity_mismatch` flag, code guards and decides. No new atomizer/linker work. The mission is amended so "numerical score calculations" means scoring rules, not figures the assessment states about interview facts. Contract goes to **1.2.0** in one coordinated change. Built last so the TofuEval dev run before/after is clean.

## Problem
- The 12 types came from the mission's examples. A wrong dose, count, amount or age changes what happened with no qualifier, direction or timing change, so checks 1-12 do not name it; it lands under generic `unsupported_claim` / `contradictory_evidence`, hiding the highest-stakes filterable class for a reviewer. [verified: no numeric/quantity concept in `check/models.py` FlagType or `models/audit.py` ConcernType]
- Two mission checks are already broader than their code definitions: check 8 (an omitted qualification that changes meaning) covers scope widening; check 3 ("who experienced or reported") applies equally to non-person owners (previous vs current medication, prior employer).
- The mission excludes "numerical score calculations", which can be misread as excluding any arithmetic. Needs one clarifying sentence before check 13 is defensible.
- Constraint (user): no edits made to move a benchmark score. TofuEval only revealed the gap; each change below is argued from mission and interview use (clinical, hiring, research).

## Goals / Non-Goals
**Goals**
- `quantity_mismatch` end to end: mission, contract, backend enum/prompt/synth/template, frontend label, fixtures, ADR 0015.
- Widened definitions and two labelling rules in prompt, templates, mission, concepts docs.
- ADHD harness green with gold for buckets 1-12 unchanged; bucket 13 covered separately.
- Everything the owner needs to record a before/after on TofuEval dev via the eval UI (owner manual run; agents run no live LLM calls or evals).

**Non-Goals**
- Verifying numbers against the real world; auditing scoring rules or rubric totals (mission exclusion stays); diagnosis, protocol review, new formats.
- New types for wrong entity, overgeneralization, wrong action; broadening `unsupported_causal_link`.
- Deterministic number extraction in the atomizer (see Decision 4) [DEFERRED].
- Any change to mapping.json, TofuEval projection, or the ADHD gold/spec.
- Tuning on the TofuEval test split; copying TofuEval text into prompts or fixtures.

## Requirements
1. **Enum.** `ConcernType.quantity_mismatch` appended last; contract schema enum, frontend `CONCERN_TYPES`, `CONCERN_LABELS` ("Quantity mismatch") updated in the same order.
2. **Detection.** Verifier may emit flag `quantity_mismatch` (keys = evidence items showing the different figure). Code accepts it only if (a) confidence floor P1, (b) the claim proposition contains a numeral, number word or amount token, (c) at least one cited item's cited turn text contains a numeral/number word. Otherwise suppressed and counted (`flags_suppressed`), like `has_causal_cue` for causal links. A figure the interview never gives stays `unsupported_claim`.
3. **Boundary.** How often / how bad / how long stays `frequency_severity_inflation`; dates and timing stay `timeframe_mismatch`; "about ten" to "exactly ten" is `certainty_inflation`. Faithful rounding, including dropping decimals ("$10.6B" written as "$10B"), is not a mismatch. One discrepancy yields one concern, never a stack.
4. **Verdict.** Figure differs while the behaviour is supported: `partially_supported`. If the verifier judges the item `contradicts` (the claim is only the figure): `contradicted`, with `quantity_mismatch` replacing generic `contradictory_evidence`. No amount-gap escalation in v1.
5. **Widened `wrong_attribution`** ("wrong person, source, or entity"): prompt/template/mission wording only; `experiencer` value `other_person` is kept as the field value and documented in the prompt as "another person or entity".
6. **Widened `context_stripping`** ("dropped qualifier or broadened scope"): prompt/template/mission wording; a group/setting/condition replaced by a wider one counts; faithful summarization does not.
7. **Labelling rules** (prompt + `docs/concepts`): changed action: `contradictory_evidence` if the interview states the actual action, else `unsupported_claim`; two true facts merged into an unstated relation: `unsupported_claim` (`unsupported_causal_link` only if cause and effect is asserted).
8. **Contract 1.2.0** in request, response, error schemas and every producer/consumer B1 moved to 1.1.0; old versions rejected as before.
9. **Mission amended** (wording below) with user approval before any code lands.
10. **Fixtures.** One new fictional full mock fixture exercising `quantity_mismatch` (also boundary cases); at least 10 fictional boundary pairs as tests (below).
11. **Eval.** Bucket 13 appears automatically (`CONCERNS` from enum, `gold.py:17`); ADHD oracle report keeps buckets `1,3,4,5,7,8,9,11,12` and no 13 [verified: `eval/tests/test_oracle.py:59`].

## Architecture

**Pipeline touch points** (checker flag to assembler concern)
```
verifier prompt  --flag quantity_mismatch(keys,conf)-->  verifier.apply_floors (P1 floor)
  --> synth.judge: guard (claim has number token AND cited turn text has number token) else suppress
  --> synth._FLAG_CONCERN: quantity_mismatch -> ConcernType.quantity_mismatch
  --> synth.dedup (_CHAIN) -> templates.concern_text -> ClaimDraft -> assembler (unchanged)
```
- `check/models.py`: add `"quantity_mismatch"` to `FlagType`. No change to `ItemObs`/`QuantityObs` (those carry frequency/severity only).
- `synth.judge`: extend the `cited` set with `quantity_mismatch` so a `not_addresses` item the flag rests on still counts as partial support (otherwise D6/D7 keep only `wrong_attribution`/`timeframe`, which would silently drop the concern).
- `synth._FLAG_CONCERN`: add the mapping. `flag_concerns` already uses the flag's keys.
- **Dedup order.** Make `_CHAIN` = wrong_attribution, negation_reversal, frequency_severity_inflation, **quantity_mismatch**, contradictory_evidence. Later entries are suppressed by earlier ones on shared keys. So: frequency wins over quantity on the same item (preserves ADHD behaviour exactly: a rate claim keeps today's label), quantity wins over generic contradiction. D4's `kept` filter (`type in _CHAIN`) then keeps it on contradicted claims automatically. `_ORDER` follows enum position, so it sorts last in output.
- `D5` precedence (conflicting accounts > correction ignored > generic contradiction) is unchanged; quantity stays alongside them if on different keys, which is correct.
- `templates.concern_text` (no numbers, no transcript text, same neutral vocabulary): "The claim states an amount, count or value that may differ from the supplied interview; a reviewer may wish to confirm the figure." Wording for `wrong_attribution` becomes "...the source, person or entity described may differ..."; `context_stripping` becomes "...includes a qualifier, reason or limit that the claim leaves out or broadens." `REVISABLE` gains `quantity_mismatch`; `vet_revision` already blocks timestamps and banned words.
- `prompts/check_system.md`: add flag definition (below), widen the `experiencer` and `context_stripping` lines, add the two labelling rules to Rules, and a rounding rule: ordinary rounding is not a mismatch, including dropping decimals ("$10.6B" as "$10B") and "about". Relation stays "ignore amount" so the item is judged on behaviour; the flag carries the figure.
- `prompts/check_fewshot.json`: add ~5 fictional examples (Jordan-style, outside scored speaker ids): quantity mismatch (team size), faithful rounding (no flag), rate claim that must NOT raise quantity (frequency stays), entity attribution (previous vs current medication), scope broadening plus one faithful generalization (no flag). Roughly +1.5-2k tokens in the cached stage block.
- Frontend: label, enum list, test "labels all 12 mission checks" becomes 13.

**Mission wording (draft, for user approval)**

| Place | Current | Proposed |
|---|---|---|
| Intro to table | "The following twelve checks define the scope" | "The following thirteen checks define the scope" |
| Check 3 name/what | "Wrong person or source attribution" / "Who experienced something, who reported it, and whether those sources are represented correctly." | "Wrong person, source, or entity attribution" / "Who or what experienced something, who reported it, and which person, source, or entity a fact belongs to." Example adds: "Side effects the patient attributed to a previous medication are recorded against the current one." |
| Check 8 what | "Whether an omitted qualification materially changes the meaning of a claim." | "Whether an omitted qualification, or a broadened scope, materially changes the meaning of a claim." Example adds: "'Some members of the panel raised concerns' becomes 'the panel raised concerns.'" |
| New row 13 | n/a | "**13. Quantity mismatch** / Whether an amount, count, value, or total the assessment states about the interview matches the interview: money, doses, ages, counts, tallies, and sums of figures the interview itself gives. / The patient reports taking 20 mg; the assessment records 10 mg." |
| Boundaries bullet | "Numerical score calculations." | "Numerical score calculations: scoring rules, rubric totals, and rating arithmetic. Figures the assessment states about what the interview contained (counts, totals, doses, amounts) are checked under check 13." |
| "How these checks should be interpreted" (new bullet) | n/a | "**A stated figure is a claim like any other.** The tool compares figures with what the interview gives. It does not judge whether a figure is clinically right, and ordinary rounding is not a discrepancy. A total is checked only against figures the interview supplies." |

`quantity_mismatch` flag definition (prompt): "the claim states an amount, count, value or total that differs from what the cited item gives. Not for how often, how bad or how long (frequency/severity), nor for dates or timing. A figure the transcript never gives is not this flag."

**Change surface** [verified: grep `frequency_severity_inflation`, `unsupported_causal_link`, `twelve`, `1-12`/`1–12`, `12 concern`/`12 checks`, `1.0.0`, excluding node_modules/agent_files]

| Area | Files |
|---|---|
| Mission | `docs/mission.md` (line 62 "twelve", table, boundaries) |
| Contract | `audit-response.schema.json` (enum + description line 231 "checks 1-12"; all 3 schemas' version const), `docs/contracts/README.md` (concern table, "order matches checks 1-12" line 126, versioning/version strings), `docs/contracts/examples/*` |
| Version strings (1.1.0 to 1.2.0) | wherever B1 moved them: `app.py` SUPPORTED_VERSION, `models/audit.py`, `api/errors.py`, `assembler/__init__.py`, `frontend/src/contract/{types,validate}.ts`, `docs/examples/mock/validate.py`, `backend/eval/adhd.py` + `data/adhd/requests/*.json`, mock/real requests and responses, tests |
| Backend | `models/audit.py` (docstring "checks 1-12"), `check/{models,synth,templates}.py`, `prompts/check_system.md`, `check_fewshot.json` |
| Docs referencing "12" | `docs/reference/review-ui.md:77`, `docs/testing/evaluation.md:5`, `docs/concepts/how-an-audit-decides.md:9`, `docs/examples/mock/README.md:22` ("all 12 concern types"), `docs/examples/real/{README,brainstorming}.md`, `backend/eval/README.md:4`, `frontend/src/contract/types.ts:13` comment |
| Concepts | `severity-and-frequency.md` boundary note; `how-an-audit-decides.md` (thirteen; a short quantity paragraph) |
| Not changed | `backend/eval/{score,gold,build_adhd}.py` logic (all bucket-derived from the enum; `len(CONCERNS)` bounds check auto-widens), ADHD `spec.json`/`gold`/`expected`, `docs/examples/real/*/expected.json` (historical key; its "12 checks" scope text is about the mapping at the time) |
| Hits left alone | ADR 0010 and other historical ADR text; text with "twelve" meaning age (ADHD transcripts) |

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | New type vs fold | Add `quantity_mismatch`, 13th enum value | Fold into `frequency_severity_inflation` or `contradictory_evidence` | A dose of 20 mg stated as 10 mg is not "more" or "worse"; folding hides a filterable high-stakes class |
| 2 | Enum position | Append last | Insert next to check 7 | Bucket = 1-based enum position (`gold.py:17`); appending keeps buckets 1-12 and all gold/expected stable |
| 3 | Arithmetic | Allowed; mission amended (table above) | Exclude arithmetic; keep wording | User decision. Sums of figures the interview gives are claims about interview facts; score/rubric arithmetic stays excluded |
| 4 | Detection path | LLM flag plus deterministic guards (number token in claim and in cited turn) | (b) Atomizer extracts typed numeric quantities, verifier extracts evidence values, code compares normalized numbers and units | (b) touches atomize prompt/models, `scales.py`, gold `quantities` slot, so ADHD atomization could shift; unit/word-number normalization is brittle ("a dozen", "10 mg" vs "0.01 g"). Flag path matches "LLM observes, code decides" and the precedent of `has_causal_cue`. (b) is a later upgrade if precision is poor |
| 5 | Dedup precedence | `_CHAIN`: ... frequency, quantity, contradictory | Quantity before frequency; outside the chain | Frequency first guarantees today's labels on rate claims; quantity before contradiction makes the specific label win. Unit tests pin both |
| 6 | Verdict mapping | partially_supported (or contradicted if verifier says `contradicts`); no escalation | Always contradicted | Mission: contradicted means explicit conflict; a changed figure on a supported behaviour is "altered". Revisit with data |
| 7 | Widenings | Wording only (prompt, template, mission); keep field value `other_person` | Rename `experiencer` value; new types | No schema or fixture churn for a naming nicety. Rename is [DEFERRED] |
| 8 | Labelling rules | Prompt/doc rules, no type, no TofuEval mapping | A TofuEval-shaped category | Taxonomy driven by mission, not benchmark |
| 9 | Contract version | 1.2.0 for all three schemas | Fold into 1.1.0; 1.0.0 silently | New allowed value is minor by the README's rule; B1 owns 1.1.0 and the shared-version rule |
| 10 | ADR | 0015 "Add quantity_mismatch; widen attribution and context stripping" (ADR 0014 is B1's) | None | ADR 0010 shows contract-visible choices get ADRs |
| 11 | mapping.json | **Leave v1.0.0 untouched** | Bump to v1.1.0 to allow `quantity_mismatch` for Reasoning Error/Contradiction | A mapping bump after seeing results is label drift (C integrity rule 1). Reasoning Error is recall-only already (any flag counts), so number errors that now carry the new label still count for recall. Mapped concern-match may fall where a number error moves from `contradictory_evidence` to `quantity_mismatch`; accepted by owner as a labelled known side effect (finer types can be combined later); the report states it, plus a separate count of `quantity_mismatch` outputs. No secondary mapping file |
| 12 | Measurement | TofuEval dev, same model/mapping/split, via eval UI (no CLI); baseline run before the first A1 commit. Owner runs all live passes manually; agents build only | Re-baseline after | Clean before/after; wording tuned on dev only; test split run once at the end |
| 13 | Fixture | New fictional mock `11-...` (medication/team size) plus boundary pairs as tests | Edit an existing mock | Existing mocks' offsets and ADHD gold stay untouched |

## Manual steps
- User approves the final mission wording (table above) before implementation starts; the mission wins on conflict. [DONE: mission wording approved by owner 2026-10-21]
- User records the TofuEval dev baseline (C/D tooling) before A1 prompt changes merge, and runs the after pass [baseline step waived by owner 2026-10-21]; test-split run once, only at the end.
- User runs the final end-to-end test (incl. saved-item replay) after all changes. Owner runs everything live manually; implementing agents run no live LLM calls, live evals, or TofuEval before/after.
- User confirms the 13-label ADR wording and ADR number if B1's changes.

## Risks / Open Questions
- [RESOLVED: dropping decimals is faithful rounding, not a mismatch (e.g. "$10.6B" as "$10B"); tweak later on dev only, owner decision 2026-10-20] Do not copy dev strings into prompts.
- [RESOLVED: B1 takes ADR 0014 and 1.1.0 as written (see `eval-core-20261020/01-contract-run-info/PRD.md`); this PRD uses ADR 0015 and 1.2.0] Re-check numbers at implementation only if B1 changes.
- [RESOLVED: B3 and C2 derive concerns from the schema enum / `mapping.json` (C2 R8 validates mapped concerns against the current enum); D1/D2 render no per-concern columns] Re-grep `eval/` and `frontend/src/eval/` at implementation for a hard-coded 12.
- [RESOLVED: `leakage.toml` will be extended to scan root `eval/data` incl. `eval/data/tofueval`, owned by eval-tofueval C1 (`eval-tofueval-20261020/01-data-and-items/PRD.md`), owner decision 2026-10-20] A1 still runs `test_prompt_leakage` on its new few-shot; fictional, must not echo TofuEval or the brief's sample examples.
- [RESOLVED: concern-match drop in Contradiction accepted as a labelled known side effect (Decision 11); no secondary mapping file; granular types can be combined later, owner decision 2026-10-20]
- [RESOLVED: 1.2.0 breaking item-view replay of saved 1.1.0 items (incl. pre-A1 baseline) accepted; owner does final test after all changes, owner decision 2026-10-20] Before/after metrics and compare are unaffected.
- User decisions recorded here: mission amended to allow arithmetic in `quantity_mismatch` (Decision 3); a version bump moves backend, frontend and validators together (Req 8).
- [RESOLVED: Decisions 5, 13] Double-labelling with frequency: pinned by chain order and 10 boundary pairs asserting exactly one of the two types; ADHD frequency fixtures must not change.
- [RESOLVED: recordings empty] Fixture-mode replay: recordings dir is empty (`backend/eval/recorded` README), so prompt edits break no recorded keys; re-check at implementation.
- [DEFERRED: owner measures in manual runs] Widened `wrong_attribution` may raise false positives on current-vs-previous items; widened `context_stripping` may over-fire on legitimate summarization. Mitigation: clean few-shot cases, ADHD bucket 3 and 8 precision compared before/after by the owner in their own runs.
- [DEFERRED: owner measures in manual runs; checks p95 latency] Prompt growth vs the audit deadline: 100 s (`config.py` `audit_deadline_s`) is canonical; ADR 0008 is corrected in eval-core B2 (owner decision 2026-10-20). Compare p95 latency on the ADHD set against 100 s; prompt token count only if available (backend does not compute tokens/cost).
- [DEFERRED] Deterministic numeric comparison in code (Decision 4 alt b); rename `other_person`; broaden `unsupported_causal_link`; evidence-based escalation to contradicted.
- [RESOLVED: mission wording approved and TofuEval dev baseline step waived, owner decision 2026-10-21]
- Labelled evidence caveat: the 13-of-84 residue behind the brief is LLM-judged, not gold; a recall change is evidence about the implementation, not proof the taxonomy is right.

## Acceptance Criteria
- Mission edited exactly as approved; AGENTS.md rule met: contract lists mirror mission, `schema_version` bumped.
- `grep` for `"1.1.0"` contract strings over docs/contracts, docs/examples, backend/src, backend/eval, frontend/src finds none (ADR text excepted); all three schemas, mock `validate.py`, backend and frontend reject any other version.
- Schema enum has 13 values with `quantity_mismatch` last; Python `ConcernType`, TS `CONCERN_TYPES`, and `CONCERN_LABELS` match; label test passes for 13.
- Unit tests: `decide()` with a quantity flag yields D8 (entails) or D4 (contradicts) with `quantity_mismatch`; frequency and quantity on the same key yield only frequency; quantity and contradictory on the same key yield only quantity; flag suppressed when claim or cited turn lacks a number token; `not_addresses` + flag keeps the concern; template contains no digits or banned words.
- 10 fictional boundary pairs (rate vs count, date vs count, "about ten" vs "ten", rounding incl. dropped decimals, sum, unstated figure, attribution to previous medication, scope broadening, faithful generalization, merged facts) with scripted verifier outputs pass in CI; same pairs in a live run are an owner manual check (reported, not gated; agents do not run them).
- New mock fixture passes `docs/examples/mock/validate.py` and contains a `quantity_mismatch` concern; mock README counts updated to 13.
- `test_prompt_leakage` passes with new few-shot; no TofuEval or brief-sample text in prompts.
- ADHD: `uv run pytest`, `ruff check`, `python -m eval.run --mode oracle --gate poc` green; gold for buckets 1-12 byte-identical; oracle buckets unchanged; frontend `npm run typecheck` and `npm test` pass.
- ADR 0015 plus `docs/decisions/README.md` line added in the same commit as the schema.
- Owner manual check (agents do not run live): TofuEval dev before/after recorded in the eval UI under mapping v1.0.0 (same models/prompts hashes except the A1 change), reporting per-group recall, the `quantity_mismatch` count, and the concern-match caveat.
