"""Job state machine core (PRD R4): transitions, progress table, status mirror."""

import pytest

from onolys_api.errors import ApiError
from onolys_api.jobs import machine as m
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import SessionDoc, SessionError, SessionStatusDoc
from onolys_api.storage.fake import FakeBlobStore

UID, SID = "u1", "s1"


@pytest.fixture
def repo(tmp_path):
    r = FakeRepo(FakeBlobStore(tmp_path / "b"))
    r.create_session(UID, SID, SessionDoc(uid=UID), SessionStatusDoc(uid=UID))
    return r


def walk(repo, *states):
    for s in states:
        m.advance(repo, UID, SID, to=s, error=SessionError(code="x") if s == "failed" else None)


def test_states_match_the_prd_enum():
    assert set(m.STATES) == {
        "created", "uploading", "validating", "transcribing", "awaiting_input",
        "running", "report_ready", "failed", "deleting",
    }  # fmt: skip
    assert set(m.TRANSITIONS) == set(m.STATES)


def test_happy_path_and_progress_table(repo):
    seen = []
    for s in ("uploading", "validating", "transcribing", "awaiting_input", "running"):
        m.advance(repo, UID, SID, to=s)
        seen.append(repo.get_status(UID, SID).progress)
    assert seen == [5, 10, 20, 40, 45]
    m.advance(repo, UID, SID, to="report_ready")
    st = repo.get_status(UID, SID)
    assert (st.state, st.progress) == ("report_ready", 100)
    assert repo.get_session(UID, SID).state == "report_ready"


@pytest.mark.parametrize(
    "start,to",
    [
        ("created", "running"),
        ("created", "validating"),
        ("uploading", "transcribing"),
        ("validating", "awaiting_input"),
        ("transcribing", "running"),
        ("awaiting_input", "report_ready"),
        ("running", "awaiting_input"),
        ("report_ready", "uploading"),
        ("report_ready", "report_ready"),
    ],
)
def test_illegal_transitions_are_409_invalid_state(repo, start, to):
    repo.update_session(UID, SID, {"state": start})
    with pytest.raises(ApiError) as e:
        m.advance(repo, UID, SID, to=to)
    assert e.value.status == 409 and e.value.details[0]["code"] == "invalid_state"
    assert repo.get_session(UID, SID).state == start


def test_deleting_is_terminal_and_reachable_from_everywhere(repo):
    for s in m.STATES:
        if s != "deleting":
            assert "deleting" in m.TRANSITIONS[s]
    assert m.TRANSITIONS["deleting"] == frozenset()


def test_rerun_goes_from_report_ready_or_failed_and_restarts_at_45(repo):
    walk(repo, "uploading", "validating", "transcribing", "awaiting_input", "running")
    walk(repo, "report_ready")
    m.advance(repo, UID, SID, to="running")
    assert repo.get_status(UID, SID).progress == 45
    m.advance(repo, UID, SID, to="failed", error=SessionError(code="x"))
    m.advance(repo, UID, SID, to="running")
    assert repo.get_status(UID, SID).progress == 45


def test_failed_keeps_last_progress_and_needs_an_error(repo):
    walk(repo, "uploading", "validating")
    with pytest.raises(ValueError):
        m.advance(repo, UID, SID, to="failed")
    m.advance(
        repo, UID, SID, to="failed", error=SessionError(code="audio_unreadable", step="validate")
    )
    st = repo.get_status(UID, SID)
    assert (st.state, st.progress, st.error_code) == ("failed", 10, "audio_unreadable")
    assert repo.get_session(UID, SID).error == SessionError(
        code="audio_unreadable", step="validate"
    )


def test_error_is_cleared_when_leaving_failed(repo):
    walk(repo, "uploading", "validating", "failed", "running")
    assert repo.get_status(UID, SID).error_code is None
    assert repo.get_session(UID, SID).error is None


def test_stage_weights_sum_and_never_decrease_in_any_order(repo):
    assert sum(m.STAGE_WEIGHTS.values()) == 55 and m.RUN_START_PROGRESS + 55 == 100
    walk(repo, "uploading", "validating", "transcribing", "awaiting_input", "running")
    order = ["eaudit", "paudit", "compare", "tips", "assemble"]
    last = repo.get_status(UID, SID).progress
    for stage in order:
        m.advance(repo, UID, SID, step=stage)  # started: label only
        assert repo.get_status(UID, SID).progress == last
        m.advance(repo, UID, SID, step=stage, stage_done=stage)
        p = repo.get_status(UID, SID).progress
        assert p > last
        last = p
    assert last == 99  # 100 only on report_ready
    m.advance(repo, UID, SID, to="report_ready")
    assert repo.get_status(UID, SID).progress == 100


def test_progress_never_decreases_on_repeated_or_lower_updates(repo):
    walk(repo, "uploading", "validating", "transcribing", "awaiting_input")
    before = repo.get_status(UID, SID).progress
    m.advance(repo, UID, SID, flags={"transcript_ready": True})
    assert repo.get_status(UID, SID).progress == before
    assert m.next_progress(50, "uploading") == 50  # table value 5 < current


def test_flags_and_error_code_mirror_to_status_doc(repo):
    walk(repo, "uploading", "validating", "transcribing", "awaiting_input")
    m.advance(repo, UID, SID, flags={"transcript_ready": True, "speaker_confirmed": True})
    m.advance(repo, UID, SID, error=SessionError(code="daily_cap_reached"))
    st, s = repo.get_status(UID, SID), repo.get_session(UID, SID)
    assert st.transcript_ready and st.speaker_confirmed and not st.rating_submitted
    assert s.transcript_ready and s.speaker_confirmed
    assert st.state == "awaiting_input" and st.error_code == "daily_cap_reached"
    with pytest.raises(ValueError):
        m.advance(repo, UID, SID, flags={"bogus": True})


def test_report_version_mirrors_to_both_docs(repo):
    walk(repo, "uploading", "validating", "transcribing", "awaiting_input", "running")
    m.advance(repo, UID, SID, to="report_ready", latest_report_version=1)
    assert repo.get_status(UID, SID).latest_report_version == 1
    assert repo.get_session(UID, SID).latest_report_version == 1


def test_every_write_mirrors_status_in_one_update(repo):
    n = len(repo.status_writes)
    walk(repo, "uploading", "validating")
    assert len(repo.status_writes) == n + 2


def test_status_doc_has_only_the_contract_fields():
    assert set(SessionStatusDoc.model_fields) - {"id"} == m.STATUS_FIELDS
