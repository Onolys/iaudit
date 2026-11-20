import pytest
from conftest import write_pack
from onolys_core import InputError
from onolys_core.transcript import Transcript, Turn

from paudit.hooks import load_hooks
from paudit.pack import load_pack
from paudit.prepare import RoleTurn, build_volleys, mark_roles, prepare, select_turns

pytestmark = pytest.mark.unit

SM = {"subject": "A", "other": "B"}
CHECKS = [
    {"id": "dur_max", "kind": "duration_max", "value": 25, "severity": "error"},
    {"id": "dur_min", "kind": "duration_min", "value": 10, "severity": "warn"},
    {"id": "goal", "kind": "param_required", "value": "change_goal", "severity": "error"},
    {"id": "subj", "kind": "min_subject_turns", "value": 5, "severity": "error"},
    {"id": "oth", "kind": "min_other_turns", "value": 3, "severity": "error"},
]


def make_pack(tmp_path, pack_data, checks=CHECKS, volley=None, rules_py="# hooks\n"):
    pack_data["input_checks"] = checks
    if volley is not None:
        pack_data["volley"] = volley
    return load_pack(write_pack(tmp_path / "p", pack=pack_data, rules_py=rules_py))


def convo(n_pairs=5, step_s=200, text="synthetic words here"):
    """A, B, A, B ... alternating, 5 pairs ~ 14 min at 200 s per pair."""
    turns = []
    for i in range(n_pairs):
        t0 = i * step_s * 1000
        turns.append(Turn(id=f"t{2 * i}", speaker="A", text=text, start_ms=t0, end_ms=t0 + 1000))
        turns.append(
            Turn(id=f"t{2 * i + 1}", speaker="B", text=text, start_ms=t0 + 60000, end_ms=t0 + 61000)
        )
    return Transcript(turns=turns)


def params(**kw):
    return {"speaker_map": SM, "change_goal": "synthetic goal", **kw}


def test_ok_input_no_warnings(tmp_path, pack_data):
    p = prepare(convo(), make_pack(tmp_path, pack_data), params())
    assert p.warnings == []
    assert [v.id for v in p.volleys] == ["v1", "v2", "v3", "v4", "v5"]


def test_over_length_error(tmp_path, pack_data):
    with pytest.raises(InputError, match="dur_max"):
        prepare(convo(n_pairs=14), make_pack(tmp_path, pack_data), params())


def test_missing_change_goal_error(tmp_path, pack_data):
    with pytest.raises(InputError, match="change_goal"):
        prepare(convo(), make_pack(tmp_path, pack_data), {"speaker_map": SM})


def test_too_few_subject_turns(tmp_path, pack_data):
    t = convo()
    t.turns = [x for x in t.turns if x.id not in ("t0", "t2")]
    with pytest.raises(InputError, match="subj"):
        prepare(t, make_pack(tmp_path, pack_data), params())


def test_too_few_other_turns(tmp_path, pack_data):
    t = convo()
    t.turns = [x for x in t.turns if x.id not in ("t1", "t3", "t5")]
    with pytest.raises(InputError, match="oth"):
        prepare(t, make_pack(tmp_path, pack_data), params())


def test_under_ten_minutes_warns(tmp_path, pack_data):
    p = prepare(convo(step_s=60), make_pack(tmp_path, pack_data), params())
    assert [w.code for w in p.warnings] == ["short_session"]
    assert "dur_min" in p.warnings[0].detail


def test_unknown_speaker_treated_as_other(tmp_path, pack_data):
    t = convo()
    t.turns[1] = t.turns[1].model_copy(update={"speaker": "Z"})
    t.turns[3] = t.turns[3].model_copy(update={"speaker": None})
    p = prepare(t, make_pack(tmp_path, pack_data), params())
    codes = [w.code for w in p.warnings]
    assert codes == ["unknown_speaker"]
    assert sum(rt.role == "other" for rt in p.turns) == 5


def test_span_ignored_without_timestamps(tmp_path, pack_data):
    t = Transcript(turns=[Turn(id=x.id, speaker=x.speaker, text=x.text) for x in convo().turns])
    p = prepare(
        t, make_pack(tmp_path, pack_data, checks=[]), params(coded_span={"from_s": 0, "to_s": 60})
    )
    assert [w.code for w in p.warnings] == ["span_ignored"]
    assert len(p.turns) == 10


def _rt(turns):
    return [RoleTurn(t, "subject" if t.speaker == "A" else "other") for t in turns]


def test_partial_overlap_turn_included_whole():
    turns = [
        Turn(id="a", speaker="A", text="x", start_ms=0, end_ms=9000),
        Turn(id="b", speaker="A", text="x", start_ms=9000, end_ms=20000),  # straddles from_s
        Turn(id="c", speaker="A", text="x", start_ms=29000, end_ms=40000),  # straddles to_s
        Turn(id="d", speaker="A", text="x", start_ms=30000, end_ms=40000),  # starts at to_s: out
    ]
    kept, w = select_turns(_rt(turns), {"from_s": 10, "to_s": 30})
    assert [r.turn.id for r in kept] == ["b", "c"] and w == []
    assert kept[0].turn.text == "x" and kept[0].turn.end_ms == 20000


def test_missing_end_ms_falls_back_to_start():
    turns = [
        Turn(id="a", speaker="A", text="x", start_ms=5000),
        Turn(id="b", speaker="A", text="x", start_ms=15000),
    ]
    kept, _ = select_turns(_rt(turns), {"from_s": 10, "to_s": 30})
    assert [r.turn.id for r in kept] == ["b"]


def test_span_open_ended():
    turns = [
        Turn(id="a", speaker="A", text="x", start_ms=5000, end_ms=6000),
        Turn(id="b", speaker="A", text="x", start_ms=15000, end_ms=16000),
    ]
    kept, _ = select_turns(_rt(turns), {"from_s": 10, "to_s": None})
    assert [r.turn.id for r in kept] == ["b"]


def _seq(spec):
    return [
        RoleTurn(Turn(id=f"t{i}", speaker=s, text=txt), "subject" if s == "A" else "other")
        for i, (s, txt) in enumerate(spec)
    ]


def test_mm_hm_breaks_volley_by_default():
    vs = build_volleys(
        _seq(
            [
                ("A", "one two"),
                ("B", "mm-hm"),
                ("A", "three"),
                ("B", "long reply here"),
                ("A", "four"),
            ]
        ),
        {"breaks_on": "other_speaker"},
    )
    assert [v.id for v in vs] == ["v1", "v2", "v3"]
    assert vs[1].prev_other.text == "mm-hm" and vs[0].prev_other is None


def test_min_other_words_knob():
    spec = [
        ("A", "one"),
        ("B", "mm-hm"),
        ("A", "two"),
        ("B", "a longer reply here"),
        ("A", "three"),
    ]
    vs = build_volleys(_seq(spec), {"breaks_on": "other_speaker", "min_other_words": 3})
    assert [[t.id for t in v.turns] for v in vs] == [["t0", "t2"], ["t4"]]
    assert vs[1].prev_other.text == "a longer reply here"


def test_consecutive_subject_turns_one_volley():
    vs = build_volleys(_seq([("A", "a"), ("A", "b"), ("B", "c")]), {"breaks_on": "other_speaker"})
    assert len(vs) == 1 and len(vs[0].turns) == 2


def test_mark_roles_requires_subject():
    with pytest.raises(InputError):
        mark_roles(convo(), {})


HOOKS = """
def check_input(inp, ctx):
    return [{"code": "custom_warn", "detail": f"{len(inp.turns)} turns"}]

def compute_summary(counts, globals_, ctx):
    return None
"""


def test_hooks_loaded_and_check_input_runs(tmp_path, pack_data):
    pack = make_pack(tmp_path, pack_data, rules_py=HOOKS)
    hooks = load_hooks(pack)
    assert hooks.check_input and hooks.compute_summary and hooks.validate_codes is None
    p = prepare(convo(), pack, params(), hooks)
    assert [w.code for w in p.warnings] == ["custom_warn"]


def test_hooks_absent_or_empty(tmp_path, pack_data):
    assert load_hooks(make_pack(tmp_path, pack_data)).check_input is None
    assert load_hooks(make_pack(tmp_path / "n", pack_data, rules_py=None)).check_input is None


def test_broken_rules_py_is_pack_error(tmp_path, pack_data):
    from onolys_core import PackError

    with pytest.raises(PackError):
        load_hooks(make_pack(tmp_path, pack_data, rules_py="raise ValueError('x')\n"))
