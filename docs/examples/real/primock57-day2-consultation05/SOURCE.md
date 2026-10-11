# Source: PriMock57 `day2_consultation05`

| Field | Value |
|---|---|
| Dataset | [PriMock57](https://github.com/babylonhealth/primock57) |
| Upstream commit | [`cd2ac70`](https://github.com/babylonhealth/primock57/tree/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5) |
| Doctor transcript | [`transcripts/day2_consultation05_doctor.TextGrid`](https://github.com/babylonhealth/primock57/blob/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5/transcripts/day2_consultation05_doctor.TextGrid) |
| Patient transcript | [`transcripts/day2_consultation05_patient.TextGrid`](https://github.com/babylonhealth/primock57/blob/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5/transcripts/day2_consultation05_patient.TextGrid) |
| Clinician note | [`notes/day2_consultation05.json`](https://github.com/babylonhealth/primock57/blob/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5/notes/day2_consultation05.json), field `note` |
| Evaluator labels | [`human_eval_data/results.csv`](https://github.com/babylonhealth/primock57/blob/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5/human_eval_data/results.csv), rows where `Consultation` is `day2_consultation05` and `Model` is `doctor`, column `Incorrect statements` |
| Presenting complaint (upstream) | "My asthma is not responding to my inhalers" |
| Kind of interview | Role-played: a Babylon clinician with a Babylon employee acting as the patient from a case card |
| License | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

## What was converted

- `request.json` has 137 transcript turns and 1 assessment section.
  - Turns are the doctor and patient utterances, merged by start time.
  - The note is split at its blank lines, and its text is kept verbatim.
- `expected.json` has 4 labelled claims.
  - It maps 8 of the 11 incorrect-statement items that the 5 evaluators listed.
  - The other 3 items didn't map to one of the 12 checks, or the transcript supports the claim marked. They are not shown.
  - The 27 omission items aren't used.
- The evaluators reviewed the note only up to its impression or plan. The full note is in `request.json`, but any errors in the impression and plan sections are unlabelled.

See [../README.md](../README.md) for the conversion and mapping rules.

## Attribution

This folder contains material adapted from PriMock57 by Babylon Health, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Upstream: [babylonhealth/primock57](https://github.com/babylonhealth/primock57).

Changes made:
- The two speaker files were merged into one turn list.
- Transcription tags were removed, as upstream's `strip_transcript_tags` does.
- Start times were rounded down to whole seconds.
- The note was split into sections.
- The answer key was written by hand from the evaluator labels.

The original material is provided as is, with no warranty.

## Citation

```bibtex
@inproceedings{korfiatis2022primock57,
  title={(in press): PriMock57: A Dataset Of Primary Care Mock Consultations},
  author={Papadopoulos Korfiatis, Alex and Moramarco, Francesco and Sarac, Radmila and Savkov, Aleksandar},
  booktitle={Proceedings of the 60th Annual Meeting of the Association for Computational Linguistics},
  year={2022}
}

@inproceedings{moramarco2022human,
  title={(In press): Human Evaluation and Correlation with Automatic Metrics in Consultation Note Generation},
  author={Moramarco, Francesco and Papadopoulos Korfiatis, Alex and Perera, Mark and Juric, Damir and Flann, Jack and Reiter, Ehud and Belz, Anya and Savkov, Aleksandar},
  booktitle={Proceedings of the 60th Annual Meeting of the Association for Computational Linguistics},
  year={2022}
}
```
