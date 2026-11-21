"""Live check (SP03 R9, D20): one fixture (transcript + final card) end to end on the real model.

    python -m onolys_evaluation.check [--pack ID@VERSION|DIR] [--preset NAME] [--fixture-dir DIR]

Runs `run_evaluation` on the fixture transcript and final rating card. Passes when there are at
least 3 tips whose quote really sits in the transcript and `reasons_audit.status` is `ran`.
Prints the tips quote-valid rate, per-stage latency, tokens per engine and an estimated cost.
Needs the route's API key in the environment (never printed). Exit code 0 only on pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from onolys_core import OnolysError
from onolys_core.engine import RunContext
from onolys_core.llm import LLMConfig, MetricsCollector, make_client
from onolys_core.transcript import Transcript

MIN_TIPS = 3
ENGINES = ("paudit", "eaudit", "evaluation")
# ESTIMATE, USD per million tokens: Claude Sonnet published list prices (input $3, output $15,
# 5-minute cache write $3.75, cache read $0.30). Assumed to apply to the route's Sonnet model.
PRICES_USD_PER_MTOK = {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30}
_FIELDS = {"input_tokens": "input", "output_tokens": "output",
           "cache_write_tokens": "cache_write", "cache_read_tokens": "cache_read"}


def default_pack() -> Path:
    """The only pack directory under `<repo>/protocols`, else a ValueError asking for `--pack`."""
    packs = sorted(p for p in (Path(__file__).resolve().parents[4] / "protocols").glob("*")
                   if (p / "pack.yaml").exists())
    if len(packs) != 1:
        raise ValueError(f"found {len(packs)} packs under protocols/; pass --pack")
    return packs[0]


def estimate_cost(usage: Mapping[str, Any]) -> float:
    """Estimated USD for one engine's `run_info.usage` (see `PRICES_USD_PER_MTOK`)."""
    return sum((usage.get(f) or 0) * PRICES_USD_PER_MTOK[k] / 1_000_000
               for f, k in _FIELDS.items())


@dataclass
class CheckResult:
    passed: bool
    problems: list[str] = field(default_factory=list)
    tips_valid: int = 0
    tips_proposed: int = 0
    quote_valid_rate: float = 0.0
    reasons_status: str | None = None
    stage_s: dict[str, float] = field(default_factory=dict)
    wall_s: float = 0.0
    usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_calls: int = 0
    cost_usd: float = 0.0


class StageTimer:
    """A `ProgressCb` that records started -> done/failed seconds per stage."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._t0: dict[str, float] = {}
        self.stage_s: dict[str, float] = {}
        self.failed: list[str] = []

    def __call__(self, stage: str, status: str) -> None:
        if status == "started":
            self._t0[stage] = self._now()
            return
        if stage in self._t0:
            self.stage_s[stage] = self._now() - self._t0[stage]
        if status == "failed":
            self.failed.append(stage)


def _quote_ok(tip: Mapping[str, Any], turns: Mapping[str, str]) -> bool:
    q = tip.get("quote") or {}
    text = turns.get(q.get("turn_id"))
    start, end = q.get("start"), q.get("end")
    return (text is not None and isinstance(start, int) and isinstance(end, int)
            and 0 <= start < end <= len(text) and text[start:end] == q.get("text"))


def evaluate(report: Mapping[str, Any], transcript: Transcript, *, stage_s: Mapping[str, float],
             proposals: int, wall_s: float) -> CheckResult:
    """Pure pass/fail logic over a finished report.

    Passes when at least `MIN_TIPS` tips quote the transcript exactly and the reasons audit
    ran. `quote_valid_rate` = verified tips / tips the model proposed (rejected ones count)."""
    turns = {t.id: t.text for t in transcript.turns}
    tips = report.get("tips") or []
    verified = sum(1 for t in tips if _quote_ok(t, turns))
    status = (report.get("reasons_audit") or {}).get("status")
    problems: list[str] = []
    if verified < MIN_TIPS:
        problems.append(f"tips: {verified} valid, need at least {MIN_TIPS}")
    if status != "ran":
        problems.append(f"reasons_audit.status is {status!r}, need 'ran'")
    denom = max(proposals, len(tips))
    usage: dict[str, dict[str, Any]] = {}
    for eng in ENGINES:
        u = ((report.get("run_info") or {}).get(eng) or {}).get("usage")
        if u:
            usage[eng] = dict(u)
    return CheckResult(
        passed=not problems, problems=problems, tips_valid=verified, tips_proposed=denom,
        quote_valid_rate=(verified / denom) if denom else 0.0, reasons_status=status,
        stage_s=dict(stage_s), wall_s=wall_s, usage=usage,
        total_calls=sum(u.get("calls") or 0 for u in usage.values()),
        cost_usd=sum(estimate_cost(u) for u in usage.values()))


def format_result(r: CheckResult) -> str:
    lines = [f"{'PASS' if r.passed else 'FAIL'}  tips {r.tips_valid} valid"
             f" (quote-valid rate {r.quote_valid_rate:.0%} of {r.tips_proposed} proposed),"
             f" reasons_audit.status={r.reasons_status}",
             f"wall time {r.wall_s:.1f}s; per-stage latency (s):"]
    lines += [f"  {s:<9}{v:>8.1f}" for s, v in r.stage_s.items()]
    lines.append(f"{'tokens':<11}{'calls':>6}{'in':>10}{'out':>9}{'cache_rd':>10}{'cache_wr':>10}")
    for eng, u in r.usage.items():
        lines.append(f"  {eng:<9}{u.get('calls', 0):>6}{u.get('input_tokens', 0):>10}"
                     f"{u.get('output_tokens', 0):>9}{u.get('cache_read_tokens', 0):>10}"
                     f"{u.get('cache_write_tokens', 0):>10}")
    p = PRICES_USD_PER_MTOK
    lines.append(f"estimated cost ${r.cost_usd:.3f} over {r.total_calls} calls (ESTIMATE at "
                 f"${p['input']}/${p['output']} per M in/out, cache write ${p['cache_write']}, "
                 f"read ${p['cache_read']})")
    lines += [f"problem: {x}" for x in r.problems]
    return "\n".join(lines)


async def run_check(pack_ref: str | Path, preset: str | None, fixture_dir: Path | None = None,
                    llm: Any | None = None) -> CheckResult:
    """Run the fixture through `run_evaluation` on `llm` (default: the live client)."""
    from paudit.pack import load_pack

    from onolys_evaluation.api import run_evaluation
    from onolys_evaluation.rating import validate_rating

    pack = load_pack(pack_ref)
    fixture_dir = fixture_dir or pack.root / "fixtures" / "evaluation"
    transcript = Transcript.model_validate_json(
        (fixture_dir / "transcript.json").read_text(encoding="utf-8"))
    speaker_map = json.loads((fixture_dir / "speaker_map.json").read_text(encoding="utf-8"))
    card = json.loads((fixture_dir / "rating_card.json").read_text(encoding="utf-8"))
    issues = validate_rating(pack, card, final=True)
    if issues:
        raise ValueError(f"fixture rating card invalid: {[i.code for i in issues]}")
    llm = llm or make_client(LLMConfig(llm_mode="live", preset=preset))
    ctx = RunContext(llm=llm, metrics=MetricsCollector(), request_id="check")
    params = {"n_runs": 1, "preset": preset, "change_goal": card.get("change_goal"),
              "coded_span": card.get("coded_span"), "language": transcript.language}
    timer = StageTimer()
    t0 = time.monotonic()
    out = await run_evaluation(ctx, pack, transcript, speaker_map, params, card, None, timer)
    wall = time.monotonic() - t0
    report = json.loads(out.report.model_dump_json())
    proposals = len(out.artifacts.tips.proposals) if out.artifacts.tips else 0
    return evaluate(report, transcript, stage_s=timer.stage_s, proposals=proposals, wall_s=wall)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="onolys_evaluation.check",
                                description=__doc__.split("\n")[0])
    p.add_argument("--pack", default=None,
                   help="pack id@version or directory (default: the only pack)")
    p.add_argument("--preset", help="route preset (default: the default preset)")
    p.add_argument("--fixture-dir", type=Path, default=None,
                   help="folder with transcript.json, speaker_map.json, rating_card.json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(run_check(args.pack or default_pack(), args.preset,
                                       args.fixture_dir))
    except (OnolysError, OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
