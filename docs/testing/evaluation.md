# Evaluation

**Audience:** contributors.

Quality is measured per bucket (mission checks 1 to 12), never as one score. Data is the worked ADHD example: a faithful assessment plus eight variants with one injected fault each (plus an extra variant with roles removed). Results are labelled split `poc-all`: a smoke check on data the authors have seen, not an estimate for real interviews. No precision claim is made from it.

## Commands (from `backend/`)

```bash
uv run python -m eval.smoke                       # the POC gate through POST /v1/audit
uv run python -m eval.run --mode oracle --gate poc
uv run python -m eval.run --mode gold             # checker alone on gold claims and evidence
uv run python -m eval.run --mode linked           # linker, then checker
uv run python -m eval.run --mode e2e              # the whole pipeline
uv run python -m eval.compare a/report.json b/report.json
```

**Gold** shows a weak checker, **linked** a weak linker, **e2e** a weak atomizer. `--mode all` writes the three side by side. `oracle` echoes the gold through the assembler and must score 1.0 everywhere, which proves the harness itself.

## The POC gate

`--gate poc` is a pass or fail per fixture. The faithful fixture passes if every claim is `supported` with no concerns. A variant passes if its target claim has the expected verdict, every required concern, and any required wording (variant 1 must say "inflates"). Concerns on other claims are reported, not gated. Evidence recall is printed, not gated.

## Replay and live

Replay (the default) reads recorded answers from `eval/recorded/` and reports a missing recording as an error, not a score. `--live` needs a provider key, prints a cost estimate first, and never falls back to replay; `--max-cost` aborts before any call. `--live --record` writes recordings and a manifest (prompt hashes, model ids, date). Replay warns when a prompt changed since recording, and `--strict-fresh` fails instead. Recorded data must be synthetic.

## Reading a report

Each bucket row has TP, FP, FN, precision, recall, F1 and verdict accuracy. Below 5 faults a row says "indicative only". The 0.8 precision target is flagged only at 10 or more faults. F1 is 0.0 when a bucket has faults and none were found. The side-by-side table helps place a weak stage; `compare.py` flags a gain of 0.05 or more, the bar for a new stage to earn its cost.

## Leakage

Few-shot examples are fictional and must not share an 8-word run with scored data or use the scored speaker ids. Real interview data never enters prompts, tuning or recordings in the repo; it belongs in the gitignored `eval/private/`.

## Not built yet

Multi-fault fixture `adhd-multi` (waits for approved content) and the cleanup script for the real CDR interviews (waits for the files). A 60/20/20 split and the 0.8 precision gate wait for more data.
