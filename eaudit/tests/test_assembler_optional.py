"""02 optional: 8-gram copy check and partial-overlap trimming."""

import copy

from test_claims import SEC, cd, sections
from test_copycheck import claim

from eaudit.assembler.claims import resolve_claims
from eaudit.assembler.copycheck import CopyContext, scrub_claim
from eaudit.assembler.models import AssembleReport
from eaudit.config import Settings
from eaudit.models import AuditRequest

# -- 8-gram copy check -----------------------------------------------------------------------

COPIED = "I missed one last year, when I was traveling."  # transcript turn t3 (9 words)


def ctx(req, **kw):
    return CopyContext.from_request(AuditRequest.model_validate(req), **kw)


def scrubbed(req, c, **kw):
    r = AssembleReport()
    notes = scrub_claim(c, ctx(req, **kw), r)
    return notes, r


def test_eight_word_verbatim_run_without_quotes_is_stripped(example_request):
    c = claim(explanation=f"The respondent was clear. Then {COPIED.lower()} That is all.")
    notes, r = scrubbed(example_request, c)
    assert "traveling" not in c["explanation"]
    assert c["explanation"] == "The respondent was clear. That is all."
    assert notes and r.repairs["copy_explanation"] == 1


def test_seven_word_run_is_allowed(example_request):
    c = claim(explanation="Noted: I missed one last year, when I.")
    notes, _ = scrubbed(example_request, c)
    assert notes == []


def test_run_is_matched_ignoring_case_and_punctuation(example_request):
    c = claim(explanation="Here: I MISSED one last-year when I was traveling!")
    notes, _ = scrubbed(example_request, c)
    assert notes


def test_assessor_own_words_are_allowed(example_request):
    req = copy.deepcopy(example_request)
    req["assessment"][0]["text"] += " " + COPIED
    c = claim(explanation=f"The assessment says {COPIED}")
    notes, _ = scrubbed(req, c)
    assert notes == []


def test_gram_check_covers_concern_note_revision_and_reason(example_request):
    c = claim(suggested_revision=f"Write: {COPIED}")
    c["concerns"][0]["explanation"] = COPIED
    c["evidence"][0]["note"] = f"Because {COPIED}"
    notes, r = scrubbed(example_request, c)
    assert c["suggested_revision"] is None
    assert "traveling" not in c["concerns"][0]["explanation"]
    assert "note" not in c["evidence"][0]
    assert len(notes) == 1


def test_gram_check_can_be_switched_off(example_request):
    c = claim(explanation=f"Then {COPIED}")
    notes, _ = scrubbed(example_request, c, ngram=0)
    assert notes == []


def test_ngram_size_comes_from_settings(example_request):
    from eaudit.assembler import CopyContext as exported  # noqa: F401

    assert Settings().copy_ngram == 8


def test_transcript_grams_built_once(example_request):
    cx = ctx(example_request)
    assert cx.turn_grams is cx.turn_grams and len(cx.turn_grams) > 0


# -- partial overlap trimming ----------------------------------------------------------------

CFG = Settings()


def run(drafts, *texts, trim=True):
    r = AssembleReport()
    cfg = CFG.model_copy(update={"overlap_trim": trim})
    return resolve_claims(drafts, sections(*texts), [], cfg, r), r


def test_less_severe_later_claim_is_trimmed_at_its_start():
    res, _ = run(
        [
            cd("a", "The caregiver reported two medication lapses.", verdict="contradicted"),
            cd("b", "lapses. The patient frequently loses keys.", verdict="supported"),
        ],
        SEC,
    )
    a, b = res.claims
    assert SEC[a.start : a.end] == "The caregiver reported two medication lapses."
    assert SEC[b.start : b.end] == "The patient frequently loses keys."
    assert [(e.kind, e.key, e.kept_key) for e in res.events] == [("overlap_trimmed", "b", "a")]


def test_less_severe_earlier_claim_is_trimmed_at_its_end():
    res, _ = run(
        [
            cd("a", "The caregiver reported two medication lapses.", verdict="supported"),
            cd("b", "lapses. The patient frequently loses keys.", verdict="contradicted"),
        ],
        SEC,
    )
    a, b = res.claims
    assert SEC[a.start : a.end] == "The caregiver reported two medication"
    assert SEC[b.start : b.end] == "lapses. The patient frequently loses keys."
    assert res.events[0].key == "a"


def test_tie_trims_the_later_claim():
    res, _ = run(
        [cd("a", "reported two medication lapses."), cd("b", "lapses. The patient frequently")],
        SEC,
    )
    assert [c.key for c in res.claims] == ["a", "b"]
    assert res.events[0].key == "b"


def test_claim_with_under_three_visible_chars_left_is_dropped():
    res, _ = run(
        [
            cd("a", "The caregiver reported two medication lapses.", verdict="contradicted"),
            cd("b", "lapses. Th", verdict="supported"),
        ],
        SEC,
    )
    assert [c.key for c in res.claims] == ["a"]
    assert res.events[0].kind == "overlap_partial"


def test_trim_off_keeps_the_drop_behaviour():
    res, _ = run(
        [
            cd("a", "The caregiver reported two medication lapses.", verdict="contradicted"),
            cd("b", "lapses. The patient frequently loses keys.", verdict="supported"),
        ],
        SEC,
        trim=False,
    )
    assert [c.key for c in res.claims] == ["a"]
    assert res.events[0].kind == "overlap_partial"


def test_trimmed_spans_never_overlap():
    drafts = [
        cd("a", "The caregiver reported two medication"),
        cd("b", "medication lapses. The patient"),
        cd("c", "The patient frequently loses keys."),
        cd("d", "Done."),
    ]
    res, _ = run(drafts, SEC)
    cl = res.claims
    assert len(cl) == 4
    assert all(x.end <= y.start for x, y in zip(cl, cl[1:], strict=False))


def test_trimmed_claim_gets_a_warning_with_its_claim_id():
    from eaudit.assembler.warnings import event_warning

    res, _ = run(
        [
            cd("a", "The caregiver reported two medication lapses.", verdict="contradicted"),
            cd("b", "lapses. The patient frequently loses keys.", verdict="supported"),
        ],
        SEC,
    )
    id_of = {c.key: c.id for c in res.claims}
    w = event_warning(res.events[0], id_of)
    assert w["code"] == "other" and w["claim_id"] == id_of["b"] and "trimmed" in w["message"]


# -- copied run that crosses a sentence boundary ---------------------------------------------

CROSS_TURN = "I misplace the car keys most mornings. After that I am late for the bus."


def cross_request(example_request):
    req = copy.deepcopy(example_request)
    req["transcript"][3]["text"] = CROSS_TURN
    return req


def test_cross_sentence_run_in_explanation_uses_fallback(example_request):
    text = "Overall note. I misplace the car keys most mornings. After that I am late."
    c = claim(explanation=text)
    notes, r = scrubbed(cross_request(example_request), c)
    assert c["explanation"] == "The cited excerpts conflict with this claim."
    assert notes and r.repairs["copy_explanation"] == 1


def test_cross_sentence_run_in_concern_explanation_uses_fallback(example_request):
    c = claim()
    c["concerns"][0]["explanation"] = (
        "Overall note. I misplace the car keys most mornings. After that I am late."
    )
    notes, r = scrubbed(cross_request(example_request), c)
    assert "keys" not in c["concerns"][0]["explanation"] and notes
    assert r.repairs["copy_concern"] == 1


def test_cross_sentence_run_in_out_of_scope_reason_uses_fallback(example_request):
    c = claim(
        verdict="out_of_scope",
        out_of_scope_reason=(
            "Overall note. I misplace the car keys most mornings. After that I am late."
        ),
    )
    c["concerns"], c["evidence"] = [], []
    notes, r = scrubbed(cross_request(example_request), c)
    assert "keys" not in c["out_of_scope_reason"] and c["out_of_scope_reason"] and notes
    assert r.repairs["copy_reason"] == 1
