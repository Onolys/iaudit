import asyncio
import json

import pytest
from conftest import write_pack
from onolys_core.llm import LLMBadOutput, LLMResult
from onolys_core.transcript import Turn
from pydantic import ValidationError

from paudit.globals_pass import GlobalsPassFailed, globals_pass, make_response_model
from paudit.pack import load_pack
from paudit.prepare import Prepared, RoleTurn

pytestmark = pytest.mark.unit

T1 = "You want to walk more. What would help?"
T2 = "I would have more energy."
T3 = "You decide what fits your week."


def prepared():
    turns = [
        RoleTurn(Turn(id="t1", speaker="A", text=T1, start_ms=0, end_ms=1000), "subject"),
        RoleTurn(Turn(id="t2", speaker="B", text=T2, start_ms=1000, end_ms=2000), "other"),
        RoleTurn(Turn(id="t3", speaker="A", text=T3, start_ms=2000, end_ms=3000), "subject"),
    ]
    return Prepared(turns=turns, volleys=[])


def ev(turn_id, quote):
    return {"turn_id": turn_id, "quote": quote}


def g(score, evidence, poor=None, reason="r"):
    return {"score": score, "reason": reason, "evidence": evidence, "poor_practice_cited": poor or []}


class FakeClient:
    def __init__(self, handler):
        self.handler, self.requests = handler, []

    async def complete_json(self, req, metrics=None):
        self.requests.append(req)
        parsed = self.handler(req, len(self.requests))
        if asyncio.iscoroutine(parsed):
            parsed = await parsed
        return LLMResult(parsed=parsed, model="fake")


def reply(req, globals_):
    return req.response_model.model_validate({"globals": globals_})


def make_pack(tmp_path, pack_data):
    return load_pack(write_pack(tmp_path / "p", pack=pack_data))


def run(client, pack, params=None):
    return asyncio.run(globals_pass(client, pack, prepared(), params or {"change_goal": "walk more"}))


GOOD = [ev("t1", "What would help?"), ev("t3", "You decide what fits")]


def test_no_evidence_resets_to_default(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: reply(req, {"g1": g(5, []), "g2": g(4, [])}))
    res = run(c, pack)
    g1 = res.globals["g1"]
    assert (g1.score, g1.source, g1.raw_score) == (3, "default", 5)
    assert g1.evidence == []
    assert any(w.code == "insufficient_evidence" and w.item_id == "g1" for w in res.warnings)
    # g2 evidence_min is 1: zero evidence resets too
    assert res.globals["g2"].score == 3 and res.globals["g2"].source == "default"


def test_evidence_located_and_kept(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: reply(req, {"g1": g(4, GOOD), "g2": g(2, [ev("t2", "more energy")])}))
    res = run(c, pack)
    g1 = res.globals["g1"]
    assert (g1.score, g1.source, g1.raw_score) == (4, "model", 4)
    e = g1.evidence[0]
    assert (e.turn_id, e.quote) == ("t1", "What would help?")
    assert T1[e.start : e.end] == e.quote
    assert res.globals["g2"].score == 2
    assert res.warnings == []


def test_unlocatable_quote_dropped_then_insufficient(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    bad = [ev("t1", "What would help?"), ev("t3", "totally invented sentence xyz qqq")]
    c = FakeClient(lambda req, n: reply(req, {"g1": g(4, bad), "g2": g(4, [ev("t1", "What would help?")])}))
    res = run(c, pack)
    codes = [(w.code, w.item_id) for w in res.warnings]
    assert ("quote_not_found", "g1") in codes and ("insufficient_evidence", "g1") in codes
    assert res.globals["g1"].source == "default"
    assert res.globals["g2"].score == 4


def test_cap_only_for_item_with_caps(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)  # g1 has caps (max 3), g2 has none
    poor = [ev("t1", "What would help?")]
    c = FakeClient(lambda req, n: reply(req, {"g1": g(5, GOOD, poor), "g2": g(5, GOOD, poor)}))
    res = run(c, pack)
    g1, g2 = res.globals["g1"], res.globals["g2"]
    assert (g1.score, g1.source, g1.raw_score) == (3, "capped", 5)
    assert any(w.code == "capped" and w.item_id == "g1" for w in res.warnings)
    assert (g2.score, g2.source, g2.raw_score) == (5, "model", 5)
    assert not any(w.code == "capped" and w.item_id == "g2" for w in res.warnings)


def test_no_cap_without_poor_practice_or_below_max(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: reply(req, {"g1": g(5, GOOD), "g2": g(5, GOOD)}))
    assert run(c, pack).globals["g1"].source == "model"
    c = FakeClient(lambda req, n: reply(req, {"g1": g(2, GOOD, [ev("t1", "x")]), "g2": g(2, GOOD)}))
    r = run(c, pack).globals["g1"]
    assert (r.score, r.source) == (2, "model")


@pytest.mark.parametrize("bad", [0, 6, -1])
def test_out_of_scale_errors(tmp_path, pack_data, bad):
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: reply(req, {"g1": g(bad, GOOD), "g2": g(3, GOOD)}))
    with pytest.raises(GlobalsPassFailed) as ei:
        run(c, pack)
    assert ei.value.code == "run_failed" and "g1" in str(ei.value)


def test_truncation_retried_once_then_ok(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)

    def handler(req, n):
        if n == 1:
            raise LLMBadOutput("truncated")
        return reply(req, {"g1": g(4, GOOD), "g2": g(4, GOOD)})

    c = FakeClient(handler)
    res = run(c, pack)
    assert len(c.requests) == 2 and res.globals["g1"].score == 4


def test_truncation_twice_fails_run(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: (_ for _ in ()).throw(LLMBadOutput("truncated")))
    with pytest.raises(GlobalsPassFailed) as ei:
        run(c, pack)
    assert ei.value.code == "run_failed" and len(c.requests) == 2


def test_request_shape_route_and_no_counts(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: reply(req, {"g1": g(4, GOOD), "g2": g(4, GOOD)}))
    run(c, pack)
    req = c.requests[0]
    assert req.tier == "paudit_globals"
    assert req.max_tokens == 2000  # pack params.globals_max_tokens
    user = json.loads(req.user)
    assert user["change_goal"] == "walk more"
    assert [t["turn_id"] for t in user["turns"]] == ["t1", "t2", "t3"]
    assert "count" not in req.user.lower() and "tally" not in req.user.lower()
    prefix = "\n".join(req.cache_prefixes)
    assert "globals system" in prefix and "Global one" in prefix and "g2" in prefix
    assert "poor_practice_cited" in prefix


def test_default_max_tokens_when_pack_has_no_param(tmp_path, pack_data):
    pack_data["params"] = {}
    pack = make_pack(tmp_path, pack_data)
    c = FakeClient(lambda req, n: reply(req, {"g1": g(4, GOOD), "g2": g(4, GOOD)}))
    run(c, pack)
    assert c.requests[0].max_tokens == 4000


def test_response_model_requires_every_global():
    m = make_response_model(["g1", "g2"])
    with pytest.raises(ValidationError):
        m.model_validate({"globals": {"g1": g(3, [])}})
