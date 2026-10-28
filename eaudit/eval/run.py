"""Evaluation harness CLI (07 R9). Run from eaudit/:

    uv run python -m eval.run --mode gold|linked|e2e|oracle [--only v1,v3] [--replay | --live
        [--record]] [--max-cost USD] [--out DIR] [--gate poc] [--strict-fresh] [--baseline NAME]

Replay (the default) reads recorded LLM answers, so it tests plumbing, assembler and scoring
offline. `--live` needs provider keys and prints a cost estimate first. Results are labelled
split `poc-all`: a smoke check on data the authors have seen, not a generalization estimate.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from eaudit.config import Settings
from eaudit.llm import (
    FixtureClient,
    RecordingClient,
    make_client,
)
from eval.adapters import MODES, RUNNERS, MissCounter, load_fixture
from eval.adhd import DATA
from eval.baselines import BaselineNotInstalled, get_baseline, run_baseline
from eval.score import FixtureResult, aggregate, evaluate

EVAL_DIR = Path(__file__).resolve().parent
RECORDED = EVAL_DIR / "recorded"
GATED = ["faithful", *[f"v{i}" for i in range(1, 9)]]  # v4-noroles is an extra check, not gated
SPLIT = "poc-all"
KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LITELLM_API_KEY")
PROMPTS = Path(__file__).resolve().parents[1] / "src" / "eaudit" / "prompts"
STAGE_FILES = {
    "atomize": ["atomize_system.md", "atomize_fewshot.json"],
    "link": ["link_system.md", "link_fewshot.json"],
    "check": ["check_system.md", "check_fewshot.json"],
}


def prices() -> dict:
    return json.loads((EVAL_DIR / "prices.json").read_text(encoding="utf-8"))


def prompt_hashes() -> dict[str, str]:
    out = {}
    for stage, files in STAGE_FILES.items():
        h = hashlib.sha256()
        for f in files:
            h.update((PROMPTS / f).read_bytes())
        out[stage] = h.hexdigest()[:16]
    from eaudit.prep.prompt import SYSTEM

    out["prep"] = hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]
    return out


def write_manifest(fixture_dir: Path, settings: Settings) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "manifest.json").write_text(
        json.dumps(
            {
                "date": date.today().isoformat(),
                "models": {"cheap": settings.model_cheap, "mid": settings.model_mid,
                           "strong": settings.model_strong},
                "prompt_hashes": prompt_hashes(),
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )  # fmt: skip


def stale_stages(fixture_dir: Path) -> list[str] | None:
    """Stages whose prompt changed since recording; None if there is no manifest."""
    path = fixture_dir / "manifest.json"
    if not path.is_file():
        return None
    recorded = json.loads(path.read_text(encoding="utf-8")).get("prompt_hashes", {})
    now = prompt_hashes()
    return sorted(s for s in now if recorded.get(s) != now[s])


def estimate_cost(mode: str, names: list[str], settings: Settings) -> float:
    """Rough upper-ish estimate: claims x calls x (transcript + stage tokens)."""
    if mode == "oracle":
        return 0.0
    per_call_in, per_call_out = 6000, 600
    calls = {"gold": 11, "linked": 22, "e2e": 23}[mode] * len(names)
    p = prices()["models"]["sonnet"]
    return round(calls * (per_call_in * p["input"] + per_call_out * p["output"]) / 1e6, 2)


def pick_names(only: str | None) -> list[str]:
    available = sorted(p.stem for p in (DATA / "requests").glob("*.json"))
    if not only:
        return [n for n in GATED if n in available]
    names = [n.strip() for n in only.split(",") if n.strip()]
    unknown = [n for n in names if n not in available]
    if unknown:
        raise SystemExit(f"unknown fixture(s): {', '.join(unknown)}")
    return names


async def run_mode(mode: str, names: list[str], settings: Settings, llm) -> tuple[list, list]:
    """Returns (results, errors). A replay gap or a pipeline failure is an error, not a score."""
    results: list[FixtureResult] = []
    errors: list[dict] = []
    counter = MissCounter(llm) if llm is not None else None
    for name in names:
        request, gold = load_fixture(name)
        before = counter.misses if counter else 0
        started = time.monotonic()
        try:
            response, metrics = await RUNNERS[mode](request, gold, settings, counter)
        except Exception as exc:  # DeadlineExceeded, LLMUnavailable, ...
            errors.append({"fixture": name, "error": type(exc).__name__})
            continue
        wall = time.monotonic() - started
        if counter and counter.misses > before:
            errors.append({"fixture": name, "error": f"FixtureMiss x{counter.misses - before}"})
            continue
        results.append(evaluate(name, request, response, gold, metrics.snapshot(), wall))
    return results, errors


def _pct(x) -> str:
    return "-" if x is None else f"{x:.2f}"


def _verdicts(va: dict | None) -> str:
    return "-" if not va else f"{va['correct']}/{va['total']}"


def render_md(reports: dict[str, dict], notes: list[str]) -> str:
    lines = [f"# Evaluation report (split `{SPLIT}`)", ""]
    lines += [f"> {n}" for n in notes] + ([""] if notes else [])
    lines += ["No overall score is computed; every number is per bucket.", ""]
    head = "| bucket | concern | n | P | R | F1 | verdicts | flags |"
    for mode, rep in reports.items():
        lines += [f"## {mode}", "", head, "|---|---|---|---|---|---|---|---|"]
        for b, r in rep["buckets"].items():
            cells = [
                b, r["concern"], str(r["n"]), _pct(r["precision"]), _pct(r["recall"]),
                _pct(r["f1"]), _verdicts(r["verdict_accuracy"]), "; ".join(r["flags"]),
            ]  # fmt: skip
            lines.append("| " + " | ".join(cells) + " |")
        c, e, lat = rep["control"], rep["evidence"], rep["latency"]
        cost = rep["cost_estimate_usd"]
        lines += [
            "",
            f"Control false-alarm rate: {c['false_alarms']}/{c['controls']}. "
            f"Evidence turn recall {_pct(e['recall'])}, "
            f"turn precision {_pct(e['turn_precision'])}, "
            f"role agreement {_pct(e['role_ok_rate'])}.",
            "",
            f"Latency p50/max per request: {_pct(lat['request_p50_s'])}s / "
            f"{_pct(lat['request_max_s'])}s. Estimated cost: "
            f"{'-' if cost is None else '$' + format(cost, '.2f')}.",
        ]
        if rep.get("errors"):
            lost = ", ".join(f"{x['fixture']} ({x['error']})" for x in rep["errors"])
            lines += ["", f"Errors (not scored): {lost}"]
        lines.append("")
    if len(reports) > 1:  # side by side localizes the weak stage
        modes = list(reports)
        buckets = sorted({b for r in reports.values() for b in r["buckets"]}, key=int)
        lines += ["## Side by side (F1 per bucket)", "", "| bucket | " + " | ".join(modes) + " |",
                  "|---|" + "---|" * len(modes)]  # fmt: skip
        for b in buckets:
            cells = [_pct(reports[m]["buckets"].get(b, {}).get("f1")) for m in modes]
            lines.append(f"| {b} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def bucket1_inputs(names: list[str]) -> list[tuple[str, str, str]]:
    rows = []
    for name in names:
        request, gold = load_fixture(name)
        turns = request["transcript"]
        for g in gold:
            evidence = " ".join(turns[e.turn]["text"] for e in g.evidence)
            rows.append(
                (
                    g.claim_text,
                    evidence,
                    "supported" if g.verdict == "supported" else "not_supported",
                )
            )
    return rows  # fmt: skip


def empty_report() -> dict:
    """What a mode reports when every fixture errored (nothing was scored)."""
    return {
        "buckets": {},
        "gate": {},
        "control": {"false_alarms": 0, "controls": 0},
        "evidence": {"recall": None, "turn_precision": None, "role_ok_rate": None},
        "latency": {"request_p50_s": None, "request_max_s": None},
        "cost_estimate_usd": None,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="eval.run", description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", default="oracle", help="oracle|gold|linked|e2e, comma list, or all")
    ap.add_argument("--fixtures", default="adhd")
    ap.add_argument("--only", help="comma-separated fixtures, e.g. v1,v3")
    live = ap.add_mutually_exclusive_group()
    live.add_argument("--replay", action="store_true", help="read recordings (default)")
    live.add_argument("--live", action="store_true", help="call the providers (needs keys)")
    ap.add_argument("--record", action="store_true", help="with --live: write recordings")
    ap.add_argument("--max-cost", type=float, help="abort a live run estimated above this (USD)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--gate", choices=["poc"])
    ap.add_argument("--strict-fresh", action="store_true")
    ap.add_argument("--allow-test-split", action="store_true")
    ap.add_argument("--baseline")
    ap.add_argument("--fixture-dir", type=Path, default=RECORDED)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fixtures != "adhd":
        print(f"unknown fixture set {args.fixtures!r}; only 'adhd' exists")
        return 2
    if args.record and not args.live:
        print("--record needs --live")
        return 2
    modes = ["gold", "linked", "e2e"] if args.mode == "all" else args.mode.split(",")
    bad = [m for m in modes if m not in MODES]
    if bad:
        print(f"unknown mode(s): {', '.join(bad)}; choose from {', '.join(MODES)}")
        return 2
    names = pick_names(args.only)
    notes = [f"Split `{SPLIT}`: data the authors have seen. A smoke check, not a generalization "
             "estimate; no precision claim is made from it."]  # fmt: skip
    if not (DATA / "requests" / "multi.json").exists():
        print("adhd-multi: skipped (waiting for an approved composition, 07 O-5)")
    if not (EVAL_DIR / "private" / "prepare_cdr.py").exists():
        print("cdr: not built (waiting for the interview files, 07 O-10 and O-11)")

    if args.baseline:
        try:
            baseline = get_baseline(args.baseline)
        except (BaselineNotInstalled, KeyError) as exc:
            print(exc)
            return 2
        print(json.dumps(run_baseline(baseline, bucket1_inputs(names)), indent=1))
        return 0

    needs_llm = [m for m in modes if m != "oracle"]
    settings = Settings(
        llm_mode="live" if args.live else "fixture", fixture_dir=str(args.fixture_dir)
    )
    llm = None
    if needs_llm:
        if args.live:
            if not any(k in os.environ for k in KEY_VARS):
                print("--live needs a provider key in the environment "
                      f"({', '.join(KEY_VARS)}); not falling back to replay")  # fmt: skip
                return 2
            estimate = sum(estimate_cost(m, names, settings) for m in needs_llm)
            print(f"estimated cost: ${estimate:.2f} for {len(names)} fixture(s) in "
                  f"{', '.join(needs_llm)}")  # fmt: skip
            if args.max_cost is not None and estimate > args.max_cost:
                print(f"estimate exceeds --max-cost ${args.max_cost:.2f}; nothing was called")
                return 2
            llm = make_client(settings)
            if args.record and not isinstance(llm, RecordingClient):
                llm = RecordingClient(llm, args.fixture_dir)
        else:
            llm = FixtureClient(args.fixture_dir)
            stale = stale_stages(args.fixture_dir)
            if stale is None:
                notes.append("No recording manifest: freshness unknown.")
            elif stale:
                msg = f"Stale recordings: prompts changed for {', '.join(stale)}."
                print("warning:", msg)
                notes.append(msg)
                if args.strict_fresh:
                    return 2

    reports: dict[str, dict] = {}
    failed = False
    for mode in modes:
        results, errors = asyncio.run(
            run_mode(mode, names, settings, llm if mode != "oracle" else None)
        )
        rep = aggregate(results, prices(), settings.audit_deadline_s) if results else empty_report()
        rep.update(mode=mode, split=SPLIT, errors=errors)
        reports[mode] = rep
        if args.out:
            d = args.out / mode
            d.mkdir(parents=True, exist_ok=True)
            (d / "report.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
            (d / "claims.jsonl").write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for r in results for row in r.rows),
                encoding="utf-8",
            )
        if args.gate == "poc":
            for r in results:
                if r.fixture in GATED:
                    print(
                        f"{'PASS' if r.gate else 'FAIL'}  {mode}  adhd-{r.fixture}: {r.gate_detail}"
                    )
                    failed |= not r.gate
                    if r.collateral:
                        print(f"      collateral concerns (not gated): {', '.join(r.collateral)}")
        for e in errors:
            print(f"ERROR {mode} adhd-{e['fixture']}: {e['error']} (not scored)")
        failed |= bool(errors)
    if args.record and args.live:
        write_manifest(args.fixture_dir, settings)
    if args.out:
        (args.out / "report.md").write_text(render_md(reports, notes), encoding="utf-8")
    elif not args.gate:
        print(render_md(reports, notes))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
