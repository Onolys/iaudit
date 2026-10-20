---
status: approved
summary: TofuEval dataset plug-in for the eval framework - one item per summary, sentence-offset projection of iAudit claim verdicts, binary + per-type recall + 5-type concern agreement, dev/test discipline.
date: 2026-10-20
---

# TofuEval plug-in (project C)

## 1. TL;DR

- Add `eval/datasets/tofueval/` as a plug-in on the project B framework. One item = one summary (doc_id, topic, model_name): 1,777 items.
- Assessment = reconstructed summary, sentences ordered by numeric `sent_idx`, with a per-sentence character-offset map. Transcript = source document (shared across items).
- iAudit claim verdicts are projected back to sentences by span overlap. Sentence inconsistent if any mapped claim is `contradicted`/`partially_supported`/`insufficient_evidence`. Summary inconsistent iff any sentence is.
- Metrics: sentence- and summary-level balanced accuracy, inconsistent-class P/R/F1, recall by all 7 native error types, concern agreement for 5 clean types only (frozen `mapping.json`).
- Splits: dev (70 docs) / test (30 docs) / all. Mapping frozen and versioned before any test run. Tuning on dev only.
- Data never committed. Download button fetches pinned TofuEval repo + MediaSum + MeetingBank files.
- TofuEval validates binary detection and 5 concern types. It cannot validate 3 concerns (question_as_answer, correction_ignored, conflicting_accounts_flattened) or the four-way verdict.

## 2. Problem

INVESTIGATION.md sec 5 picks TofuEval as the primary natural-dialogue factuality benchmark but stops at policy. This doc turns that into a buildable plug-in design.

Hard parts:
- TofuEval is sentence-level binary gold. iAudit emits atomic claims with four-way verdicts and 12 concerns. A projection is needed in both directions.
- Source transcripts are not in the TofuEval repo. They must be fetched from two third-party datasets with different structures (speaker-labelled turns vs one unlabeled blob).
- The product must not guess speakers or roles (ADR 0011).
- Dev/test discipline must be enforced by process, since the mapping and projection rules are researcher degrees of freedom.

## 3. Decision log

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| 1 | Item = one summary (doc_id, topic, model_name); 1,777 items | One item per sentence; one per document | iAudit audits a whole assessment against the transcript. Sentence items would drop summary context and inflate cost. Per-document items would mix topics. |
| 2 | Sentences ordered by numeric `sent_idx` | String sort of the CSV column | String sort puts 10 before 2. Order defines offsets. |
| 3 | Assessment = reconstructed summary with per-sentence offset map | Send sentences separately | Gold labels were made with the whole summary visible. Keeps annotator context. |
| 4 | Source transcript shared across items | Duplicate per item | Same doc has 3 topics x ~6 models. Cache once. |
| 5 | Splits dev (70 docs) / test (30 docs) from `document_ids_dev_test_split.json`, plus "all" | Own random split | Matches paper's test set so references.json rows are comparable. Doc-level split avoids leakage across topics. |
| 6 | Report original-five models vs Model-Extra separately | Pool all six | Paper covers five only. Pooling breaks comparability. |
| 7 | MediaSum from HF `ccdv/mediasum` `test_data.zip` (33.9 MB, JSONL) parsed directly | HF `load_dataset`; MediaSum GitHub `news_dialogue.json` | HF loader drops `id`. Zip is small and all 50 ids present. |
| 8 | MeetingBank from HF `huuuyeah/meetingbank` `test.json` (13.4 MB), match on `uid` | TofuEval README snippet (`lytang/MeetingBank-transcript`, `meeting_id`) | Chosen source verified to contain all 50 ids; see risk R1 on equality with annotated text. |
| 9 | Download button fetches pinned TofuEval commit `17555c5` + the two files | Vendor data into repo; floating `main` | Licenses forbid redistribution. Pin gives reproducibility. |
| 10 | MediaSum: real speaker names as `speaker`; no `role` | Guess interviewer/respondent | ADR 0011: role optional, never guessed. |
| 11 | MeetingBank: single speaker `"unlabeled"`, text split into sentence-chunk turns | Invent speakers; one giant turn | Blob has multiple real but unlabeled speakers. Inventing is forbidden. Chunking keeps evidence spans small. |
| 12 | `wrong_attribution` concern-match scored on MediaSum only; binary and per-type recall on both | Score attribution on both | With one placeholder speaker, attribution is not checkable on MeetingBank. |
| 13 | Sentence inconsistent if any mapped claim is contradicted / partially_supported / insufficient_evidence | Only `contradicted`; majority vote | Gold "no" = not stated or implied. insufficient_evidence and partial both mean that. Any-claim rule follows how a sentence with one bad fact is labelled. |
| 14 | Sentence consistent if all mapped claims supported | Require coverage threshold | Coverage cannot prove atomization. Diagnostics reported separately. |
| 15 | out_of_scope-only sentences count as consistent; count reported | Unresolved; drop | Meta sentences ("The document discusses X", ~19% of dev "yes" sentences) are labelled consistent by annotators. Counting unresolved would punish correct behavior. See R4. |
| 16 | Unmapped / failed sentence = unresolved, wrong in primary | Drop from denominator; default consistent | Matches B's policy: failures count wrong in primary, secondary excludes them. |
| 17 | Summary inconsistent iff any sentence inconsistent | Direct whole-summary prediction | Same aggregation as the paper (sec 3.4) and INVESTIGATION 5.2. |
| 18 | Claim-to-sentence by span overlap; frozen rules for boundary-crossing claims | Embedding / LLM alignment | Deterministic, auditable. |
| 19 | Concern agreement for 5 clean types via `mapping.json`, any-predicted-in-allowed-set | Map all 7; strict one-to-one | NMS and RE are too mixed to map honestly. Any-in-set tolerates iAudit emitting extra concerns. |
| 20 | NMS and Reasoning Error: recall only | Force a mapping | See above. |
| 21 | Slices: dataset, main/marginal topic, model, contamination flag | Aggregate only | Paper shows ~10 pt main-vs-marginal gap. Needed for comparison and diagnosis. |
| 22 | references.json holds paper-reported numbers as greyed rows "paper-reported, different model & date" | Omit; mix into live results | Context without implying same-conditions comparison. |
| 23 | Mapping frozen and versioned before any test run; tuning on dev only | Iterate on all data | Prevents test leakage. |
| 24 | No TofuEval text in prompts or few-shot | Use dev examples as few-shot | Benchmark is no-training; leakage would invalidate dev too. |

## 4. Background: how TofuEval was built

All figures from the paper (NAACL 2024) and repo at `17555c5`; row counts from the CSVs.

| Aspect | Fact |
|---|---|
| Documents | 100: 50 MediaSum (NPR/CNN interviews), 50 MeetingBank (city council). Segments 800-1,200 words (avg 970 / 930 per Table 5). |
| Topics | 3 LLM-generated topics per doc. Annotators classed each main or marginal (merged {marginal, irrelevant}). Repo `topic_category/{dataset}_topic_category.json` maps topic string to main/marginal; 150 unique topic keys per dataset, no cross-doc collisions. |
| Summaries | Topic-focused, under 50 words, from 5 LLMs in the paper; repo adds `Model-Extra`. |
| Sentence label | Professional linguists, per sentence, whole summary visible. Consistent if "stated or implied" by the document. |
| Agreement | Cohen's kappa 0.42 (MediaSum), 0.34 (MeetingBank). Authors ran a second-stage review removing false-positive labels. So "no" labels are fairly reliable; some "yes" may hide errors. |
| Error types | Taxonomy from Tang et al. 2022 (SAMSum), extended from explanations (added Reasoning Error, Stating Opinion as Fact). Assigned post hoc by the author-linguists from summary + explanation (source only if needed). Multi-label. Fleiss kappa 0.78 on pilot. "Others" unused. |
| Granularity | Category is per sentence only. No spans. The `exp` prose names the wrong part. |
| Multi-label | 25 of 966 inconsistent rows carry 2+ types. |
| Counts, all splits | 4,947 rows, 966 "no" (inconsistent), 1,777 summaries. |
| Counts by type (tag assignments) | Extrinsic 467; Nuanced Meaning Shift 154; Reasoning Error 149; Mis-Referencing 111; Opinion as Fact 42; Tense/Modality 39; Contradiction 30. |
| Split counts | Dev 3,437 rows / 644 "no" (70 docs). Test 1,510 rows / 322 "no" (30 docs). |
| Limitations | No cross-sentence errors, no severity, English only. |
| Paper vs release | Paper: 1,479 summaries, 3,966 sentences (five models). Release adds Model-Extra. Keep the one-row discrepancy (INVESTIGATION 5.1). |
| Terms | Annotations MIT-0 with a "do not train" note. MediaSum research-use. MeetingBank CC BY-NC-ND 4.0. |

Session probe, not gold: an LLM judged 84 dev "no" rows for iAudit-concern fit. EI to unsupported_claim 11/12; MR to wrong_attribution 9/12; TAM to timeframe 11/12; OF to certainty_inflation 12/12 (+attribution 7); CO to contradictory/negation 8/12; NMS and RE scattered; ~15% fit no concern (wrong number, wrong object/action, overgeneralization, merged facts). This informs the mapping below but does not validate it.

## 5. Design

### 5.1 Item construction

| Field | Value |
|---|---|
| Group key | (doc_id, topic, model_name) across the 4 CSVs |
| Item id | `{dataset}:{doc_id}:{topic_slug}:{model_name}` (slug deterministic) |
| Sentence order | integer sort on `sent_idx` |
| Split | dev/test from `document_ids_dev_test_split.json`; "all" = both |
| Item fields kept | dataset, doc_id, topic, topic_category (main/marginal), model_name, `contamination_identifier`, per-sentence label/type/exp |
| Selection | B's split + optional N seeded sample (sample by doc cluster, not by item, to keep CIs honest) |

### 5.2 Source acquisition (Download button)

| File | Source | Notes |
|---|---|---|
| TofuEval annotations | Pinned git commit `17555c5` of amazon-science/tofueval | Includes `topic_category`, split json |
| MediaSum | HF `ccdv/mediasum` `test_data.zip` | JSONL keys `id, program, date, url, summary, utt, speaker`. Parse directly (loader drops `id`). Keep only the 50 ids. |
| MeetingBank | HF `huuuyeah/meetingbank` `test.json` | JSONL keys `summary, uid, id, transcript`. Match TofuEval ids on `uid` (some contain spaces; match exactly, no trimming rules beyond what is verified). |

Everything lands in gitignored `eval/data/tofueval/`. Download verifies all 100 ids are present and records file hashes in the run manifest. Missing id = hard error, not silent skip.

### 5.3 Transcript to turns adapter

| Dataset | Turn rule | speaker | role |
|---|---|---|---|
| MediaSum | One turn per `(speaker[i], utt[i])` pair, in order | Name as given | omitted (ADR 0011) |
| MeetingBank | Split blob into sentence-chunk turns (deterministic splitter, fixed max ~N words, never mid-sentence) | `"unlabeled"` | omitted |

- Turn ids `t0..tn`. No `timestamp` (not supplied; never inferred).
- Both outputs validate against `audit-request.schema.json` (`speaker` minLength 1, `role` optional).
- Splitter rule is frozen in the adapter version; changing it bumps `adapter_version`.
- Consequence: MeetingBank evidence spans are chunk-level. Checks that need speaker identity yield warnings or insufficient_evidence, which count against the system. Report MeetingBank separately for this reason.

### 5.4 Assessment construction with sentence offsets

- `assessment` = one Section (single section is valid per schema): sentences joined by a single space, in `sent_idx` order. No label/score fields.
- Offset map per item: `[{sent_idx, start, end}]`, code-point offsets into the section text (the contract counts code points).
- Sentence text is used verbatim from `summ_sent`; nothing is normalized except the join. Assert `text[start:end] == summ_sent` at build time.

### 5.5 Projection rules

| Step | Rule |
|---|---|
| Claim to sentence | Claim span overlap with sentence span. Assign to the sentence with maximal overlap. |
| Boundary-crossing claim (frozen) | Overlap tie or spanning: assign to every sentence it overlaps by at least 1 code point. For the inconsistent rule it flags all overlapped sentences; for the consistent rule it must be `supported` for all. |
| Sentence inconsistent | Any mapped claim in {contradicted, partially_supported, insufficient_evidence} |
| Sentence consistent | At least one mapped claim, all `supported` |
| Sentence consistent (meta) | Only out_of_scope claims mapped. Counted consistent; tally reported (`meta_consistent_n`). |
| Sentence unresolved | No mapped claim at all, or response failed/empty. (Supported + out_of_scope mix, none flagged: consistent, supported claims decide.) |
| Summary inconsistent | Any sentence inconsistent |
| Summary consistent | All sentences consistent |
| Summary unresolved | No inconsistent sentence and at least one unresolved |
| Scoring of unresolved | Primary: wrong. Secondary: excluded. Per B. |

Rule precedence: inconsistent beats unresolved beats consistent at the summary level.

### 5.6 Metrics and slices

| Metric (registry name) | Level | Notes |
|---|---|---|
| `bacc_sentence`, `bacc_summary` | sentence, summary | Balanced accuracy, 50% = constant baseline |
| `prec_inconsistent`, `rec_inconsistent`, `f1_inconsistent` | both | Inconsistent = positive |
| `recall_by_type` x 7 | sentence | Recall of "no" rows tagged with that type; multi-label rows count in every type they carry |
| `concern_match_rate` x 5 types | sentence | Among gold sentences with the type: fraction where any predicted concern on a mapped claim is in the allowed set |
| `unresolved_rate`, `meta_consistent_n` | both | Coverage / policy diagnostics |
| `claims_per_sentence`, `unmapped_claim_rate` | diagnostic | Adapter health |

- CIs: doc-clustered bootstrap (B default; cluster = source document, since topics and models share a source).
- Slices: dataset (mediasum/meetingbank), topic category (main/marginal), model_name, contamination flag, original-five vs Model-Extra.
- Contamination flag: the `contamination_identifier` is kept per row for web-crawl detection. The slice is a run-level flag on the audited model (release/cutoff vs 2024-03 publication) set by the operator, not computed from the data.
- Type recall n is small for Contradiction (30), Tense/Modality (39), Opinion as Fact (42). CIs will be wide; render n next to every value.

### 5.7 `mapping.json` content (versioned, frozen before test)

```json
{
  "mapping_version": "1.0.0",
  "semantics": "gold type matches if ANY predicted concern on a claim mapped to the sentence is in the allowed set",
  "types": {
    "Extrinsic Information":    {"allowed": ["unsupported_claim"]},
    "Mis-Referencing":          {"allowed": ["wrong_attribution"], "datasets": ["mediasum"]},
    "Tense/Modality":           {"allowed": ["timeframe_mismatch", "certainty_inflation"]},
    "Stating Opinion as Fact":  {"allowed": ["certainty_inflation", "wrong_attribution"],
                                "dataset_overrides": {"meetingbank": ["certainty_inflation"]}},
    "Contradiction":            {"allowed": ["contradictory_evidence", "negation_reversal"]},
    "Nuanced Meaning Shift":    {"allowed": null, "recall_only": true},
    "Reasoning Error":          {"allowed": null, "recall_only": true}
  }
}
```

`wrong_attribution` is unscorable on MeetingBank (single placeholder speaker), so the `dataset_overrides` entry drops it there. Mis-Referencing is not scored for concern match on MeetingBank at all (recall only). Both rules are part of frozen v1.0.0.

### 5.8 `references.json` content

Paper-reported test-set balanced accuracy, Table 3 (sentence-level, then summary-level; MediaSum/MeetingBank x main/marginal). Values below were read from the text extraction of the paper. Column order follows the table header (Sentence: MS main, MS marginal, MB main, MB marginal; Summary: same). Re-verify against the PDF layout before shipping (R7).

| Evaluator | Sent MS main | Sent MS marg | Sent MB main | Sent MB marg | Summ MS main | Summ MS marg | Summ MB main | Summ MB marg |
|---|---|---|---|---|---|---|---|---|
| AlignScore | 69.2 | 76.2 | 61.2 | 78.6 | 65.5 | 72.1 | 63.4 | 71.8 |
| GPT-4 | 64.9 | 80.2 | 67.5 | 90.3 | 63.7 | 78.9 | 74.7 | 83.1 |
| GPT-3.5-Turbo | 61.6 | 68.9 | 56.0 | 65.0 | 59.6 | 65.8 | 63.2 | 65.7 |
| SummaC-ZS | 66.1 | 73.9 | 63.9 | 80.6 | 62.7 | 64.1 | 58.1 | 72.4 |
| Baseline (constant) | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |

- Include remaining Table 3 rows (SummaC-CV, QAFactEval, Vicuna, WizardLM) in the file; omitted here for length.
- Each row label: "paper-reported, different model & date"; LLM numbers are averages of 3 runs, gpt-4-0613.
- Rendered greyed, no CI, never ranked against live runs. Aggregation caveat: paper LLM summary labels come from aggregated sentence labels, matching our rule.
- Paper evaluation is per-document/per-sentence with provided source; our setting adds claim atomization and projection, so equivalence is not claimed.

### 5.9 `metadata.json` sketch

```json
{
  "name": "tofueval",
  "version": "1.0.0",
  "adapter_version": "1.0.0",
  "splits": ["dev", "test", "all"],
  "item_unit": "summary",
  "cluster_key": "doc_id",
  "sources": [
    {"id": "tofueval", "repo": "amazon-science/tofueval", "commit": "17555c5bfc27f95371fd82b2de7014d8e14e1024", "license": "MIT-0 (no-training note)"},
    {"id": "mediasum", "hf": "ccdv/mediasum", "file": "test_data.zip", "license": "research use"},
    {"id": "meetingbank", "hf": "huuuyeah/meetingbank", "file": "test.json", "license": "CC BY-NC-ND 4.0"}
  ],
  "redistribute": false,
  "slices": ["dataset", "topic_category", "model_name", "contamination"],
  "mapping": "mapping.json",
  "references": "references.json",
  "data_dir": "eval/data/tofueval"
}
```

## 6. Category crosswalk and what TofuEval can/cannot validate

Builds on INVESTIGATION 5.4.1 (interpretive crosswalk). This doc does not contradict it; it adds a frozen operational subset for scoring.

| TofuEval type | Allowed iAudit concerns (scored) | Status vs INVESTIGATION | Scored as |
|---|---|---|---|
| Extrinsic Information | unsupported_claim | "Broad analogue" kept | Concern match + recall |
| Mis-Referencing | wrong_attribution | "Partial overlap" kept; MediaSum only | Concern match (MS) + recall |
| Tense/Modality | timeframe_mismatch, certainty_inflation | Matches TAM partial overlap; adds certainty_inflation | Concern match + recall |
| Stating Opinion as Fact | certainty_inflation, wrong_attribution | Consistent with OF row | Concern match + recall |
| Contradiction | contradictory_evidence, negation_reversal | Consistent | Concern match + recall |
| Nuanced Meaning Shift | none | Consistent (no honest map) | Recall only |
| Reasoning Error | none (unsupported_causal_link is partial only) | Consistent | Recall only |

Only 5 of 12 concerns can be exercised at all, and only through agreement, not gold.

| iAudit capability | TofuEval can validate? | Remark |
|---|---|---|
| Binary unfaithful-content detection | Yes, after projection | Main result |
| Concern types: unsupported_claim, wrong_attribution (MS), timeframe_mismatch, certainty_inflation, contradictory_evidence, negation_reversal | Weakly (agreement with mapped types) | Label noise and many-to-many mapping |
| frequency_severity_inflation, context_stripping, unsupported_causal_link | Not directly | Only via RE/NMS recall |
| question_as_answer, correction_ignored, conflicting_accounts_flattened | No (<=4% keyword hits in probe) | Needs another dataset |
| Four-way verdict | Collapsed only | No claim about partial vs insufficient vs contradicted |
| Claim atomization | No | Diagnostics only |
| Evidence selection quality | No gold offsets | Sentence overlap only |
| About 15% of errors fit no concern | Identified | Taxonomy work in project A |

## 7. Scientific-integrity rules

1. `mapping.json` and projection rules are frozen and versioned before the first test-split run. Any change after bumps the version; old test results are labelled with the old version and not mixed.
2. Prompt tuning, threshold choices, error analysis: dev only. Test runs are for reporting. Record the test-run count.
3. No TofuEval text (summaries, explanations, transcripts) in prompts, few-shot examples, or tuning sets. Do not train on it.
4. Failures count wrong in primary; secondary excludes them and says so. Report both.
5. Report original-five and Model-Extra separately; never pool in headline numbers.
6. Reference rows are context, never a leaderboard.
7. Never commit data or derived text. Reports may include ids, counts, and labels, not source or summary text beyond what each license allows (default: none).
8. No invented quotes, speakers, or timestamps. MeetingBank uses `"unlabeled"`; MediaSum uses supplied names only.
9. Judge-free: primary metrics use only released human labels. LLM probes (like the 84-row sample) are labelled as such and not gold.
10. Disclose label noise (kappa 0.34-0.42) next to headline numbers.

## 8. Non-goals

- No new human annotation, no relabeling of TofuEval.
- No claim of four-way verdict validation or complete atomization validation.
- No explanation-quality automatic metric (Appendix H is a human rubric).
- No completeness / key-point scoring.
- No product change (mission, concerns, schema). Uncovered concerns go to project A and other datasets.
- No cross-sentence error evaluation (not in gold).
- No attribution scoring on MeetingBank; no role inference.
- No redistribution of source data.

## 9. Open risks with cheapest tests

| # | Risk | Cheapest test |
|---|---|---|
| R1 | HF source records may differ from the 800-1,200-word segments annotators saw (MediaSum full transcripts may be longer; MeetingBank blob may be a different cut). | Compute word counts for all 100 docs; compare to Table 5 averages (970 / 930) and the 800-1,200 range. Check TofuEval README snippet's source (`lytang/MeetingBank-transcript`) against `huuuyeah/meetingbank` text for the same ids. Spot-check a few "no" explanations against the text. |
| R2 | Label noise (kappa 0.34-0.42) caps achievable accuracy; some "yes" hide errors. | Report precision with this caveat; hand-inspect 20 false positives on dev to estimate how many are gold misses. |
| R3 | Model contamination (benchmark public since early 2024). | Per-run contamination flag; compare against older/open model if available; check contamination_identifier is not echoed. |
| R4 | Meta-sentence policy ("The document discusses X") changes results; ~19% of dev "yes" sentences. | Run dev scoring both ways (out_of_scope as consistent vs unresolved) and report the delta; policy stays as decided. |
| R5 | Claim to sentence mapping errors (paraphrased claims, bad offsets). | Measure `unmapped_claim_rate` and boundary-crossing frequency on a 20-item dev sample before test. |
| R6 | MeetingBank chunking affects evidence quality and the splitter choice is arbitrary. | Run a dev subset with two chunk sizes; if binary BAcc moves more than the CI, document sensitivity. |
| R7 | Table 3 column assignment was inferred from text extraction. | Open the PDF page (p. 4460) and confirm header order against each row; also re-verify Table 3 caption states test set only. |
| R8 | Small type strata (CO 30, TAM 39, OF 42) give wide CIs. | Show n and CI always; do not rank types. |
| R9 | `uid` matching with spaces in MeetingBank ids. | Download-time check that exactly 50 ids resolve with exact match; fail loudly otherwise. |
| R10 | Mapping choices (any-in-set) inflate agreement. | Report the base rate: fraction of all predicted concerns falling in the allowed set on consistent sentences. |

## 10. Links

- [eval-core (project B)](../eval-core-20261020/brainstorming.md)
- [eval-ui (project D)](../eval-ui-20261020/brainstorming.md)
- [taxonomy-v1 (project A)](../taxonomy-v1-20261020/brainstorming.md)
- [Evaluation investigation](../users-codex-eval-investigation-20261020-035707/INVESTIGATION.md) (sec 5 and 5.4.1)
- [Mission](../../mission.md), [ADR 0011](../../decisions/0011-role-optional-never-guessed.md), [audit-request contract](../../contracts/audit-request.schema.json)
