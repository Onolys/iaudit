from onolys_core.transcript import Transcript, Turn


def test_to_eaudit_turns_formats_mmss_and_drops_none():
    t = Transcript(
        turns=[
            Turn(id="t1", speaker="A", text="hi", start_ms=65_000, role="interviewer"),
            Turn(id="t2", text="yo", start_ms=4_500_999),
            Turn(id="t3", text="no time"),
        ]
    )
    out = t.to_eaudit_turns()
    assert out[0] == {
        "id": "t1",
        "speaker": "A",
        "role": "interviewer",
        "text": "hi",
        "timestamp": "01:05",
    }
    assert out[1]["timestamp"] == "75:00" and "speaker" not in out[1]
    assert "timestamp" not in out[2]


def test_round_trip_and_object_input():
    turns = [
        {"id": "a", "speaker": "S1", "role": "respondent", "text": "x", "timestamp": "00:07"},
        {"id": "b", "text": "y"},
        {"id": "c", "text": "z", "timestamp": "free text"},
    ]
    t = Transcript.from_eaudit_turns(turns)
    assert t.turns[0].start_ms == 7000 and t.turns[0].role == "respondent"
    assert t.turns[1].start_ms is None
    assert t.turns[2].start_ms is None  # not mm:ss: never inferred
    assert t.to_eaudit_turns()[0] == turns[0]
    assert t.to_eaudit_turns()[1] == turns[1]

    class Obj:
        def model_dump(self, **_):
            return turns[0]

    assert Transcript.from_eaudit_turns([Obj()]).turns[0].start_ms == 7000
