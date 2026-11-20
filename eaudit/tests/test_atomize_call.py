import asyncio

import pytest
from atomize_helpers import FIXTURES, ROSTER, adhd_section, raw

from eaudit.atomize import atomize_section, atomize_sections
from eaudit.atomize.models import AtomizerOutput
from eaudit.atomize.prompt import Speaker, build_cache_prefix
from eaudit.llm import (
    FailingClient,
    FixtureClient,
    LLMBadOutput,
    LLMTimeout,
    LLMUnavailable,
    StubClient,
)
from eaudit.models import Section, Turn


def stub_with(output: dict | None = None, capture: list | None = None):
    c = StubClient()

    def fn(req):
        if capture is not None:
            capture.append(req)
        return AtomizerOutput.model_validate(output or {"claims": [raw()], "links": []})

    c.register("atomize", fn)
    return c


async def test_fixture_replay_of_adhd_section_returns_parsed_claims(make_ctx):
    ctx = make_ctx(llm=FixtureClient(FIXTURES), request_id="adhd-faithful")
    roster = [*ROSTER, Speaker("sam1", "informant")]
    res = await atomize_section(adhd_section(), roster, ctx, index=0)
    assert res.status == "ok" and res.section_index == 0 and res.failure is None
    assert [c.id for c in res.claims] == [f"c0.{n}" for n in range(1, 12)]
    assert all(c.section_index == 0 for c in res.claims)
    informant = [c for c in res.claims if c.reported_by[0].source == "informant"]
    assert len(informant) == 1 and informant[0].reported_by[0].speaker == "sam1"
    assert any(c.hedged and c.reported_by[0].source == "self" for c in res.claims)


async def test_request_shape(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub_with(capture=seen))
    await atomize_section(Section(id="s", text="Alex forgets things."), ROSTER, ctx, index=2)
    (req,) = seen
    assert (req.tier, req.call_tag, req.temperature) == ("mid", "atomize", 0.0)
    assert req.response_model is AtomizerOutput
    assert req.cache_prefix == build_cache_prefix(30)
    assert req.max_tokens == 16000
    assert req.deadline == ctx.deadline
    assert 0 < req.timeout_s <= ctx.settings.atomize_call_timeout_s
    assert "Alex forgets things." in req.user and "alex1" in req.user
    assert req.fixture_key == "r1.atomize.s2"


async def test_label_score_and_transcript_text_are_never_sent(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub_with(capture=seen))
    section = Section(id="s", label="LABELCANARY", score="SCORECANARY", text="Alex forgets.")
    turns = [Turn(id="1", speaker="alex1", text="TRANSCRIPTCANARY words")]
    await atomize_sections([section], turns, ctx)
    blob = seen[0].user + seen[0].system + (seen[0].cache_prefix or "")
    assert not any(w in blob for w in ("LABELCANARY", "SCORECANARY", "TRANSCRIPTCANARY"))


async def test_fixture_key_is_filesystem_safe(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub_with(capture=seen), request_id="we ird/../id")
    await atomize_section(Section(id="s", text="Alex forgets."), ROSTER, ctx, index=0)
    assert seen[0].fixture_key.replace(".", "").replace("_", "").replace("-", "").isalnum()
    assert "/" not in seen[0].fixture_key and ".." not in seen[0].fixture_key


async def test_no_request_id_means_hash_keyed_fixture(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub_with(capture=seen), request_id=None)
    await atomize_section(Section(id="s", text="Alex forgets."), ROSTER, ctx, index=0)
    assert seen[0].fixture_key is None


async def test_numeric_text_beats_llm_bucket_and_relative_words_use_lexicon(make_ctx):
    q = [
        {"kind": "frequency", "raw": "three or four times a week", "bucket": "always"},
        {"kind": "frequency", "raw": "most meetings", "bucket": "often"},
    ]
    ctx = make_ctx(llm=stub_with({"claims": [raw(quantities=q)], "links": []}))
    res = await atomize_section(Section(id="s", text="Alex forgets."), ROSTER, ctx, index=0)
    a, b = res.claims[0].quantities
    assert (a.bucket, a.rate_per_week) == ("often", 3.5)
    assert (b.bucket, b.rate_per_week) == ("most", None)


@pytest.mark.parametrize(
    "exc,reason",
    [
        (LLMTimeout("t"), "timeout"),
        (LLMUnavailable("u"), "unavailable"),
        (LLMBadOutput("b"), "bad_output"),
    ],
)
async def test_llm_errors_become_section_failures(make_ctx, exc, reason):
    ctx = make_ctx(llm=FailingClient(exc))
    res = await atomize_section(Section(id="s", text="Alex forgets."), ROSTER, ctx, index=3)
    assert (res.status, res.failure, res.section_index, res.claims) == ("failed", reason, 3, [])


async def test_fixture_miss_is_a_failure_not_a_crash(make_ctx, tmp_path):
    ctx = make_ctx(llm=FixtureClient(tmp_path))
    res = await atomize_section(Section(id="s", text="Alex forgets."), ROSTER, ctx, index=0)
    assert res.status == "failed" and res.failure == "unavailable"


async def test_no_call_when_budget_is_exhausted(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub_with(capture=seen), deadline_in=0.5)
    res = await atomize_section(Section(id="s", text="Alex forgets."), ROSTER, ctx, index=0)
    assert seen == [] and (res.status, res.failure) == ("failed", "timeout")


async def test_atomize_sections_is_concurrent_ordered_and_isolated(make_ctx):
    started = 0
    both = asyncio.Event()

    class Client:
        async def complete_json(self, req, metrics=None):
            nonlocal started
            if "boom" in req.user:
                raise LLMUnavailable("down")
            started += 1
            if started == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)  # only passes if calls overlap
            from eaudit.llm import LLMResult

            return LLMResult(parsed=AtomizerOutput.model_validate({"claims": [raw()]}))

    sections = [
        Section(id="a", text="Alex forgets one."),
        Section(id="b", text="boom"),
        Section(id="c", text="Alex forgets two."),
    ]
    turns = [Turn(id="1", speaker="alex1", text="x"), Turn(id="2", speaker="clinician1", text="y")]
    out = await atomize_sections(sections, turns, make_ctx(llm=Client()))
    assert [(s.section_index, s.status) for s in out] == [(0, "ok"), (1, "failed"), (2, "ok")]
    assert out[1].failure == "unavailable"
    assert out[0].claims[0].id == "c0.1" and out[2].claims[0].id == "c2.1"


async def test_link_refs_are_remapped_to_claim_ids(make_ctx):
    out = {
        "claims": [
            raw(ref="x", segments=["Alex is slow"]),
            raw(ref="y", segments=["Alex forgets"]),
            raw(ref="z", segments=["Alex naps"]),
        ],
        "links": [
            {
                "type": "causal",
                "cause_ids": ["y", "z"],
                "effect_id": "x",
                "connector": "because",
                "source": "assessor",
            }
        ],
    }
    ctx = make_ctx(llm=stub_with(out))
    res = await atomize_section(
        Section(id="s", text="Alex is slow. Alex forgets. Alex naps."), ROSTER, ctx, index=1
    )
    assert (res.links[0].cause_ids, res.links[0].effect_id) == (["c1.2", "c1.3"], "c1.1")
