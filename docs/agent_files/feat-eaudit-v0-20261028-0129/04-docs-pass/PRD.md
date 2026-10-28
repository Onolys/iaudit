---
status: approved
summary: Docs pass after SP01-03 - fix names and versions, add Mermaid flowcharts, an Eval architecture section, four new concept/research pages (eval, research, concerns and groups, rewritten how-an-audit-decides), richer contracts README, plain-language stage and frontend deep dives.
date: 2026-10-28
---
# PRD: SP04 Docs pass

Repo/branch: iaudit / `feat/eaudit-v0` · Depends on: SP01 (rename, utils, retry, Haiku 5.5), SP02 (contract 0.0.1, `group`, 17 types, optional speaker, new error body), SP03 (taxonomy v2, mission 17 checks) · Owns: `docs/**` except `docs/agent_files/**` and ADR narrative (see Architecture); code untouched.

## TL;DR
Docs-only pass, run after code lands. Describe the system as it is now (eaudit, 17 types, 4 groups, 0.0.1) with no version history. Keep the plain tone owners like. Add what is missing: eval concepts, research provenance, concerns/groups with many examples, one running example through every stage, "who decides what" and "what the model outputs" tables, simple Mermaid flowcharts. Verify every behaviour claim against code, not memory.

**Contract-versioning rule (whole initiative): all schemas are `"0.0.1"`; the project is not deployed; no legacy/back-compat code, version history or migration; a non-conforming file just shows a validation error and the owner deletes it.**

**Taxonomy source of truth: SP03 PRD.** Copy exactly: 17 types in enum order (13 existing, then 14 opinion_as_fact, 15 calculation_error, 16 meaning_shift, 17 unsupported_inference; SP03 Requirement 5), the group map (SP03 Requirement 2, also SP02 R3), definitions incl. narrowed certainty_inflation (hedge dropped only), quantity_mismatch (wrong value only) and context_stripping (dropped qualifier only) (SP03 Requirement 1), and the TofuEval crosswalk (SP03 Eval mapping table; unscored: quantity_mismatch, frequency_severity_inflation, context_stripping, correction_ignored, conflicting_accounts_flattened). The two old labelling rules are gone; docs must not mention them as current behaviour. Where this PRD's text differs, SP03 wins.

## Problem
- `how-an-audit-decides.md` says "a second model call"; there are 3 (atomize per section, link per claim, check per claim). [verified: pipeline docs + `atomize/models.py`, `link/models.py`, `check/models.py`]
- Owner finds the model-vs-code split and response-field derivation confusing; no single place says who computes each field.
- Eval (datasets, projection, metrics, splits, integrity rules) is described only in `testing/evaluation.md`, `eval/README.md`, `reference/eval-*.md`, `implementation/eval-server.md`; `architecture.md` has no Eval section; no concepts page.
- Research basis (FRANK, Tang 2022, TofuEval, AggreFact, SummaC, DiaSumFact, PriMock57, WiCE) lives only in `agent_files/` brainstorms.
- Concern knowledge is split across how-an-audit-decides, severity-and-frequency, contract README; only some types have examples.
- Contract README lacks types, nested-field layout, span shape, concern/group tables, model-tier and `prompt_hashes` explanation. Stale: "Audit contract 1.2.0", Versioning/Version history, `backend/` paths, "Mission check 13" numbering.
- Jargon unexplained (BM25, fuzzy, tokenize, D0-D9, group-a, confidence floors, copycheck, boundary repair). An external DeepWiki summary misread "dialogue-assessment pairing" (really question-to-answer pairing in prep) and "synthetic decision functions" (really `check/synth.py`).

## Goals / Non-Goals
**Goals:** requirements D1-D10 below, each independently checkable.
**Non-Goals:** code, schema or prompt changes; editing `docs/agent_files/**` or ADR history; new ADRs for decisions SP01-03 own (they write theirs); deploy/ops docs; making complex diagrams (note "could be an artifact later").

## Requirements
**Rule 0 - Versioning.** All schemas are `0.0.1`; not deployed; no legacy, back-compat or version history; a non-conforming file errors and is deleted. State this once (contracts README intro). Remove every "1.0.0/1.1.0/1.2.0", "Version history", "added in", "formerly" mention outside `agent_files/`. ADRs keep decisions but drop version-bump wording (SP02 already edits 0011/0014/0015).
**D1 Mermaid.** Basic `flowchart` only, GitHub-renderable, <=10 nodes: pipeline stages; request flow (`POST /v1/audit` steps); eval flow; frontend flow; decision table if it stays simple (else a table + "artifact later" note).
**D2 `architecture.md`.** Backend section gets one running example per stage (same example as D6, 3-5 lines each: input, output). New "Eval" section: datasets, adapter, engine, metrics, eval API, Eval UI, with flowchart and links.
**D3 `concepts/eval.md` (new).** How eval works: datasets (TofuEval, synthetic/ADHD), projection (our concerns/verdicts mapped to their labels), metrics, dev/test splits, scientific-integrity rules (no tuning on test, no copying dataset text into prompts/fixtures, no edits to move a score, mapping frozen before runs), what each dataset can/cannot test. Audit all docs for eval gaps; fix or link.
**D4 `concepts/research.md` (new).** Sources and what we took from each; how checks were chosen (owner-written mission, adapted to interviews: who said it, question vs answer, corrections, disagreement); superset mapping table per TofuEval label to our types (from INVESTIGATION.md, taxonomy docs, SP03); PriMock57 (incorrect = union of our types; omission out of scope; completeness check parked as future); WiCE (supported to supported, partially_supported to partially, contradicted+insufficient to not supported; evidence-sentence overlap). Honest about limits.
**D5 `concepts/concerns-and-groups.md` (new).**
- Verdict (one per claim, overall answer) vs concern (zero or more per claim, what is off) vs group (family of concerns).
- 4 groups (map = SP03 Requirement 2; SP02 R3 implements): Not in interview / Opposite of interview / Changed detail / Missing context; each with meaning and boundary.
- Every one of 17 types (definitions per SP03 Requirement 1 and the existing 13 from the mission; same order as SP03 Requirement 5): definition, short interview+claim example, verdict it usually gives, near-miss (what it is not).
- Absorbs quantity-mismatch and labelling-rule content from how-an-audit-decides, and `severity-and-frequency.md` (buckets, inflates/understates, boundaries). **severity-and-frequency.md is merged in and deleted**; links fixed.
- Ends with a small mock interview + 4-5 assessment claims, each labelled verdict, concerns, group.
**D6 Rewrite `concepts/how-an-audit-decides.md`.**
- One running example: T0 clinician "How often do you forget appointments?", T1 patient "Maybe once a month. Only when I'm on night shifts.", T2 mother "I'd say every week."; assessment "Patient forgets appointments weekly and takes 20 mg sertraline." Walk prep, atomize, link, check, assemble with real intermediate values (verify by running the replay/mock or reading fixtures, not inventing).
- State plainly: 3 model calls (atomize per section, link per claim, check per claim) plus optional cheap prep tagging (off by default).
- Supporting vs qualifying vs contradicting evidence with examples (T1 qualifies, T2 contradicts).
- Why prep (interview, rules, no model) and atomize (assessment, model) are separate.
- **Who decides what** table:

| Output | Decided by |
|---|---|
| verdict | code (fixed order over observations) |
| explanation | code templates |
| `out_of_scope_reason` | model picks category, code writes sentence |
| concern types | code: the 6+ derived from observations; flagged types raised by model, then vetted by code (floors, guards) |
| evidence role | link suggests, code final |
| spans | code |
| evidence note, `suggested_revision` | model writes, code vets |

- **What the model outputs** section: per call, each field; then for each response field, step by step where it comes from and how calculated. Verify against `check/{models,synth,templates}.py`, `atomize/models.py`, `link/models.py`, `assembler/`.
**D7 `contracts/README.md`.** Type column in every field table; nested fields indented under parent ("transcript" then "└ id"); span shape `{start:{index,char}, end:{index,char}}` with example; Concern table (type, group, explanation, evidence_ids) and an evidence-to-concern linkage example; where verdicts come from (mission's 4 results + `out_of_scope` from the mission's outside-scope sentence); model tiers (cheap = prep tagging, off by default; mid = atomize/link/check, the one that matters; strong = offline only; `run_info` records the model per tier so a result can be reproduced/compared) and `prompt_hashes` (sha256 prefix of each prompt file, to know which prompt version made a result); error table copied from SP02; Rule 0 statement. Normative tables must still match the schemas (SP02 owns them; SP04 only reorganises).
**D8 `implementation/frontend.md`.** Plain explanations with tiny examples: `utils/codepoints.ts` (emoji = 1 code point, 2 UTF-16 units, so highlights would shift); `contract/analysis.ts` (validates spans, counts verdicts, orders claims, finds unprocessed sections); `contract/excerpts.ts` (merges excerpt turn ranges plus expansion into display chunks); `utils/retry.ts`; frontend flowchart; tab registry.
**D9 `implementation/{prep-atomize→split, link, check, assembler}.md`.** Split `prep-atomize.md` into `prep.md` and `atomize.md`. Each stage page: one-paragraph purpose, "model vs code" table, running-example input/output, jargon box (BM25 = keyword ranking; fuzzy = near-match on spelling; tokenize = split into words; D0-D9 = ordered rows of the check decision table; group-a = code-only checks needing no model; confidence floors = minimum model confidence to accept an observation; copycheck = reject quote not copied from the interview; boundary repair = snap spans to turn/word edges). A "Not to be confused with" note for question-to-answer pairing and `synth.py`. Update `pipeline.md`, `llm-client.md` (retry wrapper, Haiku 5.5).
**D10 Indexes and reference.** Update `docs/README.md`, every folder README, `decisions/README.md` (ADR index incl. 0016+ from SP02/03), `reference/configuration.md` (eaudit paths, models, retry settings, Haiku 5.5; verify against `config.py`), `reference/backend-api.md` renamed to `reference/eaudit-api.md` in the same commit with every link fixed (error body per SP02), `testing/*` paths and commands, `eval/README.md`, `eval-server.md`. Every doc keeps an Audience line.

## Architecture (doc map)
| File | Action | Contents |
|---|---|---|
| `docs/README.md`, `*/README.md`, `decisions/README.md` | changed | new index rows, ADR list |
| `architecture.md` | changed | stage examples, Eval section, flowcharts |
| `concepts/eval.md` | new | D3 |
| `concepts/research.md` | new | D4 (concepts, since it explains why; not reference) |
| `concepts/concerns-and-groups.md` | new | D5 |
| `concepts/severity-and-frequency.md` | deleted | merged into concerns-and-groups |
| `concepts/how-an-audit-decides.md` | rewritten | D6 |
| `concepts/{limits-of-an-audit,missing-role,review-ui}.md` | changed | speaker-optional note, group display, links, versions |
| `contracts/README.md` | changed | D7 |
| `implementation/{prep,atomize}.md` | new (split) | D9 |
| `implementation/{link,check,assembler,pipeline,llm-client,frontend,eval-server}.md` | changed | D8/D9, paths, retry |
| `reference/{configuration,eval-api,eval-ui,review-ui,warnings}.md` | changed | D10, group, error body, `ambiguous_speaker` text |
| `reference/backend-api.md` → `reference/eaudit-api.md` | renamed | D10; links fixed in same commit |
| `testing/*`, `examples/*`, `eval/README.md`, `docs/mission.md` | changed | paths; mission only if SP03 left it stale |

Doc flow: `README -> mission -> architecture -> concepts (how-an-audit-decides -> concerns-and-groups -> eval -> research) -> contracts / reference -> implementation`.

## Decisions
| # | Decision | Why |
|---|---|---|
| 1 | Docs written after SP01-03 | Facts verifiable against final code |
| 2 | Research page under concepts/ | Explains rationale, not lookup facts |
| 3 | Merge+delete severity-and-frequency | Concern knowledge in one place; fewer cross-links |
| 4 | Split prep-atomize.md | Prep (code, interview) and atomize (model, assessment) differ; owner confusion |
| 5 | Flowcharts only if simple | GitHub render, low upkeep; complex ones deferred |
| 6 | No version history anywhere | Not deployed; Rule 0 |
| 7 | Plain tone, short sentences, examples first | Owner preference |
| 8 | Intermediate values in examples come from fixtures/replay | No invented numbers |

## Manual steps
- Owner reviews concerns-and-groups examples (clinical wording) and research.md claims about papers before merge.
- Owner confirms group names and mission wording from SP03.

## Risks
- Docs drift if SP01-03 change late: mitigate by starting only after merge; grep checks below.
- Paper details quoted wrongly: cite only what INVESTIGATION.md / brainstorms record; mark unverified items.
- Running example not matching real pipeline output: run it on the mock/replay path and paste actual values.
- Length growth: tables over prose; split pages rather than lengthen.

## Open Questions
- [RESOLVED: yes, rename to `eaudit-api.md`, all links fixed in the same commit] backend-api.md rename.
- [RESOLVED: running example must match real checker output; verify by running mock/replay; if it does not yield the expected concern, change the example, not the code] Running example.
- [RESOLVED: SP03 PRD read and aligned; 17-type list, definitions, examples, enum order and group map come from SP03 Requirements 1, 2, 5] SP03 details.
- [DEFERRED] Completeness (omission) check; documented as future in research.md only.
- [DEFERRED] Rich interactive diagram artifact for the decision table.
- [RESOLVED: merge and delete] severity-and-frequency.md.

## Acceptance Criteria
- Every relative link in `docs/**` (excluding `agent_files/`) resolves (link-check script passes), including after the `backend-api.md` → `eaudit-api.md` rename (old name appears nowhere).
- Mermaid blocks render on GitHub (previewed); none exceed ~10 nodes.
- Every non-agent_files doc has an Audience line; folder READMEs list every file.
- `grep -rIn -E '1\.[012]\.0|[Vv]ersion history|iaudit_backend|backend/src' docs --exclude-dir=agent_files` returns nothing relevant.
- All 17 types and all 4 groups have an example in concerns-and-groups.md; ends with the labelled mock interview.
- how-an-audit-decides states 3 model calls, has the who-decides table and the "what the model outputs" section; no "second model call".
- Contracts README: Type column, nested layout, span shape, Concern table, tiers, `prompt_hashes`, error table match the schemas (spot-checked by the contract tests' examples).
- Each stage page has a model-vs-code table, the running example, and jargon defined; DeepWiki misnames addressed.
- `concepts/eval.md` and `research.md` cover every item in D3/D4; TofuEval mapping table lists all labels.
- No code, schema or `agent_files/` changes in the diff.
