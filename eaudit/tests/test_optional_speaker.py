"""Missing speaker identity stays unknown across contract, preparation and audit checks."""

from dataclasses import replace

import pytest
from check_helpers import adhd_prep, claim, ev, link

from eaudit import contract
from eaudit.atomize.prompt import roster_from_turns
from eaudit.check.group_a import run_group_a
from eaudit.check.synth import _reply_speakers
from eaudit.check.verifier import build_prompt
from eaudit.config import Settings
from eaudit.link.shortlist import TurnIndex
from eaudit.link.validate import answer_status
from eaudit.models import Turn
from eaudit.prep import Act, PrepResult, index_turns, pair_turns
from eaudit.prep.rules import rederive_position_acts


def prepared(*rows):
    turns = [Turn(id=f"t{i}", text=text, speaker=speaker) for i, (speaker, text) in enumerate(rows)]
    indexed, pairs = pair_turns(index_turns(turns))
    return PrepResult(turns=indexed, qa_pairs=pairs)


def test_request_omits_speaker_but_rejects_null_and_empty(example_request):
    for turn in example_request["transcript"]:
        turn.pop("speaker")
    assert contract.validate_request(example_request) == []
    turn = Turn.model_validate(example_request["transcript"][0])
    assert turn.speaker is None and "speaker" not in turn.model_dump(exclude_none=True)
    for value in (None, ""):
        example_request["transcript"][0]["speaker"] = value
        assert contract.validate_request(example_request)


def test_unknown_question_is_not_paired_and_unknown_replies_do_not_end_run():
    prep = prepared((None, "Do you sleep?"), ("a", "Yes."))
    assert prep.qa_pairs == []
    assert Act.answer not in prep.turns[1].acts
    prep = prepared(
        ("q", "Do you sleep?"),
        (None, "Do you nap?"),
        (None, "Yes."),
        ("a", "No."),
        ("q", "Thanks."),
    )
    assert [(p.question_index, p.response_indices) for p in prep.qa_pairs] == [(0, (3,))]
    assert [t.responds_to for t in prep.turns] == [None, None, None, 0, None]
    assert all(Act.answer not in t.acts for t in rederive_position_acts(prep.turns)[1:3])


def test_unknown_speaker_cannot_endorse_question_even_with_answer_act():
    prep = prepared(("q", "Do you sleep?"), (None, "Yes."))
    prep.turns[1] = replace(prep.turns[1], acts=frozenset({Act.answer}))
    assert answer_status([0, 1], prep) != "endorsed"


@pytest.mark.parametrize("role", ["respondent", "informant"])
def test_group_a_skips_unknown_attribution_and_reports_ambiguity(role):
    turns = list(adhd_prep(roles=True).turns)
    turns[19] = replace(turns[19], speaker=None, role=role)
    c = claim("Alex forgets.", reported_by=[{"source": "self", "speaker": "alex1"}])
    ga = run_group_a(c, link(ev(turn=19)), turns)
    assert ga.attribution == {"c0.1:e1": "skip"}
    assert ga.ambiguous == [19] and ga.role_skipped == 1


def test_unknown_question_does_not_trigger_question_as_answer():
    turns = list(adhd_prep(roles=True).turns)
    turns[12] = replace(turns[12], speaker=None)
    ga = run_group_a(claim("He is distracted."), link(ev(turn=12, status="question_only")), turns)
    assert ga.question_as_answer == [] and ga.ambiguous == [12] and ga.role_skipped == 1


def test_unknown_speakers_do_not_create_conflicting_accounts_or_roster_entries():
    turns = [Turn(id="a", text="Sometimes."), Turn(id="b", speaker="named", text="Never.")]
    prep = index_turns(turns)
    assert _reply_speakers(ev(turns=[0, 1]), prep) == ["named"]
    assert _reply_speakers(ev(turn=0), prep) == []
    assert [s.speaker for s in roster_from_turns(turns)] == ["named"]


def test_unknown_identity_does_not_gain_speaker_floor_or_self_correction():
    prep = prepared(
        (None, "Sleep is fine."), (None, "Actually sleep is poor."), ("a", "Sleep is poor.")
    )
    idx = TurnIndex(prep)
    cfg = Settings()
    assert idx._speaker_floor([0, 1, 2], [0], cfg) == [2]
    assert idx._later_corrections(claim("Sleep is fine."), [0], cfg) == []


def test_verifier_prompt_renders_unknown_without_changing_data():
    prep = adhd_prep(roles=True)
    prep.turns[3] = replace(prep.turns[3], speaker=None)
    prompt = build_prompt(claim("Alex forgets."), link(ev()), prep, prep.turns)
    assert '<turn i="3" speaker="unknown"' in "\n".join(prompt)
    assert prep.turns[3].speaker is None


def test_speaker_free_request_audits_through_api_and_warns():
    import json
    from pathlib import Path

    from atomize_helpers import raw
    from fastapi.testclient import TestClient

    from eaudit.app import create_app
    from eaudit.atomize.models import AtomizerOutput
    from eaudit.check.models import VerifierOutput
    from eaudit.link.models import LinkerOutput
    from eaudit.llm import StubClient

    examples = Path(__file__).resolve().parents[2] / "docs/contracts/examples"
    request = json.loads((examples / "no-speaker.request.json").read_text())
    llm = StubClient()
    llm.register(
        "atomize",
        lambda _: AtomizerOutput.model_validate(
            {
                "claims": [
                    raw(
                        segments=["The participant forgets appointments"],
                        proposition="The participant forgets appointments.",
                        subject_text="The participant",
                        subject_speaker=None,
                        reported_by=[{"source": "self", "speaker": None}],
                    )
                ]
            }
        ),
    )
    llm.register(
        "link",
        lambda _: LinkerOutput.model_validate(
            {
                "items": [
                    {
                        "key": "e1",
                        "role": "supporting",
                        "link_type": "quote",
                        "segments": [{"turn": 0, "text": request["transcript"][0]["text"]}],
                    }
                ]
            }
        ),
    )
    llm.register(
        "check",
        lambda _: VerifierOutput.model_validate(
            {
                "items": [
                    {
                        "key": "c0.1:e1",
                        "relation": "entails",
                        "conf": "high",
                    }
                ]
            }
        ),
    )
    with TestClient(create_app(Settings(llm_mode="stub"), llm=llm)) as client:
        response = client.post("/v1/audit", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert contract.validate_response(body) == []
    assert len(body["claims"]) == 1 and body["claims"][0]["evidence"]
    assert body["warnings"] == [
        {
            "code": "ambiguous_speaker",
            "claim_id": body["claims"][0]["id"],
            "message": "Speaker or role was missing for turn(s) 0; none was assumed.",
        }
    ]
    assert "speaker" not in request["transcript"][0]
    example = json.loads((examples / "no-speaker.response.json").read_text())
    assert contract.validate_response(example) == []
    assert {k: v for k, v in body.items() if k != "run_info"} == example
