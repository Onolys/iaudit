import pytest
from pl_scripted import Scripted

from eaudit.api.errors import DeadlineExceeded
from eaudit.llm import LLMBadOutput, LLMTimeout, LLMUnavailable
from eaudit.models import AuditRequest
from eaudit.pipeline.full import FullPipeline
from eaudit.pipeline.guards import assess


class Failing(Scripted):
    """Raise `exc` for the given call tags (optionally only for prompts containing `only`)."""

    def __init__(self, exc, tags, only=None):
        super().__init__()
        self.exc, self.tags, self.only = exc, tags, only

    async def complete_json(self, req, metrics=None):
        if req.call_tag in self.tags and (self.only is None or self.only in req.user):
            raise self.exc
        return await super().complete_json(req, metrics)


def run(make_ctx, s, **kw):
    ctx = make_ctx(llm=s, request_id=s.request["request_id"], **kw)
    return FullPipeline().run(AuditRequest.model_validate(s.request), ctx)


async def test_one_link_timeout_stalls_only_that_claim(make_ctx):
    s = Failing(LLMTimeout("t"), {"link"}, only="Alex misplaces his phone daily")
    body = (await run(make_ctx, s)).to_json()
    assert body["status"] == "complete" and len(body["claims"]) == 11
    bad = [c for c in body["claims"] if c["verdict"] == "insufficient_evidence"]
    assert len(bad) == 1 and bad[0]["evidence"] == []
    (w,) = [w for w in body["warnings"] if w["code"] == "other"]
    assert w["claim_id"] == bad[0]["id"]


async def test_one_atomize_failure_marks_the_section_and_spares_the_rest(make_ctx):
    s = Scripted()
    s.request["assessment"] = [
        {"id": "sA", "text": s.request["assessment"][0]["text"]},
        {"id": "sB", "text": "Something unrelated about a gardening trip."},
    ]

    orig = s._atomize

    def atomize(req):
        if "gardening" in req.user:
            raise LLMBadOutput("x")
        return orig(req)

    s._atomize = atomize
    body = (await run(make_ctx, s)).to_json()
    assert body["status"] == "partial" and len(body["claims"]) == 11
    assert [w["code"] for w in body["warnings"]] == ["section_not_processed"]
    assert body["warnings"][0]["section_index"] == 1


@pytest.mark.parametrize(
    "exc,tags,expected",
    [
        (LLMUnavailable("down"), {"atomize", "link", "check"}, LLMUnavailable),
        (LLMUnavailable("down"), {"link"}, LLMUnavailable),
        (LLMTimeout("t"), {"atomize"}, DeadlineExceeded),
        (LLMTimeout("t"), {"link"}, DeadlineExceeded),
        (LLMBadOutput("b"), {"check"}, DeadlineExceeded),
        (ValueError("bug"), {"atomize"}, RuntimeError),
        (ValueError("bug"), {"check"}, RuntimeError),
    ],
)
async def test_nothing_usable_raises_the_matching_error(make_ctx, exc, tags, expected):
    with pytest.raises(expected) as info:
        await run(make_ctx, Failing(exc, tags))
    assert type(info.value) is expected


async def test_all_out_of_scope_assessment_is_a_valid_200(make_ctx):
    s = Scripted()
    for c in s.claims:
        c.update(scope="out_of_scope", oos_category="recommendation")
    body = (await run(make_ctx, s)).to_json()
    assert {c["verdict"] for c in body["claims"]} == {"out_of_scope"}
    assert s.calls == ["atomize"]


async def test_claim_cap_omits_extra_claims_and_warns(make_ctx):
    body = (await run(make_ctx, Scripted(), pipeline_max_claims=3)).to_json()
    assert len(body["claims"]) == 3 and body["status"] == "complete"
    assert [w["code"] for w in body["warnings"]] == ["input_truncated"]


def test_assess_table():
    ok = dict(sections_total=1, sections_ok=1, in_scope=2, in_scope_ok=1, reasons=set())
    assert assess(**ok) is None
    assert assess(**{**ok, "in_scope": 0, "in_scope_ok": 0}) is None
    assert assess(**{**ok, "sections_total": 0, "sections_ok": 0}) is None
    assert isinstance(assess(**{**ok, "in_scope_ok": 0}), DeadlineExceeded)
    assert isinstance(
        assess(**{**ok, "in_scope_ok": 0, "reasons": {"timeout", "error"}}), RuntimeError
    )
    assert isinstance(
        assess(**{**ok, "sections_ok": 0, "reasons": {"unavailable", "error"}}), LLMUnavailable
    )
