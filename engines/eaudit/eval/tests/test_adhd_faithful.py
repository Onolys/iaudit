import hashlib
from pathlib import Path

from eaudit.contract import validate_request
from eval.adhd import DATA, canonical_transcript, dump_json, faithful_request, load_spec

TRANSCRIPT_SHA256 = "bb30676b3439b75a99cdf29393a188dfffab9f0322366b749a2ab6aae9306704"


def test_transcript_pin():
    spec = load_spec()
    assert len(spec["transcript"]) == 26
    digest = hashlib.sha256(canonical_transcript(spec["transcript"]).encode()).hexdigest()
    assert digest == TRANSCRIPT_SHA256, "transcript changed: a deliberate, reviewed edit is needed"


def test_turn_ids_speakers_and_roles():
    t = load_spec()["transcript"]
    assert [x["id"] for x in t] == [f"t{i}" for i in range(26)]
    roles = {"clinician1": "interviewer", "alex1": "respondent", "sam1": "informant"}
    assert all(roles[x["speaker"]] == x["role"] for x in t)
    assert [t[i]["speaker"] for i in (0, 1, 19, 21, 23)] == [
        "clinician1",
        "alex1",
        "sam1",
        "sam1",
        "alex1",
    ]


def test_faithful_request_validates():
    req = faithful_request()
    assert validate_request(req) == []
    assert req["request_id"] == "adhd-faithful"
    (sec,) = req["assessment"]
    assert (sec["id"], sec["label"], sec["score"]) == ("s1", "Inattention (DSM-5 A1)", "5/9")
    assert sec["text"].startswith("Alex reports losing attention") and sec["text"].endswith(
        "He denies careless mistakes at work."
    )


def test_committed_faithful_file_matches():
    path = Path(DATA) / "requests" / "faithful.json"
    assert path.read_text(encoding="utf-8") == dump_json(faithful_request())
