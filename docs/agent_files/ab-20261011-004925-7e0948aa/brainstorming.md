# Brainstorming: Elaborate mock audit samples 06–10

Source of truth: [Clinical Mockups](https://app.party.build/issues/7) (Party Issue #7, mirrored to GitHub issue #11). Depth: **Bounded**. It adds to an existing fixture set and does not change the contract.

## TL;DR

Add five new fictional request/response pairs, `docs/examples/mock/06-…` through `10-…`, for contract 1.0.0. Each one reads like a real clinical interview, with clinician reasoning across 2–3 sub-domains. The audit is realistic: some claims are supported and some show visible discrepancies of several concern types. Every file is standard, valid input and output that passes `validate.py`, with no edge cases.

## Problem

Mocks 01–05 are tiny (4–10 turns) and exist to test contract plumbing. Their verdicts are placeholders. The review UI and its demos need realistic samples with much more content. A reviewer should be able to see a supported claim next to a real discrepancy, trace it back to the transcript, and judge it.

## Decision log

| Decision | Alternative rejected | Why |
|---|---|---|
| Fictional mock data in `docs/examples/mock/06`–`10` | Use the real PriMock57 data (Dataset Search session) | The user still needs mocks. Real data has no planted discrepancies known in advance. |
| No edge cases: standard ASCII-safe text, `status: complete`, empty `warnings`, roles and timestamps present | Repeat partial status, warnings, Unicode or minimal fields | 03–05 already cover those, and the user asked for safe, standard input and output. |
| Every sample is valid and passes `validate.py` (schema plus rules 1–12) | Include invalid or error fixtures | The user said "no failure cases… each should be valid cases that pass". |
| Audit verdicts mix `supported` with problem verdicts (`contradicted`, `partially_supported`, `insufficient_evidence`), plus the occasional `out_of_scope` for a diagnostic conclusion | All claims supported | The original request asks for "some failures, some success" and failures that can be seen. "Valid" refers to the fixtures, not to the verdicts. |
| Verdicts and concerns are clinically and logically defensible | Placeholder verdicts, as in 01–05 | They must feel like real reasoning and real catches. |
| Five clinical areas: adult ADHD; depression and anxiety; child assessment with a parent informant; cognitive decline with a caregiver informant; substance use and sleep | Arbitrary topics | Together they exercise the attribution, informant, timeline and correction checks. |
| About 40–80 turns, 2–3 labeled sections, 8–15 claims, roughly 40% supported and 60% problems per sample | Short samples | The user wants "way more content". |
| 4–6 concern types per sample, at least one claim with two concerns, all 12 types at least twice across the set | One concern per claim | The user asked for multiple check types per sample. |
| Each problem claim has a `suggested_revision` and an explanation naming the discrepancy. Evidence includes counter-evidence (contradicting or qualifying) | Bare verdicts | Makes failures visible and defensible in the UI. |
| Contract stays at 1.0.0, no schema changes | Extend the contract | Fixtures only. |

## Design (short)

- Each folder has two files:
  - `request.json`: transcript turns with `speaker`, `role` and `timestamp`, plus 2–3 assessment sections with a `label` and a display-only `score`.
  - `response.json`: claims with spans, verdicts, concerns and evidence.
- Transcripts include natural hedging, a later correction, and a qualification given several turns after the first answer. Where an informant is present, the respondent and informant disagree. This gives checks 3, 9, 10 and 11 real material.
- Responses never copy quote text or timestamps (rule 9). `explanation` and `note` are paraphrases.
- Update the table in `docs/examples/mock/README.md` with one row per new sample, plus coverage totals.

## Non-goals

- No edge cases (Unicode offsets, empty turns, partial status, warnings, minimal fields).
- No invalid or error fixtures.
- No contract or schema changes, scoring, diagnosis checks or model benchmark.
- No real patient data, and no work on `docs/examples/real`.

## Open risks (cheapest test)

| Risk | Cheapest test |
|---|---|
| A planted discrepancy may be too subtle or arguable. | Run `python3 validate.py --show 06-…` and read each claim against its evidence. |
| Long hand-written offsets are error-prone. | `uv run --with jsonschema python3 validate.py` must exit 0 for all ten samples. |
| Copied runs of 6 or more words trip rule 9. | The same validator run. |

## Open questions

- **OPEN:** whether to write one sample first so the user can judge realism before the other four. Brainstorm proposed this as the cheapest kill test (Round 1, Q4). The user's answer adopted Brainstorm's choices in general but did not address this point directly.

## Q&A asked and answered

| Question | Answer |
|---|---|
| Real or mock data? | Mock. "Dont worry about the real ones. I still need mock ones." |
| Edge cases, warnings, partial status? | None. "Assume completely safe and standard input and output." |
| Invalid or failure fixtures? | None. "Each of them should be valid cases that pass." |
| Clinical areas, length, concern mix, what to cut, non-goals, suggested revisions? | "Everything else what you chose": the user accepted Brainstorm's recommendations, as recorded above. |

## Research sources

No research step ran for this idea. The design draws on the existing repository material:

- [docs/examples/mock/README.md](../../examples/mock/README.md): the existing samples 01–05 and their coverage
- [docs/examples/mock/validate.py](../../examples/mock/validate.py): the validator every new sample must pass
- [docs/contracts/README.md](../../contracts/README.md): contract 1.0.0
