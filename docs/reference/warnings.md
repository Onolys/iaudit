# Warnings

When the backend emits each contract warning code. The code list and the warning shape are owned by the [contract](../contracts/README.md). Messages are fixed templates: they never contain transcript or assessment text.

**Audience:** users.

`status` is `partial` if and only if a `section_not_processed` warning is present. Warnings come in this order: section warnings, then claim warnings in claim order, then aggregates. The one exception is the `other` warning for a claim dropped by final validation, which is appended last.

| Code | Carries | Emitted when |
|---|---|---|
| `section_not_processed` | `section_index` | A section produced no claims: the audit ran out of time for it, an internal error occurred, or no claim could be located in its text. |
| `ambiguous_speaker` | `claim_id` | A claim relies on a turn with no `role`. No speaker or role is assumed. The message names turn indexes only. See [missing role](../concepts/missing-role.md). |
| `input_truncated` | none | More claims were found than `IAUDIT_PIPELINE_MAX_CLAIMS`. The extra claims were not audited. |
| `span_out_of_range` | `claim_id` | A claim or evidence span did not fit the input and was omitted. A safety net; not expected in normal runs. |
| `other` | `claim_id` or `section_index` | See below. |

## What `other` covers

Each case is one fixed message, at most once per claim for the adjustments.

| Case | Message says |
|---|---|
| The verdict changed because cited evidence could not be verified | The verdict was adjusted because cited evidence could not be verified. |
| The verdict changed because a contradicting excerpt conflicts with it | The verdict was adjusted because a contradicting excerpt conflicts with it. |
| Wording was replaced to avoid reproducing the transcript | The wording was adjusted to avoid reproducing transcript text. Triggered by a quoted span of four or more words, a timestamp, or a run of `IAUDIT_COPY_NGRAM` (8) words from the transcript that the assessment does not itself contain. |
| The claim was not audited in time or the model failed | The claim was not audited in the available time. The claim is still returned, as `insufficient_evidence`. |
| The claim failed final validation | The claim failed final validation and was omitted. |
| Two claims overlapped | The less severe claim was omitted, or trimmed when `IAUDIT_OVERLAP_TRIM` is on, to keep claim spans from overlapping. |
| A claim could not be located | The claim could not be located in the section text and was omitted. |

Failures that map to HTTP errors instead (nothing usable finished) are in [backend-api.md](backend-api.md#errors).
