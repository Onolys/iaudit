import pytest
from link_helpers import adhd_prep, adhd_turns

from iaudit_backend.assembler.evidence import resolve_evidence
from iaudit_backend.assembler.models import AssembleReport
from iaudit_backend.link.models import LinkerOutput
from iaudit_backend.link.validate import validate_output


def out(*items):
    return LinkerOutput.model_validate({"items": list(items)})


def it(key, role, segs, lt="quote", **kw):
    return {
        "key": key,
        "role": role,
        "link_type": lt,
        "segments": [{"turn": t, "text": x} for t, x in segs],
        **kw,
    }


def run(output, indices=None, cfg=None, roles=False, cid="c0.1"):
    from iaudit_backend.config import Settings

    prep = adhd_prep(roles)
    turns = adhd_turns(roles)
    return validate_output(cid, output, turns, prep, indices or list(range(26)), cfg or Settings())


def keys(v):
    return [e.draft.key for e in v.evidence]


def test_valid_item_passes_and_keys_are_claim_scoped():
    v = run(out(it("e1", "supporting", [(7, "My phone, constantly.")])))
    assert keys(v) == ["c0.1:e1"] and v.counts["items_kept"] == 1
    e = v.evidence[0]
    assert e.draft.role.value == "supporting" and e.link_type == "quote"
    assert (e.draft.segments[0].turn_index, e.draft.segments[0].text) == (
        7,
        "My phone, constantly.",
    )


def test_turn_outside_shortlist_is_dropped():
    v = run(out(it("e1", "supporting", [(7, "My phone, constantly.")])), indices=[3, 4])
    assert (
        v.evidence == [] and v.counts["not_in_shortlist"] == 1 and v.counts["items_returned"] == 1
    )


def test_turn_index_out_of_range_is_dropped_not_a_crash():
    v = run(out(it("e1", "supporting", [(99, "x y z")]), it("e2", "supporting", [(-1, "x")])))
    assert v.evidence == [] and v.counts["not_in_shortlist"] == 2


def test_text_not_in_the_turn_is_dropped_even_if_in_another_turn():
    v = run(out(it("e1", "supporting", [(3, "My phone, constantly.")])))  # that text is turn 7
    assert v.evidence == [] and v.counts["unlocatable"] == 1


def test_fuzzy_unmatched_dropped_but_a_typo_is_accepted():
    bad = run(out(it("e1", "supporting", [(7, "My phone, occasionally. Rarely I hunt")])))
    assert bad.evidence == []
    ok = run(
        out(
            it(
                "e1",
                "supporting",
                [(7, "My phone, constantly. Probably every day Im hunting for it.")],
            )
        )
    )
    assert len(ok.evidence) == 1


def test_empty_text_is_dropped():
    v = run(out(it("e1", "supporting", [(7, "   ")])))
    assert v.evidence == [] and v.counts["empty_text"] == 1


def test_item_losing_one_segment_keeps_the_other():
    v = run(
        out(it("e1", "supporting", [(7, "My phone, constantly."), (9, "nonexistent text here")]))
    )
    assert [s.turn_index for s in v.evidence[0].draft.segments] == [7]


def test_segments_sorted_by_turn_and_one_per_turn():
    v = run(out(it("e1", "supporting", [(9, "Keys, no."), (7, "My phone"), (7, "constantly")])))
    segs = v.evidence[0].draft.segments
    assert [s.turn_index for s in segs] == [7, 9] and v.counts["dup_turn_segment"] == 1


def test_question_plus_reply_snaps_to_full_turns_and_merges_in_02():
    v = run(out(it("e1", "qualifying", [(8, "keys?"), (9, "Keys, no.")])))
    segs = v.evidence[0].draft.segments
    turns = adhd_turns()
    assert [s.text for s in segs] == [turns[8].text, turns[9].text]  # verbatim full turns
    assert v.counts["snapped"] == 2
    res = resolve_evidence(
        [v.evidence[0].draft],
        turns,
        __import__("iaudit_backend.config").config.Settings(),
        AssembleReport(),
    )
    (item,) = res.items
    assert item["span"] == {
        "start": {"index": 8, "char": 0},
        "end": {"index": 9, "char": len(turns[9].text)},
    }


def test_long_reply_is_not_snapped():
    turns = adhd_turns()
    assert len(turns[11].text) > 80
    v = run(out(it("e1", "supporting", [(10, "household projects?"), (11, "Sometimes.")])))
    segs = v.evidence[0].draft.segments
    assert segs[0].text == turns[10].text and segs[1].text == "Sometimes."


def test_single_segment_items_are_never_snapped():
    v = run(out(it("e1", "supporting", [(8, "keys?")])))
    assert v.evidence[0].draft.segments[0].text == "keys?" and v.counts["snapped"] == 0


def test_no_segment_ever_spans_two_turns():
    v = run(out(it("e1", "qualifying", [(12, "easily distracted"), (13, "Hm.")])))
    turns = adhd_turns()
    for e in v.evidence:
        for s in e.draft.segments:
            assert s.text in turns[s.turn_index].text


@pytest.mark.parametrize(
    "segs,status,role_in,role_out",
    [
        (
            [(12, "Are you easily distracted by things going on around you?")],
            "question_only",
            "supporting",
            "qualifying",
        ),
        ([(12, "easily distracted"), (13, "Hm.")], "non_answer", "supporting", "qualifying"),
        (
            [(0, "trouble keeping your attention"), (1, "Yeah, in meetings especially.")],
            "endorsed",
            "supporting",
            "supporting",
        ),
        ([(7, "My phone, constantly.")], "n/a", "supporting", "supporting"),
    ],
)
def test_answer_status_and_coercion(segs, status, role_in, role_out):
    v = run(out(it("e1", role_in, segs)))
    e = v.evidence[0]
    assert (e.answer_status, e.draft.role.value) == (status, role_out)
    assert v.counts["coerced"] == (1 if role_in != role_out else 0)


def test_contradicting_is_not_coerced_for_non_answers():
    v = run(out(it("e1", "contradicting", [(12, "easily distracted"), (13, "Hm.")])))
    assert v.evidence[0].draft.role.value == "contradicting" and v.counts["coerced"] == 0


def test_variant_6_turn_23_accepts_contradicting_or_qualifying():
    for role in ("contradicting", "qualifying"):
        v = run(
            out(
                it("e1", "supporting", [(19, "maybe twice a month")]),
                it(
                    "e2",
                    role,
                    [
                        (22, "do you agree about the groceries?"),
                        (23, "I think it's less than that."),
                    ],
                ),
            )
        )
        assert [e.draft.role.value for e in v.evidence] == ["supporting", role]
        assert v.evidence[1].answer_status == "endorsed"


def test_valid_inference_keeps_premises_and_stays_internal():
    v = run(
        out(
            it("e1", "supporting", [(7, "My phone, constantly.")]),
            it("e2", "supporting", [(9, "Keys, no.")]),
            it(
                "e3",
                "supporting",
                [],
                lt="inference",
                premises=["e1", "e2"],
                inference_step="Both lapses together.",
            ),
        )
    )
    inf = v.evidence[2]
    assert inf.link_type == "inference" and inf.premise_keys == ["c0.1:e1", "c0.1:e2"]
    assert inf.inference_step == "Both lapses together." and inf.draft.segments == []
    assert v.counts["items_kept"] == 3


@pytest.mark.parametrize(
    "inf",
    [
        {"premises": ["e1", "missing"], "inference_step": "Because."},
        {"premises": ["e1"], "inference_step": "  "},
        {"premises": ["e1"], "inference_step": None},
    ],
)
def test_bad_inference_is_dropped_and_premises_become_qualifying(inf):
    v = run(
        out(
            it("e1", "supporting", [(7, "My phone, constantly.")]),
            it("e3", "supporting", [], lt="inference", **inf),
        )
    )
    assert [e.link_type for e in v.evidence] == ["quote"]
    assert v.evidence[0].draft.role.value == "qualifying" and v.counts["inference_dropped"] == 1


@pytest.mark.parametrize(
    "inf",
    [
        {"premises": [], "inference_step": "Because."},
        {"premises": ["e3"], "inference_step": "Self reference."},
    ],
)
def test_inference_without_usable_premises_is_dropped_and_other_items_untouched(inf):
    v = run(
        out(
            it("e1", "supporting", [(7, "My phone, constantly.")]),
            it("e3", "supporting", [], lt="inference", **inf),
        )
    )
    assert [e.link_type for e in v.evidence] == ["quote"]
    assert v.evidence[0].draft.role.value == "supporting" and v.counts["inference_dropped"] == 1


def test_inference_whose_premise_was_dropped_is_dropped():
    v = run(
        out(
            it("e1", "supporting", [(7, "nonexistent words nowhere")]),
            it("e2", "supporting", [(9, "Keys, no.")]),
            it(
                "e3",
                "supporting",
                [],
                lt="inference",
                premises=["e1", "e2"],
                inference_step="Step.",
            ),
        )
    )
    assert [e.link_type for e in v.evidence] == ["quote"] and v.evidence[
        0
    ].draft.role.value == "qualifying"


def test_inference_cannot_use_an_inference_as_premise():
    v = run(
        out(
            it("e1", "supporting", [(7, "My phone, constantly.")]),
            it("e2", "supporting", [], lt="inference", premises=["e1"], inference_step="Step."),
            it("e3", "supporting", [], lt="inference", premises=["e2"], inference_step="Step."),
        )
    )
    assert [e.link_type for e in v.evidence] == ["quote", "inference"]


def test_dedup_identical_turn_set_and_role():
    v = run(
        out(
            it("e1", "supporting", [(7, "My phone, constantly.")], note="first"),
            it("e2", "supporting", [(7, "Probably every day")], note="second"),
            it("e3", "contradicting", [(7, "My phone, constantly.")]),
        )
    )
    assert len(v.evidence) == 2 and v.counts["dedup"] == 1
    assert v.evidence[0].draft.note == "first"


def test_cap_keeps_adverse_items_first():
    cfg = __import__("iaudit_backend.config").config.Settings(link_max_items=2)
    v = run(
        out(
            it("e1", "supporting", [(3, "Most meetings.")]),
            it("e2", "supporting", [(7, "My phone")]),
            it("e3", "contradicting", [(5, "Not really.")]),
            it("e4", "qualifying", [(9, "Keys, no.")]),
        ),
        cfg=cfg,
    )
    assert sorted(e.draft.role.value for e in v.evidence) == ["contradicting", "qualifying"]
    assert v.counts["capped"] == 2 and [e.draft.key for e in v.evidence] == ["c0.1:e1", "c0.1:e2"]


def test_ambiguous_turns_are_cited_turns_without_role():
    v = run(
        out(
            it(
                "e1",
                "supporting",
                [(7, "My phone, constantly.")],
            )
        ),
        roles=False,
    )
    assert v.ambiguous_turns == [7]
    v2 = run(out(it("e1", "supporting", [(7, "My phone, constantly.")])), roles=True)
    assert v2.ambiguous_turns == []
    mixed = run(out(it("e1", "supporting", [(7, "My phone"), (9, "Keys, no.")])), roles=False)
    assert mixed.ambiguous_turns == [7, 9]


def test_ambiguous_turns_only_from_surviving_evidence():
    v = run(out(it("e1", "supporting", [(7, "nonexistent words nowhere")])))
    assert v.ambiguous_turns == []


def test_duplicate_item_keys_keep_the_first():
    v = run(
        out(
            it("e1", "supporting", [(7, "My phone, constantly.")]),
            it("e1", "contradicting", [(9, "Keys, no.")]),
        )
    )
    assert len(v.evidence) == 1 and v.counts["dup_key"] == 1


def test_counts_hold_numbers_only():
    v = run(out(it("e1", "supporting", [(7, "My phone, constantly.")])))
    assert all(isinstance(x, int) for x in v.counts.values())


def test_nothing_returned_is_not_all_dropped():
    v = run(out())
    assert v.counts["items_returned"] == 0 and v.evidence == []
