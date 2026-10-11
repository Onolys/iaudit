# Datasets reviewed

This is every dataset reviewed while looking for free interview transcripts paired with a written assessment of the same interview. It is kept so the ones not used yet can be picked up later.

Facts come from the research round recorded in [brainstorming.md](brainstorming.md), checked in October 2026. Licenses and access terms can change, so recheck before converting anything new.

**Selection bar:** free to download with no request or agreement (a free login is fine). Each record needs speaker turns plus a written assessment of that specific interview.

| Status | Meaning |
|---|---|
| **Used** | Converted in this folder. |
| **Later** | Meets the bar; not converted yet. |
| **Excluded** | Fails the bar; the reason is given. |

## Summary

| Dataset | Status | Real? | Access | Size | Error labels |
|---|---|---|---|---|---|
| [PriMock57](#primock57) | **Used** (10 of 57) | Role-played | Free (git clone) | 57 consultations | Yes |
| [TofuEval on MediaSum](#tofueval-on-mediasum) | **Later** | Real | Free (public download) | 50 interviews | Yes |
| [ACI-Bench](#aci-bench) | **Later** | Role-played | Free (figshare) | 207 encounters | No |
| [MTS-Dialog](#mts-dialog) | Excluded | Written from notes | Free | 1.7k pairs | No |
| [NoteChat](#notechat) | Excluded | Synthetic | Free | Not stated | No |
| [MedDialog](#meddialog) | Excluded | Real | Free | Not stated | No |
| [AnnoMI](#annomi) | Excluded | Not stated | Free | 133 sessions | No |
| [Kaggle AI Recruitment Pipeline](#kaggle-ai-recruitment-pipeline) | Excluded | Probably synthetic | Free login | 10,174 transcripts | No |
| [MIT Interview](#mit-interview) | Excluded | Not checked | Gated | Not stated | No |
| [DAIC-WOZ](#daic-woz) | Excluded | Not checked | Gated | Not stated | No |
| [MIMIC-IV](#mimic-iv) | Excluded | Real | Gated | Not stated | No |

## Used

### PriMock57

- **Link:** [github.com/babylonhealth/primock57](https://github.com/babylonhealth/primock57), with papers on [arXiv 2204.00333](https://arxiv.org/abs/2204.00333) and [arXiv 2204.00447](https://arxiv.org/abs/2204.00447).
- **License:** CC BY 4.0. Redistribution is allowed with attribution.
- **Access:** `git clone`. Git LFS is needed only for the audio, which we don't use.
- **Size:** 57 consultations.
- **Real?** Role-played. In upstream's words: "57 Babylon employees acting as patients, using case cards". The notes were written by the clinicians who ran the consultations.
- **Turns and assessment:**
  - Timed utterances come in separate doctor and patient TextGrid files.
  - Each consultation has one clinician note.
- **Error labels:** For each evaluator, "Incorrect statements" and "Omissions", marked critical (`!`) or non-critical (`-`).
  - Of the 285 evaluator rows on the clinicians' own notes, 186 list at least one incorrect statement.
  - The labels are free text and aren't tied to transcript spans.
- **Mapping effort:** Low to medium. Merge the speaker files by start time, then map the labels to checks by hand.
- **Status:** **Used.** Ten consultations are in this folder; see [README.md](README.md).
  - The other 47 can be converted the same way.
  - Three more already meet the selection rule: `day4_consultation07`, `day5_consultation02` and `day5_consultation05`.

## Later

### TofuEval on MediaSum

- **Link:** [github.com/amazon-science/tofueval](https://github.com/amazon-science/tofueval) (labels), with transcripts from [github.com/zcgzcgzcg1/MediaSum](https://github.com/zcgzcgzcg1/MediaSum).
- **License:**
  - Labels: MIT-0.
  - MediaSum: research purpose only. TofuEval says its data "should not be used in training".
- **Access:** Free. The transcripts are a public Google Drive zip.
- **Size:** 50 interviews and 2,546 summary sentences, of which 526 are labelled not supported.
- **Real?** Real NPR and CNN interviews.
- **Turns and assessment:** Named speakers. The summaries are LLM-written and topic-focused, not written by a human assessor.
- **Error labels:** Each sentence has a label, a written explanation and an error type.
- **Mapping effort:** Medium. Join the transcripts by `doc_id`, then turn the summary sentences into one section.
- **Status:** **Later.** It is the only free set of real, non-clinical interviews with labels.
  - MediaSum's research-only terms make it a weak fit for data committed to this repository.
  - Convert it only if we can keep the transcripts out of the repo, or confirm the terms allow it.

### ACI-Bench

- **Link:** [github.com/wyim/aci-bench](https://github.com/wyim/aci-bench), with data on [figshare](https://figshare.com/articles/dataset/aci-bench-corpus_zip/22494601) and the [paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10482860/).
- **License:** CC BY 4.0.
- **Access:** Free download from figshare.
- **Size:** 207 encounters.
- **Real?** Role-played and expert-written. In the paper's words: "certified doctor and a volunteer lay person, who must role-play".
- **Turns and assessment:** Turns are tagged `[doctor]` and `[patient]`, and each encounter has a full sectioned visit note.
- **Error labels:** None. Unsupported note text was removed during curation, so most claims should be supported.
- **Mapping effort:** Low. Note headings become sections.
- **Caveat:** The ASR subsets have speaker tags that were swapped and deliberately left uncorrected. Use the human-transcribed subsets.
- **Status:** **Later.** It is useful for clinical volume and for "everything is supported" cases.

## Excluded

### MTS-Dialog

- **Link:** [github.com/abachaa/MTS-Dialog](https://github.com/abachaa/MTS-Dialog), with the [paper](https://aclanthology.org/2023.eacl-main.168.pdf).
- **License and access:** CC BY 4.0, ungated. 1.7k pairs.
- **Why excluded:** The direction is backwards. Annotators were "asked to create clinical conversations from one section" of existing notes, so the dialogue was written from the note.
  - The dialogues are short.
  - Its correlation study scores model summaries, not the source notes.

### NoteChat

- **Link:** [huggingface.co/datasets/akemiH/NoteChat](https://huggingface.co/datasets/akemiH/NoteChat).
- **License:** Not stated.
- **Why excluded:** Synthetic. Its title is "Synthetic Doctor-Patient Conversations Conditioned on Clinical Notes".

### MedDialog

- **Link:** [huggingface.co/datasets/bigbio/meddialog](https://huggingface.co/datasets/bigbio/meddialog).
- **License:** "unknown".
- **Why excluded:** These are real online Q&A exchanges, but there is no paired written assessment.

### AnnoMI

- **Link:** [github.com/uccollab/AnnoMI](https://github.com/uccollab/AnnoMI).
- **License:** Not stated. 133 counselling sessions.
- **Why excluded:** It has per-utterance codes and a high or low quality label, but no written assessment.

### Kaggle AI Recruitment Pipeline

- **Link:** [kaggle.com/datasets/yaswanthkumary/ai-recruitment-pipeline-dataset](https://www.kaggle.com/datasets/yaswanthkumary/ai-recruitment-pipeline-dataset).
- **Access:** Free Kaggle login. The data was not viewed.
- **Size:** 10,174 transcripts, each with a `Reason_for_decision` field.
- **Why excluded:** The source isn't stated, so treat it as probably synthetic.
  - Most other Kaggle hiring sets are question banks with no transcripts.

### MIT Interview

- **Link:** [roc-hci.com MIT Interview](https://roc-hci.com/past-projects/automated-prediction-of-job-interview-performance/).
- **Why excluded:**
  - Gated: request form, academic email only.
  - It has numeric ratings only, no written assessment.

### DAIC-WOZ

- **Link:** [dcapswoz.ict.usc.edu](https://dcapswoz.ict.usc.edu/).
- **Why excluded:** Gated. Users must "complete, sign and submit the form", and access is for academics and non-profit researchers only.

### MIMIC-IV

- **Link:** [physionet.org/content/mimiciv](https://physionet.org/content/mimiciv/).
- **Why excluded:** Gated. "Only credentialed users who sign the DUA".

## Not checked

- Counselling sets with session notes, for example MEMO or HOPE.
