---
status: draft
summary: Eight tasks for the TofuEval adapter data layer: metadata, fictional fixtures, assessment offsets, items, transcript turns, download, adapter assembly, leakage guard.
date: 2026-10-20
---
# Tasks: C1 TofuEval data & items

Source of truth: [PRD.md](PRD.md). Builds the TofuEval download, 1,777 summary items, turn builders and sentence-offset assessment, all schema-valid. Everything is tested offline on fictional fixtures; no real data download, no live LLM calls, no pilot runs (owner checks, see end). Gold projection, metrics and slices are C2.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Dataset `metadata.json` | none | done |
| 2 | Fictional test fixtures | none | done |
| 3 | Assessment builder with offset map | 2 | done |
| 4 | Items: grouping, ids, sentence fields | 1, 2, 3 | done |
| 5 | Transcript to turns | 2 | done |
| 6 | Download hook, manifest, derived cache | 1, 2 | in-progress |
| 7 | Adapter assembly and request validation | 4, 5, 6 | todo |
| 8 | Leakage guard extension | none | in-progress |

## Task 1 — Dataset metadata
What it is / what it means: The declarative description B2's loader and B4's Download button read (Req 1, Decision 13).
What changes at a high level: Add `metadata.json` for `tofueval` per B2's key table: splits `dev`/`test`, default `dev`, cluster key on source document, non-redistributable license block, `data_required`, `test_split_note`, three sources with pins and per-source licenses, plus `adapter_version` 1.0.0, `item_unit: summary`, and an empty `expected_sha256` map. The HF revision is a resolve-at-first-download placeholder. C2 keys are not added.
Done when: B2's metadata loader accepts the file in an offline test and the listed preserved keys are present.

## Task 2 — Fictional fixtures
What it is / what it means: Small invented data shaped like the three real sources, so every later test runs offline (Acceptance: fixture tests; no real text committed).
What changes at a high level: Add `eval/tests/datasets/tofueval/fixtures/` with a tiny CSV set, topic-category and dev/test id JSONs, a MediaSum-shaped zip, and a MeetingBank-shaped JSON. Cover the edge cases: int sort (10 after 9), sent_idx gaps, one duplicate row, an embedded newline, a long-id item, an over-long MeetingBank sentence, generic speaker labels.
Done when: fixtures load, contain no real TofuEval/MediaSum/MeetingBank text, and each edge case is present.

## Task 3 — Assessment builder
What it is / what it means: One section whose text is the summary sentences joined, with verified offsets (Req 7, Decisions 1, 7, 9).
What changes at a high level: Build `{id: "s0", text}` joining sentences with one space in int `sent_idx` order; compute start/end in code points; assert `text[start:end]` equals the sentence for every sentence; no label or score in the request. Gaps use present rows only; embedded newlines stay verbatim.
Done when: fixture tests cover sort order, gaps, newline and the offset assert, including a deliberately corrupted case that raises.

## Task 4 — Items
What it is / what it means: The 1,777 summary items with all per-sentence gold fields kept raw (Req 3-5, Decisions 2, 8, 10, 11).
What changes at a high level: Load the four CSVs, group by dataset/doc/topic/model, join topic category (hard error if missing), set split from the id file, derive `model_group`, `is_extra` and `has_gaps`. Sentences carry raw label, split types, exp, contamination id and offsets. Slug ids with the 128-char hash-suffix guard; assert id and doc_id uniqueness. Duplicate rows: keep first if identical text and label, record it, otherwise raise.
Done when: fixture tests cover duplicate handling, missing topic error, slug uniqueness, and a long id shortened deterministically to at most 128 chars and stable across runs.

## Task 5 — Transcript to turns
What it is / what it means: Schema-ready turns with no inferred role, speaker or timestamp (Req 6, Decisions 3, 4, 6).
What changes at a high level: MediaSum maps each speaker/utterance pair verbatim to a turn (length and non-empty speaker asserts; same label is one speaker). MeetingBank uses speaker "unlabeled", sentence split, greedy 60-word packing, over-long sentence alone, chunks joined by one space. Turn ids `t0..tn`; per-document memoisation.
Done when: tests cover the 60-word cap, the over-long sentence, blob reconstruction with collapsed whitespace, and the MediaSum mapping.

## Task 6 — Download hook
What it is / what it means: The reproducible, hash-recorded fetch B2's framework and B4's button call (Req 2, Decisions 5, 12, 13).
What changes at a high level: Implement `download(data_dir, progress)` returning file records: pinned TofuEval extraction (no `completeness/`), MediaSum and MeetingBank files saved as-is, a single streaming pass that keeps the 50 wanted records per source and writes `derived/transcripts.json`, and `manifest.json` (URLs, revision, sizes, hashes, id-resolution counts, duplicates, timestamp). Compare against `expected_sha256`; any mismatch or missing/duplicate/ambiguous id raises naming the ids. Write via temp dir plus atomic rename.
Done when: fixture tests (network faked) show a tampered file is rejected and a failed resolution leaves nothing partial.

## Task 7 — Adapter assembly
What it is / what it means: The B2 adapter surface that C2 and the UI build on (Req 8-10).
What changes at a high level: `adapter.py` exposes `items(split)` and `to_request(item)`; the request is `{schema_version, request_id unset, transcript, assessment}` with the version read from the loaded schema const and validated with B2's loader (invalid raises before any send). `derived/transcripts.json` loads once lazily; payload stays in memory only. `gold`/`project` are left to C2.
Done when: every fixture item's request validates, and a timing check on fixtures shows no network access.

## Task 8 — Leakage guard extension
What it is / what it means: Keep TofuEval text out of prompts (Req 11, Acceptance last bullet).
What changes at a high level: Add one entry to `backend/eval/leakage.toml` reaching root `eval/data`; adjust the loader only if the test cannot resolve the relative path. Other keys untouched.
Done when: `test_prompt_leakage` resolves the path and skips cleanly with data absent; a temporary fixture file placed there is scanned in a throwaway test.

## Owner manual checks (not tasks)
- Run the first UI download, review `manifest.json`, commit confirmed `expected_sha256` values to `metadata.json`; accept the MediaSum and MeetingBank licenses.
- Real-data smoke: 1,777 items, 4,947 rows, 966 "no", 1,479 original-five items, dev 70 / test 30 docs, all 100 ids resolved, all requests valid, all offset asserts pass; re-download gives identical hashes.
- `test_prompt_leakage` passes with real data present.
- 5-item pilot run: items run end to end, results appear in the UI, observe long-transcript deadline behaviour.
- [DEFERRED] MeetingBank source equality against `lytang/MeetingBank-transcript` and spot-check of "no" explanations.
