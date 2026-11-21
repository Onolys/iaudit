"""Live quality/latency check of a pack on the real model (PRD R5 live check, R4, Decision 18).

    python -m paudit.cli check --pack <id@version> --preset <name>

Runs every fixture in the pack's `fixtures/expected.yaml` once (sequentially, so latency is not
distorted by sibling runs), compares each result with the expected counts and global ranges, and
prints per-code count MAE, globals within 1 point, bad-output/retry rate, p95 run latency and
tokens per run. Fails (exit 1) when any value is past `fixtures/thresholds.yaml`. No `eval/`
dependency, no admin wiring. Never prints text, quotes or keys.

Metric definitions (all measured from core's MetricsCollector call log, no extra counters):
- count_mae: mean over fixtures x expected codes of |counted - expected| (run 0).
- globals_within_1: share of expected globals whose score is within 1 point of the expected range.
- bad_output_rate: share of model calls that ended `bad_output` (batch then halved / retried by
  the engine) or needed more than one client attempt.
- p95_latency_s: nearest-rank 95th percentile of the wall time of one fixture run, seconds.
- tokens_per_run: largest per-run sum of input, output and cache read/write tokens.
"""

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from onolys_core.llm import LLMClient, MetricsCollector
from onolys_core.transcript import Transcript

from paudit.engine import run
from paudit.pack import Pack

# metric name -> (threshold key, "max" = must not exceed, "min" = must reach)
LIMITS: dict[str, tuple[str, str]] = {
    "count_mae": ("count_mae_max", "max"),
    "globals_within_1": ("globals_within_1_min", "min"),
    "bad_output_rate": ("bad_output_rate_max", "max"),
    "p95_latency_s": ("p95_latency_s_max", "max"),
    "tokens_per_run": ("tokens_per_run_max", "max"),
}


@dataclass
class Failure:
    metric: str
    value: float
    limit: float
    kind: str

    def __str__(self) -> str:
        op = "<=" if self.kind == "max" else ">="
        return f"{self.metric} = {self.value:.3f}, need {op} {self.limit:g}"


@dataclass
class CheckReport:
    metrics: dict[str, float]
    thresholds: dict[str, float]
    failures: list[Failure] = field(default_factory=list)
    per_fixture: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def _distance(score: float, rng: list[float]) -> float:
    lo, hi = rng
    return max(lo - score, score - hi, 0.0)


def _bad_call(rec: dict[str, Any]) -> bool:
    return rec["error_kind"] == "bad_output" or rec["attempts"] > 1


def _tokens(metrics: MetricsCollector) -> int:
    keys = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    return sum(r[k] for r in metrics.records for k in keys)


def load_thresholds(path: Path) -> dict[str, float]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def evaluate(metrics: dict[str, float], thresholds: dict[str, float]) -> list[Failure]:
    out = []
    for name, (key, kind) in LIMITS.items():
        if key not in thresholds:
            raise ValueError(f"thresholds file has no {key}")
        limit = float(thresholds[key])
        bad = metrics[name] > limit if kind == "max" else metrics[name] < limit
        if bad:
            out.append(Failure(name, metrics[name], limit, kind))
    return out


async def run_check(
    pack: Pack,
    fixtures_dir: Path,
    client_for: Callable[[str], LLMClient],
    thresholds: dict[str, float],
) -> CheckReport:
    """Run each fixture in `fixtures_dir/expected.yaml` with `client_for(name)`."""
    for _name, (key, _k) in LIMITS.items():
        if key not in thresholds:
            raise ValueError(f"thresholds file has no {key}")
    expected = yaml.safe_load((fixtures_dir / "expected.yaml").read_text(encoding="utf-8"))
    errors: list[float] = []
    within: list[bool] = []
    latencies: list[float] = []
    tokens: list[int] = []
    calls = bad = 0
    per_fixture: dict[str, dict[str, float]] = {}
    for name, exp in expected["fixtures"].items():
        transcript = Transcript.model_validate_json(
            (fixtures_dir / exp["transcript"]).read_text(encoding="utf-8")
        )
        params = json.loads((fixtures_dir / exp["params"]).read_text(encoding="utf-8"))
        metrics = MetricsCollector()
        t0 = time.monotonic()
        result = await run(transcript, pack, params, client_for(name), metrics=metrics)
        latencies.append(time.monotonic() - t0)
        tokens.append(_tokens(metrics))
        calls += len(metrics.records)
        bad += sum(_bad_call(r) for r in metrics.records)
        counted = result.results[0].counts
        errs = [abs(counted.get(c, 0) - n) for c, n in exp["counts"].items()]
        errors += errs
        ok = [
            _distance(result.results[0].globals[g].score, spec["range"]) <= 1
            for g, spec in exp["globals"].items()
        ]
        within += ok
        per_fixture[name] = {
            "count_mae": sum(errs) / len(errs) if errs else 0.0,
            "globals_within_1": sum(ok) / len(ok) if ok else 1.0,
            "latency_s": latencies[-1],
            "tokens": tokens[-1],
        }
    metrics_out = {
        "count_mae": sum(errors) / len(errors) if errors else 0.0,
        "globals_within_1": sum(within) / len(within) if within else 1.0,
        "bad_output_rate": bad / calls if calls else 0.0,
        "p95_latency_s": p95(latencies),
        "tokens_per_run": float(max(tokens)),
        "runs": float(len(latencies)),
    }
    return CheckReport(
        metrics_out, thresholds, evaluate(metrics_out, thresholds), per_fixture
    )


def format_report(rep: CheckReport) -> str:
    lines = []
    for name, (key, kind) in LIMITS.items():
        op = "<=" if kind == "max" else ">="
        lines.append(f"{name:18} {rep.metrics[name]:10.3f}   need {op} {rep.thresholds[key]:g}")
    lines.append(f"{'runs':18} {int(rep.metrics['runs']):10d}")
    for name, v in rep.per_fixture.items():
        lines.append(
            f"  {name}: count_mae {v['count_mae']:.2f}, globals_within_1 "
            f"{v['globals_within_1']:.2f}, {v['latency_s']:.1f}s, {int(v['tokens'])} tokens"
        )
    if rep.failures:
        lines += [f"FAIL {f}" for f in rep.failures]
        lines.append("FAIL")
    else:
        lines.append("PASS")
    return "\n".join(lines)
