from iaudit_backend.assembler.copycheck import CopyContext, scrub_claim
from iaudit_backend.assembler.models import AssembleReport
from iaudit_backend.models import AuditRequest


def ctx(example_request):
    return CopyContext.from_request(AuditRequest.model_validate(example_request))


def claim(**kw):
    c = {
        "verdict": "contradicted",
        "explanation": "The respondent denied it.",
        "suggested_revision": "The patient denied losing keys.",
        "concerns": [{"type": "negation_reversal", "explanation": "A denial.", "evidence_ids": []}],
        "evidence": [{"id": "e1", "role": "contradicting", "span": {}, "note": "A paraphrase."}],
    }
    c.update(kw)
    return c


def go(example_request, c):
    r = AssembleReport()
    return scrub_claim(c, ctx(example_request), r), r


def test_clean_claim_untouched(example_request):
    c = claim()
    before = repr(c)
    notes, r = go(example_request, c)
    assert repr(c) == before and notes == [] and not r.repairs


def test_quoted_four_word_transcript_span_stripped(example_request):
    c = claim(explanation='She said "I don\'t lose my keys" outright. The assessment differs.')
    notes, r = go(example_request, c)
    assert c["explanation"] == "The assessment differs."
    assert notes and r.repairs["copy_explanation"] == 1


def test_curly_quote_and_case_insensitive(example_request):
    c = claim(explanation="He stated “NO. I DON’T LOSE MY KEYS.” That is all.")
    go(example_request, c)
    assert "KEYS" not in c["explanation"]


def test_short_quote_allowed(example_request):
    c = claim(explanation='The respondent said "lose my keys" and denied it.')
    notes, _ = go(example_request, c)
    assert notes == [] and "lose my keys" in c["explanation"]


def test_quote_not_in_transcript_allowed(example_request):
    c = claim(explanation='The assessor wrote "frequently loses their keys often" here.')
    notes, _ = go(example_request, c)
    assert notes == []


def test_all_sentences_violating_falls_back_to_fixed_text(example_request):
    c = claim(explanation='She said "I missed one last year" plainly.')
    notes, _ = go(example_request, c)
    assert c["explanation"] == "The cited excerpts conflict with this claim."
    assert notes


def test_timestamp_string_caught(example_request):
    c = claim(explanation="At 00:01:08 the respondent denied it. Another sentence.")
    go(example_request, c)
    assert c["explanation"] == "Another sentence."


def test_timestamp_pattern_caught_even_if_not_in_request(example_request):
    c = claim(explanation="Around 14:35 they spoke. Fine.")
    go(example_request, c)
    assert c["explanation"] == "Fine."


def test_note_exact_substring_of_turn_dropped(example_request):
    c = claim()
    c["evidence"][0]["note"] = "forgot her medication twice"
    notes, r = go(example_request, c)
    assert "note" not in c["evidence"][0] and r.repairs["copy_note"] == 1


def test_note_paraphrase_kept(example_request):
    c = claim()
    c["evidence"][0]["note"] = "The caregiver mentions repeated lapses."
    go(example_request, c)
    assert c["evidence"][0]["note"].startswith("The caregiver")


def test_suggested_revision_nulled_on_violation(example_request):
    c = claim(suggested_revision='Say "I don\'t lose my keys" instead.')
    go(example_request, c)
    assert c["suggested_revision"] is None


def test_concern_explanation_fallback(example_request):
    c = claim()
    c["concerns"][0]["explanation"] = 'It says "I missed one last year" and so on'
    go(example_request, c)
    assert "missed one" not in c["concerns"][0]["explanation"]
    assert c["concerns"][0]["explanation"]


def test_out_of_scope_reason_repaired(example_request):
    c = claim(verdict="out_of_scope", out_of_scope_reason="See 00:01:02 for context")
    c["concerns"], c["evidence"] = [], []
    go(example_request, c)
    assert "00:01:02" not in c["out_of_scope_reason"] and c["out_of_scope_reason"]


def test_one_warning_note_per_claim(example_request):
    c = claim(explanation="At 00:01:08 x. Ok.", suggested_revision="At 00:01:08 y")
    notes, _ = go(example_request, c)
    assert len(notes) == 1


def test_every_verdict_has_a_fallback(example_request):
    for v in [
        "supported",
        "partially_supported",
        "contradicted",
        "insufficient_evidence",
        "out_of_scope",
    ]:
        c = claim(verdict=v, explanation="At 00:01:08 only.")
        c["concerns"], c["evidence"] = [], []
        go(example_request, c)
        assert c["explanation"] and "00:01" not in c["explanation"]


def test_straight_single_quoted_transcript_excerpt_stripped(example_request):
    c = claim(explanation="He said 'No. I don't lose my keys.' outright. The assessment differs.")
    notes, r = go(example_request, c)
    assert c["explanation"] == "The assessment differs."
    assert notes and r.repairs["copy_explanation"] == 1


def test_single_quoted_excerpt_without_contraction_stripped(example_request):
    c = claim(explanation="He said 'I missed one last year' which limits it.")
    go(example_request, c)
    assert c["explanation"] == "The cited excerpts conflict with this claim."


def test_plain_contractions_left_alone(example_request):
    text = (
        "The respondent didn't confirm it and the caregiver doesn't say otherwise. It isn't clear."
    )
    c = claim(explanation=text)
    notes, _ = go(example_request, c)
    assert notes == [] and c["explanation"] == text


def test_possessive_apostrophes_not_treated_as_quotes(example_request):
    text = "The patient's answer and the clinician's reading of the caregiver's report differ."
    c = claim(explanation=text)
    notes, _ = go(example_request, c)
    assert notes == [] and c["explanation"] == text
