# Fictional source fixtures

All document IDs, topics, utterances, summaries, explanations, annotation IDs, and
contamination identifiers here were invented for offline tests. They contain no
TofuEval, MediaSum, or MeetingBank source text. Speaker labels describe fictional
fixture speakers; repeated generic labels deliberately remain identical. These
files are test inputs, not benchmark examples or evidence about real people.

The directory mirrors the C1 local-data layout:

- `repo/factual_consistency/`: four CSVs, one per dataset and split, with the
  upstream ten-column header. Nine rows represent five summary items over four
  source documents, including one duplicate.
- `repo/topic_category/`: flat topic-string to `main`/`marginal` maps.
- `repo/document_ids_dev_test_split.json`: split first, then dataset, then a list
  of raw document IDs: `{ "dev": { "mediasum": [...], "meetingbank": [...] },
  "test": { "mediasum": [...], "meetingbank": [...] } }`.
- `mediasum/test_data.zip`: one `test_data.txt` member containing JSONL records
  with `id`, `program`, `date`, `url`, `title`, `summary`, `utt`, and `speaker`.
  Every field is a string except the two parallel arrays of strings, `utt` and
  `speaker`. Dates are deliberately empty; URLs use `example.invalid`.
- `meetingbank/test.json`: **JSONL**, despite its extension. Records have string
  `summary`, `uid`, and `transcript` fields and an integer `id`. Match annotation
  document IDs to raw `uid` values, which contain spaces, rather than numeric `id`.

Structural provenance: the C1 PRD and
`docs/agent_files/eval-tofueval-20261020/brainstorming.md` document the chosen
sources and record shapes. Header, JSON key/type, split nesting, category values,
and archive-member details were also checked offline against the existing
investigation cache at
`/tmp/claude-0/-root-projects-iaudit/10b60fb9-9326-40a5-b4ec-80133a355920/scratchpad/tofu/data/`:
`tofueval/` (pinned annotation snapshot), `src/ms_test.zip`, and `src/mb_test.json`.
Only structural metadata was inspected/output for this task; no cached source
content was copied. In particular, the MediaSum `title` field and `.txt` JSONL
member supplement the abbreviated record-key list in the brainstorm. Tests must
not depend on this temporary cache being present.

Edge cases retained for later adapter tests:

- MediaSum development rows arrive in `10, 1, 9` order, exposing string sorting
  and gaps. Sentence 1 contains an embedded newline and non-ASCII `café`.
- MeetingBank development `Model-Extra` has indices `1, 1, 3`; the duplicate
  index 1 differs **only** in `contamination_identifier`, with the first row
  carrying `fictional-first` and the duplicate `fictional-duplicate`.
- A separate MeetingBank development topic produces an unshortened item ID
  longer than 128 characters.
- MediaSum development repeats `Unidentified Male`; these are the same label,
  with no inferred identity or role.
- MeetingBank development has a 70-word sentence plus two 35-word sentences,
  exercising sentence preservation above 60 words and packing boundaries below
  that threshold. Transcripts include repeated whitespace and newline/tab runs.
- Both datasets and both splits are populated, both topic categories occur,
  and raw error types include a comma-separated multi-label cell.

Missing-ID, missing-topic, conflicting-duplicate, and hash-tampering tests can
mutate temporary copies of these inputs. No live requests, downloads, or LLM calls
are needed to load them.
