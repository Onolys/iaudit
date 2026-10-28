# Latency

**Audience:** contributors.

Target 30 to 45 seconds for a typical audit, hard cap 100 (`IAUDIT_AUDIT_DEADLINE_S`), UI timeout 120. The service sends a `Server-Timing` header on 200 replies with `total` and one entry per stage that ran (`prep`, `atomize`, `link`, `check`, `assemble`), durations only. In browser devtools it shows in the network tab for the audit request; turn it off with `IAUDIT_SERVER_TIMING=false`.

## Offline scenarios

`eaudit/tests/latency/` runs the pipeline against a scripted model whose latencies are lognormal per call tag and scaled by one factor (default 1/50), so ratios hold and a minute takes about a second. It covers the baseline run, failure injection (a link timeout, a check outage, a failed atomize), deadline overrun without leaked tasks, and a check that a sentinel word never reaches logs, metrics or headers.

## Live

Latency percentiles and cost on real providers need a key. Run `uv run python -m eval.run --mode e2e --live` and read the request p50 and max in the report. Check `cache_hit_ratio` in the metrics before enabling `IAUDIT_CACHE_LAYOUT=shared` or `IAUDIT_CACHE_WARMUP`: the provider may not share the cache across stages.
