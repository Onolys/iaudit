import itertools
import re

import pytest
from check_helpers import adhd_prep

from eaudit.check.models import Concern
from eaudit.check.templates import (
    VERDICT_TEXT,
    Slots,
    claim_text,
    concern_text,
    source_noun,
    vet_revision,
)
from eaudit.config import Settings
from eaudit.models import ConcernType, Role, Verdict

BANNED = re.compile(
    r"fabricat|\blie\b|\blies\b|\blying\b|false claim|dishonest|misconduct|deliberate|misrepresent",
    re.IGNORECASE,
)
# SP02 exposes the expanded contract; SP03 adds detection/templates for checks 14-17.
# Keep exercising every currently implemented template explicitly until that task lands.
IMPLEMENTED_CONCERN_TYPES = (
    ConcernType.unsupported_claim,
    ConcernType.contradictory_evidence,
    ConcernType.wrong_attribution,
    ConcernType.timeframe_mismatch,
    ConcernType.negation_reversal,
    ConcernType.certainty_inflation,
    ConcernType.frequency_severity_inflation,
    ConcernType.context_stripping,
    ConcernType.question_as_answer,
    ConcernType.correction_ignored,
    ConcernType.conflicting_accounts_flattened,
    ConcernType.unsupported_causal_link,
    ConcernType.quantity_mismatch,
)
SLOTS = [Slots(), Slots("the respondent", 1), Slots("the informant", 3)]


def all_texts() -> list[str]:
    out = list(VERDICT_TEXT.values())
    for t, s, d, sc in itertools.product(
        IMPLEMENTED_CONCERN_TYPES, SLOTS, (None, "inflates", "understates"), (None, "frequency", "severity")
    ):
        out.append(concern_text(Concern(t, [], d, sc), s))
    for v in Verdict:
        out.append(claim_text(v, [Concern(t, [], "understates") for t in IMPLEMENTED_CONCERN_TYPES]))
    return out


def test_every_template_renders_and_avoids_banned_words():
    texts = all_texts()
    assert len(texts) > 100
    for t in texts:
        assert t and not BANNED.search(t), t


def test_no_timestamps_or_speaker_ids_in_templates():
    for t in all_texts():
        assert not re.search(r"\d{1,2}:\d{2}", t), t
        assert "alex1" not in t and "sam1" not in t and "clinician1" not in t


def test_no_eight_gram_overlap_with_the_transcript():
    def grams(text):
        w = re.findall(r"\w+", text.lower())
        return {" ".join(w[i : i + 8]) for i in range(len(w) - 7)}

    transcript = set().union(*(grams(t.text) for t in adhd_prep().turns))
    assert all(not (grams(t) & transcript) for t in all_texts())


def test_amount_direction_words():
    up = concern_text(
        Concern(ConcernType.frequency_severity_inflation, [], "inflates", "frequency"), Slots()
    )
    down = concern_text(
        Concern(ConcernType.frequency_severity_inflation, [], "understates", "severity"), Slots()
    )
    assert "inflates" in up and "frequency" in up
    assert "understates" in down and "severity" in down


def test_claim_text_names_verdict_and_concern_types_with_direction():
    c = [Concern(ConcernType.frequency_severity_inflation, [], "inflates", "frequency")]
    t = claim_text(Verdict.partially_supported, c)
    assert t.startswith(VERDICT_TEXT[Verdict.partially_supported])
    assert "frequency_severity_inflation (inflates)" in t and "inflates" in t
    assert claim_text(Verdict.supported, []) == VERDICT_TEXT[Verdict.supported]
    assert (
        "not substantiated by the supplied interview" in VERDICT_TEXT[Verdict.insufficient_evidence]
    )


def test_source_nouns_come_from_roles_only():
    assert source_noun([Role.respondent, Role.respondent]) == "the respondent"
    assert source_noun([Role.informant]) == "the informant"
    assert source_noun([Role.respondent, Role.informant]) == "another speaker"
    assert source_noun([Role.respondent, None]) == "another speaker"
    assert source_noun([]) == "another speaker"


CFG = Settings()
INFL = [Concern(ConcernType.frequency_severity_inflation, ["k"], "inflates", "frequency")]


@pytest.mark.parametrize(
    "text,verdict,concerns,cfg,ok",
    [
        ("Alex loses attention in most meetings.", Verdict.partially_supported, INFL, CFG, True),
        ("Alex loses attention in most meetings.", Verdict.supported, [], CFG, False),
        ("Alex loses attention in most meetings.", Verdict.insufficient_evidence, INFL, CFG, False),
        ("Fine.", Verdict.contradicted, [Concern(ConcernType.unsupported_claim)], CFG, False),
        ("Said at 12:31 by Alex.", Verdict.partially_supported, INFL, CFG, False),
        (" ".join(["word"] * 41), Verdict.partially_supported, INFL, CFG, False),
        (" ".join(["word"] * 40), Verdict.partially_supported, INFL, CFG, True),
        ("Fine.", Verdict.partially_supported, INFL, Settings(check_suggest_revision=False), False),
        (None, Verdict.partially_supported, INFL, CFG, False),
        ("   ", Verdict.partially_supported, INFL, CFG, False),
    ],
)
def test_suggested_revision_rules(text, verdict, concerns, cfg, ok):
    assert (vet_revision(text, verdict, concerns, cfg) is not None) is ok


def test_banned_words_in_suggested_revision_are_rejected():
    assert (
        vet_revision("Alex deliberately skips meetings.", Verdict.partially_supported, INFL, CFG)
        is None
    )


def test_new_and_widened_templates_have_no_digits_or_banned_words():
    for t in (
        ConcernType.quantity_mismatch,
        ConcernType.wrong_attribution,
        ConcernType.context_stripping,
    ):
        for s in SLOTS:
            text = concern_text(Concern(t, [], None, None), s)
            assert not re.search(r"\d", text) and not BANNED.search(text), text


def test_widened_template_wording():
    wa = concern_text(Concern(ConcernType.wrong_attribution, [], None, None), Slots())
    assert "the source, person or entity described may differ" in wa
    cs = concern_text(Concern(ConcernType.context_stripping, [], None, None), Slots())
    assert "qualifier, reason or limit that the claim leaves out or broadens" in cs
    qm = concern_text(Concern(ConcernType.quantity_mismatch, [], None, None), Slots())
    assert "amount, count or value" in qm and "a reviewer may wish to confirm" in qm


def test_quantity_mismatch_revision_is_allowed():
    qm = [Concern(ConcernType.quantity_mismatch, ["k"])]
    assert vet_revision("The team has six people.", Verdict.partially_supported, qm, CFG)
