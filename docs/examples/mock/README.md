# Mock audit samples

Fictional request/response pairs for contract [1.2.0](../../contracts/README.md). Use them to see how the review UI lays out claims, verdicts, evidence, and warnings.

Samples 01–05 are small plumbing fixtures. Their audit content is **not** meant to be correct; the verdicts and concerns are placeholders. Samples 06–10 are full-length interviews whose verdicts are meant to be clinically and logically defensible: each problem claim names its discrepancy, cites the excerpt that conflicts with or qualifies it, and offers a `suggested_revision`. In every sample the plumbing is exact: every span resolves to real text, in Unicode code points with an exclusive end, and every response follows the schema and rules 1–12.

Each folder holds `request.json` (transcript plus assessment) and `response.json` (the audit). Every response except `05-minimal-fields` carries an illustrative `run_info` block (made-up model ids and prompt hashes, no token or cost fields); `05-minimal-fields` omits it to show that it is optional.

| Sample | What it exercises |
|---|---|
| [01-memory-basic](01-memory-basic/) | One section with roles and timestamps. `supported`, `contradicted`, `partially_supported`. Cross-turn question-and-answer evidence. Concerns: negation reversal, frequency inflation, certainty inflation, context stripping. |
| [02-multi-section](02-multi-section/) | Three sections with labels, plus numeric and string scores. `insufficient_evidence` and `out_of_scope`. Concerns: question as answer, timeframe mismatch, certainty inflation, unsupported causal link. |
| [03-partial-status](03-partial-status/) | `status: "partial"` with `section_not_processed` and `ambiguous_speaker` warnings. Custom speaker names, no roles. Concerns: correction ignored, contradictory evidence, wrong attribution. |
| [04-unicode-offsets](04-unicode-offsets/) | Emoji, accents, and curly quotes in turns, the section text, and the label, so code-point offsets matter. An empty turn and no `request_id`. Concerns: frequency inflation, unsupported causal link, conflicting accounts flattened. |
| [05-minimal-fields](05-minimal-fields/) | Only the required fields: no `request_id`, roles, timestamps, label, or score. Evidence crosses an empty turn. A claim with no evidence, plus an `other` warning. Concern: unsupported claim. |
| [06-adult-adhd](06-adult-adhd/) | Adult ADHD, with the patient and a partner informant. 56 turns, 3 sections, 14 claims (7 supported). Concerns: frequency inflation, timeframe mismatch, wrong attribution, correction ignored, unsupported causal link, certainty inflation. |
| [07-depression-anxiety](07-depression-anxiety/) | Depression and anxiety, patient only. 56 turns, 3 sections, 13 claims (5 supported). Concerns: context stripping, negation reversal, frequency inflation, question as answer, unsupported claim. |
| [08-child-parent-informant](08-child-parent-informant/) | A 9-year-old with a parent informant, plus a teacher's view relayed second-hand. 59 turns, 3 sections, 13 claims (6 supported). Concerns: wrong attribution, conflicting accounts flattened, frequency inflation, context stripping, contradictory evidence, certainty inflation. |
| [09-cognitive-caregiver](09-cognitive-caregiver/) | Memory concerns in an older adult, with a daughter informant. 59 turns, 3 sections, 13 claims (5 supported). Concerns: negation reversal, correction ignored, conflicting accounts flattened, timeframe mismatch, wrong attribution, unsupported claim. |
| [10-substance-use-sleep](10-substance-use-sleep/) | Alcohol, cannabis and insomnia after a move to night shifts, patient only. 59 turns, 3 sections, 13 claims (5 supported). Concerns: correction ignored, contradictory evidence, question as answer, timeframe mismatch, unsupported causal link, frequency inflation. |

Across 01–05: all 5 verdicts, all 3 evidence roles, all 12 concern types, and 3 warning codes. `span_out_of_range` and `input_truncated` are left out on purpose, because a valid fixture cannot contain an out-of-range span.

Samples 06–10 are standard input with no edge cases. Every turn has a role and a timestamp, every audit is `complete` with no warnings, and all text is plain. Across those five samples there are 66 claims, 28 of them supported (about 40%). All 5 verdicts and all 3 evidence roles appear, every concern type appears at least twice, and each sample has at least one claim with two concerns.

## Validate

[validate.py](validate.py) checks every sample folder, or the ones you name, against the schemas and the rules a schema cannot express.

```bash
# schema plus rule checks
uv run --with jsonschema python3 validate.py
# rule checks only, stdlib Python
python3 validate.py
# print the text each span selects
python3 validate.py --show 04-unicode-offsets
# any other folder with request.json and response.json
python3 validate.py ../../contracts/examples
```

It exits non-zero on any failure. Rule 9 (no copied transcript text) is a heuristic: it flags a run of 6 or more words copied from a turn, or any transcript timestamp. Rule 12 (wording) is not checked automatically.

In JavaScript, slice with `Array.from(text)`, not `text.slice`, or the emoji in sample 04 will shift later highlights.
