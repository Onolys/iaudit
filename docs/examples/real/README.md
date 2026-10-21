# Real interview examples

This folder holds ten real interviews converted into the audit request format, for testing the auditor. Each one comes with an answer key built from human evaluator labels.

All ten come from [PriMock57](https://github.com/babylonhealth/primock57) (CC BY 4.0). Each is a primary-care consultation run by a Babylon clinician. The patient is a Babylon employee acting from a case card. The note was written by the clinician who ran that consultation.

The patients are role-played, but the step being checked is real: a clinician writing a note from a conversation they actually had.

**Audience:** contributors testing the auditor.

Hand-written mock samples live in [`../mock/`](../mock/) and are kept. They target each check on purpose; this real data won't cover every check.

| File | What it is |
|---|---|
| `<interview-id>/request.json` | Transcript and clinician note. Valid against [audit-request.schema.json](../../contracts/audit-request.schema.json). |
| `<interview-id>/expected.json` | Answer key: the evaluator-labelled claims that map to one of the 13 checks. |
| `<interview-id>/SOURCE.md` | Exact upstream files and commit, license credit, citation and per-interview conversion notes. |
| [DATASETS.md](DATASETS.md) | Every dataset reviewed, including the ones not used yet. |
| [brainstorming.md](brainstorming.md) | The decisions behind this folder. |

## The ten interviews

| Interview | Presenting complaint (upstream) | Turns | Labelled claims | Evaluator items mapped | Concern types in the key |
|---|---|---|---|---|---|
| [`primock57-day1-consultation01`](primock57-day1-consultation01/) | I've been having really bad diarrhea for the last 3 days | 102 | 2 | 7 of 8 | `contradictory_evidence`, `wrong_attribution` |
| [`primock57-day1-consultation03`](primock57-day1-consultation03/) | I have terrible headache | 136 | 4 | 9 of 9 | `certainty_inflation`, `question_as_answer`, `unsupported_claim` |
| [`primock57-day1-consultation06`](primock57-day1-consultation06/) | hard to breathe | 157 | 4 | 10 of 10 | `contradictory_evidence`, `timeframe_mismatch`, `unsupported_claim` |
| [`primock57-day1-consultation07`](primock57-day1-consultation07/) | I have a cough and cold | 165 | 6 | 14 of 16 | `contradictory_evidence`, `frequency_severity_inflation`, `negation_reversal`, `question_as_answer`, `unsupported_claim` |
| [`primock57-day2-consultation03`](primock57-day2-consultation03/) | I can't hear very well and my face is a bit numb | 99 | 2 | 8 of 9 | `contradictory_evidence`, `timeframe_mismatch` |
| [`primock57-day2-consultation05`](primock57-day2-consultation05/) | My asthma is not responding to my inhalers | 137 | 4 | 8 of 11 | `context_stripping`, `unsupported_claim` |
| [`primock57-day3-consultation06`](primock57-day3-consultation06/) | I'm having difficulty breathing | 49 | 1 | 5 of 5 | `frequency_severity_inflation` |
| [`primock57-day3-consultation09`](primock57-day3-consultation09/) | I have pain in my jaw | 126 | 4 | 9 of 9 | `certainty_inflation`, `context_stripping`, `correction_ignored`, `question_as_answer`, `unsupported_claim` |
| [`primock57-day4-consultation02`](primock57-day4-consultation02/) | I'm feeling hot and have severe headaches | 157 | 4 | 10 of 12 | `contradictory_evidence`, `negation_reversal`, `unsupported_claim` |
| [`primock57-day4-consultation03`](primock57-day4-consultation03/) | I'm feeling short of breath | 117 | 6 | 12 of 19 | `contradictory_evidence`, `negation_reversal`, `question_as_answer`, `timeframe_mismatch`, `unsupported_claim` |

In total there are 37 labelled claims, covering 92 of the 108 evaluator items.

The keys cover checks 1–10. No label maps to check 11 (conflicting accounts flattened), because each consultation has only one respondent. None maps to check 12 (unsupported causal links) either, nor to check 13 (quantity mismatch). The keys were written when the mission had 12 checks.

Some presenting complaints don't match the conversation, for example in `day2-consultation05` and `day3-consultation09`. They are upstream intake text, and the clinician's note says so in one case.

## How the ten were chosen

The rule was fixed before any transcript was read, so no interview was chosen for how well it fits the checks:

1. Take PriMock57's evaluator rows for the clinician's own note (`Model` is `doctor` in `human_eval_data/results.csv`). Each consultation has 5.
2. Keep consultations where every evaluator listed at least one incorrect statement. An evaluator row that reads `!!DATA LOST!!` counts as having listed one. That leaves 13 consultations.
3. Take them in dataset order (day, then consultation number). Skip any where no label maps to a check, and stop at ten.

None of the first ten needed skipping. The three not used were `day4_consultation07`, `day5_consultation02` and `day5_consultation05`.

## How `request.json` was built

- **Transcript.**
  - Upstream has one TextGrid file per speaker. Empty intervals were dropped, and the two speakers' utterances were merged and sorted by start time. Upstream's `scripts/textgrid_to_transcript.py` merges them the same way.
  - `speaker` is `doctor1` or `patient1`, and `role` is `interviewer` or `respondent`.
  - Text is the upstream transcription with tags removed, as upstream's `strip_transcript_tags` does. The removed tags are `<UNSURE>`, `</UNSURE>`, `<UNIN/>` and `<INAUDIBLE_SPEECH/>`. Utterances left empty after that were dropped.
  - `timestamp` is the utterance start time (`xmin`), rounded down to whole seconds, as `HH:MM:SS`.
  - Turn `id` is `t<index>`.
- **Assessment.** This is the clinician's `note` field, split at its blank lines into sections `s0`, `s1` and so on.
  - Text is verbatim, including typos (for example `odema`, `lawer`, `disturbace`), because the auditor sees what the clinician wrote.
  - No `label` or `score` is set, since the notes don't have consistent headings.
- **`request_id`** is the folder name.

The evaluators reviewed each note only up to its impression or plan. The full note is in `request.json`, so impression and plan sections have no labels either way. The auditor should treat diagnostic impressions as `out_of_scope` anyway.

## How `expected.json` was built

The labels come from the `Incorrect statements` column for the `doctor` rows. Evaluators produced it by post-editing the note and listing what they deleted. Items start with `!` (critical) or `-` (non-critical). A line without a marker continues the item above it.

These labels are kept:
- An item is mapped when, after reading the transcript around it, the claim it marks fails one of the 13 checks in [docs/mission.md](../../mission.md).
- The evaluator's verbatim item is kept on every claim it maps to, so each mapping can be reviewed.

These are dropped, and only their counts appear in `label_counts`:
- `Omissions`, because missing information is not something we check.
- Incorrect-statement items where the transcript, read with its question, supports the claim as written.
- Items that can't be tied to one claim, such as a bare `vomiting` or a comment about the intake form.

`expected.json` reuses the [audit-response](../../contracts/audit-response.schema.json) claim shape where it fits:

| Field | Meaning |
|---|---|
| `claims[].span` | Position in `assessment`, using the contract's index and code-point rules. |
| `claims[].claim_text` | The spanned note text, for reading convenience. The contract response itself never copies text. |
| `claims[].expected_verdict` | One of the contract's verdicts, as a person would assign it after reading the transcript. |
| `claims[].concerns`, `claims[].evidence` | Same shape as the contract. Evidence spans cover whole turns. |
| `claims[].labels` | Each evaluator item mapped to this claim, with `evaluator`, `severity` and `verbatim`. |
| `claims[].agreement` | How many evaluators with data labelled this claim. |
| `claims[].mapping_note` | Present when the item needed interpreting, for example a clipped fragment or a post-edit artifact. |
| `label_counts` | Totals, mapped, not mapped, omissions excluded, and rows with lost data. |

Each key's claims, with `expected_verdict` used as `verdict`, validate against the response schema.

**A key is not a full audit.** It lists only claims that evaluators marked as incorrect and that map to a check. A claim that isn't listed was not checked; it is not confirmed as `supported`.

Explanations and notes paraphrase the transcript rather than quoting it, following contract rule 9.

## Caveats

- The labels are free text and aren't tied to transcript lines. The turn spans and concern types were added by hand during conversion, so they are a judgment call. The `verbatim` and `mapping_note` fields keep each call reviewable.
- Evaluators disagree. `agreement` shows how many marked each claim. A claim marked by 1 of 5 is weaker ground truth than one marked by 5 of 5.
- `day1_consultation06` writes `2/5` for a duration the patient gave as a couple of weeks. It is probably a typo for `2/52`, and it is mapped as written.
- One patient says "sick", which in British English can mean ill rather than vomiting (`day3_consultation09`). The key follows the evaluators, who read it as ill.

## Attribution

Material in this folder is adapted from PriMock57 by Babylon Health, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The upstream data is at commit [`cd2ac70`](https://github.com/babylonhealth/primock57/tree/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5). Each `SOURCE.md` lists the changes made and the citations. Please cite:

- Papadopoulos Korfiatis, A., Moramarco, F., Sarac, R., Savkov, A. (2022). [PriMock57: A Dataset Of Primary Care Mock Consultations](https://arxiv.org/abs/2204.00333). ACL 2022.
- Moramarco, F., Papadopoulos Korfiatis, A., Perera, M., Juric, D., Flann, J., Reiter, E., Belz, A., Savkov, A. (2022). [Human Evaluation and Correlation with Automatic Metrics in Consultation Note Generation](https://arxiv.org/abs/2204.00447). ACL 2022.
