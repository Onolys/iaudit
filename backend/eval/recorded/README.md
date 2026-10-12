# Recorded LLM answers (replay fixtures)

Empty until the first live pass. Replay (`uv run python -m eval.run --mode gold`) reads the files
here and reports a missing recording as an error, never as a score.

To record (needs a provider key; the run prints a cost estimate first):

```bash
uv run python -m eval.run --mode all --live --record --max-cost 5
```

That writes one JSON file per call plus `manifest.json` (prompt hashes per stage, model ids,
date). Replay warns when a prompt changed since recording; `--strict-fresh` makes it fail.
Commit only recordings of the synthetic ADHD set. Anything recorded from real interviews goes to
`eval/private/`, which is gitignored.
