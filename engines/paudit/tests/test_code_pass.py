import asyncio

import pytest
from conftest import write_pack
from onolys_core.llm import LLMBadOutput, LLMRequest, LLMResult, MetricsCollector
from onolys_core.llm.litellm_client import LiteLLMClient
from onolys_core.llm.routes import Route
from onolys_core.transcript import Turn
from pydantic import ValidationError

from paudit.code_pass import (
    CodePassFailed,
    build_requests_parts,
    code_pass,
    make_response_model,
)
from paudit.pack import load_pack
from paudit.prepare import Prepared, RoleTurn, Volley

pytestmark = pytest.mark.unit

TEXTS = {
    "t0": "First thing here. Second thing here.",
    "t1": "Alpha beta gamma. Delta epsilon zeta.",
    "t2": "Third thing here. Fourth thing here.",
}


def make_pack(tmp_path, pack_data, params=None):
    if params is not None:
        pack_data["params"] = params
    return load_pack(write_pack(tmp_path / "p", pack=pack_data))


def volleys(n):
    out = []
    for i in range(n):
        t = Turn(id=f"t{i}", speaker="A", text=TEXTS["t0"], start_ms=i * 1000, end_ms=i * 1000 + 500)
        prev = Turn(id=f"p{i}", speaker="B", text="client said something")
        out.append(Volley(f"v{i + 1}", [t], prev))
    return out


def prepared(vs):
    turns = [RoleTurn(t, "subject") for v in vs for t in v.turns]
    return Prepared(turns=turns, volleys=vs)


def utt(quote, code="a", rationale="r"):
    return {"quote": quote, "code": code, "rationale": rationale}


def good(req, per_volley=None):
    """A valid response for every volley in the request: one utterance each."""
    ids = [v["volley_id"] for v in _req_volleys(req)]
    per = per_volley or (lambda vid: [utt("First thing here.")])
    return req.response_model.model_validate(
        {"volleys": [{"volley_id": vid, "utterances": per(vid)} for vid in ids]}
    )


def _req_volleys(req):
    import json

    return json.loads(req.user)["volleys"]


class FakeClient:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[LLMRequest] = []

    async def complete_json(self, req, metrics=None):
        self.requests.append(req)
        parsed = self.handler(req, len(self.requests))
        if asyncio.iscoroutine(parsed):
            parsed = await parsed
        return LLMResult(parsed=parsed, model="fake")


async def run(client, pack, vs, **kw):
    return await code_pass(client, pack, prepared(vs), {"change_goal": "synthetic goal"}, **kw)


async def test_request_route_and_no_sampling_param(tmp_path, pack_data):
    client = FakeClient(lambda req, n: good(req))
    await run(client, make_pack(tmp_path, pack_data, {}), volleys(26))  # engine defaults
    assert [len(_req_volleys(r)) for r in client.requests] == [25, 1]
    req = client.requests[0]
    assert req.tier == "paudit_code"
    assert req.temperature == LLMRequest.__dataclass_fields__["temperature"].default  # untouched
    assert req.max_tokens == 8000
    assert len(req.cache_prefixes) == 2
    assert req.call_tag.startswith("paudit_code")


async def test_response_model_code_enum(tmp_path, pack_data):
    model = make_response_model(["a", "b", "c"])
    ok = {"volleys": [{"volley_id": "v1", "utterances": [utt("x", "a"), utt("y", None)]}]}
    assert model.model_validate(ok)
    bad = {"volleys": [{"volley_id": "v1", "utterances": [utt("x", "zzz")]}]}
    with pytest.raises(ValidationError):
        model.model_validate(bad)


async def test_prompt_has_system_definitions_fewshot(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data)
    parts = build_requests_parts(pack, {"change_goal": "synthetic goal"}, language="en")
    first, second = parts.cache_prefixes
    assert "code system" in first  # code_system.md
    assert "- a (A): d" in first  # items rendered from pack.yaml
    assert "synthetic goal" in second and "en" in second
    assert "synthetic goal" not in first  # first prefix identical across runs


async def test_batch_size_honoured(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data, {"volleys_per_call": 2, "code_max_tokens": 4000})
    client = FakeClient(lambda req, n: good(req))
    out = await run(client, pack, volleys(5))
    assert [len(_req_volleys(r)) for r in client.requests] == [2, 2, 1]
    assert [i.volley_id for i in out.instances] == ["v1", "v2", "v3", "v4", "v5"]
    assert [i.id for i in out.instances] == ["i1", "i2", "i3", "i4", "i5"]
    assert client.requests[0].max_tokens == 4000  # pack param overrides engine default


async def test_second_batch_not_started_before_first_returns(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data, {"volleys_per_call": 1})
    gate = asyncio.Event()

    async def handler(req, n):
        if n == 1:
            await gate.wait()
        return good(req)

    client = FakeClient(handler)
    task = asyncio.create_task(run(client, pack, volleys(3)))
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(client.requests) == 1  # warm call alone
    gate.set()
    out = await task
    assert len(client.requests) == 3
    assert len(out.instances) == 3


async def test_bad_output_halves_then_retries_each_half(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data, {"volleys_per_call": 4})

    def handler(req, n):
        if n == 1:
            raise LLMBadOutput("truncated")
        return good(req)

    client = FakeClient(handler)
    out = await run(client, pack, volleys(4))
    assert [len(_req_volleys(r)) for r in client.requests] == [4, 2, 2]
    assert len(out.instances) == 4


async def test_bad_output_in_half_fails_run(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data, {"volleys_per_call": 4})

    def handler(req, n):
        if n <= 2:
            raise LLMBadOutput("truncated")
        return good(req)

    client = FakeClient(handler)
    with pytest.raises(CodePassFailed):
        await run(client, pack, volleys(4))
    assert len(client.requests) == 2  # full, first half; no third try


async def test_single_volley_bad_output_retried_once_then_fails(tmp_path, pack_data):
    client = FakeClient(lambda req, n: (_ for _ in ()).throw(LLMBadOutput("x")))
    with pytest.raises(CodePassFailed):
        await run(client, make_pack(tmp_path, pack_data), volleys(1))
    assert len(client.requests) == 2


async def test_drop_at_20_percent_is_kept_with_warning(tmp_path, pack_data):
    text = "One aaa. Two bbb. Three ccc. Four ddd. Five eee."
    v = Volley("v1", [Turn(id="t1", speaker="A", text=text)], None)
    quotes = ["One aaa.", "Two bbb.", "Three ccc.", "Four ddd.", "not in the transcript"]
    client = FakeClient(lambda req, n: good(req, lambda vid: [utt(q) for q in quotes]))
    out = await run(client, make_pack(tmp_path, pack_data), [v])
    assert len(client.requests) == 1  # exactly 20% is not over the limit
    assert [w.code for w in out.warnings] == ["quote_not_found"]
    assert len(out.instances) == 4


async def test_drop_over_20_percent_retries_once_then_ok(tmp_path, pack_data):
    def handler(req, n):
        if n == 1:
            return good(req, lambda vid: [utt("nope one"), utt("First thing here.")])
        return good(req)

    client = FakeClient(handler)
    out = await run(client, make_pack(tmp_path, pack_data), volleys(1))
    assert len(client.requests) == 2
    assert out.warnings == []  # warnings come from the accepted attempt only
    assert len(out.instances) == 1


async def test_drop_over_20_percent_twice_fails(tmp_path, pack_data):
    client = FakeClient(lambda req, n: good(req, lambda vid: [utt("nope"), utt("First thing here.")]))
    with pytest.raises(CodePassFailed):
        await run(client, make_pack(tmp_path, pack_data), volleys(1))
    assert len(client.requests) == 2


async def test_locate_offsets_and_overlap(tmp_path, pack_data):
    v = Volley("v1", [Turn(id="t9", speaker="A", text="Alpha beta gamma. Delta epsilon zeta.",
                           start_ms=10, end_ms=20)], None)
    client = FakeClient(lambda req, n: good(req, lambda vid: [
        utt("Alpha beta gamma.", "a"),
        utt("alpha  BETA gamma.", "b"),  # same span again -> overlap
        utt("Delta epsilon zeta.", None),
        utt("Alpha beta gamma. Delta", "c"),  # earlier + overlapping -> overlap
    ]))
    # 2 of 4 dropped = 50% -> retry then fail; use a looser batch to inspect the result instead
    with pytest.raises(CodePassFailed):
        await run(client, make_pack(tmp_path, pack_data), [v])

    client = FakeClient(lambda req, n: good(req, lambda vid: [
        utt("Alpha beta gamma.", "a"),
        utt("delta  EPSILON zeta.", None),
    ]))
    out = await run(client, make_pack(tmp_path, pack_data), [v])
    first, second = out.instances
    assert (first.turn_id, first.start, first.end) == ("t9", 0, 17)
    assert first.quote == "Alpha beta gamma." and first.counted and first.code == "a"
    assert (first.start_ms, first.end_ms) == (10, 20)
    assert (second.start, second.end) == (18, 37)
    assert second.quote == "Delta epsilon zeta."  # text as in the turn, not as the model wrote it
    assert second.code is None and second.counted is False and second.uncounted_reason == "uncoded"


async def test_quote_never_crosses_turn_boundary(tmp_path, pack_data):
    v = Volley("v1", [Turn(id="t1", speaker="A", text="Alpha beta gamma."),
                      Turn(id="t2", speaker="A", text="Delta epsilon zeta.")], None)
    client = FakeClient(lambda req, n: good(req, lambda vid: [
        utt("Alpha beta gamma. Delta epsilon zeta.")]))
    with pytest.raises(CodePassFailed):  # 100% dropped, twice
        await run(client, make_pack(tmp_path, pack_data), [v])


async def test_second_turn_located_in_its_own_turn(tmp_path, pack_data):
    v = Volley("v1", [Turn(id="t1", speaker="A", text="Alpha beta gamma."),
                      Turn(id="t2", speaker="A", text="Delta epsilon zeta.")], None)
    client = FakeClient(lambda req, n: good(req, lambda vid: [
        utt("Alpha beta gamma."), utt("Delta epsilon zeta.", "b")]))
    out = await run(client, make_pack(tmp_path, pack_data), [v])
    assert [(i.turn_id, i.start, i.end) for i in out.instances] == [("t1", 0, 17), ("t2", 0, 19)]


async def test_token_params_clamped_to_route(tmp_path, pack_data):
    client = FakeClient(lambda req, n: good(req))
    await run(client, make_pack(tmp_path, pack_data), volleys(1))
    route = Route(litellm_id="x/y", max_output_tokens=3000)
    assert LiteLLMClient._limits(route, client.requests[0])[0] == 3000


async def test_metrics_passed_through(tmp_path, pack_data):
    seen = []

    class C(FakeClient):
        async def complete_json(self, req, metrics=None):
            seen.append(metrics)
            return await super().complete_json(req, metrics)

    m = MetricsCollector()
    await run(C(lambda req, n: good(req)), make_pack(tmp_path, pack_data), volleys(1), metrics=m)
    assert seen == [m]
