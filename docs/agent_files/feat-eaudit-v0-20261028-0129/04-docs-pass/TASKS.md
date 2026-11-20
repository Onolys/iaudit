---
status: draft
summary: 11 doc tasks - concerns/groups, how-an-audit-decides, contracts README, eval + research pages, architecture, stage pages, frontend, small-doc sweep, rename + indexes + link check.
date: 2026-10-28
---
# Tasks: SP04 Docs pass
Source of truth: [PRD.md](PRD.md) (approved; no [OPEN] items; DEFERRED completeness check and interactive diagram get no tasks). Docs-only, run after SP01-03 land; every claim is verified against code, fixtures or the SP03 PRD, never memory. Taxonomy facts (17 types, 4 groups, definitions, TofuEval crosswalk) are copied from SP03 Requirements 1, 2, 5.
Contract versioning rule: all schemas are schema_version "0.0.1"; the project is not deployed, so no legacy/back-compat code, version history or migration; a file or body not conforming to the current schema just shows a validation error and the owner deletes it. For docs: no version history or old-version mentions anywhere (outside `agent_files/`).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Concerns-and-groups page (merge + delete severity-and-frequency) | none | todo |
| 2 | Rewrite how-an-audit-decides | 1 | todo |
| 3 | Contracts README | none | todo |
| 4 | Eval concepts page | none | todo |
| 5 | Research page | 4 | todo |
| 6 | Architecture: stage examples, Eval section, flowcharts | 2, 4 | todo |
| 7 | Stage pages: prep and atomize split | 2 | todo |
| 8 | Stage pages: link, check, assembler, pipeline, llm-client | 7 | todo |
| 9 | Frontend implementation page | none | todo |
| 10 | Remaining concept, reference, testing, example docs sweep | 1-9 | todo |
| 11 | Rename eaudit-api, indexes, ADR index, link and grep checks | 10 | todo |

## Task 1 — Concerns-and-groups page
What it is / what it means: one place for what is off with a claim (D5). Explains verdict vs concern vs group in plain words.
What changes at a high level: new `concepts/concerns-and-groups.md`. Four groups with meaning and boundary. All 17 types in SP03 enum order, each with definition, short interview+claim example, usual verdict, near-miss. Absorbs quantity-mismatch and labelling content from how-an-audit-decides and buckets/inflates/understates from severity-and-frequency, then deletes that page and fixes its links. Ends with a small mock interview and 4-5 labelled assessment claims (verdict, concerns, group).
Done when: all 17 types and 4 groups have examples; definitions match SP03; severity-and-frequency is gone with no dangling links; relative links resolve; Mermaid (if any) valid; Audience line present.

## Task 2 — Rewrite how-an-audit-decides
What it is / what it means: the owner's main "who decides what" explainer (D6).
What changes at a high level: rewrite around one running example (clinician, patient, mother, sertraline claim) walked through prep, atomize, link, check, assemble with real intermediate values from running the mock/replay or reading fixtures; if the checker does not yield the expected concern, change the example, not code. States 3 model calls plus optional prep tagging (off by default); supporting vs qualifying vs contradicting evidence; why prep and atomize are separate; the who-decides table; a "what the model outputs" section per call and a step-by-step origin for each response field. Simple decision-flow Mermaid, or table plus "artifact later" note.
Done when: no "second model call"; table and section match `check/{models,synth,templates}`, `atomize/models`, `link/models`, `assembler/`; values verified by run; links resolve; Mermaid valid and at most 10 nodes; Audience line kept.

## Task 3 — Contracts README
What it is / what it means: the normative contract page made readable (D7, Rule 0).
What changes at a high level: Rule 0 statement in intro; Type column in every field table; nested fields indented under parent; span shape with example; Concern table (type, group, explanation, evidence_ids) with evidence-to-concern example; where verdicts come from; model tiers and `run_info`; `prompt_hashes`; error table copied from SP02. Remove 1.x versions, Version history, `backend/` paths, "Mission check 13" numbering. Reorganise only, tables stay equal to schemas.
Done when: tables spot-checked against the schemas and contract test examples; no old-version text; links resolve; Audience line kept.

## Task 4 — Eval concepts page
What it is / what it means: first concepts page for evaluation (D3).
What changes at a high level: new `concepts/eval.md` covering datasets (TofuEval, synthetic/ADHD), projection of our concerns/verdicts to their labels, metrics, dev/test splits, integrity rules (no tuning on test, no copied dataset text, no score-moving edits, mapping frozen before runs), and what each dataset can and cannot test. Audit other docs for eval gaps; fix or link them.
Done when: every D3 item covered and checked against `eval/` code and SP03 mapping; links resolve; Audience line present.

## Task 5 — Research page
What it is / what it means: provenance of the checks (D4).
What changes at a high level: new `concepts/research.md`: each source (FRANK, Tang 2022, TofuEval, AggreFact, SummaC, DiaSumFact, PriMock57, WiCE) and what we took; how checks were chosen from the owner mission and adapted to interviews; full TofuEval-label-to-our-types table; PriMock57 (incorrect = union of types, omission out of scope, completeness parked as future); WiCE label mapping and evidence overlap. Cite only what INVESTIGATION.md or brainstorms record; mark unverified items; be honest about limits.
Done when: table lists all TofuEval labels and matches SP03; paper claims traceable to repo sources; links resolve; Audience line present.

## Task 6 — Architecture doc
What it is / what it means: the overview page gains examples and an Eval view (D1, D2).
What changes at a high level: per-stage backend examples (same running example, 3-5 lines of input and output each); new Eval section (datasets, adapter, engine, metrics, eval API, Eval UI) with links; simple flowcharts for pipeline stages, `POST /v1/audit` request flow and eval flow.
Done when: examples match Task 2 values; each Mermaid at most 10 nodes and valid; links resolve; Audience line kept.

## Task 7 — Prep and atomize stage pages
What it is / what it means: split `prep-atomize.md` into `prep.md` (code, interview) and `atomize.md` (model, assessment) (D9).
What changes at a high level: each page gets purpose paragraph, model-vs-code table, running-example input/output, jargon box (BM25, fuzzy, tokenize, boundary repair as relevant), and a "Not to be confused with" note on question-to-answer pairing. Old page removed, links fixed.
Done when: claims verified against code; example values match Task 2; no link to the old file; Audience lines present.

## Task 8 — Remaining stage pages
What it is / what it means: same treatment for link, check, assembler, plus pipeline and llm-client updates (D9).
What changes at a high level: purpose, model-vs-code table, running-example values, jargon box (D0-D9, group-a, confidence floors, copycheck) and a note separating `check/synth.py` from "synthetic decision functions". `pipeline.md` links the new stage pages; `llm-client.md` covers the retry wrapper and Haiku 5.5.
Done when: verified against code and `config.py`; links resolve; Audience lines present.

## Task 9 — Frontend implementation page
What it is / what it means: plain explanation of the frontend helpers (D8).
What changes at a high level: tiny examples for `utils/codepoints.ts` (emoji = 1 code point, 2 UTF-16 units), `contract/analysis.ts`, `contract/excerpts.ts`, `utils/retry.ts` (429 only for audit POST); frontend flowchart; tab registry.
Done when: behaviour verified in the frontend source; Mermaid valid; links resolve; Audience line kept.

## Task 10 — Remaining docs sweep
What it is / what it means: bring the other pages in line (Rule 0, D3 gaps, D10).
What changes at a high level: `limits-of-an-audit`, `missing-role`, `review-ui` (speaker optional, group display, links); `reference/{configuration, eval-api, eval-ui, review-ui, warnings}` (eaudit paths, models, retry, group, error body, `ambiguous_speaker`); `implementation/eval-server`; `testing/*`; `examples/*`; `eval/README.md`; `docs/mission.md` only if SP03 left it stale; ADR wording drops version bumps. Remove 1.x/version-history text.
Done when: facts verified against code and `config.py`; grep for `1.[012].0`, "Version history", `iaudit_backend`, `backend/src` finds nothing relevant; links resolve; Audience lines kept.

## Task 11 — Rename, indexes, final checks
What it is / what it means: finish navigation and prove the docs hold together (D10).
What changes at a high level: rename `reference/backend-api.md` to `eaudit-api.md` (error body per SP02) with every link fixed in the same commit; update `docs/README.md`, all folder READMEs (list every file), `decisions/README.md` (ADR index incl. 0016+); run link-check and grep sweeps.
Done when: old name appears nowhere; every relative link in `docs/**` (excluding `agent_files/`) resolves; every doc has an Audience line; Mermaid blocks preview-valid; no code, schema or `agent_files/` change in the diff.

## Owner manual steps
- Review concerns-and-groups examples (clinical wording) and research.md paper claims before merge.
- Confirm group names and mission wording from SP03.
