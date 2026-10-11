import pytest
from pydantic import ValidationError

from iaudit_backend.atomize.models import (
    OOS_REASONS,
    AtomicClaim,
    AtomizerOutput,
    CausalLink,
    OosCategory,
    Quantity,
    RawClaim,
    ReportedBy,
)
from iaudit_backend.config import Settings


def claim(**kw):
    base = {
        "id": "c0.1",
        "section_index": 0,
        "segments": ["Alex forgets medicines"],
        "proposition": "Alex forgets medicines.",
        "scope": "in_scope",
        "subject_text": "Alex",
        "reported_by": [{"source": "assessor", "speaker": None}],
        "polarity": "affirmed",
        "timeframe": "unspecified",
        "timeframe_explicit": False,
        "hedged": False,
    }
    base.update(kw)
    return AtomicClaim.model_validate(base)


def test_in_scope_claim_has_no_oos_fields():
    c = claim()
    assert c.oos_category is None and c.oos_reason is None
    assert c.span_hint is None and c.span_quality is None
    assert c.quantities == [] and c.subject_speaker is None


def test_out_of_scope_requires_category_and_sets_fixed_reason():
    c = claim(scope="out_of_scope", oos_category="diagnostic_conclusion")
    assert c.oos_reason == OOS_REASONS[OosCategory.diagnostic_conclusion]
    assert "oos_reason" in c.model_dump()


def test_category_iff_out_of_scope():
    with pytest.raises(ValidationError):
        claim(scope="out_of_scope")
    with pytest.raises(ValidationError):
        claim(scope="in_scope", oos_category="recommendation")


def test_every_category_has_a_distinct_fixed_sentence():
    assert set(OOS_REASONS) == set(OosCategory)
    assert len(set(OOS_REASONS.values())) == len(OosCategory)
    for sentence in OOS_REASONS.values():
        assert sentence.endswith(".") and '"' not in sentence and sentence.strip()


@pytest.mark.parametrize("segs", [[], ["a", "b", "c", "d"], [""], ["   "]])
def test_segments_are_one_to_three_non_blank(segs):
    with pytest.raises(ValidationError):
        claim(segments=segs)


def test_reported_by_needs_at_least_one_and_valid_source():
    with pytest.raises(ValidationError):
        claim(reported_by=[])
    with pytest.raises(ValidationError):
        claim(reported_by=[{"source": "partner", "speaker": None}])
    c = claim(
        reported_by=[
            {"source": "self", "speaker": "alex1"},
            {"source": "informant", "speaker": "sam1"},
        ]
    )
    assert [r.source for r in c.reported_by] == ["self", "informant"]


def test_quantities_at_most_two():
    q = {"kind": "frequency", "raw": "daily", "bucket": "always"}
    assert len(claim(quantities=[q, {**q, "kind": "severity", "bucket": "mild"}]).quantities) == 2
    with pytest.raises(ValidationError):
        claim(quantities=[q, q, q])


def test_quantity_bucket_names_validated_per_kind():
    Quantity(kind="frequency", raw="x", bucket="often")
    Quantity(kind="severity", raw="x", bucket="severe")
    # a bucket from the wrong scale (or unknown) is nulled, not an error: code resolves it
    assert Quantity(kind="frequency", raw="x", bucket="severe").bucket is None
    assert Quantity(kind="severity", raw="x", bucket="often").bucket is None
    assert Quantity(kind="severity", raw="x", bucket="bogus").bucket is None
    assert Quantity(kind="frequency", raw="x").bucket is None


def test_enums_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        claim(polarity="maybe")
    with pytest.raises(ValidationError):
        claim(timeframe="yesterday")
    with pytest.raises(ValidationError):
        claim(surprise=1)
    with pytest.raises(ValidationError):
        ReportedBy(source="self", speaker=None, extra=1)


def test_timeframes():
    for tf in ["current", "past", "childhood", "future", "hypothetical", "unspecified"]:
        assert claim(timeframe=tf).timeframe == tf


def test_causal_link_shape():
    link = CausalLink(cause_ids=["a", "b"], effect_id="c", connector="because", source="assessor")
    assert link.type == "causal"
    with pytest.raises(ValidationError):
        CausalLink(cause_ids=[], effect_id="c", connector="because", source="assessor")
    with pytest.raises(ValidationError):
        CausalLink(cause_ids=["a"], effect_id="c", connector="because", source="rumor")


def test_llm_output_schema_has_no_code_owned_fields():
    raw = RawClaim.model_json_schema()["properties"]
    for owned in ("id", "span_hint", "span_quality", "oos_reason", "section_index"):
        assert owned not in raw
    assert "ref" in raw and "segments" in raw and "oos_category" in raw
    out = AtomizerOutput.model_validate({"claims": [], "links": []})
    assert out.claims == [] and out.links == []


def test_config_keys():
    s = Settings()
    assert (s.atomize_max_claims, s.atomize_max_tokens, s.atomize_retry) == (30, 4000, True)


def test_raw_claim_parses_with_inconsistent_scope_and_category():
    base = claim().model_dump(
        exclude={"id", "section_index", "span_hint", "span_quality", "oos_reason"}
    )
    base["ref"] = "a"
    assert RawClaim.model_validate({**base, "scope": "out_of_scope"}).oos_category is None
    assert RawClaim.model_validate({**base, "oos_category": "recommendation"}).scope == "in_scope"
    with pytest.raises(ValidationError):  # the final model still enforces it
        claim(scope="out_of_scope")
