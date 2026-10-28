"""Code gates and checker verdicts for taxonomy v2, with scripted observations."""

from dataclasses import replace

import pytest
from check_helpers import adhd_prep, claim, ev, link

from eaudit.atomize.models import CausalLink
from eaudit.check import check_one
from eaudit.check.group_a import run_group_a
from eaudit.check.models import VerifierOutput
from eaudit.check.synth import judge
from eaudit.check.verifier import apply_floors
from eaudit.config import Settings
from eaudit.llm import StubClient

E1, E2 = "c0.1:e1", "c0.1:e2"
NEW_TYPES = ("opinion_as_fact", "calculation_error", "meaning_shift", "unsupported_inference")
PREP = adhd_prep(roles=True)
TURNS = list(PREP.turns)
TURNS[3] = replace(TURNS[3], text="I missed two visits in March and one in April.")
TURNS[5] = replace(TURNS[5], text="I missed 12 visits.")
TURNS[7] = replace(TURNS[7], text="I missed a visit in 2019; no one else came.")
TURNS[9] = replace(TURNS[9], text="I missed one visit in April.")


def output(kind, relation="entails", keys=None, conf="high"):
    return {
        "items": [{"key": E1, "relation": relation, "conf": "high"}],
        "flags": [{"type": kind, "keys": [E1] if keys is None else keys, "conf": conf}],
    }


def gated(c, data, lk=None, causal_links=()):
    lk = lk or link(ev())
    vout, counts = apply_floors(VerifierOutput.model_validate(data), Settings())
    kwargs = {"causal_links": causal_links} if causal_links else {}
    return judge(c, lk, run_group_a(c, lk, TURNS), TURNS, vout, counts, **kwargs)


async def checked(make_ctx, c, data, lk=None, causal_links=()):
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(data))
    kwargs = {"causal_links": causal_links} if causal_links else {}
    return await check_one(c, lk or link(ev()), PREP, TURNS, make_ctx(llm=stub), **kwargs)


@pytest.mark.parametrize("kind", NEW_TYPES)
@pytest.mark.parametrize("relation", ["entails", "not_addresses"])
async def test_new_flag_preserves_partial_support_and_supporting_role(make_ctx, kind, relation):
    draft = await checked(make_ctx, claim("Alex missed five visits."), output(kind, relation))
    assert draft.outcome == "ok"
    assert draft.verdict == "partially_supported"
    assert [c.type for c in draft.concerns] == [kind]
    assert [(e.key, e.role) for e in draft.evidence] == [(E1, "supporting")]


@pytest.mark.parametrize("kind", NEW_TYPES)
async def test_new_flag_uses_verifier_contradiction_for_verdict_and_role(make_ctx, kind):
    draft = await checked(make_ctx, claim("Alex missed five visits."), output(kind, "contradicts"))
    assert draft.outcome == "ok"
    assert draft.verdict == "contradicted"
    assert kind in [c.type for c in draft.concerns]
    assert [(e.key, e.role) for e in draft.evidence] == [(E1, "contradicting")]


@pytest.mark.parametrize("kind", NEW_TYPES)
def test_new_flag_below_p1_is_dropped_and_counted(kind):
    _, sig = gated(claim("Alex missed five visits."), output(kind, conf="low"))
    assert sig.flags == []
    assert sig.counts["flags_below_floor"] == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"hedged": True},
        {"reported_by": [{"source": "self"}]},
        {"reported_by": [{"source": "informant"}]},
        {"reported_by": [{"source": "interviewer"}]},
        {"reported_by": [{"source": "assessor"}, {"source": "informant"}]},
    ],
)
def test_opinion_gate_suppresses_hedged_or_already_attributed_claim(fields):
    _, sig = gated(claim("The tablets caused headaches.", **fields), output("opinion_as_fact"))
    assert sig.flags == []
    assert sig.counts["flags_suppressed"] == 1


@pytest.mark.parametrize("source", ["assessor", "unspecified"])
def test_opinion_gate_accepts_unhedged_assessor_or_unspecified_reporter(source):
    _, sig = gated(
        claim("The tablets caused headaches.", reported_by=[{"source": source}]),
        output("opinion_as_fact"),
    )
    assert [f.type for f in sig.flags] == ["opinion_as_fact"]


def causal(source, cause_ids=None, effect_id="c0.2"):
    return CausalLink(
        cause_ids=cause_ids or ["c0.1"], effect_id=effect_id, connector="caused", source=source
    )


@pytest.mark.parametrize("where", ["cause", "effect"])
async def test_opinion_gate_rejects_reported_causal_link_covering_claim(make_ctx, where):
    links = [
        causal(
            "reported",
            **({"cause_ids": ["c0.2"], "effect_id": "c0.1"} if where == "effect" else {}),
        )
    ]
    c = claim("The tablets caused headaches.")
    _, sig = gated(c, output("opinion_as_fact"), causal_links=links)
    assert sig.flags == []
    assert sig.counts["flags_suppressed"] == 1
    draft = await checked(make_ctx, c, output("opinion_as_fact"), causal_links=links)
    assert draft.verdict == "supported" and draft.concerns == []


@pytest.mark.parametrize(
    "links",
    [
        [causal("assessor")],
        [causal("reported", cause_ids=["c0.8"], effect_id="c0.9")],
    ],
)
def test_opinion_gate_accepts_assessor_link_and_ignores_unrelated_reported_link(links):
    _, sig = gated(
        claim("The tablets caused headaches."), output("opinion_as_fact"), causal_links=links
    )
    assert len(sig.flags) == 1


@pytest.mark.parametrize(
    "text,turn",
    [
        ("Alex missed visits.", 3),  # no figure in claim
        ("Alex missed five visits.", 5),  # multi-digit single figure is one token
        ("Alex missed five visits.", 7),  # year and pronoun one are not addends
    ],
)
def test_calculation_gate_suppresses_without_claim_figure_or_two_source_tokens(text, turn):
    _, sig = gated(claim(text), output("calculation_error"), link(ev(turn=turn)))
    assert sig.flags == []
    assert sig.counts["flags_suppressed"] == 1


def test_calculation_gate_counts_numbers_across_distinct_cited_turns():
    lk = link(ev(n=1, turn=5), ev(n=2, turn=5))
    data = output("calculation_error", keys=[E1, E2])
    data["items"].append({"key": E2, "relation": "entails"})
    _, sig = gated(claim("Alex missed five visits."), data, lk)
    assert sig.flags == []  # the same single figure cited twice is not two figures
    lk = link(ev(n=1, turn=5), ev(n=2, turn=9))
    _, sig = gated(claim("Alex missed five visits."), data, lk)
    assert len(sig.flags) == 1


def test_calculation_gate_reads_only_cited_items():
    lk = link(ev(n=1, turn=5), ev(n=2, turn=3))
    _, sig = gated(claim("Alex missed five visits."), output("calculation_error"), lk)
    assert sig.flags == [] and sig.counts["flags_suppressed"] == 1


@pytest.mark.parametrize("keys", [[], ["unknown"]])
def test_meaning_shift_gate_requires_known_nonempty_keys(keys):
    _, sig = gated(claim("Physiotherapy was ordered."), output("meaning_shift", keys=keys))
    assert sig.flags == []
    assert sig.counts["flags_suppressed"] == 1


def test_meaning_shift_keeps_known_key_after_unknown_keys_are_dropped():
    _, sig = gated(
        claim("Physiotherapy was ordered."), output("meaning_shift", keys=[E1, "unknown"])
    )
    assert sig.flags[0].keys == [E1]


async def test_failed_inference_with_entailing_premises_is_insufficient_inference(make_ctx):
    lk = link(
        ev(n=1),
        ev(n=2, turn=5),
        ev(n=3, lt="inference", premises=[E1, E2], step="These facts are related."),
    )
    data = {
        "items": [{"key": E1, "relation": "entails"}, {"key": E2, "relation": "entails"}],
        "inferences": [{"key": "c0.1:e3", "step_acceptable": False, "conf": "high"}],
    }
    draft = await checked(make_ctx, claim("The project demonstrates poor planning."), data, lk)
    assert draft.outcome == "ok"
    assert draft.verdict == "insufficient_evidence"
    assert [(c.type, c.evidence_keys) for c in draft.concerns] == [
        ("unsupported_inference", [E1, E2])
    ]
    assert [(e.key, e.role) for e in draft.evidence] == [(E1, "qualifying"), (E2, "qualifying")]


@pytest.mark.parametrize(
    "source,want", [("reported", "supported"), ("assessor", "partially_supported")]
)
async def test_pipeline_passes_atomizer_causal_source_into_opinion_gate(
    make_ctx, example_request, monkeypatch, source, want
):
    from eaudit.atomize.models import SectionAtoms
    from eaudit.models import AuditRequest
    from eaudit.pipeline import flow
    from eaudit.pipeline.state import RunState

    c = claim("The tablets caused headaches.")
    st = RunState(prep=PREP, link_ctx=object())
    st.prep_ready.set()
    st.write_atoms(
        0, SectionAtoms(section_index=0, status="ok", claims=[c], links=[causal(source)])
    )

    async def linked(*args):
        return link(ev())

    monkeypatch.setattr(flow, "link_one", linked)
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(output("opinion_as_fact")))
    await flow.claim_flow(st, AuditRequest.model_validate(example_request), c, make_ctx(llm=stub))
    draft = st.drafts[c.id]
    assert draft.outcome == "ok" and draft.verdict == want
    assert [x.type for x in draft.concerns] == ([] if source == "reported" else ["opinion_as_fact"])
