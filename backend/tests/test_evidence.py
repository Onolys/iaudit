from iaudit_backend.assembler.evidence import resolve_evidence
from iaudit_backend.assembler.models import AssembleReport, EvidenceDraft, ExcerptSegment
from iaudit_backend.config import Settings
from iaudit_backend.models import AuditRequest

CFG = Settings()


def turns(example_request):
    return AuditRequest.model_validate(example_request).transcript


def ev(key, *segs, role="supporting", note=None):
    return EvidenceDraft(
        key=key,
        role=role,
        note=note,
        segments=[ExcerptSegment(turn_index=t, text=x) for t, x in segs],
    )


def span(item):
    s = item["span"]
    return (s["start"]["index"], s["start"]["char"], s["end"]["index"], s["end"]["char"])


def run(example_request, drafts):
    r = AssembleReport()
    return resolve_evidence(drafts, turns(example_request), CFG, r), r


def test_single_segment(example_request):
    res, r = run(example_request, [ev("a", (4, "forgot her medication twice"))])
    assert [span(i) for i in res.items] == [(4, 4, 4, 31)]
    assert res.items[0]["id"] == "e1" and res.items[0]["role"] == "supporting"
    assert res.key_ids == {"a": ["e1"]}
    assert r.evidence_tiers["exact"] == 1


def test_whole_turn_ends_at_length(example_request):
    res, _ = run(example_request, [ev("a", (4, "She forgot her medication twice last month."))])
    assert span(res.items[0]) == (4, 0, 4, 43)


def test_merged_cross_turn_span(example_request):
    d = ev(
        "a", (2, "What about appointments?"), (3, "I missed one last year, when I was traveling.")
    )
    res, _ = run(example_request, [d])
    assert len(res.items) == 1
    assert span(res.items[0]) == (2, 0, 3, 45)
    assert res.items[0]["span"]["end"]["char"] > 0


def test_non_consecutive_turns_split(example_request):
    d = ev("a", (1, "No. I don't lose my keys."), (3, "I missed one last year"), note="n")
    res, _ = run(example_request, [d])
    assert [span(i) for i in res.items] == [(1, 0, 1, 25), (3, 0, 3, 22)]
    assert res.items[0].get("note") == "n" and "note" not in res.items[1]
    assert res.key_ids["a"] == ["e1", "e2"]


def test_partial_first_turn_splits(example_request):
    d = ev("a", (2, "What about"), (3, "I missed one last year"))
    res, _ = run(example_request, [d])
    assert len(res.items) == 2


def test_partial_last_turn_splits(example_request):
    d = ev("a", (2, "What about appointments?"), (3, "last year"))
    res, _ = run(example_request, [d])
    assert len(res.items) == 2


def test_three_turn_chain_merges(example_request):
    d = ev(
        "a",
        (2, "What about appointments?"),
        (3, "I missed one last year, when I was traveling."),
        (4, "She forgot her medication twice last month."),
    )
    res, _ = run(example_request, [d])
    assert [span(i) for i in res.items] == [(2, 0, 4, 43)]


def test_unmatched_segment_dropped_other_kept(example_request):
    d = ev("a", (1, "not in the transcript at all anywhere"), (4, "forgot her medication"))
    res, r = run(example_request, [d])
    assert [span(i) for i in res.items] == [(4, 4, 4, 25)]
    assert r.drops["segment_unmatched"] == 1


def test_fully_unmatched_evidence_dropped_and_key_absent(example_request):
    res, r = run(example_request, [ev("a", (1, "nothing like this exists in the turn"))])
    assert res.items == [] and "a" not in res.key_ids
    assert r.drops["evidence_unmatched"] == 1


def test_search_is_confined_to_cited_turn(example_request):
    # the text exists in turn 4, but is cited as turn 1
    res, _ = run(example_request, [ev("a", (1, "forgot her medication twice"))])
    assert res.items == []


def test_bad_turn_index_dropped(example_request):
    res, r = run(example_request, [ev("a", (99, "x y z")), ev("b", (-1, "x y z"))])
    assert res.items == [] and r.drops["segment_bad_turn"] == 2


def test_identical_span_and_role_collapse(example_request):
    res, _ = run(
        example_request,
        [ev("a", (1, "I don't lose my keys")), ev("b", (1, "I don't lose my keys"))],
    )
    assert len(res.items) == 1
    assert res.key_ids == {"a": ["e1"], "b": ["e1"]}


def test_same_span_different_role_kept(example_request):
    res, _ = run(
        example_request,
        [
            ev("a", (1, "I don't lose my keys")),
            ev("b", (1, "I don't lose my keys"), role="contradicting"),
        ],
    )
    assert [i["id"] for i in res.items] == ["e1", "e2"]


def test_report_has_no_text(example_request):
    _, r = run(example_request, [ev("a", (4, "forgot her medication twice"))])
    assert "forgot" not in r.model_dump_json()
