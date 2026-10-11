from atomize_helpers import FIXTURES, ROSTER, adhd_section, raw

from iaudit_backend.atomize import atomize_section
from iaudit_backend.atomize.models import AtomizerOutput
from iaudit_backend.atomize.prompt import Speaker
from iaudit_backend.llm import FailingClient, FixtureClient, LLMResult, LLMUnavailable
from iaudit_backend.models import Section

TEXT = "Jordan misplaces receipts. Jordan double-books clients and skips lunch every day."


class Script:
    """Client returning scripted outputs in order; records requests."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.requests = []

    async def complete_json(self, req, metrics=None):
        self.requests.append(req)
        item = self.outputs[min(len(self.requests), len(self.outputs)) - 1]
        if isinstance(item, Exception):
            raise item
        return LLMResult(parsed=AtomizerOutput.model_validate(item))


def out(*claims, links=()):
    return {"claims": list(claims), "links": list(links)}


def rc(ref, *segs, **kw):
    return raw(ref=ref, segments=list(segs), **kw)


GOOD = out(
    rc("a", "Jordan misplaces receipts"),
    rc("b", "Jordan double-books clients"),
    rc("c", "skips lunch every day"),
)


async def run(client, text=TEXT, make_ctx=None, roster=None, **kw):
    ctx = make_ctx(llm=client, **kw)
    return await atomize_section(Section(id="s", text=text), roster or ROSTER, ctx, index=0), ctx


async def test_valid_output_resolves_spans_and_renumbers_in_document_order(make_ctx):
    shuffled = out(rc("z", "skips lunch every day"), rc("y", "Jordan misplaces receipts"))
    res, _ = await run(Script(shuffled), make_ctx=make_ctx)
    assert res.status == "ok"
    assert [c.id for c in res.claims] == ["c0.1", "c0.2"]
    assert [TEXT[slice(*c.span_hint)] for c in res.claims] == [
        "Jordan misplaces receipts",
        "skips lunch every day",
    ]
    assert all(c.span_quality == "covering" for c in res.claims)


async def test_segments_are_rewritten_to_exact_substrings(make_ctx):
    out_ = out(rc("a", "jordan  misplaces receipts"), rc("b", "Jordan double-books clients"))
    res, _ = await run(Script(out_), make_ctx=make_ctx)
    assert res.claims[0].segments == ["Jordan misplaces receipts"]  # normalized hit, exact text
    assert all(seg in TEXT for c in res.claims for seg in c.segments)


async def test_no_overlap_and_hint_inside_section(make_ctx):
    res, _ = await run(Script(GOOD), make_ctx=make_ctx)
    spans = sorted(c.span_hint for c in res.claims)
    assert all(0 <= s < e <= len(TEXT) for s, e in spans)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


async def test_non_contiguous_claim_gets_anchor_only_hint(make_ctx):
    text = "Jordan, who works nights, struggles to sleep during the day."
    o = out(
        rc("a", "Jordan", "struggles to sleep during the day"),
        rc("b", "who works nights"),
    )
    res, _ = await run(Script(o), text=text, make_ctx=make_ctx)
    a = next(c for c in res.claims if len(c.segments) == 2)
    assert a.span_quality == "anchor_only"
    assert text[slice(*a.span_hint)] == "struggles to sleep during the day"  # longest segment
    b = next(c for c in res.claims if c is not a)
    assert b.span_quality == "covering"


async def test_non_contiguous_claim_with_nothing_between_gets_covering_hint(make_ctx):
    text = "Jordan misplaces receipts and always loses pens."
    o = out(rc("a", "Jordan misplaces receipts", "always loses pens"))
    res, _ = await run(Script(o), text=text, make_ctx=make_ctx)
    c = res.claims[0]
    assert c.span_quality == "covering" and text[slice(*c.span_hint)] == text[:-1]


async def test_repeated_phrase_goes_to_the_earliest_unassigned_hit(make_ctx):
    text = "Jordan sleeps badly. Jordan sleeps badly."
    o = out(rc("a", "Jordan sleeps badly"), rc("b", "Jordan sleeps badly"))
    res, _ = await run(Script(o), text=text, make_ctx=make_ctx)
    assert sorted(c.span_hint for c in res.claims) == [(0, 19), (21, 40)]


async def test_invalid_speakers_become_none_without_retry(make_ctx):
    o = out(
        rc(
            "a",
            "Jordan misplaces receipts",
            subject_speaker="ghost",
            reported_by=[{"source": "informant", "speaker": "partner"}],
        ),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
    )
    client = Script(o)
    res, _ = await run(client, make_ctx=make_ctx)
    a = res.claims[0]
    assert a.subject_speaker is None and a.reported_by[0].speaker is None
    assert a.reported_by[0].source == "informant" and len(client.requests) == 1


async def test_valid_roster_speakers_are_kept(make_ctx):
    res, _ = await run(
        Script(
            out(
                rc("a", "Jordan misplaces receipts"),
                rc("b", "Jordan double-books clients"),
                rc("c", "skips lunch every day"),
            )
        ),
        make_ctx=make_ctx,
        roster=[Speaker("alex1", None)],
    )
    assert res.claims[0].subject_speaker == "alex1"


async def test_invalid_then_valid_succeeds_via_exactly_one_retry(make_ctx):
    bad = out(rc("a", "Jordan invents a thing"), rc("b", "Jordan double-books clients"))
    client = Script(bad, GOOD)
    res, ctx = await run(client, make_ctx=make_ctx)
    assert res.status == "ok" and len(client.requests) == 2 and res.retries == 1
    assert len(res.claims) == 3 and res.dropped == 0
    retry = client.requests[1]
    assert retry.call_tag == "atomize" and retry.fixture_key == "r1.atomize.s0.retry"
    assert "a: unresolved_segment" in retry.user  # ids and kinds only
    assert "invents" in retry.user  # previous output is resent
    errors_block = retry.user.split("Problems")[-1]
    assert "invents" not in errors_block and TEXT[:10] not in errors_block


async def test_retry_error_list_never_echoes_text(make_ctx):
    bad = out(rc("a", "Jordan invents a thing"))
    client = Script(bad, bad)
    await run(client, make_ctx=make_ctx)
    block = client.requests[1].user.split("Problems:")[1]
    assert block.strip().splitlines()[0].startswith("- a: unresolved_segment")
    assert "Jordan" not in block


async def test_unresolvable_claims_dropped_after_retry_and_counted(make_ctx):
    bad = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
        rc("d", "totally made up words here"),
    )
    client = Script(bad, bad)
    res, _ = await run(client, make_ctx=make_ctx)
    assert res.status == "ok" and res.dropped == 1 and len(res.claims) == 3
    assert len(client.requests) == 2


async def test_overlap_drops_the_later_claim(make_ctx):
    o = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "misplaces receipts"),  # only occurs inside a's region
        rc("c", "Jordan double-books clients"),
        rc("d", "skips lunch every day"),
    )
    res, _ = await run(Script(o, o), make_ctx=make_ctx)
    assert res.dropped == 1 and len(res.claims) == 3
    assert res.claims[0].segments == ["Jordan misplaces receipts"]


async def test_bad_link_triggers_retry_and_is_removed(make_ctx):
    link = {
        "type": "causal",
        "cause_ids": ["a"],
        "effect_id": "nope",
        "connector": "because",
        "source": "assessor",
    }
    o = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
        links=[link],
    )
    client = Script(o, o)
    res, _ = await run(client, make_ctx=make_ctx)
    assert len(client.requests) == 2 and res.links == [] and res.status == "ok"
    assert "bad_link" in client.requests[1].user


async def test_good_links_are_remapped_to_final_ids(make_ctx):
    link = {
        "type": "causal",
        "cause_ids": ["c", "b"],
        "effect_id": "a",
        "connector": "because",
        "source": "reported",
    }
    o = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
        links=[link],
    )
    res, _ = await run(Script(o), make_ctx=make_ctx)
    assert res.links[0].cause_ids == ["c0.3", "c0.2"] and res.links[0].effect_id == "c0.1"
    assert res.links[0].source == "reported"


async def test_duplicate_refs_are_an_error(make_ctx):
    o = out(
        rc("a", "Jordan misplaces receipts"),
        rc("a", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
    )
    client = Script(o, o)
    res, _ = await run(client, make_ctx=make_ctx)
    assert len(client.requests) == 2 and res.dropped == 1 and len(res.claims) == 2


async def test_coverage_gap_is_retried_then_counted_not_fabricated(make_ctx):
    o = out(rc("a", "Jordan misplaces receipts"))
    client = Script(o, o)
    res, _ = await run(client, make_ctx=make_ctx)
    assert len(client.requests) == 2 and res.status == "ok"
    assert res.coverage_gaps == 1 and len(res.claims) == 1
    assert "coverage_gap" in client.requests[1].user


async def test_short_sentences_are_not_gaps(make_ctx):
    text = "Jordan misplaces receipts. Seems fine. Ok."
    client = Script(out(rc("a", "Jordan misplaces receipts")))
    res, _ = await run(client, text=text, make_ctx=make_ctx)
    assert res.coverage_gaps == 0 and len(client.requests) == 1


async def test_claim_cap_drops_extras_without_retry(make_ctx):
    text = " ".join(f"Item{i} was noted today." for i in range(5))
    claims = [rc(f"r{i}", f"Item{i} was noted today") for i in range(5)]
    client = Script(out(*claims))
    res, _ = await run(client, text=text, make_ctx=make_ctx, atomize_max_claims=3)
    assert len(res.claims) == 3 and res.dropped == 2 and len(client.requests) == 1


async def test_empty_output_for_real_text_retries_then_fails_no_claims(make_ctx):
    client = Script(out(), out())
    res, _ = await run(client, make_ctx=make_ctx)
    assert (res.status, res.failure) == ("failed", "no_claims") and len(client.requests) == 2


async def test_only_unresolvable_claims_fail_with_no_claims(make_ctx):
    bad = out(rc("a", "nothing like this exists in the text"))
    res, _ = await run(Script(bad, bad), make_ctx=make_ctx)
    assert (res.status, res.failure, res.claims) == ("failed", "no_claims", [])


async def test_more_than_half_dropped_fails_too_many_dropped(make_ctx):
    bad = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "made up one here"),
        rc("c", "made up two here"),
    )
    res, _ = await run(Script(bad, bad), make_ctx=make_ctx)
    assert (res.status, res.failure) == ("failed", "too_many_dropped") and res.claims == []


async def test_exactly_half_dropped_is_not_a_failure(make_ctx):
    bad = out(rc("a", "Jordan misplaces receipts"), rc("b", "made up one here"))
    res, _ = await run(Script(bad, bad), text="Jordan misplaces receipts.", make_ctx=make_ctx)
    assert res.status == "ok" and res.dropped == 1


async def test_retry_skipped_under_low_budget(make_ctx):
    bad = out(rc("a", "Jordan misplaces receipts"))
    client = Script(bad, GOOD)
    res, _ = await run(client, make_ctx=make_ctx, deadline_in=10.0)  # < llm_timeout_s (30)
    assert len(client.requests) == 1 and res.retries == 0
    assert res.coverage_gaps == 1 and len(res.claims) == 1


async def test_retry_can_be_disabled(make_ctx):
    bad = out(rc("a", "Jordan misplaces receipts"))
    client = Script(bad, GOOD)
    res, _ = await run(client, make_ctx=make_ctx, atomize_retry=False)
    assert len(client.requests) == 1 and res.retries == 0


async def test_retry_llm_failure_keeps_first_pass(make_ctx):
    bad = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
        rc("d", "made up words go here"),
    )
    res, _ = await run(Script(bad, LLMUnavailable("down")), make_ctx=make_ctx)
    assert res.status == "ok" and len(res.claims) == 3 and res.dropped == 1


async def test_blank_section_makes_no_call_and_is_ok(make_ctx):
    client = Script(GOOD)
    res, _ = await run(client, text="   \n", make_ctx=make_ctx)
    assert (res.status, res.claims, client.requests) == ("ok", [], [])


async def test_adhd_fixture_still_validates_end_to_end(make_ctx):
    ctx = make_ctx(llm=FixtureClient(FIXTURES), request_id="adhd-faithful")
    res = await atomize_section(adhd_section(), ROSTER, ctx, index=0)
    text = adhd_section().text
    assert (
        res.status == "ok" and res.dropped == 0 and res.coverage_gaps == 0 and len(res.claims) == 11
    )
    for c in res.claims:
        assert all(seg in text for seg in c.segments)
        assert c.span_hint is not None and c.span_quality == "covering"
    spans = sorted(c.span_hint for c in res.claims)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))
    # "Alex estimates" and "His partner reports" stay separate accounts
    srcs = {c.reported_by[0].source for c in res.claims}
    assert {"self", "informant", "unspecified"} <= srcs


async def test_llm_failure_still_reported_as_section_failure(make_ctx):
    res, _ = await run(FailingClient(LLMUnavailable("x")), make_ctx=make_ctx)
    assert (res.status, res.failure) == ("failed", "unavailable")


async def test_the_causal_worked_case_shape(make_ctx):
    """Conclusion out_of_scope + two in-scope causes + one causal link (R7.7)."""
    text = "Jordan is disorganized because Jordan misplaces receipts and double-books clients."
    o = out(
        rc(
            "a",
            "Jordan is disorganized",
            scope="out_of_scope",
            oos_category="diagnostic_conclusion",
        ),
        rc("b", "Jordan misplaces receipts"),
        rc("c", "double-books clients"),
        links=[
            {
                "type": "causal",
                "cause_ids": ["b", "c"],
                "effect_id": "a",
                "connector": "because",
                "source": "assessor",
            }
        ],
    )
    res, _ = await run(Script(o), text=text, make_ctx=make_ctx)
    assert [c.scope for c in res.claims] == ["out_of_scope", "in_scope", "in_scope"]
    assert res.claims[0].oos_reason and res.links[0].connector == "because"
    assert res.links[0].cause_ids == ["c0.2", "c0.3"] and res.links[0].effect_id == "c0.1"


def test_atomize_has_no_matcher_of_its_own():
    import importlib
    from pathlib import Path

    import iaudit_backend.atomize.validate as val

    asm = importlib.import_module("iaudit_backend.assembler.locate")
    assert val.locate is asm.locate
    pkg = Path(val.__file__).parent
    src = "\n".join(p.read_text() for p in pkg.glob("*.py"))
    assert "rapidfuzz" not in src and "def locate" not in src and "difflib" not in src


async def test_one_bad_category_claim_is_retried_then_dropped_rest_survive(make_ctx):
    bad = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "Jordan double-books clients", scope="out_of_scope"),  # no category
        rc("c", "skips lunch every day"),
    )
    client = Script(bad, bad)
    res, _ = await run(client, make_ctx=make_ctx)
    assert res.status == "ok" and res.failure is None
    assert len(client.requests) == 2 and res.retries == 1
    assert "b: bad_category" in client.requests[1].user
    assert res.dropped == 1 and [c.segments for c in res.claims] == [
        ["Jordan misplaces receipts"],
        ["skips lunch every day"],
    ]


async def test_category_on_in_scope_claim_is_also_a_per_claim_error(make_ctx):
    bad = out(
        rc("a", "Jordan misplaces receipts", oos_category="recommendation"),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
    )
    res, _ = await run(Script(bad, bad), make_ctx=make_ctx)
    assert res.status == "ok" and res.dropped == 1 and len(res.claims) == 2


async def test_retry_fixes_the_bad_claim(make_ctx):
    bad = out(
        rc("a", "Jordan misplaces receipts"),
        rc("b", "Jordan double-books clients", scope="out_of_scope"),
        rc("c", "skips lunch every day"),
    )
    res, _ = await run(Script(bad, GOOD), make_ctx=make_ctx)
    assert res.status == "ok" and res.dropped == 0 and len(res.claims) == 3


async def test_mismatched_quantity_bucket_does_not_fail_the_section(make_ctx):
    q = [
        {"kind": "severity", "raw": "poor", "bucket": "often"},
        {"kind": "frequency", "raw": "every day", "bucket": "severe"},
    ]
    o = out(
        rc("a", "Jordan misplaces receipts", quantities=q),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
    )
    client = Script(o)
    res, _ = await run(client, make_ctx=make_ctx)
    assert res.status == "ok" and len(client.requests) == 1
    sev, freq = res.claims[0].quantities
    assert (sev.bucket, freq.bucket, freq.rate_per_week) == ("severe", "always", 7.0)


async def test_unresolvable_mismatched_bucket_becomes_none(make_ctx):
    q = [{"kind": "frequency", "raw": "off and on", "bucket": "severe"}]
    o = out(
        rc("a", "Jordan misplaces receipts", quantities=q),
        rc("b", "Jordan double-books clients"),
        rc("c", "skips lunch every day"),
    )
    res, _ = await run(Script(o), make_ctx=make_ctx)
    assert res.status == "ok" and res.claims[0].quantities[0].bucket is None
