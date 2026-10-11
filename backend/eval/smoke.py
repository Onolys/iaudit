"""POC gate: send the 9 ADHD fixtures to POST /v1/audit and print PASS/FAIL per fixture.

    uv run python -m eval.smoke [--base-url URL | --inprocess] [--only v1,v3]

Exits 1 on any failure. Prints verdicts and concern types only, never transcript text.
"""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from eval.adhd import DATA

NAMES = ["faithful", *[f"v{i}" for i in range(1, 9)]]
# Worst last: a split claim takes the most severe verdict among its pieces.
SEVERITY = [
    "supported",
    "out_of_scope",
    "partially_supported",
    "insufficient_evidence",
    "contradicted",
]


@dataclass
class Fixture:
    name: str
    request: dict
    expected: dict
    expected_path: Path


@dataclass
class Outcome:
    fixture: str
    expected: str
    actual_verdict: str
    actual_concerns: list[str]
    collateral: list[str]
    passed: bool
    detail: str = field(default="")


def load_fixtures(only: list[str] | None = None) -> list[Fixture]:
    unknown = [n for n in only or [] if n not in NAMES]
    if unknown:
        raise ValueError(f"unknown fixture(s): {', '.join(unknown)}")
    out = []
    for name in NAMES:
        if only and name not in only:
            continue
        exp_path = DATA / "expected" / f"{name}.json"
        out.append(
            Fixture(
                name,
                json.loads((DATA / "requests" / f"{name}.json").read_text(encoding="utf-8")),
                json.loads(exp_path.read_text(encoding="utf-8")),
                exp_path,
            )
        )
    return out


def _concerns(claim: dict) -> list[str]:
    return [c["type"] for c in claim.get("concerns", [])]


def _overlaps(claim: dict, section: int, start: int, end: int) -> bool:
    s, e = claim["span"]["start"], claim["span"]["end"]
    if s["index"] != section or e["index"] != section:
        return False
    return s["char"] < end and e["char"] > start


def _worst(verdicts: list[str]) -> str:
    return max(verdicts, key=lambda v: SEVERITY.index(v) if v in SEVERITY else len(SEVERITY))


def _judge_faithful(response: dict) -> Outcome:
    claims = response.get("claims", [])
    verdicts = [c["verdict"] for c in claims]
    concerns = sorted({t for c in claims for t in _concerns(c)})
    ok = bool(claims) and all(v == "supported" for v in verdicts) and not concerns
    actual = _worst(verdicts) if verdicts else "none"
    return Outcome("", "all supported, no concerns", actual, concerns, [], ok)


def judge(expected: dict, response: dict, section_texts: list[str]) -> Outcome:
    """Compare one response with one expected file (R14 matching: span overlap, worst verdict)."""
    if "all_claims" in expected:
        out = _judge_faithful(response)
        out.fixture = expected["fixture"]
        return out
    target = expected["target_text"]
    section = next((i for i, t in enumerate(section_texts) if target in t), -1)
    want = f"{expected['verdict']} + {','.join(expected['concerns_required']) or 'no concern'}"
    if section < 0:
        return Outcome(expected["fixture"], want, "none", [], [], False, "target not in request")
    start = section_texts[section].index(target)
    end = start + len(target)
    hit = [c for c in response.get("claims", []) if _overlaps(c, section, start, end)]
    other = [c for c in response.get("claims", []) if c not in hit]
    collateral = sorted({t for c in other for t in _concerns(c)})
    if not hit:
        return Outcome(
            expected["fixture"], want, "none", [], collateral, False, "no claim overlaps"
        )
    verdict = _worst([c["verdict"] for c in hit])
    concerns = sorted({t for c in hit for t in _concerns(c)})
    explanation = " ".join(c.get("explanation", "") for c in hit).lower()
    missing = [t for t in expected["concerns_required"] if t not in concerns]
    absent = [s for s in expected.get("explanation_contains", []) if s.lower() not in explanation]
    ok = verdict == expected["verdict"] and not missing and not absent
    detail = ""
    if absent:
        detail = f"explanation lacks: {', '.join(absent)}"
    return Outcome(expected["fixture"], want, verdict, concerns, collateral, ok, detail)


def run_fixture(fx: Fixture, post: Callable[[dict], object]) -> Outcome:
    resp = post(fx.request)
    if resp.status_code != 200:
        return Outcome(
            fx.request["request_id"],
            "200 OK",
            f"HTTP {resp.status_code}",
            [],
            [],
            False,
            f"HTTP {resp.status_code}",
        )
    texts = [s["text"] for s in fx.request["assessment"]]
    return judge(fx.expected, resp.json(), texts)


def _make_post(base_url: str | None) -> Callable[[dict], object]:
    if base_url:
        import httpx

        url = base_url.rstrip("/") + "/v1/audit"
        return lambda body: httpx.post(url, json=body, timeout=130)
    from fastapi.testclient import TestClient

    from iaudit_backend.app import create_app

    client = TestClient(create_app())
    client.__enter__()  # runs the app lifespan (pipeline and LLM client are built there)
    return lambda body: client.post("/v1/audit", json=body)


def _line(o: Outcome) -> str:
    actual = o.actual_verdict
    if not o.actual_verdict.startswith(("HTTP", "error")):
        actual += f" + {','.join(o.actual_concerns) or 'no concern'}"
    text = (
        f"{'PASS' if o.passed else 'FAIL'}  {o.fixture}: expected [{o.expected}] actual [{actual}]"
    )
    if o.detail and not o.actual_verdict.startswith("HTTP"):
        text += f" ({o.detail})"
    if o.collateral:
        text += f" collateral: {','.join(o.collateral)}"
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.smoke", description=__doc__.splitlines()[0])
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--base-url", help="running server, e.g. http://localhost:8000")
    where.add_argument("--inprocess", action="store_true", help="in-process app (default)")
    ap.add_argument("--only", help="comma-separated fixtures, e.g. v1,v3")
    args = ap.parse_args(argv)
    try:
        fixtures = load_fixtures([n for n in (args.only or "").split(",") if n] or None)
    except ValueError as exc:
        ap.error(str(exc))
    post = _make_post(args.base_url)
    outcomes = []
    for fx in fixtures:
        try:
            outcomes.append(run_fixture(fx, post))
        except Exception as exc:  # a transport failure is a FAIL, not a crash
            outcomes.append(
                Outcome(
                    fx.request["request_id"], "200 OK", "error", [], [], False, type(exc).__name__
                )
            )
        print(_line(outcomes[-1]))
    failed = sum(not o.passed for o in outcomes)
    print(f"{len(outcomes) - failed}/{len(outcomes)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
