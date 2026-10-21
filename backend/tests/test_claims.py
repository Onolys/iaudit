from iaudit_backend.assembler.claims import resolve_claims
from iaudit_backend.assembler.models import AssembleReport, ClaimDraft, SectionFailure
from iaudit_backend.config import Settings
from iaudit_backend.models import AuditRequest

CFG = Settings(
    overlap_trim=False
)  # core drop policy; trimming is tested in test_assembler_optional
SEC = "The caregiver reported two medication lapses. The patient frequently loses keys. Done."


def sections(*texts):
    return AuditRequest.model_validate(
        {
            "schema_version": "1.1.0",
            "transcript": [{"id": "t", "speaker": "s", "text": "x"}],
            "assessment": [{"id": f"s{i}", "text": t} for i, t in enumerate(texts)],
        }
    ).assessment


def cd(key, *segs, section=0, hint=None, verdict="supported"):
    return ClaimDraft(
        key=key,
        section_index=section,
        segments=list(segs),
        span_hint=hint,
        verdict=verdict,
        explanation="e",
    )


def run(drafts, *texts, failures=(), cfg=CFG):
    r = AssembleReport()
    res = resolve_claims(drafts, sections(*texts), list(failures), cfg, r)
    return res, r


def spans(res):
    return [(c.id, c.section, c.start, c.end) for c in res.claims]


def test_locates_by_text_and_assigns_ids_in_document_order():
    # drafts given out of order; ids follow (section, start)
    res, _ = run(
        [cd("b", "The patient frequently loses keys."), cd("a", "The caregiver reported two")],
        SEC,
    )
    assert [(c[0], c[1]) for c in spans(res)] == [("c1", 0), ("c2", 0)]
    assert [c.key for c in res.claims] == ["a", "b"]
    assert [c.id for c in res.claims] == ["c1", "c2"]


def test_valid_hint_is_used():
    res, r = run([cd("a", "caregiver reported", hint=(0, 45))], SEC)
    assert (res.claims[0].start, res.claims[0].end) == (0, 45)
    assert r.claim_tiers["hint"] == 1


def test_stale_hint_falls_back_to_locate():
    res, r = run([cd("a", "The patient frequently loses keys.", hint=(0, 10))], SEC)
    assert SEC[res.claims[0].start : res.claims[0].end] == "The patient frequently loses keys."
    assert r.claim_tiers["exact"] == 1


def test_out_of_range_hint_falls_back():
    res, _ = run([cd("a", "Done.", hint=(0, 9999))], SEC)
    assert SEC[res.claims[0].start : res.claims[0].end] == "Done."


def test_multi_segment_covering_span():
    res, _ = run([cd("a", "The caregiver reported", "frequently loses keys")], SEC)
    c = res.claims[0]
    assert (
        SEC[c.start : c.end]
        == "The caregiver reported two medication lapses. The patient frequently loses keys"
    )


def test_segments_must_be_in_document_order():
    res, r = run([cd("a", "frequently loses keys", "The caregiver reported")], SEC)
    assert res.claims == [] and r.drops["claim_unlocatable"] == 1


def test_span_is_trimmed_to_non_whitespace():
    res, _ = run([cd("a", "  hello there  ")], "x   hello there   y")
    assert (res.claims[0].start, res.claims[0].end) == (4, 15)


def test_unlocatable_claim_dropped_with_event_naming_no_text():
    res, r = run([cd("a", "nonexistent statement about nothing"), cd("b", "Done.")], SEC)
    assert [c.key for c in res.claims] == ["b"]
    ev = [e for e in res.events if e.kind == "unlocatable"]
    assert len(ev) == 1 and ev[0].key == "a" and ev[0].section_index == 0
    assert "nonexistent" not in repr(ev)


def test_bad_section_index_dropped():
    res, r = run([cd("a", "Done.", section=5)], SEC)
    assert res.claims == [] and r.drops["claim_unlocatable"] == 1


def test_non_blank_section_without_located_claims_is_not_processed():
    res, _ = run([cd("a", "Done.")], SEC, "Another section with text")
    assert res.unprocessed == [(1, "no_claims_located")]


def test_blank_section_is_not_flagged():
    res, _ = run([cd("a", "Done.")], SEC, "   ")
    assert res.unprocessed == []


def test_failed_section_not_double_flagged():
    res, _ = run(
        [cd("a", "Done.")],
        SEC,
        "Other",
        failures=[SectionFailure(section_index=1, reason="timeout")],
    )
    assert res.unprocessed == []


def test_nested_drops_outer():
    res, _ = run(
        [
            cd("outer", "The caregiver reported two medication lapses. The patient"),
            cd("inner", "The patient"),
        ],
        SEC,
    )
    assert [c.key for c in res.claims] == ["inner"]
    assert [e.kind for e in res.events] == ["overlap_nested"]


def test_identical_keeps_more_severe():
    res, _ = run(
        [
            cd("a", "Done.", verdict="supported"),
            cd("b", "Done.", verdict="contradicted"),
            cd("c", "Done.", verdict="insufficient_evidence"),
        ],
        SEC,
    )
    assert [c.key for c in res.claims] == ["b"]
    assert [e.kind for e in res.events] == ["overlap_identical"] * 2


def test_identical_tie_keeps_first():
    res, _ = run([cd("a", "Done."), cd("b", "Done.")], SEC)
    assert [c.key for c in res.claims] == ["a"]


def test_partial_overlap_drops_less_severe():
    res, _ = run(
        [
            cd("a", "The caregiver reported two medication lapses.", verdict="supported"),
            cd("b", "lapses. The patient frequently", verdict="partially_supported"),
        ],
        SEC,
    )
    assert [c.key for c in res.claims] == ["b"]
    assert res.events[0].kind == "overlap_partial" and res.events[0].kept_key == "b"


def test_partial_overlap_tie_drops_later():
    res, _ = run(
        [cd("a", "reported two medication lapses."), cd("b", "lapses. The patient frequently")],
        SEC,
    )
    assert [c.key for c in res.claims] == ["a"]


def test_result_spans_never_overlap():
    drafts = [
        cd("a", "The caregiver reported two medication"),
        cd("b", "medication lapses. The patient"),
        cd("c", "The patient frequently loses keys."),
        cd("d", "Done."),
    ]
    res, _ = run(drafts, SEC)
    cl = res.claims
    assert all(x.end <= y.start for x, y in zip(cl, cl[1:], strict=False))


def test_ids_run_across_sections():
    res, _ = run([cd("a", "Done.", section=1), cd("b", "first", section=0)], "first part", SEC)
    assert [(c.id, c.section) for c in res.claims] == [("c1", 0), ("c2", 1)]
