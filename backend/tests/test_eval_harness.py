"""The harness against the scripted pipeline: e2e mode, a finer atomizer, and variants."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))
from pl_scripted import Scripted  # noqa: E402

from eval.adapters import load_fixture, run_e2e  # noqa: E402
from eval.score import aggregate, evaluate  # noqa: E402
from iaudit_backend.config import Settings  # noqa: E402


async def e2e(vid):
    s = Scripted(None if vid == "faithful" else vid)
    request, gold = load_fixture(vid)
    assert request["assessment"] == s.request["assessment"]  # same text as the committed fixture
    response, metrics = await run_e2e(request, gold, Settings(), s)
    return evaluate(vid, request, response, gold, metrics.snapshot()), response


async def test_faithful_e2e_passes_the_gate_even_though_the_atomizer_is_finer_than_gold():
    res, response = await e2e("faithful")
    assert len(response["claims"]) == 11 and res.gate, res.gate_detail  # gold has 10 claims
    assert res.controls == [0, 10]


@pytest.mark.parametrize("vid", ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8"])
async def test_each_variant_target_is_found_and_scored_by_bucket(vid):
    res, _ = await e2e(vid)
    assert res.gate, (vid, res.gate_detail)
    rep = aggregate([res])
    (bucket,) = [b for b, r in rep["buckets"].items() if r["tp"] == 1]
    assert rep["buckets"][bucket]["recall"] == 1.0
    assert rep["buckets"][bucket]["verdict_accuracy"] == {"correct": 1, "total": 1}


def _resp(*pieces):
    def pt(c):
        return {"char": c, "index": 0}

    return {
        "claims": [
            {
                "span": {"start": pt(s), "end": pt(e)},
                "verdict": v,
                "concerns": [{"type": t} for t in ts],
                "explanation": "",
            }
            for s, e, v, ts in pieces
        ]
    }


def test_smoke_judge_split_target_takes_partial_over_insufficient():
    from eval.smoke import judge

    text = "Alpha beta. Gamma delta."
    expected = {
        "fixture": "vx",
        "target_text": text,
        "verdict": "partially_supported",
        "concerns_required": ["frequency_severity_inflation"],
    }
    resp = _resp(
        (0, 11, "partially_supported", ["frequency_severity_inflation"]),
        (12, 24, "insufficient_evidence", []),
    )
    out = judge(expected, resp, [text])
    assert out.actual_verdict == "partially_supported" and out.passed
