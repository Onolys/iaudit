---
status: done
summary: ADHD and oracle gold are unaffected by failed-inference relabelling; no regeneration required.
date: 2026-10-28
---
# Task 5 — Failed-inference gold check

Outcome: **unaffected; gold retained unchanged**.

## Findings

- Loaded every committed ADHD gold row with `eval.gold.load_gold`: 10 fixtures, 102 claims, 93 controls and 9 targets. Exactly one required or allowed `unsupported_claim`: `adhd-v4-noroles`, `g11`, bucket 1, `insufficient_evidence`.
- That target concerns missing speaker roles, with `ambiguous_speaker` expected and qualifying evidence at turns 12–13. Its slots contain `links: []`. The deterministic generator explicitly assigns `unsupported_claim` in `NOROLES_EXPECTED` and the no-roles gold override (`eaudit/eval/build_adhd.py`). It is not a rejected inference.
- Every gold row has empty `slots.links`; no other bucket-1 candidate exists. The other required concerns are frequency/severity, negation, attribution, question-as-answer, timeframe, conflicting accounts, context stripping and unsupported causality (one each). Only `contradictory_evidence` occurs as an allowed concern (once).
- Oracle has no separate gold: `load_fixture` loads these same rows and `oracle_audit` echoes them. Gold-mode `gold_link` creates `link_type="quote"` evidence only (`eaudit/eval/adapters.py`). Neither path introduces a failed inference group. `eaudit/eval/recorded/` contains only its README, so no recorded gold-mode inference observations exist to migrate.
- The changed D6/D7 branch requires `demote == "inference"`. `resolve_inferences` creates that demotion from linked inference groups (`eaudit/src/eaudit/check/synth.py`); missing-role evidence is a different path. The existing Task 2 regression, `test_failed_inference_with_entailing_premises_is_insufficient_inference`, verifies the new `unsupported_inference` result and passed below.
- Compared every in-memory `eval.build_adhd.build()` output against the committed file: **30 files, zero mismatches**. No generator, gold, expected results, requests or recordings changed.

## Offline verification

Run from `eaudit/`:

```bash
uv run pytest eval/tests/test_gold.py eval/tests/test_oracle.py eval/tests/test_adhd_data.py eval/tests/test_adhd_expected.py tests/test_check_taxonomy_v2.py -q
```

Result: **129 passed in 1.99s** (exit 0). Includes strict gold loading, generated-file equality, oracle scoring and the failed-inference regression.

```bash
uv run python -m eval.run --mode oracle --only faithful,v1,v2,v3,v4,v5,v6,v7,v8,v4-noroles --gate poc
```

Result: exit 0; all nine POC-gated fixtures PASS. The CLI also evaluates `v4-noroles`, which is deliberately outside the POC gate. `adhd-multi` and CDR report their existing unavailable-data skips.

A separate direct `run_mode('oracle', names, Settings(llm_mode='fixture'), None)` / `aggregate(results)` check confirmed **10 results, zero errors, all ten fixture checks true**; 0/93 control false alarms; required evidence 101/101 covered; evidence roles 123/123 correct. Bucket 1 remains `unsupported_claim`: TP 1, FP 0, FN 0, verdict accuracy 1/1.

The inventory command used `load_gold` over every `DATA/gold/*.jsonl`, counted required/allowed concerns, printed every bucket-1 or `unsupported_claim` row and all nonempty `slots.links`, then compared all 30 `build()` outputs byte-for-byte with `DATA / rel`. Output: one no-roles target, no nonempty links, no build mismatches.

No live calls or recording updates. Full-suite verification is assigned to the SP03 completion tasks; this task ran scoped checks only. No code/gold changes or new tests were necessary.
