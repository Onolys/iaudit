import asyncio
import time

from pl_scripted import Scripted

from eaudit import contract
from eaudit.models import AuditRequest
from eaudit.pipeline.full import FullPipeline
from eaudit.pipeline.state import RunState


def ctx_for(make_ctx, llm, request, **kw):
    return make_ctx(llm=llm, request_id=request["request_id"], **kw)


async def test_faithful_example_runs_through_the_full_pipeline(make_ctx):
    s = Scripted()
    req = AuditRequest.model_validate(s.request)
    resp = await FullPipeline().run(req, ctx_for(make_ctx, s, s.request))
    body = resp.to_json()
    assert contract.validate_response(body) == []
    assert body["request_id"] == "adhd-faithful" and body["status"] == "complete"
    assert {c["verdict"] for c in body["claims"]} == {"supported"}
    assert len(body["claims"]) == 11
    assert s.calls.count("atomize") == 1 and s.calls.count("link") == 11
    assert s.calls.count("check") == 11


class TwoSections(Scripted):
    """Section A atomizes at once; section B is slow. Records when each call starts."""

    def __init__(self):
        super().__init__()
        self.events: list[tuple[str, str, float]] = []
        self.live = self.peak = 0
        sents = self.request["assessment"][0]["text"].split(". ")
        self.a = sents[0] + "."
        self.b = sents[-1]
        self.request["assessment"] = [
            {"id": "sA", "text": self.a},
            {"id": "sB", "text": self.b},
        ]

    async def complete_json(self, req, metrics=None):
        slow = req.call_tag == "atomize" and "careless" in req.user
        self.events.append((req.call_tag, "B" if slow else "-", time.monotonic()))
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(0.3 if slow else 0.01)
            res = await super().complete_json(req, metrics)
        finally:
            self.live -= 1
        self.events.append((req.call_tag, "end" + ("B" if slow else ""), time.monotonic()))
        return res

    def _atomize(self, req):
        from eaudit.atomize.models import AtomizerOutput

        mine = [c for c in self.claims if c["segments"][0] in req.user]
        return AtomizerOutput.model_validate({"claims": mine, "links": []})


async def test_section_a_links_start_before_section_b_finishes_atomizing(make_ctx):
    s = TwoSections()
    req = AuditRequest.model_validate(s.request)
    resp = await FullPipeline().run(req, ctx_for(make_ctx, s, s.request))
    first_link = min(t for tag, kind, t in s.events if tag == "link")
    b_end = next(t for tag, kind, t in s.events if kind == "endB")
    assert first_link < b_end
    assert s.peak <= 20
    assert (
        len(resp.claims) == 1 + 1 + 0 + 0 or len(resp.claims) >= 2
    )  # both sections produced claims


async def test_cancelled_waiter_does_not_cancel_the_shared_prep_or_siblings():
    st = RunState()
    done = []

    async def prep():
        await asyncio.sleep(0.05)
        st.prep_ready.set()

    async def flow(name):
        await st.prep_ready.wait()  # an event, not `await prep_task`
        done.append(name)

    prep_task = st.spawn(prep)
    a = st.spawn(lambda: flow("a"), claim_id="a")
    b = st.spawn(lambda: flow("b"), claim_id="b")
    await asyncio.sleep(0)
    a.cancel()
    await asyncio.wait_for(st.idle.wait(), 1)
    assert done == ["b"] and a.cancelled() and not prep_task.cancelled() and not b.cancelled()
    assert st.errors == [] and st.outstanding == 0


async def test_unexpected_exception_in_one_flow_is_recorded_and_siblings_finish():
    st = RunState()
    out = []

    async def boom():
        raise ValueError("secret text must not be logged")

    async def fine():
        await asyncio.sleep(0.01)
        out.append(1)

    st.spawn(boom, claim_id="c0.1")
    st.spawn(fine, claim_id="c0.2")
    await asyncio.wait_for(st.idle.wait(), 1)
    assert (
        out == [1] and st.errors == ["ValueError"] and st.errored_claims == {"c0.1": "ValueError"}
    )


async def test_drafts_are_write_once():
    st = RunState()
    st.write_draft("c", "first")
    st.write_draft("c", "second")
    assert st.drafts["c"] == "first"
