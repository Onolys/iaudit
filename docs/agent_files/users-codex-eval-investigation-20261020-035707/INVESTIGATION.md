# Evaluation investigation: reusable evidence without new human annotation

**Status:** research record and recommendations; no benchmark adapters, product changes, or evaluation runs implemented by this task. This is not an approved build plan.

**Branch:** `users/codex/eval-investigation`
**Recorded:** 2026-10-20 UTC
**Audience:** maintainers deciding how to evaluate iAudit beyond its current proof of concept.

## 1. Decisions and constraints to preserve

The user asked to preserve the session's substantive investigation in a document under `docs/agent_files/`, with every document from this session on branch `users/codex/eval-investigation`. This document consolidates the findings, corrections, limitations, and proposed measurement methods so the discussion can be recovered without the chat.

The governing constraint is **no new human annotation resources**. The proposed core evaluation must use existing released labels, deterministic adapters and projections, and, where useful, modified data or constructed tests. A supplementary LLM layer is allowed. An earlier recommendation to commission or require newly human-adjudicated gold is superseded: new human labeling is not a prerequisite for the approach recorded here.

Other constraints and decisions:

- For this investigation, a transcript counts as the interview/audio evidence. Evaluating speech recognition or supporting new recording/file formats is not required.
- The target is fidelity to the supplied source. Medical correctness, diagnosis, scoring, protocol completeness, and real-world truth remain outside the product mission.
- The user is open to additional nonmedical diagnostic categories, such as entity, action, number, or location errors. This is permission to investigate their usefulness, not approval to change the product taxonomy or contracts now.
- Existing labels need not cover every iAudit field for a dataset to be useful. Score the components that the released data actually labels, and state the gaps.
- No audit benchmarks have been run in this investigation. File counts and PriMock alignment figures below are preliminary read-only observations from the session, not iAudit performance measurements.
- A publishable evaluation does not require a particular dataset or a new human-labeling project. It does require a defensible task definition, transparent projections, suitable splits, appropriate uncertainty, and claims bounded by the evidence.

**Current recommendation:** begin with TofuEval for naturally occurring dialogue factuality errors, PriMock57 for clinical relevance, and WiCE for evidence selection and partial support. Add DiaSumFact for dialogue error categories or RAGTruth for output-error localization if those measurements are needed. Treat controlled edits as a separate challenge set.

## 2. Product scope and current implementation

The [mission](../../mission.md) asks whether a written assessment faithfully represents a supplied interview. Findings support human review; they do not automatically change the assessment or establish clinical truth.

The four factual verdicts are `supported`, `contradicted`, `partially_supported`, and `insufficient_evidence`. Outside-scope handling is separate from that four-way factual decision. The [response contract](../../contracts/audit-response.schema.json) defines the twelve concern types:

| Concern type | Mission check |
|---|---|
| `unsupported_claim` | Claim support |
| `contradictory_evidence` | Contradictory evidence |
| `wrong_attribution` | Wrong person or source attribution |
| `timeframe_mismatch` | Timeframe mismatch |
| `negation_reversal` | Negation reversal |
| `certainty_inflation` | Certainty inflation |
| `frequency_severity_inflation` | Frequency or severity inflation |
| `context_stripping` | Context stripping |
| `question_as_answer` | Question mistaken for an answer |
| `correction_ignored` | Correction ignored |
| `conflicting_accounts_flattened` | Conflicting accounts flattened |
| `unsupported_causal_link` | Unsupported causal links |

Not every omission is an error under this mission. Selective summarization is legitimate. An omission belongs in the core audit only when it materially changes a claim the assessment actually makes.

The [architecture](../../architecture.md) consists of prep, atomize, link, check, and assemble stages in Python, with a React review UI. The UI connects exact assessment spans to supporting, contradicting, or qualifying transcript spans. The [request contract](../../contracts/audit-request.schema.json) accepts ordered transcript turns with `id`, `speaker`, and `text`, plus optional supplied role and timestamp, and assessment sections. Positions count Unicode code points. Never infer speaker identities or fabricate timestamps when adapting a dataset.

The [current evaluation documentation](../../testing/evaluation.md) describes the worked ADHD fixture set and `poc-all` split. The [runner](../../../backend/eval/run.py) imports the ADHD data and currently accepts only that fixture set. Its gold, linked, and end-to-end modes provide useful stage separation, but importing another benchmark requires an adapter and runner integration. Existing evidence reports measure turn-level recall and precision; they do not establish exact source-span accuracy. See also the [evaluation directory](../../../backend/eval/README.md) and [scorer](../../../backend/eval/score.py).

The proof of concept is a smoke check on familiar data, not an estimate of performance on new interviews. Nothing in this investigation upgrades that claim.

## 3. What the candidate benchmarks can measure

| Dataset | Main value for iAudit | Released supervision | Main limitation |
|---|---|---|---|
| TofuEval | Natural dialogue factuality; sentence and whole-summary consistency | Human sentence labels, error explanations, seven overlapping error categories | No atomic claim boundaries or structured source-evidence offsets |
| PriMock57 | Clinical consultation-to-note fidelity | Repeated human note reviews, incorrect-statement lists, omissions, post-edited notes | Notes and checklists are not complete claim-level gold; human agreement and alignment vary |
| WiCE | Partial support and source evidence retrieval | Three-way claim/subclaim labels and supporting sentence sets | Wikipedia/article task rather than interview dialogue; no contradiction gold |
| DiaSumFact | Dialogue error types and output-error spans | Human sentence errors, spans, classes, comments | Taxonomy differs from iAudit; no source-evidence gold |
| RAGTruth | Output-error localization and conflict/baselessness distinctions | Human response-error spans with offsets | Mixed tasks, not a dedicated interview benchmark; output spans are not source evidence |
| ACI-Bench | Later source-conditioned constructed challenges | Dialogues and reference notes | No equivalent human factuality-error annotations; base notes are not all verified faithful |

Natural benchmark labels, deterministic projections, and constructed labels must remain distinguishable in reports. A binary sentence label cannot validate all four iAudit verdicts. An output-error span cannot validate the evidence excerpt selected from the source.

## 4. PriMock57: assets, review process, and usable labels

### 4.1 What is in the release

Repository: [babylonhealth/primock57](https://github.com/babylonhealth/primock57), inspected revision [`cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5`](https://github.com/babylonhealth/primock57/tree/cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5). Relevant papers: [PriMock57 dataset paper](https://aclanthology.org/2022.acl-short.65/) and [clinical note evaluation study](https://aclanthology.org/2022.acl-long.394/), also available as [HTML](https://arxiv.org/html/2204.00447v1).

The dataset contains 57 mock, role-played clinician consultations. Assets include audio, manually timed doctor/patient TextGrid transcripts, and original consulting-clinician notes. The notes JSON includes history and impression/plan material. The repository's `scripts/textgrid_to_transcript.py` provides a transcript conversion route. For this investigation, the transcript is the source to audit against; the original clinician note is a candidate assessment, not automatically a faithful reference.

Session inspection of `human_eval_data/results.csv` found:

| Quantity | Observed count | Interpretation |
|---|---:|---|
| Review rows | 1,425 | Five reviews per distinct consultation/model note |
| Distinct consultation/model notes | 285 | 57 encounters × five candidate notes |
| Generated candidate notes | 228 | Four generated candidates per encounter, sampled from ten systems |
| Original consulting-clinician notes | 57 | One original note per encounter |

The `Model = doctor` entry denotes the original human note. It is not a model-generation system. Running iAudit once per 285 distinct notes avoids rerunning the same note for each of its five reviewers. The 1,425 rows are repeated reviews, not independent encounters.

### 4.2 What the human evaluators did

The study evaluated subjective SOAP-note generation and editing; it did not establish complete clinical correctness. An evaluator listened to the consultation and wrote an independent `Evaluator Note`, then manually edited the `Model Note`, producing the HTML post-edited note and recording incorrect statements, omissions, other issues, and post-editing time in seconds. This was human editing, not an AI-feedback loop.

Interpretation rules:

- `Evaluator Note` is an evaluator's account, not additional interview evidence.
- `!` and `-` mark critical and noncritical items in the error lists. Remove the marker for text alignment while retaining severity separately.
- HTML editing dates are editing metadata, not interview timestamps.
- Recovering the final edited text means retaining insertions and dropping deletions. A deletion can reflect repetition, punctuation, or style; it is not automatically a factual-error label.
- Raters can disagree. Preserve individual reviews rather than collapsing disagreement into invented consensus gold.
- Qualitative examples in the study cover issues relevant to correction ignored, questions treated as facts, attribution to the wrong family member, and missing context, as well as style. These examples demonstrate relevance; they do not label every released note with iAudit's twelve concern types.
- Pure omissions are outside the core task unless they distort an existing claim.

### 4.3 Consultation checklists: useful but not a complete gold set

Session inspection found 27 workbooks: 20 under `Clinician_1` and seven under `Clinician_2`, with uneven consultation overlap. There is no checklist README establishing who created them or a documented mapping from `Note 1` to a generated model/system. Do not infer that mapping.

A concrete artifact is [Day 1 Consultation 1 — Checklist.xlsx](https://github.com/babylonhealth/primock57/blob/main/consultation_checklists/Clinician_1/Day%201%20Consultation%201%20-%20Checklist.xlsx). The visible material includes fact inventories with a `CHECKLIST` importance field (`c` critical, `nc` noncritical, `i` irrelevant), and `Note 1` / `Note 2` clauses with correctness fields (`c` correct, `i` incorrect). Those two uses of `c` and `i` have different meanings.

Common section abbreviations are PC/HPC (presenting complaint/history of presenting complaint), PMH (past medical history), DH (drug history), and SH (social history). Stars and arrows appear to express a hierarchy, but no formal semantics were documented. Hidden `Note 1`–`Note 4` tabs, incomplete fields, `#REF!` cells, and some conflicting correctness ratings were observed. Use the sheets as reference helpers, not as full, consistently mapped gold.

### 4.4 Proposed zero-annotation evaluation

**Note-level association.** Predeclare a fixed iAudit signal, preferably the count of distinct flagged assessment sentences, deduplicated across claims and concern types. Report flagged-text fraction as a companion signal. Summing twelve concern counts would reward duplicate flags on the same error.

Compare the signal with the mean of five human incorrect-statement counts for each note, using Spearman rank correlation and Pearson correlation. Include a note-length baseline because longer notes can contain more errors and attract more flags. Bootstrap by the 57 encounters, keeping all five notes and repeated human reviews together. Report disagreement and uncertainty. Count or rank agreement is a proxy, not proof that the system counts individual errors correctly.

**Output localization from existing error lists.** Strip severity markers from each nonempty `Incorrect statements` line, apply reversible case/whitespace normalization, and search for the resulting substring in that review's `Model Note`. Keep maps back to original offsets. The session's preliminary mechanical alignment found:

| Alignment result | Lines | Share of all nonempty lines |
|---|---:|---:|
| All nonempty incorrect-statement lines | 4,985 | 100% |
| At least one substring match | 4,712 | 94.52% |
| Unique substring match | 4,498 | 90.23% |
| Multiple substring matches | 214 | — |
| No substring match | 273 | — |

These are alignment-coverage observations, not manually validated alignment accuracy and not iAudit results. The main localization track should use unique alignments, disclose the selection, and report coverage. Compute token or sentence overlap against each rater's aligned references and then aggregate, rather than pretending all five raters supplied one consistent annotation. Unmarked note text is a reference complement, not guaranteed true text.

A supplementary LLM could align the unmatched or ambiguous lines, but that should be a separate track with its own coverage and model dependence. It must not silently replace the deterministic reference.

**Post-edit pairs.** Compare audit responses before and after human editing as a secondary analysis. Do not assume every post-edited note is completely clean or that every edit repairs factuality. Preserve the encounter groups and distinguish factual edits from unclassified edits where the release permits it.

## 5. TofuEval: primary natural-dialogue factuality benchmark

### 5.1 Data and counts

Repository: [amazon-science/tofueval](https://github.com/amazon-science/tofueval), inspected revision [`17555c5bfc27f95371fd82b2de7014d8e14e1024`](https://github.com/amazon-science/tofueval/tree/17555c5bfc27f95371fd82b2de7014d8e14e1024). Paper: [TofuEval](https://aclanthology.org/2024.naacl-long.251/).

TofuEval uses 50 MediaSum and 50 MeetingBank documents, with source segments of approximately 800–1,200 words and three topics per document. There are 70 development document IDs and 30 test document IDs. Relevant files are `factual_consistency/{mediasum,meetingbank}_factual_eval_{dev,test}.csv`.

Fields include `doc_id`, `annotation_id`, `topic`, `model_name`, `sent_idx`, `summ_sent`, `sent_label`, `exp`, `type`, and `contamination_identifier`. `yes` means factually consistent and `no` means inconsistent. `exp` is a human error explanation; `type` may contain multiple categories. Preserve contamination metadata for analysis.

Reconstruct a complete summary by grouping on document, topic, and model and sorting by **numeric** `sent_idx`. Keep deterministic maps from original sentence rows to the reconstructed assessment offsets.

| Current released file | Sentence rows | Reconstructed summaries |
|---|---:|---:|
| MediaSum development | 1,813 | 626 |
| MeetingBank development | 1,624 | 617 |
| MediaSum test | 733 | 267 |
| MeetingBank test | 777 | 267 |
| Total | 4,947 | 1,777 |
| Test total | 1,510 | 534 |

The session counted six model names in the current release and 966 inconsistent sentence rows overall. Excluding `Model-Extra` gives the original five-model subset: 1,479 summaries and 3,965 released rows. The paper reports 3,966 sentences; retain this one-row discrepancy rather than altering counts to match the paper. The current README rounds the expanded release to about 1.8k summaries and 5k sentences. Report the original-five subset and the extension separately when comparing with published results.

The source transcripts must be acquired separately: MediaSum's `news_dialogue.json` and the MeetingBank source instructions are relevant. The repository provides annotations, not a ready-to-run iAudit evaluator. The paper appendix supplies evaluation prompts. The paper's limitations state that annotations do not cover consistency errors requiring comparison across different summary sentences; the annotation unit is a single summary sentence against the source. Topic main/marginal information and separate completeness/key-point work should not be confused with the core fidelity task.

### 5.2 Sentence level and summary level mean different units

A **sentence** is one `summ_sent` row, labeled by a human as consistent or inconsistent with the source. It can contain several factual claims. iAudit atomizes those claims, so their verdicts must be projected back onto the original sentence span.

A **summary** is the entire generated, topic-focused write-up for a document/topic/model group. It is the assessment being checked, not the auditing model's reasoning outline. The summary label can be derived from its released sentence labels:

- If any sentence is inconsistent, the summary is inconsistent.
- If every sentence is consistent, the summary is consistent.

For example, the abstract label sequence `[yes, yes, no]` produces an inconsistent summary; `[yes, yes, yes]` produces a consistent summary. These sequences illustrate label aggregation and are not invented dataset quotations.

The two levels answer different questions. Sentence scoring measures whether the system finds the location of inconsistency. Summary scoring measures whether the reviewer is warned that the write-up contains at least one inconsistency. A model can find one of several errors and get the summary-level decision right while missing errors at sentence level. Whole-summary consistency does **not** measure whether the summary includes every important source point.

### 5.3 Proposed iAudit projection

Supply the full available source and the reconstructed summary to iAudit. Preserve original text and sentence offsets; do not run isolated sentences without their source and summary context unless reporting that as a separate setting.

| Native benchmark target | Proposed projection from iAudit | What it measures |
|---|---|---|
| Sentence inconsistent | At least one mapped claim has `contradicted`, `partially_supported`, or `insufficient_evidence` | Binary detection of potentially unfaithful content |
| Sentence consistent | Mapped claims are all `supported`, with sufficient mapped coverage | Consistency on represented claims |
| Sentence unresolved | Missing/failed mapping, empty result, incomplete required coverage, or outside-scope-only result | Coverage and failures; never silently consistent |
| Summary inconsistent | At least one sentence is predicted inconsistent | Detection of any inconsistency in the write-up |
| Summary consistent | Every sentence resolves as consistent | Consistency of the full reconstructed write-up under the projection |
| Summary unresolved | No inconsistent sentence found, but at least one sentence unresolved | Missing evaluable output rather than a clean audit |

Claim spans should be matched to source assessment sentence offsets. Freeze rules for claims crossing sentence boundaries and for sentences with multiple claims before scoring. Even when some claims map successfully, missed factual content must not silently turn the rest of the sentence into a supported prediction. Coverage checks cannot prove complete semantic atomization, but they can expose obvious empty or unmapped outputs.

Report balanced accuracy, inconsistent-class precision/recall/F1, coverage, and failures at sentence and summary level separately, with source and topic strata. Use source-document bootstrap clusters because topics and model outputs from one source are related. For the primary strict evaluation, unresolved outcomes count as incorrect on the relevant gold item. If reproducing an evaluator that requires a binary answer for every item, predeclare the fallback and report both its effect and the unresolved penalty. Never improve apparent accuracy by removing failures from the denominator.

The released binary gold cannot distinguish iAudit's `contradicted`, `partially_supported`, and `insufficient_evidence`. A projection can validate their combined detection behavior, not the correctness of the four-way distinction.

### 5.4 Error types and the measures they support

The seven TofuEval categories are Extrinsic Information, Mis-Referencing, Opinion as Fact, Reasoning Error, Tense/Modality Error, Contradiction, and Nuanced Meaning Shift. They overlap; the current release has only 30 Contradiction tag assignments, so that stratum is small.

They relate to iAudit's support, attribution, certainty, timeframe, causal reasoning, and context checks, but they are not twelve-way gold and have no one-to-one mapping. With no category changes, report error-detection recall stratified by the seven released types. Evaluating category classification would require a documented mapping, disclosure of ambiguity, and separation from native-label scores. Entity/action/number/location diagnostics could be useful later, but no product expansion is approved here.

| iAudit output | Directly evaluated by TofuEval? | Appropriate treatment |
|---|---|---|
| Binary consistency detection | Yes, after a declared projection | Main sentence and summary metrics |
| Atomic claim coverage | No atomic claim-boundary gold | Report adapter/coverage diagnostics; do not claim complete atomization validation |
| Four-way verdict | Only collapsed to binary | Do not claim four-way validation |
| Twelve concerns | No native one-to-one gold | Detection-by-type strata; mapping diagnostics only |
| Exact assessment error location | Sentence-level references exist | Sentence overlap; finer atomic boundaries remain unvalidated |
| Source evidence selection | No structured source offsets | Validate offset mechanics; semantic quality needs another reference or a supplementary judge |
| Explanation correctness | Human reference explanations and a human evaluation rubric exist; no turnkey automatic gold metric | Optional reference-assisted analysis, explicitly model-dependent if judged by an LLM |
| Summary completeness | No, not from factuality labels | Keep separate from the core audit |

Appendix H of the [paper PDF](https://aclanthology.org/2024.naacl-long.251.pdf) describes a human binary explanation-evaluation procedure: an explanation is assessed for being supported by, or equivalent to, the reference explanation, with optional source consultation. This is an existing rubric and reference resource. Automating it under the no-new-human-annotation constraint would require a supplementary judge, such as an LLM, with separately reported reliability. It is not a turnkey automatic semantic gold metric. Sections 3.4 and 5 describe sentence-to-summary aggregation and balanced-accuracy reporting at both levels, alongside error-type recall.

The paper's LLM findings should be read with their setting and date: GPT-4 performed best on balanced accuracy in most evaluated settings, while specialized factuality metrics could do better on some error categories. Explanation prompting did not improve binary factuality classification in that study. This does not support a blanket claim that LLM evaluators never work, or a conclusion about every current model.

### 5.5 Terms and source access

The repository uses MIT-0, but its no-training instruction and underlying source terms must also be respected. MediaSum carries research-use restrictions described in the repository's third-party license material. MeetingBank states [CC BY-NC-ND 4.0 terms](https://meetingbank.github.io/license/). Do not assume the annotation repository license grants unrestricted use of separately sourced transcripts or redistribution of transformed source material.

## 6. ACI-Bench: later constructed tests, not natural-error gold

Repository: [wyim/aci-bench](https://github.com/wyim/aci-bench), inspected revision [`b909b2bb9cf1d19de08df15cddde7bd0179665e4`](https://github.com/wyim/aci-bench/tree/b909b2bb9cf1d19de08df15cddde7bd0179665e4). Paper: [ACI-Bench](https://arxiv.org/html/2306.02022v1). Data release: [Figshare 22494601](https://figshare.com/articles/dataset/ACI-Bench/22494601), CC BY 4.0.

ACI-Bench has 207 mock/synthetic demonstrations: 67 training, 20 validation, and three 40-example test sets. CSV fields include dataset, encounter ID, dialogue, and note. Some ASR, human, and corrected dialogue variants exist. The release warns that some doctor/patient tags are swapped and intentionally leaves them as released; adapters must preserve or explicitly handle the warning rather than silently treating tags as reliable gold.

Reference notes were cleaned of unsupported content, but some names, ages, units, and details remain that are not substantiated by the dialogue. Metadata is not dialogue evidence. There is no equivalent released human error list or source-evidence gold. Consequently, treating every base note as a positive example would make false assumptions.

A possible later use is a controlled challenge set: select unambiguous source-conditioned material, change known note or source positions, retain unedited and faithful-paraphrase controls, and skip ambiguous bases. Keep transformation provenance and affected spans. Label this as constructed or weakly supervised evaluation, separate from naturally occurring human-labeled errors. No such challenge set has been built here.

## 7. Additional benchmarks and why they were selected or pruned

### 7.1 WiCE: evidence and partial support

Repository: [ryokamoi/wice](https://github.com/ryokamoi/wice). Paper: [WiCE](https://aclanthology.org/2023.emnlp-main.470/).

WiCE uses naturally occurring Wikipedia claims checked against cited articles, not conversations. The inspected test assets include:

| File | Items | Released labels |
|---|---:|---|
| `data/entailment_retrieval/claim/test.jsonl` | 358 claims | 111 supported, 215 partially supported, 32 not supported |
| `data/entailment_retrieval/subclaim/test.jsonl` | 958 subclaims | 528 supported, 165 partially supported, 265 not supported |
| `data/non_supported_tokens/test.jsonl` | 105 partially supported subclaims | Claim tokens and non-supported spans |

Fields include `claim`, `evidence` as source sentences, `label`, `supporting_sentences` as alternative index sets, and `meta.id`/context. The token task adds `claim_tokens` and `non_supported_spans`.

Proposed verdict projection: `supported` → supported; `partially_supported` → partially supported; `contradicted` or `insufficient_evidence` → not supported. Outside-scope outputs remain unresolved. Declare how multiple iAudit atoms aggregate to the original claim. Report the native supported-versus-other binary accuracy/F1 as appropriate to the official task, plus three-way macro-F1 diagnostics. Do not claim WiCE distinguishes contradiction from missing evidence.

Map returned source offsets back to provided sentence IDs for evidence evaluation. Compare with the best matching alternative gold evidence set using F1, limited to supported/partially supported items with gold evidence. Alternative valid sets should not be incorrectly treated as one required union. This tests sentence selection; it does not provide exact source-boundary gold. The non-supported-token subset can separately test output localization with its native masks.

The annotation license is ODC-BY and code is MIT; Wikipedia/Common Crawl source terms still apply. See the repository's [license material](https://github.com/ryokamoi/wice/blob/main/LICENSE.md).

### 7.2 DiaSumFact: dialogue categories and output spans

Repository: [731935354/Dia-Sum-Fact](https://github.com/731935354/Dia-Sum-Fact). Paper: [DiaSumFact](https://aclanthology.org/2023.acl-long.377/).

Session inspection of `annotations.json` found 475 summaries, 1,340 sentences, and 119 dialogue records drawn from SAMSum and QMSum. Human annotations include `error_class`, `error_span` as a substring of the output, intrinsic/extrinsic classification, and comments. Its six categories are EntE (entity), PredE (predicate), CirE (circumstance), CorefE (reference), LinkE (relations), and Others.

Use no-errors versus any-errors as the native binary task, with category diagnostics. Do not force the six classes into twelve iAudit labels. Intrinsic/extrinsic has a token-origin definition and is not equivalent to contradicted/insufficient evidence. Output error spans can support localization after deterministic alignment; they are not source-evidence gold. The repository is MIT, with underlying data terms, including SAMSum's noncommercial/no-derivatives terms, retained.

### 7.3 RAGTruth: output-error localization

Repository: [ParticleMedia/RAGTruth](https://github.com/ParticleMedia/RAGTruth).

`dataset/response.jsonl` contains 17,790 responses: 15,090 training and 2,700 test. `source_id` joins `source_info.jsonl`; tasks include summarization, question answering, and data-to-text. Human response-error annotations have `start`, `end`, `text`, and `label_type`, with Evident Conflict, Subtle Conflict, Evident Baseless Info, and Subtle Baseless Info. Preserve the release's offset conventions before mapping to iAudit code-point spans.

Some records mark `implicit_true`: content may be true in the world while unsupported by the supplied context. This is directly relevant to the mission's distinction between source fidelity and world truth. The annotated spans are erroneous output text, not the supporting or contradicting source excerpts iAudit should show. The repository is MIT; underlying source terms remain relevant.

### 7.4 Candidates retained as secondary or excluded from the main suite

| Candidate | What was found | Decision/limitation |
|---|---|---|
| SummEdits | 6,348 human-labeled binary edited pairs over ten domains, including dialogue; `edit_types` are GPT-4 predictions | Useful separate constructed challenge, not natural errors or human category gold |
| FRANK | `human_annotations_sentence.json` has 2,246 records versus README's 2,250; entity, predicate, circumstance, coreference, discourse, and out-of-article categories | News-domain complement; no source-evidence spans |
| DialSummEval | `annotation_campus/human_judgment.jsonl` has 1,400 summaries with three human 1–5 consistency ratings | Possible rating correlation; use campus annotations, not the rejected AMT set |
| FactCC | Official manual processor exposes source, claim, and binary labels; span training is mostly synthetic; archive access returned 403 in the session | Do not describe as established human source-evidence gold |
| RAGBench | Evidence/source links generated by GPT | Silver supervision, not interchangeable with WiCE human annotations |

Sources: [SummEdits paper](https://aclanthology.org/2023.emnlp-main.600/) and [benchmark notebook](https://github.com/salesforce/factualNLG/blob/master/SummEdits_Benchmark.ipynb); [FRANK repository](https://github.com/artidoro/frank); [DialSummEval repository](https://github.com/kite99520/DialSummEval) and [paper](https://aclanthology.org/2022.naacl-main.418/); [official FactCC repository](https://github.com/salesforce/factCC); [RAGBench dataset](https://huggingface.co/datasets/galileo-ai/ragbench). SummEdits' repository is Apache 2.0, with underlying data terms still applying. An access failure is a session observation, not a claim that an archive is permanently unavailable.

## 8. Supplementary LLM judges: useful, bounded roles

An LLM judge is optional. Existing released labels support the main evaluations without any new human labeling. No requirement exists to collect gold for every response field before evaluating the fields with usable references.

The most defensible supplementary roles are reference-assisted alignment of difficult PriMock error strings and assessment of explanation agreement against existing human error explanations. Freeze prompts, judge model/version, decoding settings, input formatting, and label projection. Calibrate on development/released labels, keep test labels out of prompt tuning, and report model dependence. Judge output remains an auxiliary estimate, not newly established human gold.

Research ideas informing the discussion:

| Source | Relevant lesson | Boundary for iAudit |
|---|---|---|
| [FActScore](https://aclanthology.org/2023.emnlp-main.741/) | Decompose long output into atomic factual units for source-supported checking | Adapt source fidelity, not a biography/world-knowledge correctness target |
| [ALCE](https://aclanthology.org/2023.emnlp-main.398/) | Citation provenance and whether cited material entails a claim are distinct | A valid pointer is not proof that the excerpt supports the claim |
| [FACTS Grounding v1](https://arxiv.org/html/2501.03200v1) | Existing human labels can calibrate grounding judges | Historical v1 findings are not a guarantee for all later settings |
| [Later FACTS suite](https://arxiv.org/html/2512.10791v1) | The evaluation program evolved beyond the original grounding setup | Specify which version and task is being used |
| [MT-Bench](https://arxiv.org/abs/2306.05685) | LLM judging can evaluate broad assistant preferences | Preference agreement is not factuality validation |
| [G-Eval](https://aclanthology.org/2023.emnlp-main.153/) | Explicit evaluation criteria and structured judging can be useful | Criteria and judge reliability need task-specific checking |

Mechanical validation remains essential: offsets must resolve to supplied text and evidence must reference valid turns. Those checks establish traceability, not semantic entailment. Similarly, a plausible explanation does not validate a verdict, and agreement between two models does not create an independent factual reference.

## 9. Measurement and reporting policy proposed by the investigation

### 9.1 Keep native tasks and projections visible

Report each benchmark's native task separately, followed by the explicit iAudit projection. Record dataset revision, source acquisition version, split IDs, adapter version, normalization rules, output mapping, and failure policy. Releasing a projection is more reproducible than describing an unspecified conversion to a common score.

Do not pool unlike targets into a single headline accuracy. TofuEval binary consistency, PriMock human-count association, WiCE evidence retrieval, and RAGTruth output-span overlap answer different questions. They can support one body of evidence without pretending to be one interchangeable gold set.

Preserve document, encounter, and source groups across all derived variants, model outputs, notes, and references. Use group-held-out development/test boundaries and clustered confidence intervals. Test data must not leak into prompt examples, judge calibration, threshold selection, or constructed training examples. Existing benchmark exposure remains a limitation for widely trained models even when the local adaptation is careful.

### 9.2 Separate the layers of quality

| Layer | Available evaluation route | Claim to avoid |
|---|---|---|
| Input and output validity | Schema checks, offset checks, conversion round trips | That valid JSON means accurate auditing |
| Atomization and assessment coverage | Sentence/claim offset mapping and coverage diagnostics | That a binary benchmark labels all atomic boundaries |
| Detection | TofuEval, DiaSumFact, selected RAGTruth projections | That detecting an error proves the exact concern type |
| Four-way verdicts | WiCE three-way projection plus available native labels | That binary gold validates all four verdicts |
| Assessment error localization | PriMock aligned strings, DiaSumFact spans, RAGTruth spans, WiCE token subset | That output-error spans measure source evidence |
| Source evidence selection | WiCE supporting sentence sets; code validity elsewhere | That turn-level recall proves exact semantic source-span quality |
| Explanations | Supplementary reference-assisted analysis | That an LLM judge creates human gold |
| Mission-specific rare concerns | Released examples and disclosed strata where available | That all twelve concerns are validated automatically |

The current harness's gold/linked/end-to-end separation is conceptually useful. Applying it requires compatible benchmark records and must respect which stages actually have gold inputs. Do not manufacture gold claim atomization or gold evidence for a dataset that only provides sentence labels.

### 9.3 Failures, cost, and uncertainty

Record empty output, schema errors, timeouts, provider failures, outside-scope results, mapping failures, and unresolved coverage separately. Include failures in the primary denominator under the declared policy. Report latency and model cost with model configuration, rather than dropping unsuccessful runs or comparing only completed examples.

Use per-domain and per-type results where sample size supports them; flag rare strata. In particular, 30 TofuEval Contradiction assignments do not establish broad coverage of every form of contradiction, and PriMock's repeated reviews do not create 1,425 independent clinical cases. Claims about real clinical performance, clinical correctness, diagnosis, or improved patient outcomes are unsupported by this proposed suite.

## 10. Current recommendations versus superseded interpretations

| Topic | Current recommendation | Superseded or rejected interpretation |
|---|---|---|
| Human resources | Reuse released labels; deterministic projections are the core | Require a newly human-adjudicated gold set before proceeding |
| Main suite | TofuEval + PriMock57 + WiCE, then targeted additions | Find one benchmark that labels every iAudit field |
| PriMock original notes | Audit as candidate assessments | Treat a consulting doctor's note as automatically correct gold |
| PriMock error alignment | Unique mechanical matches as the main track; disclose coverage | Treat every deletion or unmatched string as a validated factual span |
| PriMock checklists | Reference helpers with incomplete mappings | Assume `Note 1` identifies a known generated model |
| TofuEval whole-summary score | Any inconsistent sentence makes the generated write-up inconsistent | Interpret summary as an auditing model's reasoning outline or as completeness |
| Missing output | Unresolved and penalized under the declared primary policy | Treat no mapped claim or outside-scope-only output as consistent |
| Categories | Native labels first; optional diagnostic mappings | Rename native errors into twelve-way gold without justification |
| Source evidence | Evaluate sentence gold where available; otherwise separate semantics from offset validity | Treat output-error localization or valid offsets as evidence correctness |
| Constructed edits | Separate, provenance-preserving challenge set | Merge synthetic errors with naturally occurring human-labeled errors |
| LLM judges | Optional, frozen, calibrated, reference-assisted supplement | Judge agreement as independent gold or a mandatory replacement for labels |
| Product scope | Preserve the mission and current contracts | Add categories, diagnosis, scoring, or file support through an evaluation note |

## 11. Open questions and work not authorized by this record

The following are decisions for a later implementation proposal, not blockers to preserving this research:

1. Which suite and benchmark subset should be implemented first, and what resource budget should be allocated?
2. Can all separately licensed source transcripts be acquired and used under the intended evaluation and redistribution arrangements?
3. What exact sentence/claim overlap rule and factual-content coverage check should the TofuEval adapter freeze?
4. What deterministic multi-atom aggregation should be used for WiCE, and which native evaluation script/version should anchor comparability?
5. Which PriMock reviewer fields can be normalized without changing their interpretation, and how should duplicate or disputed reviewer strings be reported?
6. Is the deterministic PriMock alignment track sufficient initially, or is an explicitly separate LLM-assisted track worth its added uncertainty and cost?
7. Which optional explanation or category diagnostics would change a practical decision, rather than merely expand the report?
8. Should controlled challenges be added later for mission checks not well covered by existing labels, with no new human annotation requirement?
9. How should the benchmark adapters integrate with the ADHD-only runner while preserving native task outputs and the current proof-of-concept gate?

No app/backend code, contract taxonomy, benchmark adapter, constructed dataset, test split, LLM judge, live model run, or published performance claim was created by this documentation task. No new human annotation was requested. The next implementation step requires its own concrete scope; this record preserves research and corrected recommendations only.

## 12. Provenance and reproducibility limits

Repository facts about iAudit were checked against the files linked above while writing this record. External dataset details, counts, alignment observations, and research conclusions are preserved from the investigation supplied to this task; they were not rerun as fresh experiments during documentation. Pinned revisions are supplied for PriMock57, TofuEval, and ACI-Bench where the session recorded them. Other repository links identify the referenced project but do not imply a new frozen snapshot.

The source links support inspection and later reproduction. Counts describe the inspected release rather than an eternal dataset size. License notes identify recorded source conditions and should be checked against the exact artifacts acquired for an eventual run. No source quotations, speaker identities, interview timestamps, or clinical case examples have been invented in this document.
