# Mock audit samples

Fictional request/response pairs for contract [1.0.0](../../contracts/README.md). Use them to see how the review UI lays out claims, verdicts, evidence, and warnings.

The audit content is **not** meant to be correct. Verdicts and concerns are placeholders. What is exact is the plumbing: every span resolves to real text, in Unicode code points with an exclusive end, and every response follows the schema and rules 1–12.

Each folder holds `request.json` (transcript plus assessment) and `response.json` (the audit).

| Sample | What it exercises |
|---|---|
| [01-memory-basic](01-memory-basic/) | One section with roles and timestamps. `supported`, `contradicted`, `partially_supported`. Cross-turn question-and-answer evidence. Concerns: negation reversal, frequency inflation, certainty inflation, context stripping. |
| [02-multi-section](02-multi-section/) | Three sections with labels, plus numeric and string scores. `insufficient_evidence` and `out_of_scope`. Concerns: question as answer, timeframe mismatch, certainty inflation, unsupported causal link. |
| [03-partial-status](03-partial-status/) | `status: "partial"` with `section_not_processed` and `ambiguous_speaker` warnings. Custom speaker names, no roles. Concerns: correction ignored, contradictory evidence, wrong attribution. |
| [04-unicode-offsets](04-unicode-offsets/) | Emoji, accents, and curly quotes in turns, the section text, and the label, so code-point offsets matter. An empty turn and no `request_id`. Concerns: frequency inflation, unsupported causal link, conflicting accounts flattened. |
| [05-minimal-fields](05-minimal-fields/) | Only the required fields: no `request_id`, roles, timestamps, label, or score. Evidence crosses an empty turn. A claim with no evidence, plus an `other` warning. Concern: unsupported claim. |

Across the set: all 5 verdicts, all 3 evidence roles, all 12 concern types, and 3 warning codes. `span_out_of_range` and `input_truncated` are left out on purpose, because a valid fixture cannot contain an out-of-range span.

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
