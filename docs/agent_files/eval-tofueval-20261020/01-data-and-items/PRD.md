---
status: draft
summary: TofuEval data download + verification, 1,777 summary items, transcript-to-turns and sentence-offset assessment builders, all request-schema-valid; no projection or metrics.
date: 2026-10-20
---
# PRD: C1 TofuEval data & items

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: B2 (adapter protocol, `metadata.json` loader, download framework, `select`), B4 (UI Download button calls it) · Owns: `eval/datasets/tofueval/{metadata.json, adapter.py, download.py, items.py, transcripts.py, assessment.py}`, `eval/tests/datasets/tofueval/` incl. `fixtures/` (fictional)

## TL;DR
Turn the three public sources into 1,777 audit requests. `download.py` fetches the pinned TofuEval commit plus the MediaSum and MeetingBank files into gitignored `eval/data/tofueval/`, proves all 100 doc ids resolve, and records hashes. `items.py` groups CSV rows into summary items with per-sentence gold fields kept intact. `transcripts.py`/`assessment.py` build schema-valid `transcript` turns and a one-section `assessment` with a verified per-sentence offset map. Gold projection, `mapping.json`, metrics, slices, `references.json` are C2.

## Problem
- Transcripts are not in the TofuEval repo; they come from two third-party datasets with different shapes (named-speaker turns vs one unlabeled blob).
- Summary sentences are separate CSV rows; the audit needs one assessment string and C2 needs each sentence's span in it.
- Source drift, silent id misses, or off-by-one offsets would invalidate every downstream number, so they must fail loudly at build time.

## Goals / Non-Goals
**Goals**
- Reproducible, hash-recorded download; hard error on any unresolved id.
- Deterministic items, ids, turns, offsets (same bytes in, same request out).
- Request validates against `audit-request.schema.json` for all 1,777 items.
- Keep every per-sentence field the GoldPanel (D2) and C2 need.

**Non-Goals**
- `gold()` / `project()`, concern mapping, metrics, slices, references (C2).
- Role/speaker/timestamp inference (ADR 0011; AGENTS.md).
- Completeness data; relabeling; any TofuEval text in prompts or few-shot.
- Committing data or derived text. Source-equality check vs annotated text (owner task).

## Requirements
1. **`metadata.json`** per B2's key table (`02-eval-engine/PRD.md`): `name`, `title`, `description`, `dataset_version`, `kind: "adapter"`, `splits` = `[dev, test]` (`all` is implicit), `default_split: dev`, `cluster_key` (label "source document"; rows cluster on `Item.doc_id`), `license {name, redistributable: false, contains_licensed_text: true}`, `data_required: true`, `test_split_note` (informational, brief #13), `sources[]` (3 entries with pins/`revision` and per-source `license`: MIT-0 with no-training note; research use; CC BY-NC-ND 4.0). Preserved extra keys: `adapter_version` `1.0.0`, `item_unit: summary`, `expected_sha256` (map extracted filename to sha256, filled after the first owner-verified download). C2 adds `levels`, `slices`, `metrics`, `references`, `mapping`, `gold_kind`, `pool_all: false` to this file.
2. **Download** (`download.py`) is the optional adapter hook `download(data_dir, progress) -> list[FileRecord]` (B2 protocol), called by B2's framework/B4 button; the framework writes `download.json` (`not_downloaded|downloading|ready|failed`), and `manifest.json` below is C1's additional, richer file:
   - TofuEval: GitHub zip at commit `17555c5…`; extract only `factual_consistency/*.csv`, `document_ids_dev_test_split.json`, `topic_category/*.json`, `LICENSE`/README. Not `completeness/`.
   - MediaSum `test_data.zip` and MeetingBank `test.json` from Hugging Face, saved as-is.
   - Single streaming pass over each source file keeping only the 50 wanted records; write `derived/transcripts.json` (100 docs: turns-ready fields only).
   - `manifest.json`: source URL/revision, size, sha256 per file, id-resolution counts, timestamp. Re-download compares to `expected_sha256`; mismatch is a hard error.
   - Any of the 100 ids missing, duplicated, or ambiguous -> raise, name the ids, write nothing partial (temp dir + atomic rename).
3. **Items** (`items.py`): load 4 CSVs; group key (dataset, doc_id, topic, model_name) -> 1,777 items; `sent_idx` cast to int and sorted; `topic_category` joined from the JSON (hard error on a missing topic); `split` from the id file; `is_extra = model_name == "Model-Extra"`.
4. **Item fields**, mapped onto B2's `Item`: `id`, `doc_id` (cluster key), `split`; `meta` (slice attributes) = `dataset`, `topic`, `topic_category`, `model_name`, `model_group` (`original_five`|`model_extra`; `is_extra = model_name == "Model-Extra"`), `has_gaps`; `payload` = `{sentences[]}`. Each sentence: `sent_idx`, `text` (verbatim `summ_sent`), `label` (raw `yes`/`no`; C2 normalises to consistent/inconsistent), `types[]` (CSV `type` split on `,`, stripped; raw strings kept), `exp`, `contamination_identifier`, `start`, `end` (offsets, req. 7). `payload` is built in memory from local data and never written to run files.
5. **Item id**: `{dataset}--{doc_slug}--{topic_slug}--{model_slug}` (lowercase, `[^a-z0-9]+` -> `-`, trimmed). Build asserts all ids unique, `doc_id` unique across the 100 docs, and each id matches B2's `[A-Za-z0-9._-]{1,128}` (a longer id fails the build; shortening rule would be a new decision, max length not yet measured). `request_id` is left unset: B2's engine sets `<run_id>:<item_id>`.
6. **Transcript -> turns** (`transcripts.py`), ids `t0..tn`, no `role`, no `timestamp`:
   - MediaSum: one turn per `(speaker[i], utt[i])` in order; speaker verbatim; text verbatim. Assert `len(speaker)==len(utt)` and non-empty speaker.
   - MeetingBank: speaker `"unlabeled"`; blob split into sentences at `(?<=[.!?])\s+`, then greedy-packed into turns of at most **60 words** (whitespace-split), never splitting a sentence (an over-long sentence is its own turn); chunks joined with one space. Frozen at `adapter_version`; any change bumps it. Test asserts chunks concatenated with one space equal the blob with whitespace runs collapsed.
7. **Assessment** (`assessment.py`): one section `{id: "s0", text}`, sentences joined by one space in `sent_idx` order; offsets in Unicode code points via `len()` accumulation; build-time assert `text[start:end] == summ_sent` for every sentence; no `label`/`score`. Gaps in `sent_idx` and duplicate rows are handled per Decisions 7-8.
8. **Request**: `{schema_version, request_id, transcript, assessment}`, `schema_version` read from the loaded schema `const` (1.1.0 after B1), validated with the schema loader B2 provides; invalid = hard error before any send.
9. **Adapter** (`adapter.py`): `items(split)`, `to_request(item)`; `gold`/`project` left to C2. Selection/seeding/N is B2's `select`, clustered by `doc_id`.
10. **Caching/performance**: `derived/transcripts.json` read once per process (lazy singleton); turns built per `(dataset, doc_id)` and memoised; all 1,777 requests build in a few seconds with no network.

## Architecture
```
eval/data/tofueval/            (gitignored)
  repo/{factual_consistency,topic_category}/..  document_ids_dev_test_split.json
  mediasum/test_data.zip   meetingbank/test.json
  derived/transcripts.json     # {"mediasum:CNN-104129": {"speaker":[..],"utt":[..]}, "meetingbank:<uid>": {"transcript": "..."}}
  manifest.json
```
```python
# B2 interfaces (reconciled with 02-eval-engine/PRD.md)
class Item:  id: str; doc_id: str; split: str; payload: Mapping; meta: Mapping
def download(data_dir: Path, progress: Callable) -> list[FileRecord]   # optional adapter hook; framework writes download.json
# readiness = download.json status == ready (framework)
# C1 per-item attrs consumed by C2 / D2
Item.payload['sentences']: list[Sentence]   # Sentence: sent_idx,text,label,types,exp,contamination_identifier,start,end
```
Flow: CSV rows -> `items.py` (group, sort, join) -> `assessment.py` (text + offsets + assert) ; `transcripts.py` (derived cache -> turns) ; `adapter.to_request` assembles and schema-validates.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Sentence order key | `int(sent_idx)`; indices are **1-based**, not 0-based as brief implied `[verified: min sent_idx = 1 in all 1,777 items]` | String sort; assume 0-based | Order defines offsets |
| 2 | Item id | Slug form `ds--doc--topic--model` | Brief's `ds:doc_id:topic:model` | 284 items have doc_ids with spaces (MeetingBank `uid`); colons/spaces are unsafe in B's `items/<id>.json` filenames. Raw `doc_id` stays a field `[verified: 0 slug collisions, 1,777 unique]` |
| 3 | MediaSum trimming | None; use full record | Trim to 800-1,200 words | `[verified: 50 records, 643-976 words, median 768, none >1,200]` so records fit the annotated range |
| 4 | MeetingBank chunk size | 60 words, sentence-bounded | 30/120; one turn per sentence | Naive sentence max 104 words, median longest 54 `[verified]`; 60 keeps evidence spans small yet sentence-whole. Sensitivity run is C2 risk R6 |
| 5 | Sources format | Parse zip/JSONL directly, keep raw files + `derived/` cache | HF `load_dataset` (drops MediaSum `id`) | Brief decision 7 |
| 6 | Transcript text fidelity | Verbatim; no Unicode normalization or whitespace edits except MeetingBank sentence-join | NFC/strip | Offsets and evidence must match source `[verified: MeetingBank 1 non-ASCII blob, MediaSum none]` |
| 7 | `sent_idx` gaps | Allowed; reconstruct from present rows; item flagged `has_gaps` | Drop item; fail build | `[verified: 3 items have gaps, e.g. [1,3], [2], [1,2,4]]`; annotators saw the full summary, so gold context is imperfect for these; C2 reports the flag |
| 8 | Duplicate rows | Same (item, sent_idx) with identical `summ_sent` and label: keep first, record in manifest; any other conflict raises | Keep both | `[verified: exactly 1 duplicate, Model-Extra LongBeach 17-0944 sent 1; differs only in contamination_identifier]` |
| 9 | Embedded newline in a sentence | Keep verbatim | Replace with space | `[verified: 1 sentence, CNN-105920 model_B, "(Source: CNN)\n..."]`; offset assert still holds; no TofuEval text altered |
| 10 | Raw type strings | Keep CSV spellings | Normalize to brief names | CSV has `Tense/Modality Error`, brief says `Tense/Modality` `[verified]`; C2 owns the canonical mapping |
| 11 | `contamination_identifier` | Store per sentence | Per item | `[verified: unique per row; 2-7 distinct values within one item]` |
| 12 | Hash pinning | Hash extracted needed files (repo zip bytes are not stable) | Hash archive | GitHub archives are not byte-stable |
| 13 | HF revision | Resolve and record the HF commit sha at first download, then pin it | Floating `main` | Reproducibility |

## Manual steps (owner)
1. [DEFERRED] **MeetingBank source equality**: confirm HF `huuuyeah/meetingbank` text equals what annotators saw (`lytang/MeetingBank-transcript` per TofuEval README, field `source`, `meeting_id`) for a handful of ids; also spot-check a few "no" explanations against the text.
2. Run the first UI download; review `manifest.json`; commit the confirmed `expected_sha256` values to `metadata.json`.
3. Accept licenses (MediaSum research-use, MeetingBank CC BY-NC-ND 4.0); data stays local.

## Risks / Open Questions
- [DEFERRED] Annotated text vs HF sources (manual step 1). Downstream results carry this caveat until closed.
- [OPEN] Paper says segments average 970 (MediaSum) / 930 (MeetingBank) words; sources measure 778 / 752 whitespace words. Ratio 1.25 / 1.24 suggests the paper counted tokens `[verified: counts; token explanation is inference, untested]`. Cheapest test: tokenise the 100 docs with a common tokenizer and compare to 970/930.
- [OPEN] MediaSum `ccdv/mediasum` vs original `news_dialogue.json` equality (TofuEval README uses the original). Cheapest test: owner diffs 3 ids.
- [RESOLVED: reconciled with `02-eval-engine/PRD.md`] B2 interface names (Item payload/meta, download hook, split names, metadata keys).
- [OPEN] Audit deadline: ADR 0008 says 60 s but `config.py` `audit_deadline_s` is 100 s [verified; see B2 Risks]. ~750-1,000-word transcripts with up to 63 turns (MediaSum) or ~15 MeetingBank chunks may hit it and return `partial`/timeouts. Cheapest test: 5-item live dev run.
- [RESOLVED: raw `uid` match, 50/50 found, 244 double-space occurrences are in text, not ids] MeetingBank ids with spaces. IDs are matched exactly `[verified]`.
- [RESOLVED: all 50 ids present, none duplicated] MediaSum `id` coverage `[verified]`.
- [RESOLVED: 100 unique ids globally] `doc_id` safe as cluster key across datasets.
- [OPEN] MediaSum speaker strings may include generic labels (e.g. "Unidentified Male"); passed through as supplied, which is allowed but may affect attribution checks.
- [OPEN] `leakage.toml` `scored_dirs` covers `backend/eval/*` only, not root `eval/data/tofueval` (see B2 Risks). Extending it edits backend files; owner decides. Real data first exists after this project's first download.

## Acceptance Criteria
- Fixture tests (small fictional CSV + JSONL + zip shaped like the real sources, no real text committed) cover: sort by int (10 after 9), gaps, duplicate row, embedded newline, missing id -> error, missing topic -> error, id slug uniqueness, offset assert, MeetingBank splitter (60-word cap, over-long sentence, reconstruction), MediaSum turn mapping.
- `to_request` output validates against the loaded request schema for every fixture item.
- Real-data smoke (local, after download): 1,777 items (split by doc: dev 70 docs, test 30 docs; dev 3,437 / test 1,510 rows), 4,947 rows, 966 "no", 1,479 original-five items, all 100 ids resolved, all requests schema-valid, all offset asserts pass.
- Re-running download with unchanged sources yields identical hashes; tampered file is rejected.
- No file under `eval/data/` or any TofuEval text is tracked by git; no TofuEval text in prompts.
