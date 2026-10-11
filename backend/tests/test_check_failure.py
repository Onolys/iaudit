import logging

import pytest
from check_helpers import adhd_prep, claim, ev, link

from iaudit_backend.assembler import InternalAudit, assemble
from iaudit_backend.check import check_claims
from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.config import Settings
from iaudit_backend.llm import (
    FailingClient,
    LLMBadOutput,
    LLMTimeout,
    LLMUnavailable,
    StubClient,
)
from iaudit_backend.models import AuditRequest

PREP = adhd_prep(roles=True)
UNSPEC = [{"source": "unspecified", "speaker": None}]


def item(key, **kw):
    return {"key": key, "relation": "entails", **kw}


class Scripted:
    """Per-claim behaviour: a value to return or an exception to raise."""

    def __init__(self, by_claim):
        self.by_claim = by_claim
        self.calls = []

    async def complete_json(self, req, metrics=None):
        from iaudit_backend.llm import LLMResult

        cid = req.fixture_key.split(".check.")[1].removesuffix(".retry")
        self.calls.append(req.fixture_key)
        v = self.by_claim[cid]
        if isinstance(v, list):
            v = v.pop(0)
        if isinstance(v, BaseException):
            raise v
        return LLMResult(parsed=VerifierOutput.model_validate(v))


def setup(**by_claim):
    cs = [claim(f"Claim {cid}.", cid=cid, reported_by=UNSPEC) for cid in by_claim]
    ls = [link(ev(cid=cid), cid=cid) for cid in by_claim]
    return cs, ls


@pytest.mark.parametrize(
    "bad,reason",
    [
        (LLMTimeout("t"), "timeout"),
        (LLMUnavailable("u"), "unavailable"),
        (LLMBadOutput("b"), "bad_output"),
        (RuntimeError("bug"), "bad_output"),
    ],
)
async def test_one_failure_stalls_only_that_claim(make_ctx, bad, reason):
    by = {
        "c0.1": {"items": [item("c0.1:e1")]},
        "c0.2": bad,
        "c0.3": {"items": [item("c0.3:e1")]},
    }
    cs, ls = setup(**by)
    ctx = make_ctx(llm=Scripted(by))
    out = await check_claims(cs, ls, PREP, PREP.turns, ctx)
    assert [d.outcome for d in out] == ["ok", "stalled", "ok"]
    assert out[0].verdict == out[2].verdict == "supported"
    assert ctx.extras["check_stalls"] == {"c0.2": reason}


async def test_bad_json_twice_stalls(make_ctx):
    cs, ls = setup(**{"c0.1": None})
    ctx = make_ctx(llm=Scripted({"c0.1": [LLMBadOutput("x"), LLMBadOutput("y")]}))
    (d,) = await check_claims(cs, ls, PREP, PREP.turns, ctx)
    assert d.outcome == "stalled" and ctx.extras["check_stalls"] == {"c0.1": "bad_output"}


async def test_unjudged_item_after_retry_stalls_only_that_claim(make_ctx):
    cs = [claim("A.", cid="c0.1", reported_by=UNSPEC), claim("B.", cid="c0.2", reported_by=UNSPEC)]
    ls = [link(ev(n=1), ev(n=2, turn=5)), link(ev(cid="c0.2"), cid="c0.2")]
    short = {"items": [item("c0.1:e1")]}
    ctx = make_ctx(llm=Scripted({"c0.1": [short, short], "c0.2": {"items": [item("c0.2:e1")]}}))
    out = await check_claims(cs, ls, PREP, PREP.turns, ctx)
    assert [d.outcome for d in out] == ["stalled", "ok"]


async def test_all_claims_unavailable_is_visible_to_the_caller(make_ctx):
    cs, ls = setup(**{"c0.1": 0, "c0.2": 0})
    ctx = make_ctx(llm=FailingClient(LLMUnavailable("down")))
    out = await check_claims(cs, ls, PREP, PREP.turns, ctx)
    assert all(d.outcome == "stalled" for d in out)
    assert set(ctx.extras["check_stalls"].values()) == {"unavailable"}


async def test_logs_hold_counts_only(make_ctx, caplog):
    canary = "zebracanary"
    c = claim(f"{canary} forgets quokkaproposition.", reported_by=UNSPEC)
    e = ev(text=f"{canary} narwhalturn")
    flag = {"type": "context_stripping", "keys": ["c0.1:e1"], "conf": "low"}
    stub = StubClient()
    stub.register(
        "check",
        lambda r: VerifierOutput.model_validate({"items": [item("c0.1:e1")], "flags": [flag]}),
    )
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        await check_claims([c], [link(e)], PREP, PREP.turns, make_ctx(llm=stub))
        await check_claims(
            [c], [link(e)], PREP, PREP.turns, make_ctx(llm=FailingClient(LLMTimeout(canary)))
        )
    text = caplog.text
    assert canary not in text and "quokkaproposition" not in text and "narwhalturn" not in text
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("check_claim")]
    assert any("verdict=" in m and "flags_below_floor=1" in m and "called=1" in m for m in lines)
    assert any('failure="timeout"' in m for m in lines)


def test_check_settings_defaults():
    s = Settings()
    assert (s.check_concurrency, s.check_max_tokens) == (20, 1500)
    assert (s.check_min_conf_p0, s.check_min_conf_p1) == (0.5, 0.6)
    assert (s.check_step_material, s.check_contradict_gap, s.check_rate_ratio) == (1, 3, 1.5)
    assert s.check_suggest_revision is True and s.check_retry is True


async def test_check_concurrency_bounds_in_flight_calls(make_ctx):
    import asyncio

    from iaudit_backend.llm import LLMResult

    live = peak = 0

    class Client:
        async def complete_json(self, req, metrics=None):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            cid = req.fixture_key.split(".check.")[1]
            return LLMResult(parsed=VerifierOutput.model_validate({"items": [item(f"{cid}:e1")]}))

    ids = [f"c0.{n}" for n in range(1, 7)]
    cs = [claim("x.", cid=i, reported_by=UNSPEC) for i in ids]
    ls = [link(ev(cid=i), cid=i) for i in ids]
    await check_claims(cs, ls, PREP, PREP.turns, make_ctx(llm=Client(), check_concurrency=2))
    assert peak == 2


async def test_drafts_pass_the_assembler_without_repair(make_ctx):
    import json

    from eval.adhd import DATA

    req = AuditRequest.model_validate(json.loads((DATA / "requests" / "v1.json").read_text()))
    sentence = "Alex loses attention in every meeting, several times a day."
    c = claim(
        sentence,
        reported_by=UNSPEC,
        segments=[sentence.rstrip(".")],
        quantities=[{"kind": "frequency", "raw": "every meeting", "bucket": "always"}],
    )
    out = {
        "items": [
            item("c0.1:e1", frequency=[{"raw": "Most meetings", "basis": "relative"}], conf="high")
        ]
    }
    stub = StubClient()
    stub.register("check", lambda r: VerifierOutput.model_validate(out))
    (d,) = await check_claims([c], [link(ev())], PREP, PREP.turns, make_ctx(llm=stub))
    res = assemble(req, InternalAudit(claims=[d]), Settings())
    assert not res.report.repairs and not res.report.drops
    (claim_out,) = res.response["claims"]
    assert claim_out["verdict"] == "partially_supported"
    assert [x["type"] for x in claim_out["concerns"]] == ["frequency_severity_inflation"]


def test_floor_count_fields_are_loggable():
    from iaudit_backend.safe_log import ALLOWED_FIELDS

    assert {"items_below_floor", "inferences_below_floor", "flags_below_floor"} <= ALLOWED_FIELDS
