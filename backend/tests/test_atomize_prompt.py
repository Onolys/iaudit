import json
import re

import pytest

from iaudit_backend.atomize.models import AtomizerOutput
from iaudit_backend.atomize.prompt import (
    FEWSHOT_PATH,
    Speaker,
    build_cache_prefix,
    load_fewshot,
    render_user,
    roster_from_turns,
)
from iaudit_backend.models import Turn


def test_fewshot_file_loads_and_is_marked_prompt_split():
    raw = json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))
    assert raw["split"] == "prompt"
    assert len(load_fewshot()) == 4


@pytest.mark.parametrize("i", range(4))
def test_each_example_parses_and_segments_are_exact_non_overlapping_substrings(i):
    ex = load_fewshot()[i]
    out = AtomizerOutput.model_validate(ex["output"])
    text = ex["text"]
    spans = []
    for c in out.claims:
        cursor = 0
        for seg in c.segments:
            at = text.find(seg, cursor)
            assert at != -1, seg  # copied character-for-character, in document order
            spans.append((at, at + len(seg)))
            cursor = at + len(seg)
    spans.sort()
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False)), "segments overlap"
    refs = [c.ref for c in out.claims]
    assert len(set(refs)) == len(refs)
    for link in out.links:
        assert set(link.cause_ids) | {link.effect_id} <= set(refs)


def test_fewshot_speakers_are_in_each_roster():
    for ex in load_fewshot():
        roster = {r["speaker"] for r in ex["roster"]}
        out = AtomizerOutput.model_validate(ex["output"])
        for c in out.claims:
            for s in [c.subject_speaker, *[r.speaker for r in c.reported_by]]:
                assert s is None or s in roster


def test_fewshot_covers_required_patterns():
    outs = [AtomizerOutput.model_validate(e["output"]) for e in load_fewshot()]
    flat = [c for o in outs for c in o.claims]
    assert any(o.links and o.links[0].connector == "because" for o in outs)  # (a)
    assert any(c.reported_by[0].source == "informant" for c in flat)  # (b)
    assert any(c.hedged and c.reported_by[0].source == "self" for c in flat)
    assert any(c.polarity == "negated" for c in flat)  # (c)
    assert any(c.timeframe == "childhood" and c.quantities for c in flat)
    cats = {c.oos_category for c in flat if c.oos_category}
    assert {"scoring_rule", "recommendation", "diagnostic_conclusion"} <= {str(x) for x in cats}
    assert any(len(c.segments) > 1 for c in flat)  # non-contiguous


def test_fewshot_never_reuses_eval_material():
    blob = FEWSHOT_PATH.read_text(encoding="utf-8").lower()
    for banned in ["alex", "sam1", "alex1", "clinician1", "forgetful", "medicines", "skips dinner",
                   "attention", "meeting", "keys", "phone", "paint"]:  # fmt: skip
        assert banned not in blob, banned


def test_prefix_is_stable_and_renders_from_tier_names_only():
    p1, p2 = build_cache_prefix(), build_cache_prefix()
    assert p1 == p2 and len(p1) > 1000
    assert not re.search(r"claude|anthropic|gpt|opus|sonnet|haiku|gemini|litellm", p1, re.I)


def test_prefix_states_the_core_rules():
    p = build_cache_prefix().lower()
    for needle in [
        "character-for-character",
        "never name a speaker",
        "roster",
        "out_of_scope",
        "unobservable",
        "diagnostic_conclusion",
        "segments",
        "at most 30",
        "never infer roles",
    ]:
        assert needle in p, needle
    assert "forgets medicines" not in p and "skips dinner" not in p


def test_prefix_embeds_the_output_schema():
    p = build_cache_prefix()
    for key in ["ref", "oos_category", "reported_by", "timeframe_explicit", "links", "cause_ids"]:
        assert f'"{key}"' in p


def test_prefix_contains_bucket_definitions():
    p = build_cache_prefix()
    for w in ["rarely", "sometimes", "often", "inability", "moderate"]:
        assert w in p


def test_max_claims_comes_from_argument():
    assert "at most 12" in build_cache_prefix(max_claims=12).lower()


def test_user_message_has_roster_and_section_text_only():
    roster = [Speaker("a1", None), Speaker("b1", "informant")]
    msg = render_user("The section text.", roster)
    assert "The section text." in msg and "a1" in msg and "b1" in msg and "informant" in msg
    assert "null" in msg or "none" in msg.lower()


def test_roster_from_turns_distinct_and_roles_never_inferred():
    turns = [
        Turn(id="1", speaker="x", role="interviewer", text="t secret"),
        Turn(id="2", speaker="y", text="t"),
        Turn(id="3", speaker="x", role="interviewer", text="t"),
        Turn(id="4", speaker="z", role="respondent", text="t"),
        Turn(id="5", speaker="z", text="t"),
    ]
    assert roster_from_turns(turns) == [
        Speaker("x", "interviewer"),
        Speaker("y", None),
        Speaker("z", None),  # mixed given/missing -> not inferred
    ]
    assert "secret" not in render_user("S", roster_from_turns(turns))


def test_prompt_has_no_leftover_placeholders_or_doubled_braces():
    p = build_cache_prefix()
    assert "{max_claims}" not in p and "{schema}" not in p and "{examples}" not in p
    assert "{{" not in p and "}}`" not in p
