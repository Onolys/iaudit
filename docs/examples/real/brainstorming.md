# Brainstorm: real interview datasets

Status: **decided brainstorm.** This records [Dataset Search](https://app.party.build/issues/6), which is the source of truth, plus the research round it cites. It is not a normative spec.

The user asked for this file to sit next to the data, so it lives here rather than at the repository root. Depth: **Bounded**, a small addition to the existing test material.

## TL;DR

Ten real (role-played) clinical consultations from PriMock57 are converted into our audit request format. Each comes with an answer key built from the human evaluators' "Incorrect statements" labels.

They are committed to `docs/examples/real/`, one folder per interview. Alongside them are source citations, a catalog of every dataset we reviewed, and this brainstorming doc. The mock samples stay.

## Problem

Our test inputs so far are hand-written mocks. Tejit wants to test the auditor on real interviews paired with real written assessments. The data must be free, with no payment or access request.

## Decision log

| Decision | Alternative rejected | Why |
|---|---|---|
| Only free sets with no request or agreement | MIMIC-IV, DAIC-WOZ, MIT Interview | Tejit asked for nothing paid or gated |
| Convert 10 interviews | Converting full datasets | "10 actual ones is good" |
| Source the 10 from PriMock57 | TofuEval/MediaSum, ACI-Bench | The notes were written by the clinicians who ran the consultations, there are human error labels, and CC BY 4.0 allows redistribution with attribution. MediaSum is research-only. |
| Role-played patients count as actual interviews | Real-patient data only | No free real-patient set has paired notes, and the assessment step is real |
| Commit the converted data to the repo | A fetch-and-convert script only | Tejit: "convert them, and push them" |
| Answer keys include only labels that map to one of our 12 checks | Including every label | "Only show supported ones"; labels outside the checks are dropped |
| Drop "Omissions" labels | Including them | Missing information is not something we check |
| Keep the mock samples | Replacing them with real data | Real data won't cover every check |
| Catalog every reviewed dataset | Recording only the ones used | "note down all the datasets so we can use it later" |
| The brainstorming doc lives in `docs/examples/real/` | The repository root | "put this brainstorming doc alongside" |
| Leave out MTS-Dialog, NoteChat, MedDialog and AnnoMI | Converting them anyway | Each is backwards (dialogue written from the note), synthetic, or has no written assessment |

## Design (short)

- **`docs/examples/real/<interview-id>/`**: one folder for each of the 10 consultations, for example `primock57-day1-consultation01/`.
  - `request.json` is valid against `docs/contracts/audit-request.schema.json`.
    - `transcript`: the doctor and patient utterance files, merged by start time. Use the roles `interviewer` and `respondent`, and keep the timestamps.
    - `assessment`: the clinician's note as one or more sections, following the note's own headings where present. In practice the notes have no consistent headings, so they were split at the clinician's blank lines (see [README.md](README.md#how-requestjson-was-built)).
  - `expected.json` is an answer key. It lists each evaluator "Incorrect statement" that maps to one of the 12 checks, following the `audit-response.schema.json` claim shape where it fits. Each entry gives:
    - the assessment claim text
    - the mapped check
    - critical or non-critical
    - the transcript turns that support or contradict the claim
    - the evaluator's original wording
  - `SOURCE.md` records:
    - the dataset and the exact source file paths
    - the upstream commit or URL
    - the CC BY 4.0 attribution
    - the paper citation
    - any conversion notes
- **`docs/examples/real/README.md`**: what the folder is, how the files were converted, and how the labels were mapped.
- **`docs/examples/real/DATASETS.md`**: every dataset reviewed.
  - Fields: link, license, access, size, whether it is real, role-played or synthetic, error labels, mapping effort, and status (used, later, or excluded with the reason).
  - It covers PriMock57, TofuEval/MediaSum, ACI-Bench, MTS-Dialog, NoteChat, MedDialog, AnnoMI, the Kaggle AI Recruitment Pipeline set, MIT Interview, DAIC-WOZ and MIMIC-IV.
- **`docs/examples/real/brainstorming.md`**: this file.

The conversion rules, the selection rule for the 10 and the label-mapping rules are in [README.md](README.md).

## Non-goals

- No auditor code, no evaluation harness and no scoring.
- No omissions, or other labels that don't map to a check.
- No TofuEval or ACI-Bench conversion yet. Both are cataloged for later.
- The mock samples are not removed or changed.
- No audio, so Git LFS isn't needed.

## Open risks (cheapest test)

| Risk | Cheapest test | How it was handled |
|---|---|---|
| Few PriMock57 labels map to the 12 checks, so some answer keys come out thin or empty. | When picking the 10, prefer consultations with at least one mappable incorrect statement, and record the selection rule in the README. | The rule takes consultations where all 5 evaluators flagged something. All 10 have at least one mapped claim; the thinnest has one. See [README.md](README.md#how-the-ten-were-chosen). |
| Several evaluators label the same note and may disagree. | List each evaluator's labels separately with an evaluator id, and record agreement in `expected.json`. | Each claim lists its labels by evaluator, plus an `agreement` count. |
| Mapping a free-text label to a check is a judgment call. | Keep the evaluator's verbatim text next to the mapped check so each call can be reviewed. | `verbatim` is kept, and `mapping_note` is added where an item needed interpreting. |
| The attribution is wrong or incomplete. | Copy the upstream license notice and citation into each `SOURCE.md` and the README. | Done. The upstream BibTeX is copied as published. |

**OPEN:** how auditor output will be scored against these keys. Question 5 below put it out of scope for now. It includes what counts as a match, and how to treat flags the evaluators didn't make.

## Q&A asked and answered

1. **Do role-played consultations count as "actual interviews"?** Brainstorm recommended yes. This was accepted when PriMock57 was chosen.
2. **Which datasets for the first version?** Brainstorm recommended PriMock57 plus TofuEval. Decided: 10 interviews, all from PriMock57; the rest are cataloged.
3. **Should we hand-map about 10?** Yes: "10 actual ones is good".
4. **What if labels fall outside the 12 checks?** That's fine. Drop them, and drop Omissions too: "Missing information is not something we calculate".
5. **How do we score flags the evaluators didn't make?** Not in scope now (see OPEN above).
6. **Where does the data live?** In the repo, under `docs/examples/real/`, one folder per interview.
7. **Keep the mocks?** Yes.

Brainstorm read "only show supported ones" as "only the labels our 12 checks cover". Tejit was invited to correct that before the PR and did not.

## Research sources

Research checked these during the brainstorm. Details and statuses are in [DATASETS.md](DATASETS.md).

- PriMock57: [repository](https://github.com/babylonhealth/primock57), [dataset paper](https://arxiv.org/abs/2204.00333), [human evaluation paper](https://arxiv.org/abs/2204.00447)
- TofuEval: [repository](https://github.com/amazon-science/tofueval)
- MediaSum: [repository](https://github.com/zcgzcgzcg1/MediaSum)
- ACI-Bench: [repository](https://github.com/wyim/aci-bench), [figshare](https://figshare.com/articles/dataset/aci-bench-corpus_zip/22494601), [paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10482860/)
- MTS-Dialog: [repository](https://github.com/abachaa/MTS-Dialog), [paper](https://aclanthology.org/2023.eacl-main.168.pdf)
- NoteChat: [Hugging Face](https://huggingface.co/datasets/akemiH/NoteChat)
- MedDialog: [Hugging Face](https://huggingface.co/datasets/bigbio/meddialog)
- AnnoMI: [repository](https://github.com/uccollab/AnnoMI)
- Kaggle AI Recruitment Pipeline: [Kaggle](https://www.kaggle.com/datasets/yaswanthkumary/ai-recruitment-pipeline-dataset)
- MIT Interview: [project page](https://roc-hci.com/past-projects/automated-prediction-of-job-interview-performance/)
- DAIC-WOZ: [site](https://dcapswoz.ict.usc.edu/)
- MIMIC-IV: [PhysioNet](https://physionet.org/content/mimiciv/)
