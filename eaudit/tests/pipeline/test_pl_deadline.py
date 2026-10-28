import asyncio
import time

import pytest
from pl_scripted import Scripted

from eaudit import contract
from eaudit.api.errors import DeadlineExceeded
from eaudit.atomize.models import AtomizerOutput
from eaudit.models import AuditRequest
from eaudit.pipeline.full import FullPipeline


class SlowCheck(Scripted):
    """Checks for claims mentioning 'phone' or 'meetings' never finish within the test."""

    def __init__(self, hang=("phone", "keys")):
        super().__init__()
        self.hang = hang

    async def complete_json(self, req, metrics=None):
        if req.call_tag == "check" and any(w in req.user.lower() for w in self.hang):
            await asyncio.sleep(30)
        return await super().complete_json(req, metrics)


async def test_deadline_returns_partial_audit_in_time_and_leaks_nothing(make_ctx):
    s = SlowCheck()
    req = AuditRequest.model_validate(s.request)
    base = {t for t in asyncio.all_tasks()}
    ctx = make_ctx(
        llm=s, request_id=s.request["request_id"], deadline_in=1.2, assemble_reserve_s=0.4,
        min_call_s=0.05, cancel_grace_s=0.3,
    )  # fmt: skip
    t0 = time.monotonic()
    resp = await FullPipeline().run(req, ctx)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.2 + 0.5
    body = resp.to_json()
    assert contract.validate_response(body) == []
    verdicts = [c["verdict"] for c in body["claims"]]
    assert verdicts.count("supported") >= 8 and verdicts.count("insufficient_evidence") >= 2
    others = [w for w in body["warnings"] if w["code"] == "other"]
    assert len(others) >= 2 and all(w.get("claim_id") for w in others)
    assert body["status"] == "complete"  # claim stalls alone never make the audit partial
    st = ctx.extras["run_state"]
    assert st.deadline_hit and st.cancelled >= 2
    await asyncio.sleep(0)
    assert {t for t in asyncio.all_tasks()} == base
    assert st.link_ctx.sem._value == ctx.settings.link_concurrency  # semaphore restored
    assert set(ctx.extras["check_stalls"].values()) == {"deadline"}


async def test_unfinished_section_becomes_section_not_processed(make_ctx):
    class SlowSecond(Scripted):
        async def complete_json(self, req, metrics=None):
            if req.call_tag == "atomize" and "careless" in req.user:
                await asyncio.sleep(30)
            return await super().complete_json(req, metrics)

        def _atomize(self, req):
            mine = [c for c in self.claims if c["segments"][0] in req.user]
            return AtomizerOutput.model_validate({"claims": mine, "links": []})

    s = SlowSecond()
    text = s.request["assessment"][0]["text"].split(". ")
    s.request["assessment"] = [
        {"id": "sA", "text": text[0] + "."},
        {"id": "sB", "text": text[-1]},
    ]
    ctx = make_ctx(
        llm=s, request_id="r", deadline_in=1.5, assemble_reserve_s=0.3, min_call_s=0.05,
        cancel_grace_s=0.2,
    )  # fmt: skip
    body = (await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)).to_json()
    assert body["status"] == "partial" and len(body["claims"]) == 1
    assert [(w["code"], w["section_index"]) for w in body["warnings"]] == [
        ("section_not_processed", 1)
    ]


async def test_stages_see_the_llm_deadline_not_the_request_deadline(make_ctx):
    seen = []

    class Spy(Scripted):
        async def complete_json(self, req, metrics=None):
            seen.append(req.deadline)
            return await super().complete_json(req, metrics)

    s = Spy()
    ctx = make_ctx(llm=s, request_id="r", deadline_in=30, assemble_reserve_s=3)
    await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    assert seen and all(d == ctx.deadline - 3 for d in seen)


async def test_no_call_starts_when_less_than_min_call_s_remains(make_ctx):
    s = Scripted()
    ctx = make_ctx(llm=s, request_id="r", deadline_in=3.5, assemble_reserve_s=0.5)  # 3 s < 4 s
    with pytest.raises(DeadlineExceeded):  # nothing usable finished: 504, not an empty audit
        await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    assert s.calls == []
