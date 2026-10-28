"""R8: per-bucket metrics for one mode. Never one overall number."""

import statistics
from dataclasses import dataclass, field

from eval.gold import CONCERNS, GoldClaim
from eval.match import Matched, MatchResult, match_claims

MIN_N_INDICATIVE = 5
MIN_N_FLAGS = 10
P0_PRECISION_TARGET = 0.8


def covered_turns(evidence_span: dict, turn_lengths: list[int]) -> set[int]:
    """Turns holding at least one code point of the span (a char-0 end covers nothing)."""
    s, e = evidence_span["start"], evidence_span["end"]
    out = set()
    for k in range(s["index"], e["index"] + 1):
        if not 0 <= k < len(turn_lengths):
            continue
        lo = s["char"] if k == s["index"] else 0
        hi = e["char"] if k == e["index"] else turn_lengths[k]
        if hi > lo:
            out.add(k)
    return out


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def prf(self) -> dict:
        p = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        r = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        if self.tp:
            f1 = 2 * p * r / (p + r)
        else:  # nothing right: 0.0 when there were gold faults, unmeasured when there were none
            f1 = 0.0 if self.tp + self.fn else None
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "n": self.tp + self.fn,
                "precision": p, "recall": r, "f1": f1}  # fmt: skip


@dataclass
class FixtureResult:
    fixture: str
    gate: bool
    gate_detail: str
    rows: list[dict] = field(default_factory=list)  # claims.jsonl lines (no text)
    detection: dict[int, Counts] = field(default_factory=dict)
    verdict_by_bucket: dict[int, list[int]] = field(default_factory=dict)  # [correct, total]
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    controls: list[int] = field(default_factory=lambda: [0, 0])  # [false alarms, controls]
    evidence: dict[str, int] = field(
        default_factory=lambda: {"required": 0, "covered": 0, "pred_turns": 0, "pred_in_gold": 0,
                                 "roles_checked": 0, "roles_ok": 0}
    )  # fmt: skip
    warnings_expected: list[int] = field(default_factory=lambda: [0, 0])  # [seen, expected]
    collateral: list[str] = field(default_factory=list)
    wall_s: float | None = None
    calls: dict[str, list[float]] = field(default_factory=dict)  # call_tag -> latencies ms
    tokens: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> token counts


def _bucket(concern: str) -> int:
    return CONCERNS.index(concern) + 1


def _turn_lengths(request: dict) -> list[int]:
    return [len(t["text"]) for t in request["transcript"]]


def _evidence_scores(res: FixtureResult, m: Matched, lengths: list[int]) -> None:
    """Turn-level recall, turn precision and role agreement for one matched gold claim."""
    cover: dict[int, set[str]] = {}
    for e in m.evidence:
        for k in covered_turns(e["span"], lengths):
            cover.setdefault(k, set()).add(e["role"])
    gold_turns = {e.turn for e in m.gold.evidence}
    req = set(m.gold.required_turns)
    ev = res.evidence
    ev["required"] += len(req)
    ev["covered"] += len(req & set(cover))
    ev["pred_turns"] += len(cover)
    ev["pred_in_gold"] += len(set(cover) & gold_turns)
    for g in m.gold.evidence:
        if g.turn in cover:
            ev["roles_checked"] += 1
            ev["roles_ok"] += int(bool(cover[g.turn] & set(g.roles_ok)))


def evaluate(
    fixture: str, request: dict, response: dict, gold: list[GoldClaim],
    metrics: dict | None = None, wall_s: float | None = None,
) -> FixtureResult:  # fmt: skip
    """Match, then score one fixture. `fixture` is the short name (`faithful`, `v1`)."""
    mr: MatchResult = match_claims(gold, response["claims"])
    res = FixtureResult(fixture, True, "", wall_s=wall_s)
    lengths = _turn_lengths(request)
    pred_ids_with_warning = {}
    for w in response.get("warnings", []):
        pred_ids_with_warning.setdefault(w.get("claim_id"), set()).add(w["code"])
    for m in mr.matched:
        g = m.gold
        det = res.detection
        got = m.concerns
        allowed = set(g.concerns_required) | set(g.concerns_allowed)
        for c in g.concerns_required:
            cnt = det.setdefault(_bucket(c), Counts())
            if c in got:
                cnt.tp += 1
            else:
                cnt.fn += 1
        for c in got - allowed:
            det.setdefault(_bucket(c), Counts()).fp += 1
        res.confusion.setdefault(g.verdict, {}).setdefault(m.verdict, 0)
        res.confusion[g.verdict][m.verdict] += 1
        if g.role_in_fixture == "target" and g.bucket:
            v = res.verdict_by_bucket.setdefault(g.bucket, [0, 0])
            v[0] += int(m.verdict == g.verdict)
            v[1] += 1
        if g.role_in_fixture == "control":
            res.controls[1] += 1
            res.controls[0] += int(m.verdict != "supported" or bool(got))
        _evidence_scores(res, m, lengths)
        warns = set().union(*(pred_ids_with_warning.get(p["id"], set()) for p in m.preds))
        if g.expect_warnings:
            res.warnings_expected[1] += len(g.expect_warnings)
            res.warnings_expected[0] += len(set(g.expect_warnings) & warns)
        res.rows.append(
            {
                "fixture": f"adhd-{fixture}", "gold_id": g.claim_id,
                "pred_ids": [p["id"] for p in m.preds], "role": g.role_in_fixture,
                "gold_verdict": g.verdict, "pred_verdict": m.verdict,
                "gold_concerns": g.concerns_required, "pred_concerns": sorted(got),
                "evidence_turns_required": g.required_turns,
                "evidence_turns_covered": sorted(
                    {k for e in m.evidence for k in covered_turns(e["span"], lengths)}
                ),
            }
        )  # fmt: skip
    for g in mr.missed:
        for c in g.concerns_required:
            res.detection.setdefault(_bucket(c), Counts()).fn += 1
        if g.role_in_fixture == "target" and g.bucket:
            res.verdict_by_bucket.setdefault(g.bucket, [0, 0])[1] += 1
        if g.role_in_fixture == "control":
            res.controls[1] += 1
        res.evidence["required"] += len(g.required_turns)
        res.rows.append({"fixture": f"adhd-{fixture}", "gold_id": g.claim_id, "pred_ids": [],
                         "role": g.role_in_fixture, "gold_verdict": g.verdict,
                         "pred_verdict": None, "gold_concerns": g.concerns_required,
                         "pred_concerns": [], "missed": True})  # fmt: skip
    for c in mr.extras:  # concerns on claims the gold does not know are false positives
        for k in c["concerns"]:
            res.detection.setdefault(_bucket(k["type"]), Counts()).fp += 1
    _gate(res, fixture, mr, response)
    if metrics:
        _metrics(res, metrics)
    return res


def _gate(res: FixtureResult, fixture: str, mr: MatchResult, response: dict) -> None:
    """Per-fixture POC pass/fail (R9): a boolean, not a score."""
    claims = response["claims"]
    if fixture == "faithful":
        bad = [c for c in claims if c["verdict"] != "supported" or c["concerns"]]
        res.gate = bool(claims) and not bad and not mr.missed
        res.gate_detail = (
            "all claims supported, no concerns"
            if res.gate
            else (f"{len(bad)} claim(s) not clean, {len(mr.missed)} gold claim(s) missed")
        )
        return
    targets = [m for m in mr.matched if m.gold.role_in_fixture == "target"]
    if not targets:
        res.gate, res.gate_detail = False, "target claim not found"
        return
    m = targets[0]
    g = m.gold
    problems = []
    if m.verdict != g.verdict:
        problems.append(f"verdict {m.verdict} != {g.verdict}")
    problems += [f"missing concern {c}" for c in g.concerns_required if c not in m.concerns]
    problems += [f"explanation lacks {s}" for s in g.explanation_contains
                 if s.lower() not in m.explanation]  # fmt: skip
    res.gate, res.gate_detail = not problems, "; ".join(problems) or "target as expected"
    others = set()
    for other in mr.matched:
        if other is not m:
            others |= other.concerns
    res.collateral = sorted(others | {k["type"] for c in mr.extras for k in c["concerns"]})


def _metrics(res: FixtureResult, snap: dict) -> None:
    for r in snap.get("records", []):
        res.calls.setdefault(r["call_tag"], []).append(r["latency_ms"])
        t = res.tokens.setdefault(r["model"], {"input": 0, "output": 0, "cache_read": 0,
                                               "cache_write": 0})  # fmt: skip
        t["input"] += r["input_tokens"]
        t["output"] += r["output_tokens"]
        t["cache_read"] += r["cache_read_tokens"]
        t["cache_write"] += r["cache_write_tokens"]


def cost_usd(tokens: dict[str, dict[str, int]], prices: dict) -> float:
    """Estimate from `prices.json` ($ per million tokens, matched on a model-id fragment)."""
    total = 0.0
    for model, t in tokens.items():
        for frag, p in prices["models"].items():
            if frag in model:
                read = p.get("cache_read", p["input"] * 0.1)
                write = p.get("cache_write", p["input"] * 1.25)
                total += (
                    t["input"] * p["input"]
                    + t["output"] * p["output"]
                    + t["cache_read"] * read
                    + t["cache_write"] * write
                ) / 1e6
                break
    return round(total, 6)


def aggregate(results: list[FixtureResult], prices: dict | None = None,
              deadline_s: float = 60.0) -> dict:  # fmt: skip
    """Combine fixtures into the report dict (per-bucket, never overall)."""
    det: dict[int, Counts] = {}
    vb: dict[int, list[int]] = {}
    conf: dict[str, dict[str, int]] = {}
    ev = {k: 0 for k in results[0].evidence} if results else {}
    controls, warns = [0, 0], [0, 0]
    for r in results:
        for b, c in r.detection.items():
            d = det.setdefault(b, Counts())
            d.tp, d.fp, d.fn = d.tp + c.tp, d.fp + c.fp, d.fn + c.fn
        for b, (ok, n) in r.verdict_by_bucket.items():
            v = vb.setdefault(b, [0, 0])
            v[0], v[1] = v[0] + ok, v[1] + n
        for g, row in r.confusion.items():
            for p, n in row.items():
                conf.setdefault(g, {}).setdefault(p, 0)
                conf[g][p] += n
        for k in ev:
            ev[k] += r.evidence[k]
        controls = [controls[0] + r.controls[0], controls[1] + r.controls[1]]
        warns = [warns[0] + r.warnings_expected[0], warns[1] + r.warnings_expected[1]]
    buckets = {}
    for b in sorted(det):
        row = det[b].prf()
        n = row["n"]
        row["verdict_accuracy"] = {"correct": vb[b][0], "total": vb[b][1]} if b in vb else None
        flags = []
        if n < MIN_N_INDICATIVE:
            flags.append("indicative only (n < 5)")
        elif (
            n >= MIN_N_FLAGS
            and row["precision"] is not None
            and row["precision"] < P0_PRECISION_TARGET
        ):
            flags.append("below the 0.8 precision target")
        row["flags"] = flags
        row["concern"] = CONCERNS[b - 1]
        buckets[str(b)] = row
    lat = {t: {"p50_ms": statistics.median(v), "max_ms": max(v), "calls": len(v)}
           for t, v in _merge_calls(results).items()}  # fmt: skip
    walls = [r.wall_s for r in results if r.wall_s is not None]
    tokens: dict[str, dict[str, int]] = {}
    for r in results:
        for m, t in r.tokens.items():
            agg = tokens.setdefault(m, {k: 0 for k in t})
            for k, v in t.items():
                agg[k] += v
    return {
        "buckets": buckets,
        "verdict_confusion": conf,
        "control": {
            "false_alarms": controls[0],
            "controls": controls[1],
            "false_alarm_rate": controls[0] / controls[1] if controls[1] else None,
        },  # fmt: skip
        "evidence": {
            **ev,
            "recall": ev["covered"] / ev["required"] if ev.get("required") else None,
            "turn_precision": ev["pred_in_gold"] / ev["pred_turns"]
            if ev.get("pred_turns")
            else None,
            "role_ok_rate": ev["roles_ok"] / ev["roles_checked"]
            if ev.get("roles_checked")
            else None,
        },  # fmt: skip
        "expected_warnings": {"seen": warns[0], "expected": warns[1]},
        "latency": {
            "calls": lat,
            "request_p50_s": statistics.median(walls) if walls else None,
            "request_max_s": max(walls) if walls else None,
            "over_deadline": [
                r.fixture for r in results if r.wall_s is not None and r.wall_s > deadline_s
            ],
        },  # fmt: skip
        "tokens": tokens,
        "cost_estimate_usd": cost_usd(tokens, prices) if prices else None,
        "gate": {
            r.fixture: {"pass": r.gate, "detail": r.gate_detail, "collateral": r.collateral}
            for r in results
        },  # fmt: skip
    }


def _merge_calls(results: list[FixtureResult]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in results:
        for t, v in r.calls.items():
            out.setdefault(t, []).extend(v)
    return out
